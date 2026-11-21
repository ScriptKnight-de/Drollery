"""Albums: one library item that holds many audio files (a music album or an audiobook), shown behind a single card.

An album is an `items` row with kind='album', so tags, search, the library grid and the card image work as for any
other item. Its tracks live in the `tracks` table and as files in data/media/albums/<album id>/, its cover is
cover.jpg in that folder. The album's identity (items.sha256) is the hash of its tracks' hashes, so uploading the
same set of files again finds the album that is already there.
"""
from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import db, media
from .config import get_settings
from .i18n import t

SUBTYPES = ("album", "audiobook")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jfif"}
COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "artwork")      # preferred names when a ZIP holds several pictures
ALBUM_MIME = "application/x-drollery-album"


class AlbumError(Exception):
    """A problem with the files someone tried to upload; the message is meant for them (it is translated by the caller)."""


@dataclass
class Upload:
    path: Path
    name: str          # the name it had when uploaded (inside a ZIP: its path)


# ---------------------------------------------------------------- paths

def album_dir(item: dict) -> Path:
    return get_settings().media_dir / "albums" / item["sha256"]


def cover_path(item: dict) -> Path:
    return album_dir(item) / "cover.jpg"


def track_path(item: dict, track: dict) -> Path:
    return album_dir(item) / track["filename"]


def remove_files(item: dict) -> None:
    shutil.rmtree(album_dir(item), ignore_errors=True)


# --------------------------------------------------------------- reading

def get(c, item_id: int) -> dict | None:
    row = c.execute("SELECT * FROM albums WHERE item_id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def tracks_of(c, item_id: int) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT * FROM tracks WHERE item_id=? ORDER BY position", (item_id,))]


def summaries(c, item_ids: list[int]) -> dict[int, dict]:
    """item id -> {"tracks": n, "subtype": "album" | "audiobook"}, for the albums among the given items (one query)."""
    if not item_ids:
        return {}
    marks = ",".join("?" * len(item_ids))
    return {r["item_id"]: {"tracks": r["n"], "subtype": r["subtype"]} for r in c.execute(
        f"SELECT a.item_id, a.subtype, (SELECT COUNT(*) FROM tracks t WHERE t.item_id = a.item_id) n FROM albums a WHERE a.item_id IN ({marks})", item_ids)}


# ------------------------------------------------------------- unpacking

def natural_key(text: str) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def numbers_from_name(name: str) -> tuple[int, int]:
    """(disc, track) written at the start of a file name: '1-19. Title' -> (1, 19), '07 - Title' -> (0, 7), 'Title' -> (0, 0)."""
    stem = Path(name).stem
    m = re.match(r"\s*(\d{1,2})\s*[-.]\s*(\d{1,3})\b", stem)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"\s*(?:(?:track|titel|title|kapitel|chapter)\s*)?(\d{1,3})(?:\s*[-._)\]:]|$)", stem, flags=re.I)
    return (0, int(m.group(1))) if m else (0, 0)


def title_from_name(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"^\s*(?:(?:track|titel|title|kapitel|chapter)\s*)?(?:\d{1,3}\s*[-._)\]:]+\s*){1,2}", "", stem, flags=re.I)   # "01 - ", "1-19. ", "Track 4."
    return re.sub(r"[\s_]+", " ", stem).strip()[:120] or re.sub(r"[\s_]+", " ", Path(name).stem).strip()[:120] or "track"


def _is_audio(name: str) -> bool:
    mime = mimetypes.guess_type(name)[0] or ""
    return mime.startswith("audio/") and mime not in media.UNSAFE_MIMES


def _is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTS


def _unzip(zpath: Path, into: Path, remaining: int) -> list[Upload]:
    """Take the audio files and pictures out of a ZIP. Names inside are never used as paths on disk, and the size is
    counted while copying, because the size a ZIP announces can be a lie."""
    s = get_settings()
    out: list[Upload] = []
    per_file = s.max_upload_mb * 1024 * 1024
    try:
        zf = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        raise AlbumError(t("That ZIP file could not be read")) from None
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > 4000:
            raise AlbumError(t("That ZIP file holds too many files"))
        for i, m in enumerate(members):
            base = m.filename.replace("\\", "/")
            leaf = base.rsplit("/", 1)[-1]
            if base.startswith("__MACOSX/") or leaf.startswith("._") or leaf.startswith(".") or not (_is_audio(leaf) or _is_image(leaf)):
                continue
            dest = into / f"{i:05d}{Path(leaf).suffix.lower()}"
            copied = 0
            with zf.open(m) as src, dest.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    copied += len(chunk)
                    remaining -= len(chunk)
                    if copied > per_file or remaining < 0:
                        raise AlbumError(t("That ZIP file unpacks to more than the size limit"))
                    dst.write(chunk)
            out.append(Upload(dest, base))
    return out


