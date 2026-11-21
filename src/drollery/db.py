from __future__ import annotations

import re
import sqlite3
import time
from contextlib import contextmanager

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,              -- image | video | audio
  title TEXT NOT NULL DEFAULT '',
  title_locked INTEGER NOT NULL DEFAULT 0,
  description TEXT NOT NULL DEFAULT '',
  transcript TEXT NOT NULL DEFAULT '',
  ocr TEXT NOT NULL DEFAULT '',
  mime TEXT NOT NULL,
  ext TEXT NOT NULL,
  original_name TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL UNIQUE,
  duration REAL,
  width INTEGER,
  height INTEGER,
  has_audio INTEGER NOT NULL DEFAULT 0,
  has_thumb INTEGER NOT NULL DEFAULT 0,
  source_url TEXT NOT NULL DEFAULT '',
  source_meta TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS items_created ON items(created_at DESC);
CREATE TABLE IF NOT EXISTS tags (
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  PRIMARY KEY (item_id, tag)
);
CREATE INDEX IF NOT EXISTS tags_tag ON tags(tag);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL,
  item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
  payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | failed
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  run_after REAL NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, run_after);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',
  totp_secret TEXT NOT NULL DEFAULT '',
  totp_pending TEXT NOT NULL DEFAULT '',
  totp_enabled INTEGER NOT NULL DEFAULT 0,
  totp_last_step INTEGER NOT NULL DEFAULT 0,
  backup_codes TEXT NOT NULL DEFAULT '[]',          -- JSON list of sha256 hashes of unused codes
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'session',             -- session | pending (password ok, 2FA code still needed)
  created_at REAL NOT NULL,
  last_used REAL NOT NULL,
  expires_at REAL NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  failures INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'other',               -- browser | app | other
  token_hash TEXT NOT NULL UNIQUE,                  -- only the hash is stored; the key is shown once
  prefix TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_used_at REAL
);
CREATE TABLE IF NOT EXISTS ai_models (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  type TEXT NOT NULL,                               -- openai | command | tesseract
  base_url TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  api_key TEXT NOT NULL DEFAULT '',                 -- write-only in the UI, never returned by any endpoint
  command TEXT NOT NULL DEFAULT '',
  langs TEXT NOT NULL DEFAULT 'eng',
  language TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL DEFAULT '',
  timeout INTEGER NOT NULL DEFAULT 300,
  send_image INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  title, description, tags, transcript, ocr, source,
  tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3'
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        # jobs left 'running' by a crash/restart go back to the queue
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))


# ---------------------------------------------------------------- items

def reindex(c: sqlite3.Connection, item_id: int) -> None:
    c.execute("DELETE FROM items_fts WHERE rowid=?", (item_id,))
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        return
    tags = " ".join(r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=?", (item_id,)))
    source = f"{row['source_url']} {row['source_meta']} {row['original_name']}"
    c.execute(
        "INSERT INTO items_fts(rowid,title,description,tags,transcript,ocr,source) VALUES (?,?,?,?,?,?,?)",
        (item_id, row["title"], row["description"], tags, row["transcript"], row["ocr"], source),
    )


def normalize_tag(tag: str) -> str:
    return re.sub(r"\s+", "-", tag.strip().lower().lstrip("#"))[:40]


def set_tags(c: sqlite3.Connection, item_id: int, tags: list[str], source: str, replace: bool = False) -> None:
    if replace:
        c.execute("DELETE FROM tags WHERE item_id=?", (item_id,))
    for t in dict.fromkeys(normalize_tag(t) for t in tags):
        if t:
            c.execute("INSERT OR IGNORE INTO tags(item_id,tag,source) VALUES (?,?,?)", (item_id, t, source))
    reindex(c, item_id)


def get_item(c: sqlite3.Connection, item_id: int) -> dict | None:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["tags"] = [r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=? ORDER BY tag", (item_id,))]
    return item


def popular_tags(c: sqlite3.Connection, limit: int = 100) -> list[str]:
    return [r["tag"] for r in c.execute(
        "SELECT tag, COUNT(*) n FROM tags GROUP BY tag ORDER BY n DESC LIMIT ?", (limit,))]


def fts_query(q: str) -> str:
    """Turn free user text into a safe FTS5 query: every word is a quoted prefix term (AND)."""
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    return " ".join(f'"{w}"*' for w in words)


def search(c: sqlite3.Connection, q: str = "", kind: str = "", tag: str = "",
           limit: int = 40, offset: int = 0) -> list[dict]:
    where, args = [], []
    if kind:
        where.append("items.kind = ?")
        args.append(kind)
    if tag:
        where.append("EXISTS (SELECT 1 FROM tags t WHERE t.item_id = items.id AND t.tag = ?)")
        args.append(normalize_tag(tag))
    match = fts_query(q)
    if match:
        sql = ("SELECT items.* FROM items_fts JOIN items ON items.id = items_fts.rowid "
               "WHERE items_fts MATCH ?" + "".join(f" AND {w}" for w in where) +
               " ORDER BY bm25(items_fts, 10, 4, 6, 2, 1, 1), items.created_at DESC LIMIT ? OFFSET ?")
        args = [match, *args]
    else:
        sql = ("SELECT items.* FROM items" + (" WHERE " + " AND ".join(where) if where else "") +
               " ORDER BY items.created_at DESC LIMIT ? OFFSET ?")
    rows = c.execute(sql, [*args, limit, offset]).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["tags"] = [x["tag"] for x in c.execute("SELECT tag FROM tags WHERE item_id=? ORDER BY tag", (d["id"],))]
        items.append(d)
    return items


# ----------------------------------------------------------------- jobs

def enqueue(c: sqlite3.Connection, type_: str, item_id: int | None = None, payload: str = "{}",
            delay: float = 0) -> int:
    now = time.time()
    cur = c.execute(
        "INSERT INTO jobs(type,item_id,payload,run_after,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (type_, item_id, payload, now + delay, now, now))
    return cur.lastrowid


def claim_job() -> dict | None:
    now = time.time()
    with tx() as c:
        row = c.execute(
            "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? "
            "WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_after<=? ORDER BY id LIMIT 1) "
            "RETURNING *", (now, now)).fetchone()
    return dict(row) if row else None


def finish_job(job_id: int, error: str | None, max_attempts: int, attempts: int) -> None:
    now = time.time()
    with tx() as c:
        if error is None:
            c.execute("UPDATE jobs SET status='done', error='', updated_at=? WHERE id=?", (now, job_id))
        elif attempts >= max_attempts:
            c.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?", (error[:2000], now, job_id))
        else:
            c.execute("UPDATE jobs SET status='queued', error=?, run_after=?, updated_at=? WHERE id=?",
                      (error[:2000], now + 30 * attempts, now, job_id))
