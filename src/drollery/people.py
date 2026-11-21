"""People: creators and others involved. One record per person, shared by every item they are linked to."""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

from . import db, media
from .i18n import N_
from .config import get_settings

GENDERS = ("female", "male", "nonbinary", "other")
MAX_NAME, MAX_LINK = 120, 300


class PersonError(ValueError):
    """The message is an English catalog key; the caller translates it."""


def picture_path(person_id: int) -> Path:
    return get_settings().media_dir / "people" / f"{int(person_id)}.jpg"


def parse_birthday(text: str) -> date | None:
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def age_of(birthday: str, today: date | None = None) -> int | None:
    """Whole years since the birthday (None when there is no valid birthday)."""
    born = parse_birthday(birthday)
    if born is None:
        return None
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _row(r) -> dict:
    d = dict(r)
    d["age"] = age_of(d.get("birthday", ""))
    return d


def clean(name: str, birthday: str, gender: str, link: str) -> dict:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        raise PersonError(N_("Give the person a name"))
    birthday = (birthday or "").strip()
    if birthday:
        born = parse_birthday(birthday)
        if born is None or born > date.today() or (age_of(birthday) or 0) > 130:
            raise PersonError(N_("The birthday must be a real date in the past"))
        birthday = born.isoformat()
    gender = (gender or "").strip().lower()
    if gender and gender not in GENDERS:
        gender = ""
    link = (link or "").strip()
    if link and (not re.match(r"^https?://[^\s]+$", link, re.I) or len(link) > MAX_LINK):
        raise PersonError(N_("The link must start with http:// or https://"))
    return {"name": name[:MAX_NAME], "birthday": birthday, "gender": gender, "link": link}


def create(c, data: dict) -> int:
    now = time.time()
    return c.execute("INSERT INTO people(name,birthday,gender,link,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                     (data["name"], data["birthday"], data["gender"], data["link"], now, now)).lastrowid


def update(c, person_id: int, data: dict) -> None:
    c.execute("UPDATE people SET name=?, birthday=?, gender=?, link=?, updated_at=? WHERE id=?",
              (data["name"], data["birthday"], data["gender"], data["link"], time.time(), person_id))
    reindex_items_of(c, person_id)                                      # a new name changes how their items are found


def get(c, person_id: int) -> dict | None:
    row = c.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return _row(row) if row else None


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(c, q: str, limit: int = 8) -> list[dict]:
    """People whose name contains what was typed; names that start with it come first."""
    q = q.strip()
    if not q:
        return []
    rows = c.execute("SELECT * FROM people WHERE name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                     "ORDER BY (name LIKE ? ESCAPE '\\' COLLATE NOCASE) DESC, name COLLATE NOCASE LIMIT ?",
                     (f"%{_like(q)}%", f"{_like(q)}%", limit)).fetchall()
    return [_row(r) for r in rows]


def by_name(c, name: str) -> list[dict]:
    return [_row(r) for r in c.execute("SELECT * FROM people WHERE name = ? COLLATE NOCASE ORDER BY id", (name.strip(),))]


def everyone(c) -> list[dict]:
    rows = c.execute("SELECT p.*, (SELECT COUNT(*) FROM item_people ip WHERE ip.person_id=p.id) AS items "
                     "FROM people p ORDER BY p.name COLLATE NOCASE").fetchall()
    return [_row(r) for r in rows]


def of_item(c, item_id: int) -> list[dict]:
    rows = c.execute("SELECT p.* FROM people p JOIN item_people ip ON ip.person_id=p.id WHERE ip.item_id=? ORDER BY ip.rowid", (item_id,)).fetchall()
    return [_row(r) for r in rows]


def link(c, item_id: int, person_id: int) -> bool:
    cur = c.execute("INSERT OR IGNORE INTO item_people(item_id, person_id) VALUES (?,?)", (item_id, person_id))
    c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
    db.reindex(c, item_id)
    return cur.rowcount > 0


def unlink(c, item_id: int, person_id: int) -> None:
    c.execute("DELETE FROM item_people WHERE item_id=? AND person_id=?", (item_id, person_id))
    c.execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
    db.reindex(c, item_id)


def reindex_items_of(c, person_id: int) -> None:
    for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (person_id,)).fetchall():
        db.reindex(c, r["item_id"])


def delete(c, person_id: int) -> None:
    ids = [r["item_id"] for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (person_id,))]
    c.execute("DELETE FROM people WHERE id=?", (person_id,))
    for i in ids:
        db.reindex(c, i)
    picture_path(person_id).unlink(missing_ok=True)


def set_picture(person_id: int, src: Path) -> bool:
    """Make `src` (an image file) the person's picture: a centred square of it. False when it is not a picture."""
    dst = picture_path(person_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".src.jpg")
    try:
        if not media.make_cover(src, tmp, on_white=True):
            return False
        info = media.probe(tmp)
        w, h = info.get("width"), info.get("height")
        if not w or not h:
            return False
        m = min(w, h)
        media.make_card(tmp, dst, "image", 0.0, (1 - m / w) / 2, (1 - m / h) / 2, 1.0)
        return True
    except media.MediaError:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def note(p: dict) -> str:
    """A few facts that tell two people with the same name apart (shown next to suggestions)."""
    bits = []
    if p.get("age") is not None:
        bits.append(str(p["age"]))
    if p.get("gender"):
        bits.append(p["gender"])
    return " · ".join(bits)
