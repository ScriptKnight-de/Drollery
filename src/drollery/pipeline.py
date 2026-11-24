from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import accounts, aisettings, db, media, netguard, people, providers
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


def card_path(item: dict) -> Path:
    return get_settings().cards_dir / f"{item['sha256']}.jpg"


def card_source_path(item: dict) -> Path:
    """A picture the person brought for the card image; when it exists the card is cropped from it, not from the item."""
    return get_settings().cards_dir / f"{item['sha256']}.src.jpg"


def web_path(item: dict) -> Path:
    """The browser-friendly copy of a video or movie (H.264 + AAC in an MP4), made on request. The original is never touched."""
    return get_settings().media_dir / item["sha256"][:2] / f"{item['sha256']}.web.mp4"


def _title_from_name(name: str) -> str:
    return re.sub(r"[\s_]+", " ", Path(name).stem).strip()[:120] or "untitled"


def import_file(src: Path, original_name: str, source_url: str = "", source_meta: str = "",
                title: str = "", tags: list[str] | None = None, as_movie: bool = False) -> tuple[int, bool]:
    """Store a file in the library. Returns (item_id, created). Duplicates (same SHA-256) are not re-added.
    as_movie stores a video file as a movie (the caller adds the movie facts)."""
    s = get_settings()
    kind, mime = media.guess(original_name)
    if as_movie and kind != "video":
        raise media.MediaError("a movie must be a video file")
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
            ("movie" if as_movie else kind, title or _title_from_name(original_name), 1 if title else 0, mime, ext, original_name,
             dest.stat().st_size, sha, info["duration"], info["width"], info["height"],
             int(info["has_audio"]), int(has_thumb), source_url, source_meta, now, now))
        item_id = cur.lastrowid
        if tags:
            db.set_user_tags(c, item_id, tags)
        db.reindex(c, item_id)
        plan_jobs(c, item_id, auto=True)
    return item_id, True


def plan_track_jobs(c, item_id: int, redo: bool = False) -> int:
    """Queue speech-to-text for the tracks of an album that have none yet (all of them with redo), skipping tracks that
    are already waiting. Returns how many jobs were queued."""
    waiting = set()
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE item_id=? AND type='transcribe_track' AND status IN ('queued','running')", (item_id,)):
        try:
            waiting.add(int(json.loads(payload).get("track_id", 0)))
        except (ValueError, TypeError, AttributeError):
            pass
    n = 0
    for row in c.execute("SELECT id, transcribed_at FROM tracks WHERE item_id=? ORDER BY position", (item_id,)).fetchall():
        if row["id"] in waiting or (row["transcribed_at"] is not None and not redo):
            continue
        db.enqueue(c, "transcribe_track", item_id, json.dumps({"track_id": row["id"]}))
        n += 1
    return n


def plan_jobs(c, item_id: int, only: str = "", auto: bool = False) -> list[str]:
    """Queue the background jobs that the enabled providers can do for this item.

    only="transcribe" or only="describe" starts just that one step: a transcription then does not go on to describe, and
    describing works from what is there (the picture, and the transcript if the item has one).

    auto=True is an import (an upload, a link, a new album): a step then starts only if it is set up AND not switched off
    for imports (Settings > AI models). A person asking for it by hand always gets it, as long as the model is set up."""
    def ready(cap: str) -> bool:
        return aisettings.enabled(cap) and (not auto or aisettings.auto(cap))
    payload = {"auto": True} if auto else {}
    item = db.get_item(c, item_id)
    queued = []
    if item["kind"] == "album":
        # an album is many tracks: nothing to describe as a whole, but every track can be transcribed so its words are searchable
        if only != "describe" and ready("transcribe"):
            queued += ["transcribe_track"] * plan_track_jobs(c, item_id)
        return queued
    if item["kind"] == "movie":
        return queued                        # a movie runs for hours: nothing is transcribed or named behind the person's back
    has_speech = item["kind"] not in ("image", "gif") and item["has_audio"] and ready("transcribe")
    if only == "transcribe":
        if has_speech:
            db.enqueue(c, "transcribe", item_id, json.dumps({"describe_after": False}))
            queued.append("transcribe")
        return queued
    if only == "describe":
        if aisettings.enabled("describe"):
            db.enqueue(c, "describe", item_id)
            queued.append("describe")
        return queued
    if has_speech:
        queued.append("transcribe")          # transcribe chains into describe when it finishes
    elif ready("describe") and (item["kind"] != "audio"):
        queued.append("describe")
    for t in queued:
        db.enqueue(c, t, item_id, json.dumps(payload))
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
        p = _payload(job)
        if aisettings.enabled("describe") and p.get("describe_after", True) and (not p.get("auto") or aisettings.auto("describe")):
            db.enqueue(c, "describe", item["id"])