def _tag_int(value: str) -> int:
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else 0


def describe(path: Path, name: str) -> dict:
    """What a track file says about itself: its tags, and where it belongs (disc, track number) and what it is called.
    Numbers and titles missing from the tags are taken from the file name. Raises media.MediaError if it is not audio."""
    info = media.probe(path)
    if not info["has_audio"]:
        raise media.MediaError("no audio stream")
    tg = info["tags"]
    base = Path(name).name
    d_name, n_name = numbers_from_name(base)
    return {"info": info, "name": name,
            "disc": _tag_int(tg.get("disc") or tg.get("discnumber")) or d_name,
            "num": _tag_int(tg.get("track") or tg.get("tracknumber")) or n_name,
            "title": (tg.get("title") or "").strip()[:120] or title_from_name(base)}


def order_tracks(rows: list[dict]) -> None:
    """Sort in place: disc, then track number, then file name. Disc only counts when the tracks really span several discs;
    otherwise a few files that state one and others that do not would be split apart."""
    if len({r["disc"] for r in rows if r["disc"]}) <= 1:
        for r in rows:
            r["disc"] = 0
    rows.sort(key=lambda r: (r["disc"], r["num"] or 10 ** 6, natural_key(r["name"])))


def _most_common(values) -> str:
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def _artist_tag(info: dict) -> str:
    tg = info["tags"]
    return (tg.get("album_artist") or tg.get("albumartist") or tg.get("artist") or "").strip()


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -------------------------------------------------------------- creating

def create_album(uploads: list[Upload], work: Path, cover: Upload | None = None, title: str = "", artist: str = "",
                 subtype: str = "album", description: str = "", tags: list[str] | None = None) -> tuple[int, bool]:
    """Build an album from uploaded audio files and/or ZIPs. Returns (item_id, created); an album made of exactly the same
    tracks is not stored twice. `work` is a scratch folder for unpacking."""
    s = get_settings()
    subtype = subtype if subtype in SUBTYPES else "album"
    budget = s.max_album_mb * 1024 * 1024
    audio: list[Upload] = []
    pictures: list[Upload] = []
    zip_names: list[str] = []
    for up in uploads:
        if up.name.lower().endswith(".zip"):
            zip_names.append(Path(up.name).stem)
            sub = work / f"zip{len(zip_names)}"
            sub.mkdir(parents=True, exist_ok=True)
            found = _unzip(up.path, sub, budget)
            audio += [u for u in found if _is_audio(u.name)]
            pictures += [u for u in found if _is_image(u.name)]
        elif _is_audio(up.name):
            audio.append(up)
        elif _is_image(up.name):
            pictures.append(up)
        else:
            raise AlbumError(t("Only audio files, pictures and ZIP files can go into an album"))
    if not audio:
        raise AlbumError(t("Add at least one audio file"))
    if len(audio) > s.max_album_tracks:
        raise AlbumError(t("That is more tracks than an album may hold"))
    if sum(u.path.stat().st_size for u in audio) > budget:
        raise AlbumError(t("The tracks together are larger than the album size limit"))

    # read every track: tags (title, number, artist, album) and duration; a file ffprobe cannot read is not audio
    rows = []
    for up in audio:
        try:
            row = describe(up.path, up.name)
        except media.MediaError:
            raise AlbumError(t("A file in the album could not be read as audio")) from None
        row.update(up=up, sha=_hash(up.path))
        rows.append(row)
    order_tracks(rows)

    # the album's own title and artist: what most tracks say (some files may carry no tags at all), else the ZIP's or folder's name
    album_title = (title.strip() or _most_common(r["info"]["tags"].get("album", "").strip() for r in rows) or (zip_names[0] if zip_names else "")
                   or Path(rows[0]["up"].name).parent.name or "").strip()[:120] or "Untitled album"
    album_artist = (artist.strip() or _most_common(_artist_tag(r["info"]) for r in rows)).strip()[:120]

    sha = hashlib.sha256("\n".join(sorted(r["sha"] for r in rows)).encode()).hexdigest()
    with db.tx() as c:
        existing = c.execute("SELECT id FROM items WHERE sha256=?", (sha,)).fetchone()
        if existing:
            return existing["id"], False

    item = {"sha256": sha}
    folder = album_dir(item)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        stored = []
        for n, r in enumerate(rows, 1):
            ext = r["up"].path.suffix.lower() or Path(r["up"].name).suffix.lower()
            filename = f"{n:03d}-{r['sha'][:12]}{ext}"
            shutil.copyfile(r["up"].path, folder / filename)
            stored.append((n, r, filename, mimetypes.guess_type(filename)[0] or "audio/mpeg"))

        # cover: the one that was chosen, else the best picture from a ZIP, else the picture inside the first track that has one
        has_cover = False
        candidates = [cover] if cover else sorted(pictures, key=lambda u: (
            0 if Path(u.name).stem.lower() in COVER_NAMES else 1, natural_key(u.name)))[:3]
        for cand in candidates:
            if cand and media.make_cover(cand.path, folder / "cover.jpg"):
                has_cover = True
                break
        if not has_cover:
            for r in rows:
                if r["info"]["has_cover"] and media.make_cover(r["up"].path, folder / "cover.jpg"):
                    has_cover = True
                    break
        has_thumb = has_cover and media.make_thumb(folder / "cover.jpg", s.thumbs_dir / f"{sha}.jpg", "image", None)

        total = sum(r["up"].path.stat().st_size for r in rows)
        seconds = sum(r["info"]["duration"] or 0 for r in rows)
        now = time.time()
        with db.tx() as c:
            cur = c.execute(
                "INSERT INTO items(kind,title,title_locked,description,mime,ext,original_name,size,sha256,duration,has_audio,has_thumb,"
                "created_at,updated_at) VALUES ('album',?,?,?,?,'',?,?,?,?,1,?,?,?)",
                (album_title, 1 if title.strip() else 0, description.strip()[:2000], ALBUM_MIME,
                 (zip_names[0] + ".zip") if zip_names else "", total, sha, seconds, int(has_thumb), now, now))
            item_id = cur.lastrowid
            c.execute("INSERT INTO albums(item_id,artist,subtype) VALUES (?,?,?)", (item_id, album_artist, subtype))
            for n, r, filename, mime in stored:
                c.execute("INSERT INTO tracks(item_id,position,title,filename,original_name,mime,size,duration) VALUES (?,?,?,?,?,?,?,?)",
                          (item_id, n, r["title"], filename, Path(r["up"].name).name, mime, r["up"].path.stat().st_size, r["info"]["duration"]))
            if tags:
                db.set_user_tags(c, item_id, tags)
            db.reindex(c, item_id)
        return item_id, True
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        (s.thumbs_dir / f"{sha}.jpg").unlink(missing_ok=True)
        raise


