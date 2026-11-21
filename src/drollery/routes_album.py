"""Albums: the upload page, the tracks, the cover and the download of a whole album."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from starlette.background import BackgroundTask

from . import albums, db, i18n
from .albums import AlbumError, Upload
from .config import get_settings
from .deps import api_auth, web_auth
from .i18n import t
from .web import flash_redirect, render

router = APIRouter(dependencies=[Depends(web_auth)])
files = APIRouter(dependencies=[Depends(api_auth)])
api = APIRouter(prefix="/api/v1", dependencies=[Depends(api_auth)])


def parse_tags(raw: str) -> list[str]:
    return [w for w in raw.replace("#", " ").replace(",", " ").split() if w]


async def _spool(ups: list[UploadFile], folder: Path) -> list[Upload]:
    """Write the uploaded files into a scratch folder, enforcing the size limits while they stream in."""
    s = get_settings()
    per_file, budget = s.max_upload_mb * 1024 * 1024, s.max_album_mb * 1024 * 1024
    out: list[Upload] = []
    used = 0
    folder.mkdir(parents=True, exist_ok=True)
    for i, up in enumerate(u for u in ups if u.filename):
        name = Path(up.filename).name
        dest = folder / f"{i:04d}{Path(name).suffix.lower()}"
        size = 0
        with dest.open("wb") as f:
            while chunk := await up.read(1 << 20):
                size += len(chunk)
                used += len(chunk)
                if size > per_file or used > budget:
                    raise HTTPException(413, f"upload exceeds {s.max_album_mb} MB")
                f.write(chunk)
        out.append(Upload(dest, name))
    return out


async def _make(files_in: list[UploadFile], cover_in: list[UploadFile], title: str, artist: str, subtype: str, description: str, tags: str):
    s = get_settings()
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td:
        work = Path(td)
        ups = await _spool(files_in, work)
        covers = await _spool(cover_in, work / "cover") if cover_in and any(c.filename for c in cover_in) else []
        if covers and not albums._is_image(covers[0].name):
            raise AlbumError(t("The cover must be a picture"))
        return await asyncio.to_thread(albums.create_album, ups, work, covers[0] if covers else None, title, artist, subtype, description, parse_tags(tags))


# ------------------------------------------------------------------ pages

@router.get("/albums/new")
def new_page(request: Request):
    return render(request, "album_new.html", form={})


@router.post("/albums")
async def create(request: Request, files: list[UploadFile] = File(default=[]), cover: list[UploadFile] = File(default=[]),
                 title: str = Form(""), artist: str = Form(""), subtype: str = Form("album"), description: str = Form(""), tags: str = Form("")):
    form = {"title": title, "artist": artist, "subtype": subtype, "description": description, "tags": tags}
    try:
        (get_settings().tmp_dir).mkdir(parents=True, exist_ok=True)
        item_id, created = await _make(files, cover, title, artist, subtype, description, tags)
    except AlbumError as e:
        return render(request, "album_new.html", status_code=422, form=form, error=str(e))
    msg = t("Album created") if created else t("That album is already in the library")
    return flash_redirect(f"/items/{item_id}", msg)


@router.post("/albums/{item_id}/tracks")
async def save_tracks(request: Request, item_id: int):
    """Rename tracks and reorder them. The form has `title_<id>` and `pos_<id>` for every track."""
    data = await request.form()
    with db.tx() as c:
        item = db.get_item(c, item_id)
        if item is None or item["kind"] != "album":
            raise HTTPException(404, "album not found")
        titles, order = {}, {}
        for tr in albums.tracks_of(c, item_id):
            if f"title_{tr['id']}" in data:
                titles[tr["id"]] = str(data[f"title_{tr['id']}"])
            try:
                order[tr["id"]] = int(str(data.get(f"pos_{tr['id']}", tr["position"])))
            except ValueError:
                order[tr["id"]] = tr["position"]
        albums.save_tracks(c, item_id, titles, order)
    return flash_redirect(f"/items/{item_id}#tracks", t("Tracks saved"))


# ------------------------------------------------------------------ files

def _album_or_404(item_id: int) -> dict:
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None or item["kind"] != "album":
        raise HTTPException(404, "album not found")
    return item


@files.get("/albums/{item_id}/track/{track_id}")
def track_file(item_id: int, track_id: int):
    item = _album_or_404(item_id)
    with db.tx() as c:
        row = c.execute("SELECT * FROM tracks WHERE id=? AND item_id=?", (track_id, item_id)).fetchone()
    if row is None:
        raise HTTPException(404, "track not found")
    path = albums.track_path(item, dict(row))
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, media_type=row["mime"], filename=row["original_name"] or None, content_disposition_type="inline",
                        headers={"X-Content-Type-Options": "nosniff"})


@files.get("/albums/{item_id}/cover")
def cover_file(item_id: int):
    item = _album_or_404(item_id)
    path = albums.cover_path(item)
    if not path.exists():
        raise HTTPException(404, "no cover")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@files.get("/albums/{item_id}/download")
def download(item_id: int):
    item = _album_or_404(item_id)
    with db.tx() as c:
        tr = albums.tracks_of(c, item_id)
    tmp = tempfile.NamedTemporaryFile(dir=get_settings().tmp_dir, suffix=".zip", delete=False)
    tmp.close()
    albums.build_zip(item, tr, Path(tmp.name))
    return FileResponse(tmp.name, media_type="application/zip", filename=f"{albums.safe_filename(item['title'])}.zip",
                        background=BackgroundTask(lambda: Path(tmp.name).unlink(missing_ok=True)))


# -------------------------------------------------------------------- API

@api.post("/albums", status_code=201)
async def api_create(files: list[UploadFile] = File(default=[]), cover: list[UploadFile] = File(default=[]), title: str = Form(""),
                     artist: str = Form(""), subtype: str = Form("album"), description: str = Form(""), tags: str = Form("")):
    """Create an album from audio files and/or ZIPs (multipart: `files`, optional `cover`)."""
    try:
        item_id, created = await _make(files, cover, title, artist, subtype, description, tags)
    except AlbumError as e:
        raise HTTPException(422, str(e)) from None
    with db.tx() as c:
        item = db.get_item(c, item_id)
        tr = albums.tracks_of(c, item_id)
    return {"id": item_id, "created": created, "title": item["title"], "tracks": len(tr), "duration": item["duration"]}