def _payload(job: dict) -> dict:
    try:
        data = json.loads(job.get("payload") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _chunk_seconds(cfg) -> int:
    """Length of the pieces a track is cut into: well inside the model's timeout, so a long track never times out."""
    return int(max(60, min(300, cfg.timeout * 0.5)))


def job_transcribe_track(job: dict) -> None:
    from . import albums
    s = get_settings()
    track_id = int(json.loads(job["payload"] or "{}").get("track_id", 0))
    with db.tx() as c:
        item = db.get_item(c, job["item_id"])
        row = c.execute("SELECT * FROM tracks WHERE id=? AND item_id=?", (track_id, job["item_id"])).fetchone()
    if item is None or row is None:
        return                                           # the album or the track is gone; nothing left to do
    cfg = aisettings.provider("transcribe")
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td:
        parts = media.split_audio(albums.track_path(item, dict(row)), Path(td), _chunk_seconds(cfg))
        text = " ".join(piece for piece in (providers.transcribe(cfg, p) for p in parts) if piece)
    with db.tx() as c:
        c.execute("UPDATE tracks SET transcript=?, transcribed_at=? WHERE id=?", (text, time.time(), track_id))
        db.reindex_tracks(c, item["id"])
        db.reindex(c, item["id"])


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
        db.set_ai_tags(c, item["id"], result["tags"])


# ------------------------------------------------------------- download

def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", name).strip()[:150] or "download"


def _get_checked(client: httpx.Client, url: str) -> httpx.Response:
    """GET a link, following redirects by hand so that every address on the way is checked (see netguard.py)."""
    for _ in range(netguard.MAX_HOPS + 1):
        netguard.check_url(url)
        r = client.send(client.build_request("GET", url), stream=True, follow_redirects=False)
        location = r.headers.get("location")
        if r.status_code in netguard.REDIRECTS and location:
            url = str(httpx.URL(url).join(location))
            r.close()
            continue
        return r
    raise providers.ProviderError("too many redirects")


def _direct_download(url: str, td: Path) -> list[Path]:
    """If the URL itself is an image/video/audio file, fetch it directly."""
    try:
        with netguard.make_client() as client:
            r = _get_checked(client, url)
            try:
                return _save_direct(r, td)
            finally:
                r.close()
    except httpx.HTTPError:
        return []


def _save_direct(r: httpx.Response, td: Path) -> list[Path]:
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


_running = threading.local()                       # the fetch job this thread is working on (its progress is shown to the person)
_PERCENT = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")


def _set_progress(job_id: int, percent: float | None) -> None:
    with db.tx() as c:
        c.execute("UPDATE jobs SET progress=? WHERE id=?", (percent, job_id))


def _run_tool(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    job_id = getattr(_running, "job_id", None)
    if not job_id or cmd[0] != "yt-dlp":
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    # yt-dlp for a fetch job: its output is read while it runs, so the percentage reaches the progress bar on the library page
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    timed_out = []
    timer = threading.Timer(timeout, lambda: (timed_out.append(1), proc.kill()))
    timer.start()
    out, shown = [], -1
    try:
        for line in proc.stdout:
            out.append(line)
            m = _PERCENT.search(line)
            pct = min(99, int(float(m.group(1)))) if m else -1
            if pct > shown:                                         # never goes back: the video and then the sound are two downloads
                shown = pct
                _set_progress(job_id, shown)
        proc.wait()
    finally:
        timer.cancel()
        reader.join(timeout=5)
    if timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout)
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(out), "".join(errors))


