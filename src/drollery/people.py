"""People: creators and others involved. One record per person, shared by every item they are linked to."""
from __future__ import annotations

import os
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


def full_name(p: dict) -> str:
    """First name and surname together (empty when neither is known)."""
    return " ".join(x for x in (p.get("first_name", ""), p.get("surname", "")) if x)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:MAX_NAME]


def clean(name: str, birthday: str, gender: str, link: str, first_name: str = "", surname: str = "") -> dict:
    """`name` is the alias, the main label. Without one, the real name stands in for it."""
    name, first_name, surname = _tidy(name), _tidy(first_name), _tidy(surname)
    name = name or _tidy(f"{first_name} {surname}")
    if not name:
        raise PersonError(N_("Give the person an alias, a name or a surname"))
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
    return {"name": name, "first_name": first_name, "surname": surname, "birthday": birthday, "gender": gender, "link": link}


def create(c, data: dict) -> int:
    now = time.time()
    return c.execute("INSERT INTO people(name,first_name,surname,birthday,gender,link,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (data["name"], data["first_name"], data["surname"], data["birthday"], data["gender"], data["link"], now, now)).lastrowid


def update(c, person_id: int, data: dict) -> None:
    c.execute("UPDATE people SET name=?, first_name=?, surname=?, birthday=?, gender=?, link=?, updated_at=? WHERE id=?",
              (data["name"], data["first_name"], data["surname"], data["birthday"], data["gender"], data["link"], time.time(), person_id))
    reindex_items_of(c, person_id)                                      # a new name changes how their items are found


def get(c, person_id: int) -> dict | None:
    row = c.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return _row(row) if row else None


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_ANY_NAME = "(name || ' ' || first_name || ' ' || surname)"        # what is searched: the alias, and the real name as "first surname"


def search(c, q: str, limit: int = 8) -> list[dict]:
    """People whose alias or real name contains what was typed; aliases that start with it come first."""
    q = q.strip()
    if not q:
        return []
    rows = c.execute(f"SELECT * FROM people WHERE {_ANY_NAME} LIKE ? ESCAPE '\\' COLLATE NOCASE "
                     "ORDER BY (name LIKE ? ESCAPE '\\' COLLATE NOCASE) DESC, name COLLATE NOCASE LIMIT ?",
                     (f"%{_like(q)}%", f"{_like(q)}%", limit)).fetchall()
    return [_row(r) for r in rows]


def by_name(c, name: str) -> list[dict]:
    return [_row(r) for r in c.execute("SELECT * FROM people WHERE name = ? COLLATE NOCASE OR TRIM(first_name || ' ' || surname) = ? COLLATE NOCASE ORDER BY id",
                                       (name.strip(), name.strip()))]


PEOPLE_SORTS = {"name": "fold(p.name), p.id", "items": "items DESC, fold(p.name)", "new": "p.created_at DESC, p.id DESC"}


def everyone(c, q: str = "", sort: str = "name", unused: bool = False) -> list[dict]:
    """The people, each with how many items they are on. q looks in the alias and the real name; unused keeps only the people
    that are on no item; sort is one of PEOPLE_SORTS."""
    where, args = [], []
    if q.strip():
        where.append(f"(p.name || ' ' || p.first_name || ' ' || p.surname) LIKE ? ESCAPE '\\' COLLATE NOCASE")
        args.append(f"%{_like(q.strip())}%")
    rows = c.execute("SELECT p.*, (SELECT COUNT(*) FROM item_people ip WHERE ip.person_id=p.id) AS items FROM people p"
                     + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {PEOPLE_SORTS.get(sort, PEOPLE_SORTS['name'])}", args).fetchall()
    out = [_row(r) for r in rows]
    return [p for p in out if p["items"] == 0] if unused else out


def delete_unused(c) -> int:
    """Delete every person that is on no item (their pictures go with them). Returns how many."""
    ids = [r["id"] for r in c.execute("SELECT p.id FROM people p WHERE NOT EXISTS (SELECT 1 FROM item_people ip WHERE ip.person_id=p.id)")]
    for pid in ids:
        delete(c, pid)
    return len(ids)


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


def merge_preview(c, source_id: int, target_id: int) -> dict:
    """What merging `source` into `target` would do: how many items move, how many already have the target, which empty
    details of the target are filled from the source."""
    source, target = get(c, source_id), get(c, target_id)
    if source is None or target is None or source_id == target_id:
        raise PersonError(N_("Choose another person to merge into"))
    items = {r["item_id"] for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (source_id,))}
    has = {r["item_id"] for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (target_id,))}
    filled = [f for f in FILLABLE if not target[f] and source[f]]
    picture = bool(source["has_picture"] and not target["has_picture"])
    return {"source": source, "target": target, "items": len(items), "already": len(items & has), "filled": filled, "picture": picture}


