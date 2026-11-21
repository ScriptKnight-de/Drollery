"""Albums: the upload page, the tracks, the cover and the download of a whole album."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.background import BackgroundTask

from . import aisettings, albums, db, i18n, metadata, pipeline
from .albums import AlbumError, Upload
from .config import get_settings
from .deps import api_auth, web_auth
from .i18n import t, tn
from .metadata import MetadataError
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
        item_id, created = await asyncio.to_thread(albums.create_album, ups, work, covers[0] if covers else None, title, artist, subtype, description, parse_tags(tags))
        if created:                                    # queue speech-to-text for every track, if a model is set up
            with db.tx() as c:
                pipeline.plan_jobs(c, item_id)
        return item_id, created


# ------------------------------------------------------------------ pages

@router.get("/albums/new")
def new_page(request: Request):
    return render(request, "album_new.html", form={})


@router.post("/albums")
async def create(request: Request, files: list[UploadFile] = File(default=[]), cover: list[UploadFile] = File(default=[]),
                 title: str = Form(""), artist: str = Form(""), subtype: str = Form("album"), description: str = Form(""), tags: str = Form(""),
                 lookup: str = Form("")):
    form = {"title": title, "artist": artist, "subtype": subtype, "description": description, "tags": tags, "lookup": lookup}
    try:
        (get_settings().tmp_dir).mkdir(parents=True, exist_ok=True)
        item_id, created = await _make(files, cover, title, artist, subtype, description, tags)
    except AlbumError as e:
        return render(request, "album_new.html", status_code=422, form=form, error=str(e))
    msg = t("Album created") if created else t("That album is already in the library")
    if lookup and created and get_settings().metadata_lookup:      # the box on the form: go straight on to choosing the matching release
        return flash_redirect(f"/albums/{item_id}/lookup?run=1", msg)
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


@router.post("/albums/{item_id}/rescan")
async def rescan(item_id: int):
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None or item["kind"] != "album":
        raise HTTPException(404, "album not found")
    await asyncio.to_thread(albums.rescan, item_id)
    return flash_redirect(f"/items/{item_id}#tracks", t("Order and titles read from the files again"))


@router.post("/albums/{item_id}/transcribe")
def transcribe(item_id: int, redo: str = Form("")):
    """Queue speech-to-text for the tracks of an album: those without a transcript, or every track again."""
    with db.tx() as c:
        item = db.get_item(c, item_id)
        if item is None or item["kind"] != "album":
            raise HTTPException(404, "album not found")
        if not aisettings.enabled("transcribe"):
            return flash_redirect(f"/items/{item_id}#tracks", t("No transcription model is set up. Add one under Settings › AI models"), "error")
        n = pipeline.plan_track_jobs(c, item_id, redo=bool(redo))
    if not n:
        return flash_redirect(f"/items/{item_id}#tracks", t("Nothing to transcribe: every track is done or already waiting"))
    return flash_redirect(f"/items/{item_id}#tracks", tn("Transcription queued for {n} track", "Transcription queued for {n} tracks", n))


# ---------------------------------------------------------- online lookup

def _lookup_album(item_id: int) -> tuple[dict, dict]:
    if not get_settings().metadata_lookup:
        raise HTTPException(404, "online lookup is switched off")
    with db.tx() as c:
        item = db.get_item(c, item_id)
        album = albums.get(c, item_id) if item else None
    if item is None or item["kind"] != "album":
        raise HTTPException(404, "album not found")
    return item, album


def _plan(item_id: int, mbid: str):
    """The online release and which of the album's tracks it matches (computed fresh every time, never taken from a form)."""
    rel = metadata.release(mbid)
    with db.tx() as c:
        mine = albums.tracks_of(c, item_id)
    match = metadata.match_tracks([{"id": x["id"], "title": x["title"], "duration": x["duration"]} for x in mine], rel.tracks)
    return rel, mine, match


