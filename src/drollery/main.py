from __future__ import annotations

import asyncio
import json
import logging
import secrets
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

from . import __version__, accounts, albums, autobackup, db, i18n, media, movies, netguard, people, pipeline, shares
from .config import get_settings
from .deps import LoginRequired, SetupRequired, api_auth, item_or_404, web_auth
from .upload_redirect import UploadRedirects
from .routes_auth import router as auth_router
from .routes_movie import router as movie_router
from .routes_people import files as people_files_router
from .routes_people import router as people_router
from .routes_album import router as album_router, files as album_files_router, api as album_api_router
from .routes_card import files as card_files_router, router as card_router
from .routes_share import api as share_api_router, manage as share_manage_router, public as share_public_router, share_context, FILE_HEADERS
from .routes_settings import router as settings_router
from .routes_tags import router as tags_router
from .i18n import t, tn
from .web import BASE, PAGE, flash_redirect, jpeg_response, render, security_headers

log = logging.getLogger("drollery")


# ----------------------------------------------------------------- worker

async def _worker_loop(stop: asyncio.Event, slot: int, limit: list[int]) -> None:
    """Slot n works while the number of allowed jobs (limit[0]) is above n; when it is lowered the slot ends after its job."""
    while not stop.is_set() and slot < limit[0]:
        job = await asyncio.to_thread(db.claim_job)
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            continue
        await asyncio.to_thread(pipeline.run_job, job)


async def _supervise(stop: asyncio.Event) -> None:
    """Keeps as many worker loops alive as Settings allow (accounts.worker_limit). A changed setting applies within two seconds."""
    limit, workers = [1], {}
    while not stop.is_set():
        limit[0] = await asyncio.to_thread(accounts.worker_limit)
        for slot in range(limit[0]):
            if slot not in workers or workers[slot].done():
                workers[slot] = asyncio.create_task(_worker_loop(stop, slot, limit))
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
    await asyncio.gather(*workers.values(), return_exceptions=True)


async def _backup_scheduler(stop: asyncio.Event) -> None:
    """Once a minute: is an automatic backup due? (They are off until switched on under Settings > Backup.)"""
    try:
        await asyncio.wait_for(stop.wait(), timeout=60)            # not while the app is still starting up
        return
    except asyncio.TimeoutError:
        pass
    while not stop.is_set():
        try:
            await asyncio.to_thread(autobackup.tick)
        except Exception:  # noqa: BLE001 - the scheduler must not die
            log.exception("the backup scheduler failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


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
    with db.tx() as c:
        pipeline.plan_upkeep(c)
    stop = asyncio.Event()
    supervisor = asyncio.create_task(_supervise(stop))
    scheduler = asyncio.create_task(_backup_scheduler(stop))
    yield
    stop.set()
    await asyncio.gather(supervisor, scheduler, return_exceptions=True)


# the interactive API docs are off: they would list every endpoint to anyone who can reach the port (the API is documented in the README)
app = FastAPI(title="Drollery", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    """Browsers ask for this path by habit, whatever the page says: answer with the same icon the pages name."""
    return FileResponse(BASE / "static" / "favicon.ico", media_type="image/vnd.microsoft.icon", headers={"Cache-Control": "public, max-age=86400"})


app.add_middleware(UploadRedirects)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(tags_router)
app.include_router(card_router)
app.include_router(card_files_router)
app.include_router(movie_router)
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
async def protective_headers(request: Request, call_next):
    """A fresh nonce for every request (templates put it on their own inline scripts), and the security headers on the answer."""
    request.state.nonce = secrets.token_urlsafe(16)
    response = await call_next(request)
    for name, value in security_headers(request.state.nonce).items():
        response.headers.setdefault(name, value)
    return response


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
    return {"ok": True}                      # no version here: anyone can call it (GET /api/v1/me tells a signed-in client the version)


# ---------------------------------------------------------------- helpers

async def _save_upload(up: UploadFile, as_movie: bool = False) -> tuple[int, bool]:
    s = get_settings()
    name = Path(up.filename or "upload").name
    kind, _mime = media.guess(name)  # raises MediaError for unsupported types
    if as_movie and kind != "video":
        raise media.MediaError("a movie must be a video file")
    limit = (s.max_movie_mb if as_movie else s.max_upload_mb) * 1024 * 1024
    with tempfile.NamedTemporaryFile(dir=s.tmp_dir, delete=False) as tmp:
        size = 0
        try:
            while chunk := await up.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"file exceeds {limit // 1048576} MB")
                tmp.write(chunk)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
    try:
        return await asyncio.to_thread(pipeline.import_file, Path(tmp.name), name, as_movie=as_movie)
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
    item = item_or_404(item_id)
    path = pipeline.media_path(item)
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, media_type=item["mime"], filename=item["original_name"] or None,
                        content_disposition_type="inline", headers={k: v for k, v in FILE_HEADERS.items() if k != "Cache-Control"})