FILLABLE = ("first_name", "surname", "birthday", "gender", "link")


def merge(c, source_id: int, target_id: int) -> dict:
    """Merge `source` into `target`: its items go to the target (one link each), details the target lacks are filled from it
    (and its picture, if the target has none), and the source person is deleted. The target keeps its own values."""
    info = merge_preview(c, source_id, target_id)
    source, target = info["source"], info["target"]
    affected = [r["item_id"] for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (source_id,))]
    c.execute("INSERT OR IGNORE INTO item_people(item_id, person_id) SELECT item_id, ? FROM item_people WHERE person_id=?", (target_id, source_id))
    if info["filled"]:
        sets = ", ".join(f"{f}=?" for f in info["filled"])
        c.execute(f"UPDATE people SET {sets} WHERE id=?", [source[f] for f in info["filled"]] + [target_id])
    if info["picture"]:
        picture_path(target_id).parent.mkdir(parents=True, exist_ok=True)
        if picture_path(source_id).exists():
            os.replace(picture_path(source_id), picture_path(target_id))
            c.execute("UPDATE people SET has_picture=1 WHERE id=?", (target_id,))
    c.execute("UPDATE people SET updated_at=? WHERE id=?", (time.time(), target_id))
    c.execute("DELETE FROM people WHERE id=?", (source_id,))                      # its links go with it (cascade)
    picture_path(source_id).unlink(missing_ok=True)
    for item_id in set(affected) | {r["item_id"] for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (target_id,))}:
        db.reindex(c, item_id)                                                    # found under the target's names now
    return info


def _same_person_key(p: dict) -> list[str]:
    """Keys under which two people look like one: the alias without case, spaces and accents, and the real name when there is one."""
    keys = [" ".join(db._fold(p["name"]).split())]
    real = " ".join(db._fold(full_name(p)).split())
    if real and real != keys[0]:
        keys.append(real)
    return [k for k in keys if k]


def _filled(p: dict) -> int:
    """How much is known about a person: the details that can be filled in, and a picture."""
    return sum(bool(p.get(f)) for f in FILLABLE) + bool(p.get("has_picture"))


def duplicates(c) -> list[list[dict]]:
    """Groups of people that look like the same person (same alias or same real name, ignoring case, spaces and accents). Each
    group starts with the person who knows least (the newer one when it is a tie): that one is the one to merge into the next."""
    groups: dict[str, set[int]] = {}
    everyone_ = {p["id"]: p for p in everyone(c)}
    for p in everyone_.values():
        for key in _same_person_key(p):
            groups.setdefault(key, set()).add(p["id"])
    seen, out = set(), []
    for ids in groups.values():
        if len(ids) > 1 and frozenset(ids) not in seen:
            seen.add(frozenset(ids))
            out.append(sorted((everyone_[i] for i in ids), key=lambda p: (_filled(p), -p["id"])))      # first: the one to merge into the other
    return out


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


PICTURE_URL_MAX = 25 * 1024 * 1024                  # a picture link bigger than this is refused


def fetch_picture(person_id: int, url: str) -> bool:
    """Make the picture a link points to the person's picture. The link is checked like every other download (public
    addresses only, redirects included). Raises PersonError when it cannot be fetched or is not a picture."""
    import tempfile

    import httpx

    from . import netguard, pipeline, providers
    url = pipeline._unwrap(url.strip())
    if not url.startswith(("http://", "https://")):
        raise PersonError(N_("The picture link must start with http:// or https://"))
    s = get_settings()
    s.tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td, netguard.make_client() as client:
            r = pipeline._get_checked(client, url)
            try:
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code != 200:
                    raise PersonError(N_("The picture link could not be fetched"))
                if not ctype.startswith("image/"):
                    raise PersonError(N_("That link is not a picture"))
                raw = Path(td) / "download"
                size = 0
                with raw.open("wb") as f:
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > PICTURE_URL_MAX:
                            raise PersonError(N_("That picture is too big"))
                        f.write(chunk)
            finally:
                r.close()
            if not set_picture(person_id, raw):
                raise PersonError(N_("That is not a picture"))
    except netguard.BlockedAddress as e:
        raise PersonError(e.message()) from None
    except (httpx.HTTPError, providers.ProviderError):
        raise PersonError(N_("The picture link could not be fetched")) from None
    return True


def note(p: dict) -> str:
    """A few facts that tell two people with the same name apart (shown next to suggestions)."""
    bits = [full_name(p)] if full_name(p) and full_name(p) != p.get("name") else []
    if p.get("age") is not None:
        bits.append(str(p["age"]))
    if p.get("gender"):
        bits.append(p["gender"])
    return " · ".join(bits)
