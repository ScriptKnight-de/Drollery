"""Movies: the add form, and the IMDb lookup (search, review, apply)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from . import db, i18n, imdb, media, movies
from .config import get_settings
from .deps import web_auth
from .i18n import N_, t
from .metadata import MetadataError
from .web import flash_redirect, render

router = APIRouter(dependencies=[Depends(web_auth)])


def parse_tags(raw: str) -> list[str]:
    return [w for w in raw.replace("#", " ").replace(",", " ").split() if w]


def _movie(item_id: int, need_lookup: bool = False) -> tuple[dict, dict]:
    if need_lookup and not get_settings().metadata_lookup:
        raise HTTPException(404, "online lookup is switched off")
    with db.tx() as c:
        item = db.get_item(c, item_id)
        movie = movies.get(c, item_id) if item else None
    if item is None or item["kind"] != "movie" or movie is None:
        raise HTTPException(404, "movie not found")
    return item, movie


# ------------------------------------------------------------------ add

@router.get("/movies/new")
def new_page(request: Request):
    return render(request, "movie_new.html", form={"subtype": "movie"}, subtypes=movies.SUBTYPES)


@router.post("/movies")
async def create(request: Request, file: UploadFile | None = File(default=None), title: str = Form(""), original_title: str = Form(""),
                 subtype: str = Form("movie"), description: str = Form(""), tags: str = Form(""), lookup: str = Form("")):
    from .main import _save_upload                      # the upload handling is shared with the other kinds
    form = {"title": title, "original_title": original_title, "subtype": subtype, "description": description, "tags": tags, "lookup": lookup}

    def again(message: str):
        return render(request, "movie_new.html", status_code=422, form=form, subtypes=movies.SUBTYPES, error=t(message))

    if file is None or not file.filename:
        return again(N_("Choose a video file"))
    try:
        item_id, created = await _save_upload(file, as_movie=True)
    except media.MediaError:
        return again(N_("A movie must be a video file"))
    if not created:
        return flash_redirect(f"/items/{item_id}", t("This file is already in the library"), "error")
    with db.tx() as c:
        if title.strip():
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (title.strip()[:120], item_id))
        c.execute("UPDATE items SET description=? WHERE id=?", (description.strip()[:2000], item_id))
        movies.create(c, item_id, subtype, original_title)
        if parse_tags(tags):
            db.set_user_tags(c, item_id, parse_tags(tags))
        db.reindex(c, item_id)
    msg = t("Movie added")
    if lookup and get_settings().metadata_lookup:            # the box on the form: go straight on to choosing the matching IMDb title
        return flash_redirect(f"/movies/{item_id}/lookup?run=1", msg)
    return flash_redirect(f"/items/{item_id}", msg)


# ---------------------------------------------------------- IMDb lookup

def _rows(info) -> list[tuple[str, str]]:
    """What the lookup would store as details, as (label, value) lines for the review page."""
    rows = []
    if info.year:
        rows.append((t("Year"), info.year))
    if info.directors:
        rows.append((t("Directors"), ", ".join(info.directors)))
    if info.cast:
        rows.append((t("Cast"), ", ".join(info.cast)))
    if info.genres:
        rows.append((t("Genres"), ", ".join(info.genres)))
    if info.rating is not None:
        rows.append((t("TMDB rating") if info.rating_source == "TMDB" else t("IMDb rating"), f"{info.rating:.1f} / 10"))
    if info.runtime:
        rows.append((t("Runtime"), t("{n} min", n=info.runtime)))
    if info.language:
        rows.append((t("Language"), info.language))
    if info.country:
        rows.append((t("Country"), info.country))
    return rows


@router.get("/movies/{item_id}/lookup")
def lookup_page(request: Request, item_id: int, q: str | None = None, run: int = 0):
    item, movie = _movie(item_id, True)
    q = (movie["original_title"] or item["title"]) if q is None else q
    results, error = None, ""
    if run:
        try:
            results = imdb.search(q, i18n.current())
        except MetadataError as e:
            error = str(e)
    return render(request, "movie_lookup.html", item=item, movie=movie, q=q, results=results, error=error, has_key=imdb.has_key(), has_tmdb=imdb.has_tmdb(),
                  language_name=i18n.languages().get(i18n.current(), ""), english_ui=i18n.current() == "en")


@router.get("/movies/{item_id}/lookup/{ref}")
def lookup_preview(request: Request, item_id: int, ref: str):
    item, movie = _movie(item_id, True)
    try:
        info = imdb.title(ref, i18n.current())
    except MetadataError as e:
        return flash_redirect(f"/movies/{item_id}/lookup", str(e), "error")
    return render(request, "movie_lookup_preview.html", item=item, movie=movie, info=info, ref=ref, rows=_rows(info), has_key=imdb.has_key(), has_tmdb=imdb.has_tmdb(),
                  now_rows=movies_summary(movie))


def movies_summary(movie: dict) -> list[tuple[str, str]]:
    f = movies.facts(movie)
    rows = []
    if f.get("year"):
        rows.append((t("Year"), f["year"]))
    for key, label in (("directors", "Directors"), ("cast", "Cast"), ("genres", "Genres")):
        if f.get(key):
            rows.append((t(label), ", ".join(f[key])))
    return rows


@router.get("/movies/{item_id}/lookup/{ref}/poster")
def lookup_poster(item_id: int, ref: str):
    """The poster, passed through this server so the browser never talks to the lookup services itself."""
    _movie(item_id, True)
    try:
        info = imdb.title(ref, i18n.current())
        data = imdb.poster(info.poster)
    except MetadataError:
        raise HTTPException(502, "lookup failed") from None
    if data is None:
        raise HTTPException(404, "no poster")
    return Response(data, media_type="image/jpeg" if data[:2] == b"\xff\xd8" else "image/png",
                    headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.post("/movies/{item_id}/lookup/{ref}")
async def lookup_apply(request: Request, item_id: int, ref: str):
    _movie(item_id, True)
    form = await request.form()
    want = {k: k in form for k in ("title", "plot", "details", "poster")}
    back = f"/movies/{item_id}/lookup/{ref}"
    language = i18n.current()
    try:
        info = await asyncio.to_thread(imdb.title, ref, language)
        data = await asyncio.to_thread(imdb.poster, info.poster) if want["poster"] else None
    except MetadataError as e:
        return flash_redirect(back, str(e), "error")
    done = await asyncio.to_thread(movies.apply_details, item_id, info, data, title=want["title"], plot=want["plot"],
                                   details=want["details"], poster=want["poster"])
    if not done:
        return flash_redirect(back, t("Nothing was ticked, so nothing changed"), "error")
    return flash_redirect(f"/items/{item_id}", t("Details taken over from IMDb"))
