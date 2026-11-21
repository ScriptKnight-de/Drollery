"""Database access for users, sessions, API keys, AI model definitions and small settings."""
from __future__ import annotations

import json
import os
import time

from . import db, security
from .config import get_settings

SESSION_TTL = 60 * 60 * 24 * 30      # 30 days, sliding
PENDING_TTL = 60 * 5                 # time allowed to enter the 2FA code after the password
MAX_PENDING_FAILURES = 5
API_KEY_KINDS = ("browser", "app", "other")


# ----------------------------------------------------------------- users

def user_count() -> int:
    with db.tx() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get_user(user_id: int) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_name(username: str) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    return dict(row) if row else None


def create_user(username: str, password: str, display_name: str = "", email: str = "", role: str = "admin") -> int:
    now = time.time()
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO users(username,display_name,email,password_hash,role,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (username.strip(), display_name.strip(), email.strip(), security.hash_password(password), role, now, now))
        return cur.lastrowid


def create_first_user(username: str, password: str, display_name: str = "") -> int | None:
    """Create the admin only if no user exists yet (a single statement, so two simultaneous setups can't both win)."""
    now = time.time()
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO users(username,display_name,password_hash,role,created_at,updated_at) "
            "SELECT ?,?,?, 'admin', ?, ? WHERE NOT EXISTS (SELECT 1 FROM users)",
            (username.strip(), display_name.strip(), security.hash_password(password), now, now))
        return cur.lastrowid if cur.rowcount else None


def update_profile(user_id: int, display_name: str, email: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE users SET display_name=?, email=?, updated_at=? WHERE id=?",
                  (display_name.strip()[:80], email.strip()[:200], time.time(), user_id))


def set_password(user_id: int, password: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                  (security.hash_password(password), time.time(), user_id))


# --------------------------------------------------------- setup code

def setup_code_path():
    return get_settings().data_dir / "setup-code"


def get_setup_code() -> str:
    """The code that must be entered on the first-run page. From DROLLERY_SETUP_CODE, else generated and kept in
    the data volume until the admin exists, so a restart doesn't invalidate the code printed in the log."""
    env = os.environ.get("DROLLERY_SETUP_CODE", "").strip()
    if env:
        return env
    path = setup_code_path()
    if path.exists():
        return path.read_text().strip()
    code = security.new_token(9)
    path.write_text(code)
    path.chmod(0o600)
    return code


def clear_setup_code() -> None:
    setup_code_path().unlink(missing_ok=True)


# -------------------------------------------------------------- sessions

def create_session(user_id: int, kind: str = "session", user_agent: str = "", ip: str = "") -> str:
    token = security.new_token()
    now = time.time()
    ttl = SESSION_TTL if kind == "session" else PENDING_TTL
    with db.tx() as c:
        c.execute("INSERT INTO sessions(token_hash,user_id,kind,created_at,last_used,expires_at,user_agent,ip) VALUES (?,?,?,?,?,?,?,?)",
                  (security.token_hash(token), user_id, kind, now, now, now + ttl, user_agent[:200], ip[:64]))
    return token


def lookup_session(token: str, kind: str = "session") -> dict | None:
    """Return the user for a valid session token (refreshing its expiry at most once a day), else None."""
    if not token:
        return None
    h, now = security.token_hash(token), time.time()
    with db.tx() as c:
        row = c.execute("SELECT * FROM sessions WHERE token_hash=? AND kind=? AND expires_at>?", (h, kind, now)).fetchone()
        if row is None:
            return None
        if kind == "session" and now - row["last_used"] > 86400:
            c.execute("UPDATE sessions SET last_used=?, expires_at=? WHERE token_hash=?", (now, now + SESSION_TTL, h))
        user = c.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if user is None:
        return None
    out = dict(user)
    out["_session_hash"] = h
    out["_pending_failures"] = row["failures"]
    return out


def note_pending_failure(token: str) -> int:
    """Count a wrong 2FA code on a pending login; after MAX_PENDING_FAILURES the challenge is destroyed."""
    h = security.token_hash(token)
    with db.tx() as c:
        c.execute("UPDATE sessions SET failures=failures+1 WHERE token_hash=? AND kind='pending'", (h,))
        row = c.execute("SELECT failures FROM sessions WHERE token_hash=?", (h,)).fetchone()
        n = row["failures"] if row else MAX_PENDING_FAILURES
        if n >= MAX_PENDING_FAILURES:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (h,))
    return n


def delete_session(token: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (security.token_hash(token),))


def delete_user_sessions(user_id: int, keep_hash: str = "") -> None:
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, keep_hash))


def list_sessions(user_id: int) -> list[dict]:
    with db.tx() as c:
        rows = c.execute("SELECT * FROM sessions WHERE user_id=? AND kind='session' AND expires_at>? ORDER BY last_used DESC",
                         (user_id, time.time())).fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------- API keys

def _key_token() -> str:
    return "drl_" + security.new_token(30)


def create_api_key(user_id: int, name: str, kind: str) -> tuple[int, str]:
    token = _key_token()
    kind = kind if kind in API_KEY_KINDS else "other"
    with db.tx() as c:
        cur = c.execute("INSERT INTO api_keys(user_id,name,kind,token_hash,prefix,created_at) VALUES (?,?,?,?,?,?)",
                        (user_id, name.strip()[:60] or kind.title(), kind, security.token_hash(token), token[:8], time.time()))
        return cur.lastrowid, token


def regenerate_api_key(key_id: int, user_id: int) -> str | None:
    """Replace the secret of an existing key; the old one stops working immediately."""
    token = _key_token()
    with db.tx() as c:
        cur = c.execute("UPDATE api_keys SET token_hash=?, prefix=?, created_at=?, last_used_at=NULL WHERE id=? AND user_id=?",
                        (security.token_hash(token), token[:8], time.time(), key_id, user_id))
        return token if cur.rowcount else None


