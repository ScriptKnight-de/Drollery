"""Movies: films, parodies and synchros (dubs). A movie is one video file with the facts of the film it is, parodies or dubs;
the facts can be taken from IMDb (see imdb.py). Like an album it is an item of its own kind plus a row in `movies`."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import db, media
from .config import get_settings
from .i18n import N_

SUBTYPES = {"movie": N_("Movie"), "parody": N_("Parody"), "synchro": N_("Synchro (dub)")}


def clean_subtype(value: str) -> str:
    return value if value in SUBTYPES else "movie"


def get(c, item_id: int) -> dict | None:
    row = c.execute("SELECT * FROM movies WHERE item_id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def create(c, item_id: int, subtype: str = "movie", original_title: str = "") -> None:
    c.execute("INSERT OR IGNORE INTO movies(item_id, subtype, original_title) VALUES (?,?,?)",
              (item_id, clean_subtype(subtype), original_title.strip()[:200]))
    db.reindex(c, item_id)


def facts(movie: dict) -> dict:
    """The details kept from the lookup, with the columns merged in; empty when there are none."""
    try:
        d = json.loads(movie.get("details") or "{}")
    except (ValueError, TypeError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    return {**d, "year": movie.get("year", ""), "imdb_id": movie.get("imdb_id", "")}


def update(c, item_id: int, subtype: str, original_title: str) -> None:
    c.execute("UPDATE movies SET subtype=?, original_title=? WHERE item_id=?", (clean_subtype(subtype), original_title.strip()[:200], item_id))
    c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
    db.reindex(c, item_id)


def apply_details(item_id: int, info, poster_bytes: bytes | None, *, title: bool = False, plot: bool = False, details: bool = False,
                  poster: bool = False) -> list[str]:
    """Take over what the person ticked from an IMDb title (an imdb.Title). Returns what was changed.
    For a parody or a synchro the IMDb title is the film it is based on, so it is kept as `original_title` and the
    person's own title only changes when they tick "title"."""
    s = get_settings()
    done: list[str] = []
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if poster and poster_bytes:
        s.tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = s.tmp_dir / f"poster-{item_id}-{int(time.time())}"
        tmp.write_bytes(poster_bytes)
        try:
            if _set_poster(item, tmp):
                done.append("poster")
        finally:
            tmp.unlink(missing_ok=True)
    with db.tx() as c:
        if "poster" in done:
            c.execute("UPDATE items SET has_card=1, card_t=NULL, card_x=0, card_y=0, card_s=1, updated_at=? WHERE id=?", (time.time(), item_id))
        if title and info.title:
            c.execute("UPDATE items SET title=?, title_locked=1 WHERE id=?", (info.title[:120], item_id))
            done.append("title")
        if plot and info.plot:
            c.execute("UPDATE items SET description=? WHERE id=?", (info.plot[:2000], item_id))
            done.append("description")
        if details:
            c.execute("UPDATE movies SET original_title=CASE WHEN original_title='' THEN ? ELSE original_title END, year=?, imdb_id=?, details=? WHERE item_id=?",
                      (info.title[:200], info.year, info.imdb_id, json.dumps(info.details(), ensure_ascii=False), item_id))
            c.execute("UPDATE items SET source_url=? WHERE id=?", (info.url, item_id))
            done.append("details")
        c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
        db.reindex(c, item_id)
    return done


def _set_poster(item: dict, picture: Path) -> bool:
    """The poster becomes the card image: a square crop from its top (a poster is tall; faces and titles sit there)."""
    from . import pipeline
    src = pipeline.card_source_path(item)
    src.parent.mkdir(parents=True, exist_ok=True)
    if not media.make_cover(picture, src, on_white=True):
        return False
    try:
        media.make_card(src, pipeline.card_path(item), "image", 0.0, 0.0, 0.0, 1.0)
    except media.MediaError:
        src.unlink(missing_ok=True)
        return False
    return True


def summaries(c, item_ids: list[int]) -> dict[int, dict]:
    """{item id: {"subtype", "year"}} for the library cards."""
    if not item_ids:
        return {}
    rows = c.execute(f"SELECT item_id, subtype, year FROM movies WHERE item_id IN ({','.join('?' * len(item_ids))})", item_ids).fetchall()
    return {r["item_id"]: {"subtype": r["subtype"], "year": r["year"]} for r in rows}
