"""Share links: public, optionally expiring URLs to a single item."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from fastapi import Request

from . import accounts, db, security

PRESETS = {"never": None, "1h": 3600, "1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
PRESET_LABELS = [("never", "Never expires"), ("1h", "1 hour"), ("1d", "24 hours"), ("7d", "7 days"), ("30d", "30 days"), ("custom", "Custom…")]
UNITS = {"minutes": 60, "hours": 3600, "days": 86400}
MAX_SECONDS = 365 * 86400
MIN_SECONDS = 60


def expiry_seconds(preset: str, amount: int = 0, unit: str = "hours") -> tuple[int | None, str]:
    """Translate the form into seconds from now. Returns (seconds or None for permanent, error message or '')."""
    if preset in PRESETS:
        return PRESETS[preset], ""
    if preset == "custom":
        if unit not in UNITS or amount < 1:
            return None, "Enter how long the link should work"
        seconds = amount * UNITS[unit]
        if seconds < MIN_SECONDS or seconds > MAX_SECONDS:
            return None, "A link can last between 1 minute and 1 year"
        return seconds, ""
    return None, "Choose how long the link should work"


def humanize(seconds: float) -> str:
    seconds = int(seconds)
    for size, name in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {name}{'s' if n != 1 else ''}"
    return "under a minute"


def state(share: dict, now: float | None = None) -> dict:
    """{kind: permanent|active|expired|revoked, text}."""
    now = now if now is not None else time.time()
    if share["revoked_at"]:
        return {"kind": "revoked", "text": "Revoked"}
    if share["expires_at"] is None:
        return {"kind": "permanent", "text": "Permanent"}
    if share["expires_at"] <= now:
        return {"kind": "expired", "text": "Expired"}
    return {"kind": "active", "text": f"Expires in {humanize(share['expires_at'] - now)}"}


def create(item_id: int, user_id: int | None, expires_in: int | None, label: str = "") -> dict:
    token = security.new_token(24)
    now = time.time()
    with db.tx() as c:
        cur = c.execute("INSERT INTO shares(token,item_id,label,created_by,created_at,expires_at) VALUES (?,?,?,?,?,?)",
                        (token, item_id, label.strip()[:80], user_id, now, now + expires_in if expires_in else None))
        row = c.execute("SELECT * FROM shares WHERE id=?", (cur.lastrowid,)).fetchone()
    return decorate(dict(row))


def decorate(share: dict) -> dict:
    share["state"] = state(share)
    return share


def for_item(item_id: int) -> list[dict]:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM shares WHERE item_id=? ORDER BY id DESC", (item_id,)).fetchall()
    return [decorate(dict(r)) for r in rows]


def all_shares() -> list[dict]:
    with db.tx() as c:
        rows = c.execute("SELECT shares.*, items.title AS item_title, items.kind AS item_kind FROM shares "
                         "JOIN items ON items.id = shares.item_id ORDER BY shares.id DESC").fetchall()
    return [decorate(dict(r)) for r in rows]


def get(share_id: int) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
    return decorate(dict(row)) if row else None


def lookup(token: str) -> tuple[dict | None, dict | None]:
    """(share, item) for a token, whatever its state; (None, None) if unknown."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token or ""):
        return None, None
    with db.tx() as c:
        row = c.execute("SELECT * FROM shares WHERE token=?", (token,)).fetchone()
        if row is None:
            return None, None
        item = db.get_item(c, row["item_id"])
    return decorate(dict(row)), item


def is_open(share: dict) -> bool:
    return share["state"]["kind"] in ("permanent", "active")


def count_view(share_id: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE shares SET views=views+1, last_viewed_at=? WHERE id=?", (time.time(), share_id))


def revoke(share_id: int) -> bool:
    with db.tx() as c:
        return c.execute("UPDATE shares SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), share_id)).rowcount > 0


def delete(share_id: int) -> bool:
    with db.tx() as c:
        return c.execute("DELETE FROM shares WHERE id=?", (share_id,)).rowcount > 0


def purge_inactive() -> int:
    """Delete shares that are expired or revoked."""
    with db.tx() as c:
        return c.execute("DELETE FROM shares WHERE revoked_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at <= ?)", (time.time(),)).rowcount


# --------------------------------------------------------------- URLs

def public_base(request: Request) -> str:
    """Address used inside share links: DROLLERY_PUBLIC_URL, else the Settings value, else how you are browsing now."""
    explicit = os.environ.get("DROLLERY_PUBLIC_URL", "").strip() or (accounts.get_setting("public_url") or "")
    return (explicit or str(request.base_url)).rstrip("/")


def file_slug(item: dict) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", (item.get("title") or "file").lower()).strip("-")[:60] or "file"
    return f"{base}{item['ext']}"


def urls(request: Request, share: dict, item: dict) -> dict:
    base = public_base(request)
    return {"page": f"{base}/s/{share['token']}", "raw": f"{base}/s/{share['token']}/raw/{file_slug(item)}",
            "thumb": f"{base}/s/{share['token']}/thumb"}


def valid_public_url(value: str) -> bool:
    return bool(re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~\-/]*)?", value))


def safe_next(value: str, default: str) -> str:
    """Only same-site paths, so a crafted form can't redirect somewhere else."""
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else default


share_throttle = security.Throttle(limit=60, window=900)     # unknown-token requests per IP
