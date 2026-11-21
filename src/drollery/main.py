from __future__ import annotations

import asyncio
import hmac
import json
import logging
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, db, media, pipeline
from .config import get_settings

log = logging.getLogger("drollery")
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")
COOKIE = "drollery_token"
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    db.init()
    for old in s.tmp_dir.iterdir():
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    if not s.token:
        log.warning("DROLLERY_TOKEN is not set: the UI and API are open to anyone who can reach this port")
    stop = asyncio.Event()
    tasks = [asyncio.create_task(_worker_loop(stop)) for _ in range(max(1, s.worker_concurrency))]
    yield
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Drollery", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


# ------------------------------------------------------------------- auth

def _token_ok(request: Request) -> bool:
    token = get_settings().token
    if not token:
        return True
    supplied = request.cookies.get(COOKIE, "")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    return hmac.compare_digest(supplied.encode(), token.encode())


def api_auth(request: Request) -> None:
    if not _token_ok(request):
        raise HTTPException(401, "missing or invalid token", headers={"WWW-Authenticate": "Bearer"})


class LoginRequired(Exception):
    pass


def web_auth(request: Request) -> None:
    if not _token_ok(request):
        raise LoginRequired


@app.exception_handler(LoginRequired)
async def _login_redirect(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    """Browsers get a friendly 404 page; the API and media routes keep JSON errors."""
    if (exc.status_code == 404 and "text/html" in request.headers.get("accept", "")
            and not request.url.path.startswith(("/api/", "/media/", "/thumb/"))):
        return templates.TemplateResponse(request, "404.html", _ctx(), status_code=404)
    return await http_exception_handler(request, exc)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: int = 0):
    return templates.TemplateResponse(request, "login.html", {"error": bool(error)})


@app.post("/login")
def login(token: str = Form("")):
    ok = hmac.compare_digest(token.encode(), get_settings().token.encode())
    if not ok:
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


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
        return await asyncio_to_thread(pipeline.import_file, Path(tmp.name), name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


async def asyncio_to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _public(item: dict) -> dict:
    out = {k: v for k, v in item.items() if k not in ("sha256", "title_locked", "has_thumb")}
    out["url"] = f"/media/{item['id']}"
    out["thumb_url"] = f"/thumb/{item['id']}" if item["has_thumb"] else None
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
        c.execute("DELETE FROM items WHERE id=?", (item["id"],))
    pipeline.media_path(item).unlink(missing_ok=True)
    pipeline.thumb_path(item).unlink(missing_ok=True)


# ------------------------------------------------------------------ files

@app.get("/media/{item_id}", dependencies=[Depends(api_auth)])
def media_file(item_id: int):
    item = _get_or_404(item_id)
    path = pipeline.media_path(item)
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, media_type=item["mime"], filename=item["original_name"] or None,
                        content_disposition_type="inline")


@app.get("/thumb/{item_id}", dependencies=[Depends(api_auth)])
def thumb_file(item_id: int):
    item = _get_or_404(item_id)
    path = pipeline.thumb_path(item)
    if not item["has_thumb"] or not path.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# -------------------------------------------------------------------- API

@app.get("/api/v1/items", dependencies=[Depends(api_auth)])
def api_list(q: str = "", kind: str = "", tag: str = "", limit: int = PAGE, offset: int = 0):
    with db.tx() as c:
        items = db.search(c, q, kind, tag, min(max(limit, 1), 200), max(offset, 0))
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
            db.set_tags(c, item_id, [str(t) for t in body["tags"]], "user", replace=True)
        c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
        db.reindex(c, item_id)
    return _public(_get_or_404(item_id))


@app.delete("/api/v1/items/{item_id}", dependencies=[Depends(api_auth)], status_code=204)
def api_delete(item_id: int):
    _delete_item(_get_or_404(item_id))


@app.get("/api/v1/jobs", dependencies=[Depends(api_auth)])
def api_jobs(limit: int = 50):
    with db.tx() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return {"jobs": [dict(r) for r in rows]}


# --------------------------------------------------------------------- web

def _ctx(**extra):
    s = get_settings()
    return {"auth_enabled": bool(s.token), "providers": {
        "transcribe": s.transcribe.enabled, "describe": s.describe.enabled, "ocr": s.ocr.enabled}, **extra}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def home(request: Request, q: str = "", kind: str = "", tag: str = "", page: int = 0):
    page = max(page, 0)
    with db.tx() as c:
        items = db.search(c, q, kind, tag, PAGE, page * PAGE)
        counts = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) n FROM items GROUP BY kind")}
        pending = c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    ctx = _ctx(items=items, q=q, kind=kind, tag=tag, page=page, more=len(items) == PAGE,
               counts=counts, pending=pending)
    tpl = "grid.html" if request.headers.get("hx-request") and not request.headers.get("hx-boosted") else "index.html"
    return templates.TemplateResponse(request, tpl, ctx)


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


@app.get("/items/{item_id}", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def item_page(request: Request, item_id: int):
    item = _get_or_404(item_id)
    with db.tx() as c:
        jobs = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE item_id=? ORDER BY id DESC", (item_id,))]
    return templates.TemplateResponse(request, "item.html", _ctx(item=item, jobs=jobs))


@app.post("/items/{item_id}/edit", dependencies=[Depends(web_auth)])
def item_edit(item_id: int, title: str = Form(""), description: str = Form(""), tags: str = Form("")):
    item = _get_or_404(item_id)
    with db.tx() as c:
        if title.strip() != item["title"]:
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (title.strip()[:120], item_id))
        c.execute("UPDATE items SET description=?, updated_at=? WHERE id=?", (description.strip()[:2000], time.time(), item_id))
        db.set_tags(c, item_id, _parse_tags(tags), "user", replace=True)
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


@app.get("/jobs", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def jobs_page(request: Request):
    with db.tx() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT jobs.*, items.title AS item_title FROM jobs LEFT JOIN items ON items.id=jobs.item_id "
            "ORDER BY jobs.id DESC LIMIT 100")]
    for r in rows:
        if r["type"] == "fetch":
            r["label"] = json.loads(r["payload"]).get("url", "")
        else:
            r["label"] = r["item_title"] or ""
    return templates.TemplateResponse(request, "jobs.html", _ctx(jobs=rows))


@app.post("/jobs/retry-failed", dependencies=[Depends(web_auth)])
def jobs_retry():
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='queued', attempts=0, run_after=0 WHERE status='failed'")
    return RedirectResponse("/jobs", status_code=303)
