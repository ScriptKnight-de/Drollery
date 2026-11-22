from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,              -- image | gif | video | audio | album | movie
  title TEXT NOT NULL DEFAULT '',
  title_locked INTEGER NOT NULL DEFAULT 0,
  description TEXT NOT NULL DEFAULT '',
  transcript TEXT NOT NULL DEFAULT '',
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
  has_card INTEGER NOT NULL DEFAULT 0,              -- a custom, cropped card image exists
  card_t REAL,                                      -- video snapshot time in seconds
  card_x REAL, card_y REAL, card_s REAL,            -- crop: left/top as fractions of the frame, side as a fraction of its shorter edge
  source_url TEXT NOT NULL DEFAULT '',
  source_meta TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS items_created ON items(created_at DESC);
CREATE TABLE IF NOT EXISTS albums (                   -- extra facts of an item whose kind is 'album' (a music album or an audiobook)
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  artist TEXT NOT NULL DEFAULT '',
  subtype TEXT NOT NULL DEFAULT 'album',              -- album | audiobook
  year TEXT NOT NULL DEFAULT '',                      -- filled by the online lookup
  label TEXT NOT NULL DEFAULT '',
  mbid TEXT NOT NULL DEFAULT '',                      -- MusicBrainz release id the details came from
  details TEXT NOT NULL DEFAULT ''                    -- JSON: release date, country, catalog number, format, genres ... from the lookup
);
CREATE TABLE IF NOT EXISTS movies (                   -- extra facts of an item whose kind is 'movie' (a film, a parody or a synchro / dub)
  item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  subtype TEXT NOT NULL DEFAULT 'movie',              -- movie | parody | synchro
  original_title TEXT NOT NULL DEFAULT '',            -- the title of the film that is parodied or dubbed
  year TEXT NOT NULL DEFAULT '',
  imdb_id TEXT NOT NULL DEFAULT '',
  details TEXT NOT NULL DEFAULT '{}'                  -- JSON: plot, genres, directors, cast, rating, runtime ... from the lookup
);
CREATE TABLE IF NOT EXISTS tracks (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  filename TEXT NOT NULL,                             -- file inside the album's folder
  original_name TEXT NOT NULL DEFAULT '',
  mime TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0,
  duration REAL,
  transcript TEXT NOT NULL DEFAULT '',                -- what is said in the track (speech-to-text)
  transcribed_at REAL                                 -- NULL = not transcribed yet
);
CREATE INDEX IF NOT EXISTS tracks_item ON tracks(item_id, position);
CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
  title, transcript,
  tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3'
);
CREATE TABLE IF NOT EXISTS people (                  -- creators and other people involved; one record for everything they appear on
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,                                  -- the alias: how the person is known and shown everywhere
  first_name TEXT NOT NULL DEFAULT '',                 -- the real name, optional
  surname TEXT NOT NULL DEFAULT '',
  birthday TEXT NOT NULL DEFAULT '',                   -- YYYY-MM-DD; the age is worked out from it
  gender TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL DEFAULT '',                       -- a social media page
  has_picture INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS people_name ON people(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS item_people (
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  PRIMARY KEY (item_id, person_id)
);
CREATE INDEX IF NOT EXISTS item_people_person ON item_people(person_id);
CREATE TABLE IF NOT EXISTS tags (
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  PRIMARY KEY (item_id, tag)
);
CREATE INDEX IF NOT EXISTS tags_tag ON tags(tag);
CREATE TABLE IF NOT EXISTS tag_dismissed (            -- AI tags the user removed; the AI must not bring them back
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (item_id, tag)
);
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
  email TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',                 -- UI language code; empty = follow the browser
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
CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,                       -- unguessable capability in the public URL (stored so the link can be shown again)
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  track_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,   -- an album share: NULL = the whole album, else just this track
  label TEXT NOT NULL DEFAULT '',
  created_by INTEGER,
  created_at REAL NOT NULL,
  expires_at REAL,                                  -- NULL = permanent
  revoked_at REAL,
  views INTEGER NOT NULL DEFAULT 0,
  last_viewed_at REAL
);
CREATE INDEX IF NOT EXISTS shares_item ON shares(item_id);
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
  type TEXT NOT NULL,                               -- openai | command
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
  title, description, tags, ai_tags, transcript, source,
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


FTS_COLUMNS = ["title", "description", "tags", "ai_tags", "transcript", "source"]

# What a database from before Drollery 0.1.0 may lack. Those databases are no longer upgraded in place.
REQUIRED_COLUMNS = {
    "items": ("has_card", "card_t", "card_x", "card_y", "card_s"),
    "users": ("language",),
    "shares": ("track_id",),
    "albums": ("year", "label", "mbid", "details"),
    "tracks": ("transcript", "transcribed_at"),
    "people": ("birthday",),
}


# Columns added after the first release: a database made before them gets them at start.
ADDED_COLUMNS = {
    "people": (("first_name", "TEXT NOT NULL DEFAULT ''"), ("surname", "TEXT NOT NULL DEFAULT ''")),
}


def _check_schema(c: sqlite3.Connection) -> None:
    for table, columns in REQUIRED_COLUMNS.items():
        have = {r["name"] for r in c.execute(f"SELECT name FROM pragma_table_info('{table}')")}
        if have and (missing := [col for col in columns if col not in have]):
            raise RuntimeError(f"This database is from before Drollery 0.1.0 (table {table} lacks {', '.join(missing)}). "
                               "Start it once with Drollery 0.1.7 (image tag 0.1.7), which upgrades it, then use a newer version.")


def init() -> None:
    with tx() as c:
        _check_schema(c)
        # the search index follows FTS_COLUMNS: one from an older layout (with the removed "ocr" column) is rebuilt from the items
        cols = [r["name"] for r in c.execute("SELECT name FROM pragma_table_info('items_fts')")]
        rebuild = bool(cols) and cols != FTS_COLUMNS
        if rebuild:
            c.execute("DROP TABLE items_fts")
        c.executescript(SCHEMA)
        for table, columns in ADDED_COLUMNS.items():
            have = {r["name"] for r in c.execute(f"SELECT name FROM pragma_table_info('{table}')")}
            for column, declaration in columns:
                if column not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        if "ocr" in {r["name"] for r in c.execute("SELECT name FROM pragma_table_info('items')")}:
            c.execute("ALTER TABLE items DROP COLUMN ocr")                       # the text recognition feature was removed
        if rebuild:
            for (item_id,) in c.execute("SELECT id FROM items").fetchall():
                reindex(c, item_id)
        # jobs left 'running' by a crash/restart go back to the queue
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))