@app.get("/thumb/{item_id}", dependencies=[Depends(api_auth)])
def thumb_file(item_id: int):
    item = item_or_404(item_id)
    path = pipeline.thumb_path(item)
    if not item["has_thumb"] or not path.exists():
        raise HTTPException(404, "no thumbnail")
    return jpeg_response(path)


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
    return _public(item_or_404(item_id))


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
    try:
        await asyncio.to_thread(netguard.check_url, url)          # refuse private and local addresses up front
    except netguard.BlockedAddress as e:
        raise HTTPException(422, str(e)) from None
    payload: dict = {"url": url}
    clip = _clip_fields(body)
    if clip:
        payload["clip"] = clip
    with db.tx() as c:
        job_id = db.enqueue(c, "fetch", None, json.dumps(payload))
    return {"job_id": job_id}


def _clip_fields(body: dict) -> dict:
    """The optional title, description, tags and people a clipper sends with a link (cleaned, and capped)."""
    out: dict = {}
    if str(body.get("title") or "").strip():
        out["title"] = str(body["title"]).strip()[:120]
    if str(body.get("description") or "").strip():
        out["description"] = str(body["description"]).strip()[:2000]
    if isinstance(body.get("tags"), list):
        out["tags"] = [str(t)[:60] for t in body["tags"][:50] if str(t).strip()]
    if isinstance(body.get("people"), list):
        out["people"] = [p for p in body["people"][:50] if isinstance(p, int) and not isinstance(p, bool)]
    return out


@app.get("/api/v1/tags", dependencies=[Depends(api_auth)])
def api_tags(q: str = "", limit: int = 12):
    """Tags to offer while typing: those that contain q, or your most used ones when q is empty. Each comes with how many items carry it."""
    limit = max(1, min(limit, 50))
    with db.tx() as c:
        if q.strip():
            return db.suggest_tags(c, q, limit)
        rows = c.execute("SELECT tag, COUNT(DISTINCT item_id) AS n FROM tags WHERE source='user' GROUP BY tag ORDER BY n DESC, tag LIMIT ?", (limit,)).fetchall()
    return [{"tag": r["tag"], "n": r["n"]} for r in rows]


@app.get("/api/v1/people", dependencies=[Depends(api_auth)])
def api_people(q: str = "", limit: int = 12):
    """People to pick while typing: those whose alias or real name contains q, or the ones on the most items when q is empty."""
    limit = max(1, min(limit, 50))
    with db.tx() as c:
        found = people.search(c, q, limit) if q.strip() else people.everyone(c, sort="items")[:limit]
    return [{"id": p["id"], "name": p["name"], "first_name": p["first_name"], "surname": p["surname"],
             "picture_url": f"/people/{p['id']}/picture" if p["has_picture"] else None} for p in found]


