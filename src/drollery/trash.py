"""A short undo for deleting items in the web UI (checklist UI-11).

Deleting does not throw things away at once: the item's rows are written to a snapshot, its files are moved into a folder
below the data folder, and the person gets UNDO_SECONDS to take it back. After that the folder is deleted for good (a timer
for each batch, and at start for anything a restart left behind). Nothing is kept longer than a minute.
The API's DELETE stays immediate: a script that deletes means it.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from . import albums, db, pipeline
from .config import get_settings

UNDO_SECONDS = 60                    # how long a deleted item can still be brought back
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16}$")
# Tables that hold rows of an item, in the order they can be put back (tracks before the shares that point at them).
_CHILDREN = ("albums", "movies", "tracks", "item_people", "tags", "shares")
_lock = threading.Lock()


def _root() -> Path:
    return get_settings().data_dir / "trash"


def _files(item: dict) -> list[Path]:
    paths = [pipeline.media_path(item), pipeline.thumb_path(item), pipeline.card_path(item), pipeline.card_source_path(item)]
    if item["kind"] == "album":
        paths.append(albums.album_dir(item))
    return paths


def _encode(value):
    return {"b64": base64.b64encode(value).decode()} if isinstance(value, bytes) else value


def _decode(value):
    return base64.b64decode(value["b64"]) if isinstance(value, dict) and "b64" in value else value


def _rows(c, table: str, item_id: int) -> list[dict]:
    return [{k: _encode(r[k]) for k in r.keys()} for r in c.execute(f"SELECT * FROM {table} WHERE item_id=?", (item_id,))]


def _purge_later(token: str) -> None:
    timer = threading.Timer(UNDO_SECONDS, purge_one, args=(token,))
    timer.daemon = True
    timer.start()


def purge_one(token: str) -> None:
    if _TOKEN.match(token):
        shutil.rmtree(_root() / token, ignore_errors=True)


def purge_old(everything: bool = False) -> None:
    """Delete every batch that has outlived its undo time (with each new delete), or all of them (at start)."""
    root = _root()
    if not root.is_dir():
        return
    for folder in root.iterdir():
        try:
            if everything or time.time() - folder.stat().st_mtime > UNDO_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def delete(items: list[dict]) -> str:
    """Take these items out of the library (rows and search index) and keep them for UNDO_SECONDS. Returns the batch token."""
    purge_old()
    token = secrets.token_urlsafe(12)[:16]
    folder = _root() / token
    (folder / "files").mkdir(parents=True)
    data_dir = get_settings().data_dir
    snapshot = []
    with _lock:
        for item in items:
            with db.tx() as c:
                row = c.execute("SELECT * FROM items WHERE id=?", (item["id"],)).fetchone()
                if row is None:
                    continue
                entry = {"item": {k: _encode(row[k]) for k in row.keys()}, "children": {t: _rows(c, t, item["id"]) for t in _CHILDREN}, "files": []}
                c.execute("DELETE FROM items_fts WHERE rowid=?", (item["id"],))
                c.execute("DELETE FROM tracks_fts WHERE rowid IN (SELECT id FROM tracks WHERE item_id=?)", (item["id"],))
                c.execute("DELETE FROM items WHERE id=?", (item["id"],))
            for path in _files(item):
                if not path.exists():
                    continue
                try:
                    rel = path.relative_to(data_dir)
                except ValueError:
                    continue
                target = folder / "files" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
                entry["files"].append(str(rel))
            snapshot.append(entry)
        (folder / "snapshot.json").write_text(json.dumps(snapshot))
    _purge_later(token)
    return token


def restore(token: str) -> int:
    """Put a batch back. Returns how many items came back (0 when the time ran out or it was already restored)."""
    if not _TOKEN.match(token):
        return 0
    folder = _root() / token
    path = folder / "snapshot.json"
    with _lock:
        if not path.is_file() or time.time() - folder.stat().st_mtime > UNDO_SECONDS:
            return 0
        snapshot = json.loads(path.read_text())
        data_dir = get_settings().data_dir
        back = 0
        for entry in snapshot:
            item = {k: _decode(v) for k, v in entry["item"].items()}
            try:
                with db.tx() as c:
                    c.execute(f"INSERT INTO items ({','.join(item)}) VALUES ({','.join('?' * len(item))})", list(item.values()))
                    for table in _CHILDREN:
                        for row in entry["children"][table]:
                            row = {k: _decode(v) for k, v in row.items()}
                            if table == "item_people" and not c.execute("SELECT 1 FROM people WHERE id=?", (row["person_id"],)).fetchone():
                                continue                                     # the person was deleted in the meantime
                            c.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
                    db.reindex(c, item["id"])
                    db.reindex_tracks(c, item["id"])
            except Exception:                                                # the same file was added again, or the id is taken: leave this one out
                continue
            for rel in entry["files"]:
                source = folder / "files" / rel
                target = data_dir / rel
                if source.exists() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
            back += 1
        shutil.rmtree(folder, ignore_errors=True)
    return back