def apply_clip(item_id: int, created: bool, clip: dict) -> None:
    """What a clipper sent along with a link: tags and people are added to the item (an item that was already there keeps its own
    title and description, and keeps everything it has)."""
    with db.tx() as c:
        if created:
            if clip.get("title"):
                c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (str(clip["title"])[:120], item_id))
            if clip.get("description"):
                c.execute("UPDATE items SET description=? WHERE id=?", (str(clip["description"])[:2000], item_id))
        if clip.get("tags"):
            have = [r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=? AND source='user'", (item_id,))]
            db.set_user_tags(c, item_id, have + [str(t) for t in clip["tags"]])
        for pid in clip.get("people") or []:
            if isinstance(pid, int) and c.execute("SELECT 1 FROM people WHERE id=?", (pid,)).fetchone():
                people.link(c, item_id, pid)
        db.reindex(c, item_id)


class ConvertError(providers.ProviderError):
    """A conversion that cannot work by trying again (a wrong file, no room, ffmpeg's own refusal): the job fails at once."""
    final = True


_OUT_TIME = re.compile(r"out_time_(?:us|ms)=(\d+)")
CONVERT_MARGIN = 512 * 1024 * 1024               # free space that must remain after the copy is made


def job_convert(job: dict) -> None:
    """Make a copy of a video or movie that every browser can play: H.264 video (even sides, 4:2:0), stereo AAC sound, the
    index at the front so it starts at once. Files a browser cannot decode (HEVC, AV1, 10-bit, odd containers) play from it."""
    s = get_settings()
    item = _item(job["item_id"])
    if item["kind"] not in ("video", "movie"):
        raise ConvertError("only videos and movies can be converted")
    src = media_path(item)
    if not src.exists():
        raise ConvertError("the file is missing on disk")
    if shutil.disk_usage(s.data_dir).free < src.stat().st_size + CONVERT_MARGIN:
        raise ConvertError("there is not enough free disk space for a second copy of this file")
    duration = float(item["duration"] or 0)
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td:
        out = Path(td) / "web.mp4"
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn",
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        errors: list[str] = []
        reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
        reader.start()
        shown = -1
        for line in proc.stdout:
            m = _OUT_TIME.match(line.strip())
            if m and duration > 0:
                pct = min(99, int(int(m.group(1)) / 1_000_000 / duration * 100))
                if pct > shown:
                    shown = pct
                    _set_progress(job["id"], pct)
        proc.wait()
        reader.join(timeout=5)
        if proc.returncode != 0 or not out.exists():
            raise ConvertError(("".join(errors).strip()[-800:]) or f"ffmpeg ended with code {proc.returncode}")
        dest = web_path(item)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.replace(dest)                                   # same disk: the copy appears all at once, never half-written
    _set_progress(job["id"], 100)


def _kind_of(f: Path) -> str:
    try:
        return media.guess(f.name)[0]
    except media.MediaError:
        return ""


def _refuse_audio_left_over(files: list[Path], meta: dict[Path, dict], stderr: str, limit_mb: int) -> None:
    """A video over the size limit is skipped by yt-dlp, but its small audio stream still downloads. Saving that would put a
    sound in the library where the person asked for a video, so the job fails and says why instead."""
    if not files or any(_kind_of(f) != "audio" for f in files):
        return
    said_so = "larger than max-filesize" in stderr
    has_picture = any((fmt.get("vcodec") or "none") != "none"
                      for f in files for fmt in (meta.get(f, {}).get("requested_formats") or [])) or \
                  any((meta.get(f, {}).get("vcodec") or "none") not in ("none", "audio only") for f in files)
    if said_so or has_picture:
        raise providers.ProviderError(
            f"the video is larger than the limit of {limit_mb} MB, so only its sound could be downloaded. Nothing was saved. "
            f"Raise max_upload_mb in config.toml to fetch it")


def job_fetch(job: dict) -> None:
    _running.job_id = job.get("id")
    try:
        _fetch(job)
    finally:
        _running.job_id = None


def _fetch(job: dict) -> None:
    s = get_settings()
    first_item = 0
    payload = json.loads(job["payload"])
    url, clip = payload["url"], payload.get("clip") or {}
    if urlparse(url).scheme not in ("http", "https"):
        raise providers.ProviderError("only http(s) URLs are supported")
    netguard.check_url(url)                           # also here: a job may have been queued before the check existed, or the address may have changed
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as tds:
        td = Path(tds)
        meta: dict[Path, dict] = {}
        files = _direct_download(url, td)
        if not files:
            netguard.check_redirects(url)             # yt-dlp and gallery-dl follow redirects themselves: make sure the way is clean first
            # Prefer H.264/AAC and always merge to .mp4: it plays in every browser. Without this, YouTube pairs like H.264 video
            # + Opus audio are merged into .mkv, which many browsers cannot play. The codec comes BEFORE the resolution: -S is only a
            # ranking, so with the resolution first a 1080p HEVC stream (TikTok offers one) beat a lower-resolution H.264 one, and
            # Firefox on Linux then said "no video with supported format and MIME type found".
            r = _run_tool(["yt-dlp", "--no-playlist", "--no-warnings", "--write-info-json",
                           "--newline", "-S", "vcodec:h264,res:1080,acodec:aac", "--merge-output-format", "mp4",
                           "--max-filesize", f"{s.max_upload_mb}M",
                           "-o", str(td / "%(title).80B [%(id)s].%(ext)s"), url], s.fetch_timeout)
            err1 = r.stderr.strip()[-1500:]
            files = [p for p in td.iterdir() if p.suffix != ".json" and not p.name.endswith(".part")]
            for info in td.glob("*.info.json"):
                try:
                    d = json.loads(info.read_text())
                except ValueError:
                    continue
                for f in files:
                    if f.name.startswith(info.name.removesuffix(".info.json")):
                        meta[f] = d
            _refuse_audio_left_over(files, meta, r.stderr, s.max_upload_mb)
            if not files:
                gdir = td / "gallery"
                r = _run_tool(["gallery-dl", "-q", "-D", str(gdir), "--range", f"1-{s.fetch_max_files}",
                               "--filesize-max", f"{s.max_upload_mb}M", url], s.fetch_timeout)
                files = sorted(gdir.iterdir()) if gdir.exists() else []
                if not files:
                    raise providers.ProviderError(
                        f"nothing downloadable found. yt-dlp: {err1 or '-'} | gallery-dl: {r.stderr.strip()[-1500:] or '-'}")
        imported, skipped = 0, []
        for f in files[: s.fetch_max_files]:
            try:
                media.guess(f.name)
            except media.MediaError:
                skipped.append(f.name)
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
            if clip:
                apply_clip(item_id, created, clip)
            first_item = first_item or item_id
            imported += 1
        if imported:                                         # the progress bar on the library page opens this item when it is done
            with db.tx() as c:
                c.execute("UPDATE jobs SET item_id=?, progress=100 WHERE id=? AND item_id IS NULL", (first_item, job.get("id")))
        if not imported:
            names = ", ".join(skipped[:5]) or "(no files)"
            raise providers.ProviderError(f"downloaded files were not recognised as images, video or audio: {names}")


# ------------------------------------------------------------- upkeep

VIDEO_SIZES_DONE = "maintenance.video_sizes"        # set once every stored video has been looked at again
SEARCH_SPELLINGS_DONE = "maintenance.search_spellings"   # set once the search index has the other spelling of umlaut words


def plan_upkeep(c) -> None:
    """Queue the one-time jobs a library may still need (called when the app starts)."""
    if accounts.get_setting(VIDEO_SIZES_DONE) is None:
        pending = c.execute("SELECT 1 FROM jobs WHERE type='check_video_sizes' AND status IN ('queued','running')").fetchone()
        if not pending and c.execute("SELECT 1 FROM items WHERE kind IN ('video','movie') LIMIT 1").fetchone():
            db.enqueue(c, "check_video_sizes")
    if accounts.get_setting(SEARCH_SPELLINGS_DONE) is None:
        if not c.execute("SELECT 1 FROM items LIMIT 1").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES (?,'1') ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SEARCH_SPELLINGS_DONE,))   # an empty library is indexed the new way from the start (written on this connection: a second one would wait for it)
        elif not c.execute("SELECT 1 FROM jobs WHERE type='rebuild_search' AND status IN ('queued','running')").fetchone():
            db.enqueue(c, "rebuild_search")