@app.patch("/api/v1/items/{item_id}", dependencies=[Depends(api_auth)])
async def api_patch(item_id: int, request: Request):
    body = await request.json()
    item_or_404(item_id)
    with db.tx() as c:
        if "title" in body:
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (str(body["title"])[:120], item_id))
        if "description" in body:
            c.execute("UPDATE items SET description=? WHERE id=?", (str(body["description"])[:2000], item_id))
        if "tags" in body:
            db.set_user_tags(c, item_id, [str(t) for t in body["tags"]])
        if isinstance(body.get("people"), list):                  # exactly these people, by id (ids that do not exist are ignored)
            want = [p for p in body["people"] if isinstance(p, int) and not isinstance(p, bool)]
            for p in people.of_item(c, item_id):
                if p["id"] not in want:
                    people.unlink(c, item_id, p["id"])
            for pid in want:
                if c.execute("SELECT 1 FROM people WHERE id=?", (pid,)).fetchone():
                    people.link(c, item_id, pid)
        c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
        db.reindex(c, item_id)
    return _public(item_or_404(item_id))


@app.delete("/api/v1/items/{item_id}", dependencies=[Depends(api_auth)], status_code=204)
def api_delete(item_id: int):
    _delete_item(item_or_404(item_id))


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
def home(request: Request, q: str = "", kind: str = "", tag: str = "", src: str = "", page: int = 0, person: str = "", sort: str = ""):
    page = max(page, 0)
    sort = sort if sort in db.SORTS or sort == "best" else ""
    src = src if src in ("user", "ai") else ""
    with db.tx() as c:
        person = int(person) if person.strip().isdigit() else 0          # the form sends person= (empty) when nobody is selected
        person_row = people.get(c, person) if person > 0 else None
        person = person_row["id"] if person_row else 0                 # an unknown person is simply not a filter
        items = db.search(c, q, kind, tag, PAGE, page * PAGE, src, person, sort)
        counts = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) n FROM items GROUP BY kind")}
        pending = c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        album_ids = [i["id"] for i in items if i["kind"] == "album"]
        album_info = albums.summaries(c, album_ids)
        movie_info = movies.summaries(c, [i["id"] for i in items if i["kind"] == "movie"])
        track_hits = albums.track_hits(c, q, album_ids) if q.strip() else {}
    tpl = "grid.html" if request.headers.get("hx-request") and not request.headers.get("hx-boosted") else "index.html"
    bulk_people = []
    if tpl == "index.html":
        with db.tx() as c:
            bulk_people = [{"id": p["id"], "name": p["name"]} for p in people.everyone(c)]       # for the selection's "add person"
    return render(request, tpl, bulk_people=bulk_people, items=items, q=q, kind=kind, tag=tag, src=src, sort=sort, person_id=person, person_row=person_row, page=page, more=len(items) == PAGE, counts=counts, pending=pending, album_info=album_info, movie_info=movie_info, track_hits=track_hits)


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
        try:
            await asyncio.to_thread(netguard.check_url, url.strip())
        except netguard.BlockedAddress as e:
            return flash_redirect("/", e.message(), "error")
        with db.tx() as c:
            db.enqueue(c, "fetch", None, json.dumps({"url": url.strip()}))
        return RedirectResponse("/jobs", status_code=303)
    return RedirectResponse(f"/items/{last}" if last and len(files) == 1 else "/", status_code=303)


@app.get("/items/{item_id}", dependencies=[Depends(web_auth)])
def item_page(request: Request, item_id: int):
    item = item_or_404(item_id)
    with db.tx() as c:
        jobs = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE item_id=? ORDER BY id DESC", (item_id,))]
        if item["kind"] == "album":
            q = request.query_params.get("q", "")
            return render(request, "album.html", item=item, album=albums.get(c, item_id), facts=albums.facts(albums.get(c, item_id)),
                          item_people=people.of_item(c, item_id), transcription=albums.transcription_state(c, item_id), matches=albums.matching_track_ids(c, q, item_id) if q.strip() else set(), q=q, tracks=albums.tracks_of(c, item_id), **share_context(request, item))
    with db.tx() as c:
        item_people = people.of_item(c, item_id)
        movie = movies.get(c, item_id) if item["kind"] == "movie" else None
    return render(request, "item.html", item=item, jobs=jobs, item_people=item_people, movie=movie, movie_facts=movies.facts(movie) if movie else {},
                  subtypes=movies.SUBTYPES, **share_context(request, item))


