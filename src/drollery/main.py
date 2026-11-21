from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, accounts, albums, db, i18n, media, people, pipeline, shares
from .config import get_settings
from .deps import LoginRequired, SetupRequired, api_auth, web_auth
from .routes_auth import router as auth_router
from .routes_people import files as people_files_router
from .routes_people import router as people_router
from .routes_album import router as album_router, files as album_files_router, api as album_api_router
from .routes_card import files as card_files_router, router as card_router
from .routes_share import api as share_api_router, manage as share_manage_router, public as share_public_router, share_context, FILE_HEADERS
from .routes_settings import router as settings_router
from .i18n import t
from .web import BASE, flash_redirect, render

log = logging.getLogger("drollery")
PAGE = 40


# ----------------------------------------------------------------- worker

async def _worker_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        job = await asyncio.to_thread(db.claim_job)
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            continue
        await asyncio.to_thread(pipeline.run_job, job)


def _announce_setup() -> None:
    code = accounts.get_setup_code()
    bar = "=" * 64
    print(f"\n{bar}\n  Drollery first-run setup\n  Open the web interface and create the admin account.\n"
          f"  Setup code: {code}\n{bar}\n", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    db.init()
    for old in s.tmp_dir.iterdir():
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    if accounts.user_count() == 0:
        _announce_setup()
    stop = asyncio.Event()
    tasks = [asyncio.create_task(_worker_loop(stop)) for _ in range(max(1, s.worker_concurrency))]
    yield
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Drollery", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(card_router)
app.include_router(card_files_router)
app.include_router(people_router)
app.include_router(people_files_router)
app.include_router(album_router)
app.include_router(album_files_router)
app.include_router(album_api_router)
app.include_router(share_public_router)


@app.get("/impressum")
def impressum(request: Request):
    """Public on purpose: the legal notice must be readable without an account."""
    text, live = accounts.impressum()
    if not live:
        raise HTTPException(status_code=404)
    return render(request, "impressum.html", text=text)
app.include_router(share_manage_router)
app.include_router(share_api_router)


@app.middleware("http")
async def pick_language(request: Request, call_next):
    """The browser's cookie (set when a language is chosen in Settings), else its Accept-Language header."""
    code = i18n.normalize(request.cookies.get(i18n.COOKIE)) or i18n.from_accept_language(request.headers.get("accept-language", ""))
    i18n.set_language(code)
    return await call_next(request)


@app.middleware("http")
async def same_origin_for_browser_writes(request: Request, call_next):
    """Cookie-authenticated writes must come from this site. API-key (Bearer) requests are exempt."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.headers.get("authorization"):
        origin = request.headers.get("origin")
        if origin and origin != "null" and urlparse(origin).netloc != request.headers.get("host", ""):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)


@app.exception_handler(LoginRequired)
async def _login_redirect(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(SetupRequired)
async def _setup_redirect(request: Request, exc: SetupRequired):
    return RedirectResponse("/setup", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    """Browsers get a friendly 404 page; the API and media routes keep JSON errors."""
    if (exc.status_code == 404 and "text/html" in request.headers.get("accept", "")
            and not request.url.path.startswith(("/api/", "/media/", "/thumb/"))):
        return render(request, "404.html", status_code=404)
    return await http_exception_handler(request, exc)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


# ---------------------------------------------------------------- helpers

async def _save_upload(up: UploadFile) -> tuple[int, bool]:
    s = get_settings()
    name = Path(up.filename or "upload").name
    media.guess(name)  # raises MediaError for unsupported types
    limit = s.max_upload_mb * 1024 * 1024
    with tempfile.NamedTemporaryFile(dir=s.tmp_dir, delete=False) as tmp:
        size = 0
        try:
            while chunk := await up.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"file exceeds {s.max_upload_mb} MB")
                tmp.write(chunk)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    try:
        return await asyncio.to_thread(pipeline.import_file, Path(tmp.name), name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _public(item: dict) -> dict:
    out = {k: v for k, v in item.items() if k not in ("sha256", "title_locked", "has_thumb", "has_card", "card_t", "card_x", "card_y", "card_s")}
    out["url"] = f"/media/{item['id']}" if item["kind"] != "album" else None          # an album has tracks, not one file
    out["thumb_url"] = f"/thumb/{item['id']}" if item["has_thumb"] else None
    out["card_url"] = f"/card/{item['id']}" if item["has_card"] else out["thumb_url"]
    return out


def _parse_tags(raw: str) -> list[str]:
    return [t for t in raw.replace("#", " ").replace(",", " ").split() if t]


def _get_or_404(item_id: int) -> dict:
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


def _delete_item(item: dict) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM items_fts WHERE rowid=?", (item["id"],))
        c.execute("DELETE FROM tracks_fts WHERE rowid IN (SELECT id FROM tracks WHERE item_id=?)", (item["id"],))
        c.execute("DELETE FROM items WHERE id=?", (item["id"],))
    pipeline.media_path(item).unlink(missing_ok=True)
    if item["kind"] == "album":
        albums.remove_files(item)
    pipeline.thumb_path(item).unlink(missing_ok=True)
    pipeline.card_path(item).unlink(missing_ok=True)
    pipeline.card_source_path(item).unlink(missing_ok=True)


# ------------------------------------------------------------------ files

@app.get("/media/{item_id}", dependencies=[Depends(api_auth)])
def media_file(item_id: int):
    item = _get_or_404(item_id)
    path = pipeline.media_path(item)
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, media_type=item["mime"], filename=item["original_name"] or None,
                        content_disposition_type="inline", headers={k: v for k, v in FILE_HEADERS.items() if k != "Cache-Control"})


@app.get("/thumb/{item_id}", dependencies=[Depends(api_auth)])
def thumb_file(item_id: int):
    item = _get_or_404(item_id)
    path = pipeline.thumb_path(item)
    if not item["has_thumb"] or not path.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# -------------------------------------------------------------------- API

@app.get("/api/v1/me", dependencies=[Depends(api_auth)])
def api_me(request: Request):
    u = request.state.user
    return {"username": u["username"], "via": "api_key" if "_api_key_id" in u else "session",
            "version": __version__}


@app.get("/api/v1/items", dependencies=[Depends(api_auth)])
def api_list(q: str = "", kind: str = "", tag: str = "", tag_source: str = "", limit: int = PAGE, offset: int = 0):
    with db.tx() as c:
        items = db.search(c, q, kind, tag, min(max(limit, 1), 200), max(offset, 0), tag_source)
    return {"items": [_public(i) for i in items]}


@app.get("/api/v1/items/{item_id}", dependencies=[Depends(api_auth)])
def api_get(item_id: int):
    return _public(_get_or_404(item_id))


@app.post("/api/v1/items", dependencies=[Depends(api_auth)], status_code=201)
async def api_upload(file: UploadFile = File(...)):
    try:
        item_id, created = await _save_upload(file)
    except media.MediaError as e:
        raise HTTPException(415, str(e)) from None
    return JSONResponse({"id": item_id, "created": created}, status_code=201 if created else 200)


@app.post("/api/v1/ingest", dependencies=[Depends(api_auth)], status_code=202)
async def api_ingest(request: Request):
    body = await request.json()
    url = str(body.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "url must start with http:// or https://")
    with db.tx() as c:
        job_id = db.enqueue(c, "fetch", None, json.dumps({"url": url}))
    return {"job_id": job_id}


@app.patch("/api/v1/items/{item_id}", dependencies=[Depends(api_auth)])
async def api_patch(item_id: int, request: Request):
    body = await request.json()
    _get_or_404(item_id)
    with db.tx() as c:
        if "title" in body:
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (str(body["title"])[:120], item_id))
        if "description" in body:
            c.execute("UPDATE items SET description=? WHERE id=?", (str(body["description"])[:2000], item_id))
        if "tags" in body:
            db.set_user_tags(c, item_id, [str(t) for t in body["tags"]])
        c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
        db.reindex(c, item_id)
    return _public(_get_or_404(item_id))


@app.delete("/api/v1/items/{item_id}", dependencies=[Depends(api_auth)], status_code=204)
def api_delete(item_id: int):
    _delete_item(_get_or_404(item_id))


@app.post("/api/v1/jobs/{job_id}/retry", dependencies=[Depends(api_auth)], status_code=202)
def api_retry_job(job_id: int):
    with db.tx() as c:
        row = c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "job not found")
    if not db.retry_job(job_id):
        raise HTTPException(409, f"only failed jobs can be retried (this one is {row['status']})")
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/v1/jobs", dependencies=[Depends(api_auth)])
def api_jobs(limit: int = 50):
    with db.tx() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return {"jobs": [dict(r) for r in rows]}


# --------------------------------------------------------------------- web

@app.get("/", dependencies=[Depends(web_auth)])
def home(request: Request, q: str = "", kind: str = "", tag: str = "", src: str = "", page: int = 0, person: int = 0):
    page = max(page, 0)
    src = src if src in ("user", "ai") else ""
    with db.tx() as c:
        person_row = people.get(c, person) if person > 0 else None
        person = person_row["id"] if person_row else 0                 # an unknown person is simply not a filter
        items = db.search(c, q, kind, tag, PAGE, page * PAGE, src, person)
        counts = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) n FROM items GROUP BY kind")}
        pending = c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        album_ids = [i["id"] for i in items if i["kind"] == "album"]
        album_info = albums.summaries(c, album_ids)
        track_hits = albums.track_hits(c, q, album_ids) if q.strip() else {}
    tpl = "grid.html" if request.headers.get("hx-request") and not request.headers.get("hx-boosted") else "index.html"
    return render(request, tpl, items=items, q=q, kind=kind, tag=tag, src=src, person_id=person, person_row=person_row, page=page, more=len(items) == PAGE, counts=counts, pending=pending, album_info=album_info, track_hits=track_hits)


@app.post("/add", dependencies=[Depends(web_auth)])
async def add(files: list[UploadFile] = File(default=[]), url: str = Form("")):
    last = None
    for f in files:
        if not f.filename:
            continue
        try:
            last, _ = await _save_upload(f)
        except media.MediaError:
            continue
    if url.strip().startswith(("http://", "https://")):
        with db.tx() as c:
            db.enqueue(c, "fetch", None, json.dumps({"url": url.strip()}))
        return RedirectResponse("/jobs", status_code=303)
    return RedirectResponse(f"/items/{last}" if last and len(files) == 1 else "/", status_code=303)


@app.get("/items/{item_id}", dependencies=[Depends(web_auth)])
def item_page(request: Request, item_id: int):
    item = _get_or_404(item_id)
    with db.tx() as c:
        jobs = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE item_id=? ORDER BY id DESC", (item_id,))]
        if item["kind"] == "album":
            q = request.query_params.get("q", "")
            return render(request, "album.html", item=item, album=albums.get(c, item_id), facts=albums.facts(albums.get(c, item_id)),
                          item_people=people.of_item(c, item_id), transcription=albums.transcription_state(c, item_id), matches=albums.matching_track_ids(c, q, item_id) if q.strip() else set(), q=q, tracks=albums.tracks_of(c, item_id), **share_context(request, item))
    with db.tx() as c:
        item_people = people.of_item(c, item_id)
    return render(request, "item.html", item=item, jobs=jobs, item_people=item_people, **share_context(request, item))


@app.post("/items/{item_id}/edit", dependencies=[Depends(web_auth)])
def item_edit(item_id: int, title: str = Form(""), description: str = Form(""), tags: str = Form(""), artist: str | None = Form(None)):
    item = _get_or_404(item_id)
    with db.tx() as c:
        if title.strip() != item["title"]:
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (title.strip()[:120], item_id))
        c.execute("UPDATE items SET description=?, updated_at=? WHERE id=?", (description.strip()[:2000], time.time(), item_id))
        db.set_user_tags(c, item_id, _parse_tags(tags))
        if item["kind"] == "album" and artist is not None:
            c.execute("UPDATE albums SET artist=? WHERE item_id=?", (artist.strip()[:120], item_id))
            db.reindex(c, item_id)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/ai-tags/keep", dependencies=[Depends(web_auth)])
def item_keep_ai_tags(item_id: int, tag: str = Form("")):
    """Promote one AI tag (or all of them) to the user's own tags."""
    _get_or_404(item_id)
    with db.tx() as c:
        db.keep_ai_tags(c, item_id, tag)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/ai-tags/remove", dependencies=[Depends(web_auth)])
def item_remove_ai_tags(item_id: int, tag: str = Form("")):
    """Remove one AI tag (or all of them); the AI will not suggest a removed tag again for this item."""
    _get_or_404(item_id)
    with db.tx() as c:
        db.dismiss_ai_tags(c, item_id, tag)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/reprocess", dependencies=[Depends(web_auth)])
def item_reprocess(item_id: int):
    _get_or_404(item_id)
    with db.tx() as c:
        pipeline.plan_jobs(c, item_id)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/delete", dependencies=[Depends(web_auth)])
def item_delete(item_id: int):
    _delete_item(_get_or_404(item_id))
    return RedirectResponse("/", status_code=303)


@app.get("/jobs", dependencies=[Depends(web_auth)])
def jobs_page(request: Request):
    with db.tx() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT jobs.*, items.title AS item_title FROM jobs LEFT JOIN items ON items.id=jobs.item_id "
            "ORDER BY jobs.id DESC LIMIT 100")]
    for r in rows:
        r["label"] = json.loads(r["payload"]).get("url", "") if r["type"] == "fetch" else (r["item_title"] or "")
        if r["type"] == "transcribe_track":                       # "Album title · Track title"
            with db.tx() as c:
                tr = c.execute("SELECT title FROM tracks WHERE id=?", (json.loads(r["payload"]).get("track_id", 0),)).fetchone()
            r["label"] = f"{r['label']} · {tr['title']}" if tr else r["label"]
    return render(request, "jobs.html", jobs=rows)


@app.post("/jobs/retry-failed", dependencies=[Depends(web_auth)])
def jobs_retry():
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='queued', attempts=0, error='', run_after=0 WHERE status='failed'")
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/{job_id}/retry", dependencies=[Depends(web_auth)])
def job_retry(job_id: int, next: str = Form("/jobs")):
    """Run one failed job again, from the jobs list or from an item page."""
    back = shares.safe_next(next, "/jobs")
    if db.retry_job(job_id):
        return flash_redirect(back, t("Job queued again"))
    return flash_redirect(back, t("That job can't be retried: it isn't in a failed state any more"), "error")