# --------------------------------------------------------------- editing

def rescan(item_id: int) -> None:
    """Read the order and the titles from the track files again (their tags, then their file names). This replaces what
    was renamed or reordered by hand; the artist is filled in when it is empty."""
    with db.tx() as c:
        item = db.get_item(c, item_id)
        tracks = tracks_of(c, item_id)
        info = get(c, item_id)
    rows = []
    for tr in tracks:
        try:
            row = describe(track_path(item, tr), tr["original_name"] or tr["filename"])
        except media.MediaError:
            row = {"info": {"tags": {}}, "name": tr["original_name"] or tr["filename"], "disc": 0, "num": 0, "title": tr["title"]}
        row["tr"] = tr
        rows.append(row)
    order_tracks(rows)
    with db.tx() as c:
        for n, row in enumerate(rows, 1):
            c.execute("UPDATE tracks SET position=?, title=? WHERE id=?", (n, row["title"], row["tr"]["id"]))
        if info is not None and not info["artist"]:
            c.execute("UPDATE albums SET artist=? WHERE item_id=?", (_most_common(_artist_tag(r["info"]) for r in rows)[:120], item_id))
        c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
        db.reindex(c, item_id)


def save_tracks(c, item_id: int, titles: dict[int, str], order: dict[int, int]) -> None:
    """Rename tracks and put them in a new order. `order` maps track id -> the position the person typed; ties keep the old order."""
    rows = tracks_of(c, item_id)
    ranked = sorted(rows, key=lambda t: (order.get(t["id"], t["position"]), t["position"]))
    for n, t in enumerate(ranked, 1):
        title = (titles.get(t["id"], t["title"]) or "").strip()[:120] or t["title"]
        c.execute("UPDATE tracks SET position=?, title=? WHERE id=?", (n, title, t["id"]))
    c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
    db.reindex(c, item_id)


def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", text).strip(" .")[:100] or "track"


def build_zip(item: dict, tracks: list[dict], dest: Path) -> None:
    """All tracks (numbered, named by title) and the cover in one stored ZIP; MP3s do not compress, so nothing is squeezed."""
    width = max(2, len(str(len(tracks))))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:
        for t in tracks:
            path = track_path(item, t)
            if path.exists():
                z.write(path, f"{t['position']:0{width}d} - {safe_filename(t['title'])}{path.suffix}")
        cover = cover_path(item)
        if cover.exists():
            z.write(cover, "cover.jpg")