def job_check_video_sizes(job: dict) -> None:
    """Before 0.2.6 a video recorded on its side was stored with the size of its frames (1920x1080) and not the size people
    see (1080x1920). Read every stored video again and correct the size. Nothing else about an item is touched."""
    with db.tx() as c:
        items = [dict(r) for r in c.execute("SELECT * FROM items WHERE kind IN ('video','movie')")]
    fixed = 0
    for item in items:
        try:
            info = media.probe(media_path(item))
        except (media.MediaError, OSError, subprocess.SubprocessError):
            continue                                                   # a file that is missing or unreadable is left alone
        if info["width"] and info["height"] and (info["width"], info["height"]) != (item["width"], item["height"]):
            with db.tx() as c:
                c.execute("UPDATE items SET width=?, height=? WHERE id=?", (info["width"], info["height"], item["id"]))
            fixed += 1
    accounts.set_setting(VIDEO_SIZES_DONE, "1")
    log.info("video sizes checked: %d of %d corrected", fixed, len(items))


def job_rebuild_search(job: dict) -> None:
    """Index every item and album track again, so that the words with ä, ö, ü or ß are also found under their other spelling
    (Strasse for Straße). One item at a time, so the library stays usable while it runs."""
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM items ORDER BY id")]
    for item_id in ids:
        with db.tx() as c:
            db.reindex(c, item_id)
            db.reindex_tracks(c, item_id)
    accounts.set_setting(SEARCH_SPELLINGS_DONE, "1")
    log.info("search index rebuilt for %d items", len(ids))


HANDLERS = {"fetch": job_fetch, "transcribe": job_transcribe, "describe": job_describe, "transcribe_track": job_transcribe_track,
            "check_video_sizes": job_check_video_sizes, "rebuild_search": job_rebuild_search, "convert": job_convert}


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
        db.finish_job(job["id"], f"{type(e).__name__}: {e}", s.job_max_attempts,
                      s.job_max_attempts if getattr(e, "final", False) else job["attempts"],
                      pause=300 if getattr(e, "transient", False) else 30)      # a busy service needs minutes, not seconds
