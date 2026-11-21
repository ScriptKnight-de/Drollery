from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import aisettings, db, media, providers
from .config import get_settings

log = logging.getLogger("drollery")


# ---------------------------------------------------------------- import

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def media_path(item: dict) -> Path:
    s = get_settings()
    return s.media_dir / item["sha256"][:2] / f"{item['sha256']}{item['ext']}"


def thumb_path(item: dict) -> Path:
    return get_settings().thumbs_dir / f"{item['sha256']}.jpg"


def _title_from_name(name: str) -> str:
    return re.sub(r"[\s_]+", " ", Path(name).stem).strip()[:120] or "untitled"


def import_file(src: Path, original_name: str, source_url: str = "", source_meta: str = "",
                title: str = "", tags: list[str] | None = None) -> tuple[int, bool]:
    """Store a file in the library. Returns (item_id, created). Duplicates (same SHA-256) are not re-added."""
    s = get_settings()
    kind, mime = media.guess(original_name)
    sha = _sha256(src)
    with db.tx() as c:
        row = c.execute("SELECT id FROM items WHERE sha256=?", (sha,)).fetchone()
        if row:
            return row["id"], False

    info = media.probe(src)
    ext = Path(original_name).suffix.lower()
    dest = s.media_dir / sha[:2] / f"{sha}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    has_thumb = media.make_thumb(dest, s.thumbs_dir / f"{sha}.jpg", kind, info["duration"])

    now = time.time()
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO items(kind,title,title_locked,mime,ext,original_name,size,sha256,duration,width,height,"
            "has_audio,has_thumb,source_url,source_meta,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, title or _title_from_name(original_name), 1 if title else 0, mime, ext, original_name,
             dest.stat().st_size, sha, info["duration"], info["width"], info["height"],
             int(info["has_audio"]), int(has_thumb), source_url, source_meta, now, now))
        item_id = cur.lastrowid
        if tags:
            db.set_tags(c, item_id, tags, "user")
        db.reindex(c, item_id)
        plan_jobs(c, item_id)
    return item_id, True


def plan_jobs(c, item_id: int) -> list[str]:
    """Queue the background jobs that the enabled providers can do for this item."""
    item = db.get_item(c, item_id)
    queued = []
    if item["kind"] == "image" and aisettings.enabled("ocr"):
        queued.append("ocr")
    has_speech = item["kind"] != "image" and item["has_audio"] and aisettings.enabled("transcribe")
    if has_speech:
        queued.append("transcribe")          # transcribe chains into describe when it finishes
    elif aisettings.enabled("describe") and (item["kind"] != "audio"):
        queued.append("describe")
    for t in queued:
        db.enqueue(c, t, item_id)
    return queued


# ------------------------------------------------------------- handlers

def _item(item_id: int) -> dict:
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None:
        raise providers.ProviderError("item no longer exists")
    return item


def job_transcribe(job: dict) -> None:
    s = get_settings()
    item = _item(job["item_id"])
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td:
        audio = Path(td) / "audio.mp3"
        media.extract_audio(media_path(item), audio)
        text = providers.transcribe(aisettings.provider("transcribe"), audio)
    with db.tx() as c:
        c.execute("UPDATE items SET transcript=?, updated_at=? WHERE id=?", (text, time.time(), item["id"]))
        db.reindex(c, item["id"])
        if aisettings.enabled("describe"):
            db.enqueue(c, "describe", item["id"])


def job_describe(job: dict) -> None:
    s = get_settings()
    item = _item(job["item_id"])
    image = thumb_path(item) if item["has_thumb"] else None
    with db.tx() as c:
        existing = db.popular_tags(c)
    result = providers.describe(aisettings.provider("describe"), image, item["transcript"], existing)
    with db.tx() as c:
        cur = db.get_item(c, item["id"])
        if cur is None:
            return
        if not cur["title_locked"] and result["name"]:
            c.execute("UPDATE items SET title=? WHERE id=?", (result["name"], item["id"]))
        if result["description"]:
            c.execute("UPDATE items SET description=? WHERE id=?", (result["description"], item["id"]))
        c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item["id"]))
        db.set_tags(c, item["id"], result["tags"], "ai")