@router.get("/albums/{item_id}/lookup")
def lookup_page(request: Request, item_id: int, q: str | None = None, artist: str | None = None, run: int = 0):
    item, album = _lookup_album(item_id)
    q = item["title"] if q is None else q
    artist = album["artist"] if artist is None else artist
    results, error = None, ""
    if run:
        try:
            results = metadata.search(q, artist)
        except MetadataError as e:
            error = str(e)
    return render(request, "album_lookup.html", item=item, album=album, q=q, artist=artist, results=results, error=error,
                  mine=_count(item_id))


def _count(item_id: int) -> int:
    with db.tx() as c:
        return c.execute("SELECT COUNT(*) FROM tracks WHERE item_id=?", (item_id,)).fetchone()[0]


@router.get("/albums/{item_id}/lookup/{mbid}")
def lookup_preview(request: Request, item_id: int, mbid: str):
    item, album = _lookup_album(item_id)
    try:
        rel, mine, match = _plan(item_id, mbid)
    except MetadataError as e:
        return flash_redirect(f"/albums/{item_id}/lookup", str(e), "error")
    rows = [{"track": tr, "remote": rel.tracks[match[tr["id"]]] if tr["id"] in match else None} for tr in mine]
    unmatched = len(mine) - len(match)
    return render(request, "album_lookup_preview.html", item=item, album=album, rel=rel, rows=rows, unmatched=unmatched,
                  now_facts=albums.summary(albums.facts(album)), online_facts=albums.summary({**rel.details(), "date": rel.date}))


@router.get("/albums/{item_id}/lookup/{mbid}/cover")
def lookup_cover(item_id: int, mbid: str):
    """The release's cover, passed through this server so the browser never talks to the lookup services itself."""
    _lookup_album(item_id)
    try:
        data = metadata.cover(mbid)
    except MetadataError:
        raise HTTPException(502, "lookup failed") from None
    if data is None:
        raise HTTPException(404, "no cover")
    return Response(data, media_type="image/jpeg" if data[:2] == b"\xff\xd8" else "image/png",
                    headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.post("/albums/{item_id}/lookup/{mbid}")
async def lookup_apply(request: Request, item_id: int, mbid: str):
    _lookup_album(item_id)
    form = await request.form()
    want = {k: k in form for k in ("title", "artist", "details", "cover")}
    try:
        rel, mine, match = await asyncio.to_thread(_plan, item_id, mbid)
        cover_bytes = await asyncio.to_thread(metadata.cover, mbid) if want["cover"] else None
    except MetadataError as e:
        return flash_redirect(f"/albums/{item_id}/lookup/{mbid}", str(e), "error")
    titles = {}
    for tr in mine:                                      # a track is renamed when its own box is ticked (and the release really has it)
        if tr["id"] in match and f"track_{tr['id']}" in form:
            titles[tr["id"]] = rel.tracks[match[tr["id"]]].title
    done = await asyncio.to_thread(albums.apply_details, item_id, rel, cover_bytes, title=want["title"], artist=want["artist"],
                                   details=want["details"], cover=want["cover"], track_titles=titles)
    if not done:
        return flash_redirect(f"/albums/{item_id}/lookup/{mbid}", t("Nothing was ticked, so nothing changed"), "error")
    return flash_redirect(f"/items/{item_id}", t("Details taken over from MusicBrainz"))


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


@files.get("/albums/{item_id}/track/{track_id}/transcript")
def track_transcript(item_id: int, track_id: int, q: str = ""):
    """What is said in one track, as text and as escaped HTML with the searched words marked (for the popup on the album page)."""
    _album_or_404(item_id)
    with db.tx() as c:
        row = c.execute("SELECT title, transcript, transcribed_at FROM tracks WHERE id=? AND item_id=?", (track_id, item_id)).fetchone()
    if row is None:
        raise HTTPException(404, "track not found")
    return {"title": row["title"], "text": row["transcript"], "html": str(albums.highlight(row["transcript"], q)),
            "done": row["transcribed_at"] is not None}


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
