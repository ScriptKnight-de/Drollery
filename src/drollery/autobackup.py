"""Backups that Drollery makes by itself (Settings > Backup > Automatic backup).

A scheduler asks once a minute whether one is due (`tick`). A backup is the same archive as the download, written to a folder
(`backups/` in the data folder, or `backup_dir` in config.toml): into a `.part` file first, then renamed, so a half-made
file never looks finished. Only files this module made (`drollery-auto-...tgz`) are ever listed, downloaded, deleted or
pruned. The files have owner-only permissions: they hold password hashes and saved API keys.

The settings live in the settings table: autobackup.enabled / every / hour / kind / keep, and the state of the last run.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import accounts, backup
from .config import get_settings
from .i18n import N_

log = logging.getLogger("drollery")

NAME = re.compile(r"^drollery-auto-(\d{8}-\d{6})-(metadata|full)\.tgz$")
EVERY = ("daily", "weekly")
DEFAULTS = {"enabled": False, "every": "daily", "hour": 3, "kind": "metadata", "keep": 7}
MAX_KEEP = 60
RETRY_AFTER = 3600           # seconds to wait after a failed run before trying again
MARGIN = 256 * 1024 * 1024   # free space that must remain after the backup
_lock = threading.Lock()


class AutoBackupError(RuntimeError):
    """The message is an English catalog key; the caller translates it."""


# ---------------------------------------------------------------------- settings

def _get(key: str):
    return accounts.get_setting(f"autobackup.{key}")


def config() -> dict:
    """The saved settings, every value checked and defaulted."""
    raw = {k: _get(k) for k in DEFAULTS}
    every = raw["every"] if raw["every"] in EVERY else DEFAULTS["every"]
    kind = raw["kind"] if raw["kind"] in backup.KINDS else DEFAULTS["kind"]
    try:
        hour = min(23, max(0, int(raw["hour"])))
    except (TypeError, ValueError):
        hour = DEFAULTS["hour"]
    try:
        keep = min(MAX_KEEP, max(1, int(raw["keep"])))
    except (TypeError, ValueError):
        keep = DEFAULTS["keep"]
    return {"enabled": raw["enabled"] == "1", "every": every, "hour": hour, "kind": kind, "keep": keep}


def save(enabled: bool, every: str, hour: int, kind: str, keep: int) -> None:
    if every not in EVERY or kind not in backup.KINDS:
        raise AutoBackupError(N_("Choose how often and what to back up"))
    accounts.set_setting("autobackup.enabled", "1" if enabled else "0")
    accounts.set_setting("autobackup.every", every)
    accounts.set_setting("autobackup.hour", str(min(23, max(0, hour))))
    accounts.set_setting("autobackup.kind", kind)
    accounts.set_setting("autobackup.keep", str(min(MAX_KEEP, max(1, keep))))


def status() -> dict:
    """When the last run was, whether it worked, and whether one is running now."""
    def number(key):
        try:
            return float(_get(key))
        except (TypeError, ValueError):
            return None
    return {"last_ok": number("last_ok"), "last_run": number("last_run"), "error": _get("last_error") or "", "running": _lock.locked()}


# ------------------------------------------------------------------------ files

def folder() -> Path:
    path = get_settings().backups_dir
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def listing() -> list[dict]:
    """The automatic backups, newest first."""
    out = []
    for p in folder().iterdir():
        m = NAME.match(p.name)
        if m and p.is_file():
            st = p.stat()
            out.append({"name": p.name, "kind": m.group(2), "size": st.st_size, "made": st.st_mtime})
    return sorted(out, key=lambda x: x["name"], reverse=True)


def path_of(name: str) -> Path | None:
    """The file of this name, or None. Only the exact names this module makes are accepted: no path can get in."""
    if not NAME.match(name or ""):
        return None
    p = folder() / name
    return p if p.is_file() else None


def delete(name: str) -> bool:
    p = path_of(name)
    if p is None:
        return False
    p.unlink()
    return True


def prune(keep: int) -> int:
    """Delete the oldest automatic backups beyond the newest `keep`. Returns how many went."""
    gone = 0
    for item in listing()[keep:]:
        (folder() / item["name"]).unlink(missing_ok=True)
        gone += 1
    return gone


# --------------------------------------------------------------------- schedule

def last_slot(now: datetime, every: str, hour: int) -> datetime:
    """The most recent moment a backup was meant to be made: today at `hour` (yesterday if that is still to come), and for
    weekly the same on the latest Sunday."""
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    if every == "weekly":
        slot -= timedelta(days=(slot.weekday() - 6) % 7)           # back to Sunday (weekday 6)
    return slot


def is_due(now: datetime | None = None) -> bool:
    cfg = config()
    if not cfg["enabled"]:
        return False
    now = now or datetime.now()
    st = status()
    slot = last_slot(now, cfg["every"], cfg["hour"]).timestamp()
    if st["last_ok"] is not None and st["last_ok"] >= slot:
        return False                                                # this slot is done
    if st["error"] and st["last_run"] is not None and st["last_run"] >= slot and now.timestamp() - st["last_run"] < RETRY_AFTER:
        return False                                                # it failed a moment ago: do not hammer
    return True


# -------------------------------------------------------------------------- run

def _check_space(kind: str, target: Path) -> None:
    sizes = backup.sizes()
    need = sizes["database"] + (sizes["content"] if kind == "full" else 0)
    if shutil.disk_usage(target).free < need * 1.1 + MARGIN:
        raise AutoBackupError(N_("There is not enough free disk space for this backup"))


def run(kind: str | None = None) -> str:
    """Make one backup now and return its file name. Raises AutoBackupError when one is already running or it fails."""
    if not _lock.acquire(blocking=False):
        raise AutoBackupError(N_("A backup is already running"))
    cfg = config()
    kind = kind if kind in backup.KINDS else cfg["kind"]
    now = time.time()
    part = None
    try:
        accounts.set_setting("autobackup.last_run", str(now))
        target = folder()
        _check_space(kind, target)
        name = f"drollery-auto-{datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S')}-{kind}.tgz"
        part = target / (name + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)          # owner only from the first byte
        with os.fdopen(fd, "wb") as out:
            for chunk in backup.stream(kind):
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(part, target / name)
        part = None
        accounts.set_setting("autobackup.last_ok", str(time.time()))
        accounts.set_setting("autobackup.last_error", "")
        prune(cfg["keep"])
        log.info("automatic backup made: %s", name)
        return name
    except AutoBackupError as e:
        accounts.set_setting("autobackup.last_error", str(e))
        log.warning("automatic backup failed: %s", e)
        raise
    except Exception as e:  # noqa: BLE001 - a backup must never take the scheduler down
        message = f"{type(e).__name__}: {e}"[:300]
        accounts.set_setting("autobackup.last_error", message)
        log.warning("automatic backup failed: %s", message)
        raise AutoBackupError(message) from e
    finally:
        if part is not None:
            part.unlink(missing_ok=True)                               # never leave a half-made file
        _lock.release()


def run_in_background(kind: str | None = None) -> bool:
    """Start a backup in its own thread (for the button). False when one is already running."""
    if _lock.locked():
        return False

    def work():
        try:
            run(kind)
        except AutoBackupError:
            pass                                                        # kept in the status for the page
    threading.Thread(target=work, name="autobackup", daemon=True).start()
    return True


def tick(now: datetime | None = None) -> bool:
    """Called once a minute: make a backup if one is due. True when one was made."""
    if _lock.locked() or not is_due(now):
        return False
    try:
        run()
    except AutoBackupError:
        return False
    return True