BULK_MAX = 500          # items one bulk action may touch
BULK_ACTIONS = ("tag_add", "tag_remove", "person_add", "person_remove", "ai", "delete")


@app.post("/items/bulk", dependencies=[Depends(web_auth)])
def items_bulk(ids: str = Form(""), action: str = Form(""), tags: str = Form(""), person_id: str = Form(""), step: str = Form(""),
               next: str = Form("/")):
    """One action for several items at once (the selection on the library page). `ids` is a comma separated list of item ids."""
    back = shares.safe_next(next, "/")
    wanted = list(dict.fromkeys(int(x) for x in ids.replace(" ", "").split(",") if x.isdigit() and int(x) > 0))
    if action not in BULK_ACTIONS or not wanted:
        return flash_redirect(back, t("Select some items and choose an action"), "error")
    if len(wanted) > BULK_MAX:
        return flash_redirect(back, t("That is too many at once: {n} items at most", n=BULK_MAX), "error")
    new_tags = list(dict.fromkeys(db.normalize_tag(x) for x in _parse_tags(tags) if db.normalize_tag(x)))
    if action in ("tag_add", "tag_remove") and not new_tags:
        return flash_redirect(back, t("Type at least one tag"), "error")
    person = None
    if action in ("person_add", "person_remove"):
        with db.tx() as c:
            person = people.get(c, int(person_id)) if person_id.strip().isdigit() and int(person_id) > 0 else None
        if person is None:
            return flash_redirect(back, t("Choose a person"), "error")
    done = 0
    with db.tx() as c:
        have = {r["id"] for r in c.execute(f"SELECT id FROM items WHERE id IN ({','.join('?' * len(wanted))})", wanted)}
        found = [i for i in wanted if i in have]
        if action == "delete":
            doomed = [db.get_item(c, i) for i in found]
        elif action == "ai":
            busy = {r[0] for r in c.execute("SELECT DISTINCT item_id FROM jobs WHERE status IN ('queued','running') AND item_id IS NOT NULL")}
        for i in found:
            if action == "tag_add":
                mine = db.get_item(c, i)["tags"]
                db.set_user_tags(c, i, mine + [x for x in new_tags if x not in mine])
                done += 1
            elif action == "tag_remove":
                mine = db.get_item(c, i)["tags"]
                if any(x in mine for x in new_tags):
                    db.set_user_tags(c, i, [x for x in mine if x not in new_tags])
                    done += 1
            elif action == "person_add":
                done += people.link(c, i, person["id"])
            elif action == "person_remove":
                had = c.execute("SELECT 1 FROM item_people WHERE item_id=? AND person_id=?", (i, person["id"])).fetchone()
                if had:
                    people.unlink(c, i, person["id"])
                    done += 1
            elif action == "ai":
                if i not in busy and pipeline.plan_jobs(c, i, step if step in ("transcribe", "describe") else ""):
                    done += 1
    if action == "delete":                                                # the files go outside the transaction, like a single delete
        for item in doomed:
            _delete_item(item)
            done += 1
    gone = len(wanted) - len(found)
    text = {
        "tag_add": lambda: tn("Tags added to {n} item", "Tags added to {n} items", done),
        "tag_remove": lambda: tn("Tags removed from {n} item", "Tags removed from {n} items", done),
        "person_add": lambda: tn("{name} added to {n} item", "{name} added to {n} items", done, name=person["name"] if person else ""),
        "person_remove": lambda: tn("{name} removed from {n} item", "{name} removed from {n} items", done, name=person["name"] if person else ""),
        "ai": lambda: tn("Queued AI processing for {n} item", "Queued AI processing for {n} items", done) if done
                      else t("Nothing to queue: no AI model is assigned, or every item is already queued"),
        "delete": lambda: tn("Deleted {n} item", "Deleted {n} items", done),
    }[action]()
    if gone:
        text += ". " + tn("{n} item was not found", "{n} items were not found", gone)
    return flash_redirect(back, text)