def delete_api_key(key_id: int, user_id: int) -> bool:
    with db.tx() as c:
        return c.execute("DELETE FROM api_keys WHERE id=? AND user_id=?", (key_id, user_id)).rowcount > 0


def list_api_keys(user_id: int) -> list[dict]:
    with db.tx() as c:
        return [dict(r) for r in c.execute("SELECT id,name,kind,prefix,created_at,last_used_at FROM api_keys WHERE user_id=? ORDER BY id", (user_id,))]


def lookup_api_key(token: str) -> dict | None:
    if not token.startswith("drl_"):
        return None
    h, now = security.token_hash(token), time.time()
    with db.tx() as c:
        row = c.execute("SELECT * FROM api_keys WHERE token_hash=?", (h,)).fetchone()
        if row is None:
            return None
        if row["last_used_at"] is None or now - row["last_used_at"] > 60:
            c.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now, row["id"]))
        user = c.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    if user is None:
        return None
    out = dict(user)
    out["_api_key_id"] = row["id"]
    return out


# ------------------------------------------------------------------- 2FA

def start_2fa(user_id: int) -> str:
    secret = security.new_totp_secret()
    with db.tx() as c:
        c.execute("UPDATE users SET totp_pending=? WHERE id=?", (secret, user_id))
    return secret


def enable_2fa(user_id: int, secret: str, step: int) -> list[str]:
    codes = security.new_backup_codes()
    with db.tx() as c:
        c.execute("UPDATE users SET totp_secret=?, totp_pending='', totp_enabled=1, totp_last_step=?, backup_codes=?, updated_at=? WHERE id=?",
                  (secret, step, json.dumps([security.backup_hash(x) for x in codes]), time.time(), user_id))
    return codes


def disable_2fa(user_id: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE users SET totp_secret='', totp_pending='', totp_enabled=0, totp_last_step=0, backup_codes='[]', updated_at=? WHERE id=?",
                  (time.time(), user_id))


def regenerate_backup_codes(user_id: int) -> list[str]:
    codes = security.new_backup_codes()
    with db.tx() as c:
        c.execute("UPDATE users SET backup_codes=? WHERE id=?", (json.dumps([security.backup_hash(x) for x in codes]), user_id))
    return codes


def note_totp_step(user_id: int, step: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE users SET totp_last_step=? WHERE id=? AND totp_last_step<?", (step, user_id, step))


def use_backup_code(user_id: int, code: str) -> bool:
    h = security.backup_hash(code)
    with db.tx() as c:
        row = c.execute("SELECT backup_codes FROM users WHERE id=?", (user_id,)).fetchone()
        codes = json.loads(row["backup_codes"]) if row else []
        if h not in codes:
            return False
        codes.remove(h)
        c.execute("UPDATE users SET backup_codes=? WHERE id=?", (json.dumps(codes), user_id))
    return True


def backup_codes_left(user: dict) -> int:
    return len(json.loads(user.get("backup_codes") or "[]"))


def check_second_factor(user: dict, code: str) -> bool:
    """Accept a current authenticator code (once) or an unused backup code."""
    step = security.totp_verify(user["totp_secret"], code, user["totp_last_step"])
    if step is not None:
        note_totp_step(user["id"], step)
        return True
    return use_backup_code(user["id"], code)


# ------------------------------------------------------------ AI models

MODEL_FIELDS = ("name", "type", "base_url", "model", "api_key", "command", "langs", "language", "prompt", "timeout", "send_image")


def list_models() -> list[dict]:
    with db.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ai_models ORDER BY name")]


def get_model(model_id: int) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT * FROM ai_models WHERE id=?", (model_id,)).fetchone()
    return dict(row) if row else None


def save_model(model_id: int | None, data: dict, clear_key: bool = False) -> int:
    """Insert or update. An empty api_key on update keeps the stored secret (the form never shows it);
    clear_key=True removes it."""
    now = time.time()
    vals = {k: data.get(k, "") for k in MODEL_FIELDS}
    vals["timeout"] = max(5, min(int(vals["timeout"] or 300), 3600))
    vals["send_image"] = 1 if str(vals["send_image"]).lower() in ("1", "true", "on", "yes") else 0
    with db.tx() as c:
        if model_id is None:
            cur = c.execute(
                "INSERT INTO ai_models(name,type,base_url,model,api_key,command,langs,language,prompt,timeout,send_image,created_at,updated_at) "
                "VALUES (:name,:type,:base_url,:model,:api_key,:command,:langs,:language,:prompt,:timeout,:send_image,:now,:now)",
                {**vals, "now": now})
            return cur.lastrowid
        sets = ["name=:name", "type=:type", "base_url=:base_url", "model=:model", "command=:command", "langs=:langs",
                "language=:language", "prompt=:prompt", "timeout=:timeout", "send_image=:send_image", "updated_at=:now"]
        if vals["api_key"]:
            sets.append("api_key=:api_key")
        elif clear_key:
            sets.append("api_key=''")
        c.execute(f"UPDATE ai_models SET {', '.join(sets)} WHERE id=:id", {**vals, "now": now, "id": model_id})
        return model_id


def delete_model(model_id: int) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM ai_models WHERE id=?", (model_id,))
        c.execute("DELETE FROM settings WHERE key LIKE 'ai.%' AND value=?", (str(model_id),))


def get_setting(key: str) -> str | None:
    with db.tx() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str | None) -> None:
    with db.tx() as c:
        if value is None:
            c.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            c.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