def job_ocr(job: dict) -> None:
    s = get_settings()
    item = _item(job["item_id"])
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td:
        still = Path(td) / "still.png"
        media.ocr_image(media_path(item), still, item["kind"])
        text = providers.ocr(aisettings.provider("ocr"), still)
    with db.tx() as c:
        c.execute("UPDATE items SET ocr=?, updated_at=? WHERE id=?", (text, time.time(), item["id"]))
        db.reindex(c, item["id"])


# ------------------------------------------------------------- download

def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", name).strip()[:150] or "download"


def _direct_download(url: str, td: Path) -> list[Path]:
    """If the URL itself is an image/video/audio file, fetch it directly."""
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=30) as r:
            ctype = r.headers.get("content-type", "").split(";")[0].strip()
            if r.status_code != 200 or ctype.split("/")[0] not in media.KINDS:
                return []
            name = Path(urlparse(str(r.url)).path).name or "download"
            if not Path(name).suffix:
                ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
                       "video/mp4": ".mp4", "video/webm": ".webm", "audio/mpeg": ".mp3"}.get(ctype, "")
                name += ext
            dest = td / _safe_name(name)
            limit = get_settings().max_upload_mb * 1024 * 1024
            size = 0
            with dest.open("wb") as f:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise providers.ProviderError("file exceeds max_upload_mb")
                    f.write(chunk)
            return [dest]
    except httpx.HTTPError:
        return []


def _run_tool(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def job_fetch(job: dict) -> None:
    s = get_settings()
    url = json.loads(job["payload"])["url"]
    if urlparse(url).scheme not in ("http", "https"):
        raise providers.ProviderError("only http(s) URLs are supported")
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as tds:
        td = Path(tds)
        meta: dict[Path, dict] = {}
        files = _direct_download(url, td)
        if not files:
            r = _run_tool(["yt-dlp", "--no-playlist", "--no-warnings", "--write-info-json",
                           "--max-filesize", f"{s.max_upload_mb}M",
                           "-o", str(td / "%(title).80B [%(id)s].%(ext)s"), url], s.fetch_timeout)
            err1 = r.stderr.strip()[-300:]
            files = [p for p in td.iterdir() if p.suffix != ".json" and not p.name.endswith(".part")]
            for info in td.glob("*.info.json"):
                try:
                    d = json.loads(info.read_text())
                except ValueError:
                    continue
                for f in files:
                    if f.name.startswith(info.name.removesuffix(".info.json")):
                        meta[f] = d
            if not files:
                gdir = td / "gallery"
                r = _run_tool(["gallery-dl", "-q", "-D", str(gdir), "--range", f"1-{s.fetch_max_files}",
                               "--filesize-max", f"{s.max_upload_mb}M", url], s.fetch_timeout)
                files = sorted(gdir.iterdir()) if gdir.exists() else []
                if not files:
                    raise providers.ProviderError(
                        f"nothing downloadable found. yt-dlp: {err1 or '-'} | gallery-dl: {r.stderr.strip()[-200:] or '-'}")
        imported = 0
        for f in files[: s.fetch_max_files]:
            try:
                media.guess(f.name)
            except media.MediaError:
                continue
            d = meta.get(f, {})
            who = " ".join(str(x) for x in (d.get("uploader"), d.get("channel")) if x)
            desc = (d.get("description") or "")[:500]
            item_id, created = import_file(f, f.name, source_url=url,
                                           source_meta=f"{who} {d.get('title', '')} {desc}".strip())
            if created and d.get("title"):
                with db.tx() as c:
                    c.execute("UPDATE items SET title=? WHERE id=? AND title_locked=0",
                              (str(d["title"])[:120], item_id))
                    db.reindex(c, item_id)
            imported += 1
        if not imported:
            raise providers.ProviderError("downloaded files were not images, video or audio")


HANDLERS = {"fetch": job_fetch, "transcribe": job_transcribe, "describe": job_describe, "ocr": job_ocr}


def run_job(job: dict) -> None:
    s = get_settings()
    handler = HANDLERS.get(job["type"])
    try:
        if handler is None:
            raise providers.ProviderError(f"unknown job type {job['type']!r}")
        handler(job)
        db.finish_job(job["id"], None, s.job_max_attempts, job["attempts"])
    except Exception as e:  # noqa: BLE001 - a job must never crash the worker
        log.warning("job %s (%s) failed: %s", job["id"], job["type"], e)
        db.finish_job(job["id"], f"{type(e).__name__}: {e}", s.job_max_attempts, job["attempts"])