@app.post("/items/{item_id}/edit", dependencies=[Depends(web_auth)])
def item_edit(item_id: int, title: str = Form(""), description: str = Form(""), tags: str = Form(""), artist: str | None = Form(None),
              subtype: str | None = Form(None), original_title: str | None = Form(None)):
    item = item_or_404(item_id)
    with db.tx() as c:
        if title.strip() != item["title"]:
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (title.strip()[:120], item_id))
        c.execute("UPDATE items SET description=?, updated_at=? WHERE id=?", (description.strip()[:2000], time.time(), item_id))
        db.set_user_tags(c, item_id, _parse_tags(tags))
        if item["kind"] == "album" and artist is not None:
            c.execute("UPDATE albums SET artist=? WHERE item_id=?", (artist.strip()[:120], item_id))
            db.reindex(c, item_id)
        if item["kind"] == "movie" and subtype is not None:
            movies.update(c, item_id, subtype, original_title or "")
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/ai-tags/keep", dependencies=[Depends(web_auth)])
def item_keep_ai_tags(item_id: int, tag: str = Form("")):
    """Promote one AI tag (or all of them) to the user's own tags."""
    item_or_404(item_id)
    with db.tx() as c:
        db.keep_ai_tags(c, item_id, tag)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/ai-tags/remove", dependencies=[Depends(web_auth)])
def item_remove_ai_tags(item_id: int, tag: str = Form("")):
    """Remove one AI tag (or all of them); the AI will not suggest a removed tag again for this item."""
    item_or_404(item_id)
    with db.tx() as c:
        db.dismiss_ai_tags(c, item_id, tag)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/reprocess", dependencies=[Depends(web_auth)])
def item_reprocess(item_id: int, step: str = Form("")):
    """Run the AI steps again: both (the default), or only "transcribe" or only "describe"."""
    item_or_404(item_id)
    with db.tx() as c:
        pipeline.plan_jobs(c, item_id, step if step in ("transcribe", "describe") else "")
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/delete", dependencies=[Depends(web_auth)])
def item_delete(item_id: int):
    _delete_item(item_or_404(item_id))
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
    db.retry_failed_jobs()
    return RedirectResponse("/jobs", status_code=303)


@app.post("/jobs/delete-failed", dependencies=[Depends(web_auth)])
def jobs_delete_failed():
    """Clear every failed job from the list (nothing is retried and no item is touched)."""
    n = db.delete_failed_jobs()
    return flash_redirect("/jobs", t("Deleted {n} failed job(s)", n=n) if n else t("There were no failed jobs"))


@app.post("/jobs/{job_id}/delete", dependencies=[Depends(web_auth)])
def job_delete(job_id: int):
    if db.delete_failed_jobs(job_id):
        return flash_redirect("/jobs", t("Job deleted"))
    return flash_redirect("/jobs", t("That job can't be deleted: only failed jobs can be removed"), "error")


@app.post("/jobs/{job_id}/retry", dependencies=[Depends(web_auth)])
def job_retry(job_id: int, next: str = Form("/jobs")):
    """Run one failed job again, from the jobs list or from an item page."""
    back = shares.safe_next(next, "/jobs")
    if db.retry_job(job_id):
        return flash_redirect(back, t("Job queued again"))
    return flash_redirect(back, t("That job can't be retried: it isn't in a failed state any more"), "error")