# ---------------------------------------------------------------- items

def reindex(c: sqlite3.Connection, item_id: int) -> None:
    c.execute("DELETE FROM items_fts WHERE rowid=?", (item_id,))
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        return
    user_tags = " ".join(r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=? AND source='user'", (item_id,)))
    ai_tags = " ".join(r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=? AND source='ai'", (item_id,)))
    source = f"{row['source_url']} {row['source_meta']} {row['original_name']}"
    source += " " + " ".join(r["names"] for r in c.execute("SELECT p.name || ' ' || p.first_name || ' ' || p.surname AS names FROM people p JOIN item_people ip ON ip.person_id=p.id WHERE ip.item_id=?", (item_id,)))   # found by who made it, under any of their names
    transcript = row["transcript"]
    if row["kind"] == "movie":                                      # a movie is found by the film it parodies or dubs, its year, cast, directors and genres
        m = c.execute("SELECT original_title, year, imdb_id, details FROM movies WHERE item_id=?", (item_id,)).fetchone()
        if m:
            source += f" {m['original_title']} {m['year']} {m['imdb_id']}"
            try:
                d = json.loads(m["details"] or "{}")
                for k in ("genres", "directors", "writers", "cast"):
                    source += " " + " ".join(d.get(k, []))
                source += " " + str(d.get("plot", ""))
            except (ValueError, TypeError, AttributeError):
                pass
    if row["kind"] == "album":                                      # an album is found by its artist and by its track titles
        extra = c.execute("SELECT artist, year, label, details FROM albums WHERE item_id=?", (item_id,)).fetchone()
        if extra:
            source += f" {extra['artist']} {extra['year']} {extra['label']}"
            try:                                           # catalog number, barcode and genres are searchable too
                d = json.loads(extra["details"] or "{}")
                source += " " + " ".join(str(d.get(k, "")) for k in ("catalog", "barcode", "country")) + " " + " ".join(d.get("genres", []))
            except (ValueError, TypeError, AttributeError):
                pass
        parts = c.execute("SELECT title, transcript FROM tracks WHERE item_id=? ORDER BY position", (item_id,)).fetchall()
        transcript += " " + " ".join(f"{r['title']} {r['transcript']}" for r in parts)       # track titles and everything said in the tracks
    c.execute(
        "INSERT INTO items_fts(rowid,title,description,tags,ai_tags,transcript,source) VALUES (?,?,?,?,?,?,?)",
        (item_id, row["title"], row["description"], user_tags, ai_tags, transcript, source),
    )


def reindex_tracks(c: sqlite3.Connection, item_id: int) -> None:
    """Refresh the track-level search index of one album (titles and transcripts)."""
    c.execute("DELETE FROM tracks_fts WHERE rowid IN (SELECT id FROM tracks WHERE item_id=?)", (item_id,))
    c.execute("INSERT INTO tracks_fts(rowid,title,transcript) SELECT id,title,transcript FROM tracks WHERE item_id=?", (item_id,))


def normalize_tag(tag: str) -> str:
    return re.sub(r"\s+", "-", tag.strip().lower().lstrip("#"))[:40]


def _clean(tags: list[str]) -> list[str]:
    return [t for t in dict.fromkeys(normalize_tag(t) for t in tags) if t]


def set_user_tags(c: sqlite3.Connection, item_id: int, tags: list[str]) -> None:
    """Replace the user's tags. AI tags are never touched, except that a tag the user types which the AI also
    suggested becomes the user's (it is promoted, not duplicated)."""
    wanted = _clean(tags)
    c.execute("DELETE FROM tags WHERE item_id=? AND source='user'" + (f" AND tag NOT IN ({','.join('?' * len(wanted))})" if wanted else ""),
              (item_id, *wanted))
    for t in wanted:
        c.execute("INSERT INTO tags(item_id,tag,source) VALUES (?,?,'user') ON CONFLICT(item_id,tag) DO UPDATE SET source='user'", (item_id, t))
        c.execute("DELETE FROM tag_dismissed WHERE item_id=? AND tag=?", (item_id, t))      # re-adding a tag undoes an earlier dismissal
    reindex(c, item_id)


def set_ai_tags(c: sqlite3.Connection, item_id: int, tags: list[str]) -> None:
    """Replace the AI's tags with a fresh suggestion. The user's tags are never changed, and tags the user
    already has or has dismissed are skipped."""
    c.execute("DELETE FROM tags WHERE item_id=? AND source='ai'", (item_id,))
    have = {r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=?", (item_id,))}
    dismissed = {r["tag"] for r in c.execute("SELECT tag FROM tag_dismissed WHERE item_id=?", (item_id,))}
    for t in _clean(tags):
        if t not in have and t not in dismissed:
            c.execute("INSERT INTO tags(item_id,tag,source) VALUES (?,?,'ai')", (item_id, t))
    reindex(c, item_id)


def keep_ai_tags(c: sqlite3.Connection, item_id: int, tag: str = "") -> int:
    """Turn AI tag(s) into the user's own tags. An empty tag means all of them. Returns how many changed."""
    q, args = "UPDATE tags SET source='user' WHERE item_id=? AND source='ai'", [item_id]
    if tag:
        q, args = q + " AND tag=?", args + [normalize_tag(tag)]
    n = c.execute(q, args).rowcount
    reindex(c, item_id)
    return n


def dismiss_ai_tags(c: sqlite3.Connection, item_id: int, tag: str = "") -> int:
    """Remove AI tag(s) and remember that the user didn't want them. An empty tag means all of them."""
    q, args = "SELECT tag FROM tags WHERE item_id=? AND source='ai'", [item_id]
    if tag:
        q, args = q + " AND tag=?", args + [normalize_tag(tag)]
    gone = [r["tag"] for r in c.execute(q, args)]
    for t in gone:
        c.execute("DELETE FROM tags WHERE item_id=? AND tag=? AND source='ai'", (item_id, t))
        c.execute("INSERT OR IGNORE INTO tag_dismissed(item_id,tag) VALUES (?,?)", (item_id, t))
    reindex(c, item_id)
    return len(gone)


def clear_all_ai_tags(c: sqlite3.Connection) -> int:
    """Remove every AI tag in the library (the user's tags and the dismissed memory stay)."""
    ids = [r["item_id"] for r in c.execute("SELECT DISTINCT item_id FROM tags WHERE source='ai'")]
    n = c.execute("DELETE FROM tags WHERE source='ai'").rowcount
    for item_id in ids:
        reindex(c, item_id)
    return n


def _tags_of(c: sqlite3.Connection, item_id: int) -> tuple[list[str], list[str]]:
    rows = c.execute("SELECT tag, source FROM tags WHERE item_id=? ORDER BY tag", (item_id,)).fetchall()
    return [r["tag"] for r in rows if r["source"] == "user"], [r["tag"] for r in rows if r["source"] == "ai"]


def get_item(c: sqlite3.Connection, item_id: int) -> dict | None:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["tags"], item["ai_tags"] = _tags_of(c, item_id)         # user tags and AI tags, always kept apart
    return item


def popular_tags(c: sqlite3.Connection, limit: int = 100) -> list[str]:
    """The user's own most-used tags. Only these are offered to the AI as vocabulary, so it learns from what you
    chose and not from its own earlier output."""
    return [r["tag"] for r in c.execute(
        "SELECT tag, COUNT(*) n FROM tags WHERE source='user' GROUP BY tag ORDER BY n DESC LIMIT ?", (limit,))]


def fts_query(q: str) -> str:
    """Turn free user text into a safe FTS5 query: every word is a quoted prefix term (AND)."""
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    return " ".join(f'"{w}"*' for w in words)


def suggest_tags(c: sqlite3.Connection, q: str, limit: int = 5) -> list[dict]:
    """Tags (yours and the AI's) that contain what was typed, with how many items carry each; ones that start with it come first."""
    q = normalize_tag(q)
    if not q:
        return []
    like = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = c.execute("SELECT tag, COUNT(DISTINCT item_id) AS n FROM tags WHERE tag LIKE ? ESCAPE '\\' GROUP BY tag "
                     "ORDER BY (tag LIKE ? ESCAPE '\\') DESC, n DESC, tag LIMIT ?", (f"%{like}%", f"{like}%", limit)).fetchall()
    return [{"tag": r["tag"], "n": r["n"]} for r in rows]


def search(c: sqlite3.Connection, q: str = "", kind: str = "", tag: str = "",
           limit: int = 40, offset: int = 0, tag_source: str = "", person: int = 0) -> list[dict]:
    where, args = [], []
    if person:
        where.append("EXISTS (SELECT 1 FROM item_people ip WHERE ip.item_id = items.id AND ip.person_id = ?)")
        args.append(person)
    if kind:
        where.append("items.kind = ?")
        args.append(kind)
    if tag:
        src = " AND t.source = ?" if tag_source in ("user", "ai") else ""
        where.append(f"EXISTS (SELECT 1 FROM tags t WHERE t.item_id = items.id AND t.tag = ?{src})")
        args.append(normalize_tag(tag))
        if src:
            args.append(tag_source)
    match = fts_query(q)
    if match:
        sql = ("SELECT items.* FROM items_fts JOIN items ON items.id = items_fts.rowid "
               "WHERE items_fts MATCH ?" + "".join(f" AND {w}" for w in where) +
               " ORDER BY bm25(items_fts, 10, 4, 6, 3, 2, 1), items.created_at DESC LIMIT ? OFFSET ?")
        args = [match, *args]
    else:
        sql = ("SELECT items.* FROM items" + (" WHERE " + " AND ".join(where) if where else "") +
               " ORDER BY items.created_at DESC LIMIT ? OFFSET ?")
    rows = c.execute(sql, [*args, limit, offset]).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["tags"], d["ai_tags"] = _tags_of(c, d["id"])
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


def retry_job(job_id: int) -> bool:
    """Put one failed job back in the queue with a fresh set of attempts. Returns False if it isn't a failed job."""
    with tx() as c:
        return c.execute("UPDATE jobs SET status='queued', attempts=0, error='', run_after=0, updated_at=? WHERE id=? AND status='failed'",
                         (time.time(), job_id)).rowcount > 0


def retry_failed_jobs() -> int:
    """Put every failed job back in the queue with a fresh set of attempts. Returns how many."""
    with tx() as c:
        return c.execute("UPDATE jobs SET status='queued', attempts=0, error='', run_after=0, updated_at=? WHERE status='failed'",
                         (time.time(),)).rowcount


def delete_failed_jobs(job_id: int | None = None) -> int:
    """Remove failed jobs (one, or all when job_id is None) from the list. Only failed ones: queued and running jobs stay."""
    with tx() as c:
        if job_id is None:
            return c.execute("DELETE FROM jobs WHERE status='failed'").rowcount
        return c.execute("DELETE FROM jobs WHERE id=? AND status='failed'", (job_id,)).rowcount


def claim_job() -> dict | None:
    now = time.time()
    with tx() as c:
        row = c.execute(
            "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? "
            "WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_after<=? ORDER BY id LIMIT 1) "
            "RETURNING *", (now, now)).fetchone()
    return dict(row) if row else None


def finish_job(job_id: int, error: str | None, max_attempts: int, attempts: int, pause: int = 30) -> None:
    now = time.time()
    with tx() as c:
        if error is None:
            c.execute("UPDATE jobs SET status='done', error='', updated_at=? WHERE id=?", (now, job_id))
        elif attempts >= max_attempts:
            c.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?", (error[:8000], now, job_id))
        else:
            c.execute("UPDATE jobs SET status='queued', error=?, run_after=?, updated_at=? WHERE id=?",
                      (error[:8000], now + pause * attempts, now, job_id))
