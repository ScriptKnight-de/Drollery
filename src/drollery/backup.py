"""Backups you can download from Settings.

The archive is a .tgz laid out exactly like the data folder, so the restore steps in the README (unpack it into an empty
data volume) work for it as they do for a hand-made backup:

  metadata  drollery.db (titles, tags, transcripts, people, accounts, settings, AI keys) and config.toml
  full      the same plus media/ (your files), thumbs/ and cards/

The database is copied with SQLite's online backup, so the snapshot is consistent while Drollery keeps running. It is
streamed: nothing is written to disk except that snapshot, so a big library needs no extra space and starts downloading at
once. `tmp/` and the first-run setup code are left out.
"""
from __future__ import annotations

import os
import queue
import sqlite3
import tarfile
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

from .config import get_settings

KINDS = ("metadata", "full")
CONTENT_DIRS = ("media", "thumbs", "cards")
_DONE = object()
STALL_SECONDS = 30        # nobody reading for this long means the download was abandoned (the server does not always tell us)


def snapshot_db(dest: Path) -> None:
    """A consistent copy of the live database (WAL and all) in one file."""
    src = sqlite3.connect(get_settings().db_path, timeout=30)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def sizes() -> dict:
    """Bytes of the database and of the files a full backup adds (for the Settings page)."""
    s = get_settings()
    total = 0
    for name in CONTENT_DIRS:
        for root, _dirs, files in os.walk(s.data_dir / name):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
    db_size = s.db_path.stat().st_size if s.db_path.exists() else 0
    return {"database": db_size, "content": total}


def filename(kind: str) -> str:
    return f"drollery-{'backup' if kind == 'full' else 'metadata'}-{time.strftime('%Y%m%d-%H%M%S')}.tgz"


class _Sink:
    """A file-like object that hands what tarfile writes to the consumer, and stops writing when the download is abandoned."""

    def __init__(self, q: queue.Queue, cancelled: threading.Event):
        self.q, self.cancelled = q, cancelled

    def write(self, data: bytes) -> int:
        chunk = bytes(data)
        waited = 0.0
        while not self.cancelled.is_set() and waited < STALL_SECONDS:
            try:
                self.q.put(chunk, timeout=0.5)
                return len(chunk)
            except queue.Full:
                waited += 0.5
        raise BrokenPipeError("download abandoned")

    def flush(self) -> None:
        pass


def _add_tree(tar: tarfile.TarFile, base: Path, name: str) -> None:
    top = base / name
    if not top.is_dir():
        return
    tar.add(top, arcname=name, recursive=False)
    for root, dirs, files in os.walk(top):
        dirs.sort()
        for entry in sorted(dirs) + sorted(files):
            path = Path(root) / entry
            if path.is_symlink():
                continue                                  # never follow a link out of the data folder
            tar.add(path, arcname=str(path.relative_to(base)), recursive=False)


def _write(kind: str, sink: _Sink, errors: list) -> None:
    s = get_settings()
    snap = s.tmp_dir / f"backup-{uuid.uuid4().hex}.db"
    try:
        snapshot_db(snap)
        with tarfile.open(fileobj=sink, mode="w|gz") as tar:
            tar.add(snap, arcname="drollery.db")
            if s.data_dir.joinpath("config.toml").is_file():
                tar.add(s.data_dir / "config.toml", arcname="config.toml")
            if kind == "full":
                for name in CONTENT_DIRS:
                    _add_tree(tar, s.data_dir, name)
    except BrokenPipeError:
        pass
    except Exception as e:  # noqa: BLE001 - reported to the consumer, which ends the download
        errors.append(e)
    finally:
        snap.unlink(missing_ok=True)
        try:
            sink.q.put(_DONE, timeout=1)
        except queue.Full:
            pass                                          # nobody is reading any more


class Download:
    """One running backup: a writer thread fills a small queue, `read()` hands the chunks out. `cancel()` stops the writer
    and removes the snapshot, whoever calls it (a finished stream, a failed one, or a browser that went away)."""

    def __init__(self, kind: str):
        if kind not in KINDS:
            raise ValueError(kind)
        self.q: queue.Queue = queue.Queue(maxsize=32)
        self.cancelled = threading.Event()
        self.errors: list = []
        self.worker = threading.Thread(target=_write, args=(kind, _Sink(self.q, self.cancelled), self.errors), daemon=True)
        self.worker.start()

    def read(self) -> bytes | None:
        """The next chunk, or None at the end. Raises if the archive could not be completed, so the download fails
        instead of looking finished."""
        chunk = self.q.get()
        if chunk is _DONE:
            if self.errors:
                raise self.errors[0]
            return None
        return chunk

    def cancel(self) -> None:
        self.cancelled.set()
        while self.worker.is_alive():                     # let a blocked writer finish so the snapshot is removed
            try:
                self.q.get_nowait()
            except queue.Empty:
                self.worker.join(timeout=0.2)


def stream(kind: str) -> Iterator[bytes]:
    """The backup as chunks of a .tgz (for plain, synchronous use)."""
    dl = Download(kind)
    try:
        while (chunk := dl.read()) is not None:
            yield chunk
    finally:
        dl.cancel()
