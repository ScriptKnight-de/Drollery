"""Custom card images: pick a video frame, crop a square, and show it on the library page."""
from __future__ import annotations

import math
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response

from . import albums, db, media, pipeline
from .deps import api_auth, web_auth
from . import i18n
from .web import flash_redirect, render

router = APIRouter(dependencies=[Depends(web_auth)])
files = APIRouter(dependencies=[Depends(api_auth)])


def _item(item_id: int) -> dict:
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item["kind"] == "audio":
        raise HTTPException(404, "audio has no picture to crop")
    if item["kind"] == "album" and not albums.cover_path(item).exists():
        raise HTTPException(404, "this album has no cover to crop")
    return item


def _source(item: dict):
    """(file, kind) the cropper reads: the file itself, or an album's cover (a picture)."""
    if item["kind"] == "album":
        return albums.cover_path(item), "image"
    return pipeline.media_path(item), item["kind"]


def default_time(item: dict) -> float:
    """Where the automatic thumbnail was taken (matches media.make_thumb)."""
    return round(min(1.0, (item["duration"] or 0) / 2), 2) if item["kind"] == "video" else 0.0


@router.get("/items/{item_id}/card")
def card_page(request: Request, item_id: int):
    item = _item(item_id)
    t = item["card_t"] if item["card_t"] is not None else default_time(item)
    crop = None
    if item["has_card"] and item["card_x"] is not None:
        crop = {"x": item["card_x"], "y": item["card_y"], "s": item["card_s"]}
    return render(request, "item_card.html", item=item, t=t, crop=crop, duration=item["duration"] or 0)


@router.get("/items/{item_id}/frame")
def frame(item_id: int, t: float = 0.0):
    """The still the cropper works on: an image as-is, or the video frame at t seconds."""
    item = _item(item_id)
    if not math.isfinite(t) or t < 0:
        raise HTTPException(422, "t must be a number of seconds, zero or more")
    path, kind = _source(item)
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    if item["duration"] and kind == "video":
        t = min(t, max(item["duration"] - 0.05, 0))
    try:
        data = media.frame_jpeg(path, kind, t)
    except media.MediaError as e:
        raise HTTPException(422, str(e)) from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


def _fraction(value: float, name: str, lo: float, hi: float) -> float:
    if not math.isfinite(value) or not lo <= value <= hi:
        raise HTTPException(422, f"{name} must be between {lo} and {hi}")
    return value


@router.post("/items/{item_id}/card")
def save_card(request: Request, item_id: int, t: float = Form(0.0), x: float = Form(...), y: float = Form(...), s: float = Form(...)):
    item = _item(item_id)
    _fraction(x, "x", 0, 1), _fraction(y, "y", 0, 1), _fraction(s, "s", 0.02, 1)
    if not math.isfinite(t) or t < 0:
        raise HTTPException(422, "t must be zero or more")
    path, kind = _source(item)
    if kind != "video":
        t = 0.0
    elif item["duration"]:
        t = min(t, max(item["duration"] - 0.05, 0))
    try:
        media.make_card(path, pipeline.card_path(item), kind, t, x, y, s)
    except media.MediaError as e:
        return flash_redirect(f"/items/{item_id}/card", i18n.t("Could not make the card image: {error}", error=e), "error")
    with db.tx() as c:
        c.execute("UPDATE items SET has_card=1, card_t=?, card_x=?, card_y=?, card_s=?, updated_at=? WHERE id=?",
                  (t if kind == "video" else None, x, y, s, time.time(), item_id))
    return flash_redirect(f"/items/{item_id}", i18n.t("Card image saved. It now shows on the library page"))


@router.post("/items/{item_id}/card/reset")
def reset_card(item_id: int):
    item = _item(item_id)
    pipeline.card_path(item).unlink(missing_ok=True)
    with db.tx() as c:
        c.execute("UPDATE items SET has_card=0, card_t=NULL, card_x=NULL, card_y=NULL, card_s=NULL, updated_at=? WHERE id=?", (time.time(), item_id))
    return flash_redirect(f"/items/{item_id}", i18n.t("Card image reset to automatic"))


@files.get("/card/{item_id}")
def card_file(item_id: int):
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    path = pipeline.card_path(item)
    if not item["has_card"] or not path.exists():
        raise HTTPException(404, "no custom card image")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})
