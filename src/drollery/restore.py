"""Restoring a backup (Settings > Backup) into a fresh Drollery, from the first-run page.

The archive is read once. Every entry is checked on the way in and written into a staging folder inside the data folder:
only the parts a backup has (drollery.db, config.toml, media/, thumbs/, cards/), only plain files and folders, nothing that
leaves the staging folder, and never more than the free disk space. Then the database is checked (intact, a Drollery
database, at least one account, not older than 0.1.0). Only after all of that is anything put in place: the database first,
through SQLite's own backup into the live file (so no file is swapped under a running server), then the content folders.
A failure before that point leaves the data folder as it was.

Everything here is for a library that has no account yet: a library that is in use is never touched.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
import threading
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import accounts, db, pipeline
from .config import get_settings
from .i18n import N_

FILES = ("drollery.db", "config.toml")
CONTENT_DIRS = ("media", "thumbs", "cards")
MARGIN = 256 * 1024 * 1024          # free space that must remain after the unpacked backup
CHUNK = 1024 * 1024
_lock = threading.Lock()


class RestoreError(ValueError):
    """The message is an English catalog key; the caller translates it."""


@dataclass
class Summary:
    items: int = 0
    people: int = 0
    users: int = 0
    no_file: int = 0            # items whose file is not in this library (a metadata-only backup)


def _clean_name(name: str) -> tuple[str, ...]:
    """The parts of an entry name, or RestoreError when the name could lead out of the folder it is unpacked into."""
    if "\x00" in name or "\\" in name or name.startswith("/"):
        raise RestoreError(N_("This is not a Drollery backup: it contains a file name that is not allowed"))
    parts = tuple(p for p in name.split("/") if p not in ("", "."))
    if any(p == ".." for p in parts):
        raise RestoreError(N_("This is not a Drollery backup: it contains a file name that is not allowed"))
    return parts


def _unpack(fileobj, staging: Path, free: int) -> None:
    """Check every entry and write it below `staging`."""
    written = 0
    seen_db = False
    try:
        archive = tarfile.open(fileobj=fileobj, mode="r|gz")
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        raise RestoreError(N_("This is not a Drollery backup, or the file is damaged")) from None
    try:
        for member in archive:
            parts = _clean_name(member.name)
            if not parts:
                continue                                           # the archive's own "." entry
            if not (member.isreg() or member.isdir()):
                raise RestoreError(N_("This is not a Drollery backup: it contains links or special files"))
            top = parts[0]
            if top in FILES:
                if len(parts) != 1 or not member.isreg():
                    raise RestoreError(N_("This is not a Drollery backup: it contains files that do not belong in one"))
            elif top not in CONTENT_DIRS:
                raise RestoreError(N_("This is not a Drollery backup: it contains files that do not belong in one"))
            target = staging.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if written + member.size > free - MARGIN:
                raise RestoreError(N_("There is not enough free disk space to unpack this backup"))
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            with target.open("wb") as out:
                while chunk := source.read(CHUNK):
                    out.write(chunk)
            written += member.size
            seen_db = seen_db or parts == ("drollery.db",)
    except RestoreError:
        raise
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        raise RestoreError(N_("This is not a Drollery backup, or the file is damaged")) from None
    finally:
        archive.close()
    if not seen_db:
        raise RestoreError(N_("This is not a Drollery backup: the database is missing"))


def _check_database(path: Path) -> None:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error:
        raise RestoreError(N_("The database in this backup is damaged")) from None
    try:
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RestoreError(N_("The database in this backup is damaged"))
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.Error:
            raise RestoreError(N_("The database in this backup is damaged")) from None
        if not {"items", "users", "settings"} <= tables:
            raise RestoreError(N_("This is not a Drollery backup: the database is not one of Drollery's"))
        try:
            db._check_schema(con)
        except RuntimeError:
            raise RestoreError(N_("This backup was made before Drollery 0.1.0 and cannot be restored here. Restore it with Drollery 0.1.7 first")) from None
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            raise RestoreError(N_("This backup has no account, so nobody could sign in afterwards"))
    finally:
        con.close()


def _summary(con: sqlite3.Connection, media_root: Path) -> Summary:
    """What a library holds, and how many of its items have no file below `media_root` (what a metadata-only backup leaves
    to your own copy). The file layout is the one of pipeline.media_path and albums.track_path."""
    summary = Summary(items=con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                      people=con.execute("SELECT COUNT(*) FROM people").fetchone()[0],
                      users=con.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    for item in con.execute("SELECT id, kind, sha256, ext FROM items").fetchall():
        if item["kind"] == "album":
            names = [r["filename"] for r in con.execute("SELECT filename FROM tracks WHERE item_id=?", (item["id"],))]
            summary.no_file += any(not (media_root / "albums" / item["sha256"] / name).exists() for name in names)
        else:
            summary.no_file += not (media_root / item["sha256"][:2] / f"{item['sha256']}{item['ext']}").exists()
    return summary


def restore(fileobj, apply: bool = True) -> Summary:
    """Restore the backup in `fileobj` (a .tgz) into this library. Only for a library without an account.
    With apply=False it only checks the backup, the same way, and says what is in it; the library is not touched."""
    s = get_settings()
    with _lock:
        if apply:
            if accounts.user_count():
                raise RestoreError(N_("This library already has an account, so nothing is restored over it"))
            for name in CONTENT_DIRS:
                folder = s.data_dir / name
                if folder.exists() and any(folder.iterdir()):
                    raise RestoreError(N_("This data folder already holds files, so nothing is restored into it"))
        staging = s.data_dir / f".restore-{uuid.uuid4().hex[:12]}"
        staging.mkdir(parents=True)
        try:
            _unpack(fileobj, staging, shutil.disk_usage(s.data_dir).free)
            _check_database(staging / "drollery.db")
            if not apply:
                con = sqlite3.connect(f"file:{staging / 'drollery.db'}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                try:
                    return _summary(con, staging / "media")
                finally:
                    con.close()
            # --- from here on things are put in place: the database first (one SQLite operation), then the folders
            source = sqlite3.connect(f"file:{staging / 'drollery.db'}?mode=ro", uri=True)
            try:
                dest = db.connect()
                try:
                    source.backup(dest)
                finally:
                    dest.close()
            except sqlite3.Error:
                raise RestoreError(N_("The backup could not be put in place")) from None
            finally:
                source.close()
            for name in CONTENT_DIRS:
                staged, target = staging / name, s.data_dir / name
                if staged.exists():
                    shutil.rmtree(target, ignore_errors=True)          # the empty folder the server made
                    os.replace(staged, target)
            for name in CONTENT_DIRS:
                (s.data_dir / name).mkdir(parents=True, exist_ok=True)
            if (staging / "config.toml").exists():
                config = s.data_dir / "config.toml"
                if config.exists():
                    shutil.copy2(config, s.data_dir / "config.toml.before-restore")
                os.replace(staging / "config.toml", config)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    db.init()                                                           # columns and indexes of a newer version, cleanup of old state
    with db.tx() as c:
        c.execute("DELETE FROM sessions")                              # nobody stays signed in from before
        pipeline.plan_upkeep(c)
    accounts.clear_setup_code()
    with db.tx() as c:
        return _summary(c, s.media_dir)
