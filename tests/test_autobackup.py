"""Backups that Drollery makes by itself: the schedule, the files, the cleaning up, and the page."""
import asyncio
import io
import os
import stat
import tarfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from drollery import accounts, autobackup, backup, restore
from drollery.config import get_settings
from test_app import png


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def stamp(text):
    return at(text).timestamp()


def make_item(client, n=1):
    return client.post("/api/v1/items", files={"file": (f"p{n}.png", png(n), "image/png")}).json()["id"]


def turn_on(**over):
    cfg = {"enabled": True, "every": "daily", "hour": 3, "kind": "metadata", "keep": 7, **over}
    autobackup.save(cfg["enabled"], cfg["every"], cfg["hour"], cfg["kind"], cfg["keep"])


# ------------------------------------------------------------------ settings

def test_the_settings_have_safe_defaults_and_bad_values_are_repaired(client):
    assert autobackup.config() == {"enabled": False, "every": "daily", "hour": 3, "kind": "metadata", "keep": 7}      # off until you switch it on
    for key, junk in (("every", "hourly"), ("hour", "99"), ("kind", "everything"), ("keep", "0")):
        accounts.set_setting(f"autobackup.{key}", junk)
    cfg = autobackup.config()
    assert cfg["every"] == "daily" and cfg["hour"] == 23 and cfg["kind"] == "metadata" and cfg["keep"] == 1
    accounts.set_setting("autobackup.hour", "x")
    accounts.set_setting("autobackup.keep", "9999")
    assert autobackup.config()["hour"] == 3 and autobackup.config()["keep"] == autobackup.MAX_KEEP


def test_saving_checks_the_choices(client):
    turn_on(every="weekly", hour=5, kind="full", keep=3)
    assert autobackup.config() == {"enabled": True, "every": "weekly", "hour": 5, "kind": "full", "keep": 3}
    with pytest.raises(autobackup.AutoBackupError):
        autobackup.save(True, "monthly", 3, "metadata", 7)
    with pytest.raises(autobackup.AutoBackupError):
        autobackup.save(True, "daily", 3, "nothing", 7)
    assert autobackup.config()["every"] == "weekly"                                      # a refused save changed nothing


# ------------------------------------------------------------------- schedule

def test_the_latest_moment_a_backup_was_meant_to_be_made():
    sat_noon, sun_after = at("2026-11-21 12:00"), at("2026-11-22 04:00")                 # 2026-11-22 is a Sunday
    assert sun_after.weekday() == 6
    assert autobackup.last_slot(sat_noon, "daily", 3) == at("2026-11-21 03:00")
    assert autobackup.last_slot(at("2026-11-21 02:59"), "daily", 3) == at("2026-11-20 03:00")      # today's is still to come
    assert autobackup.last_slot(sun_after, "weekly", 3) == at("2026-11-22 03:00")
    assert autobackup.last_slot(sat_noon, "weekly", 3) == at("2026-11-15 03:00")                    # the Sunday before
    assert autobackup.last_slot(at("2026-11-22 01:00"), "weekly", 3) == at("2026-11-15 03:00")      # Sunday, but not at 3 yet


def test_when_a_backup_is_due(client):
    now = at("2026-11-21 12:00")
    assert not autobackup.is_due(now)                                                    # switched off
    turn_on()
    assert autobackup.is_due(now)                                                        # never made: now
    accounts.set_setting("autobackup.last_ok", str(stamp("2026-11-21 03:05")))
    assert not autobackup.is_due(now)                                                    # today's is done
    assert autobackup.is_due(at("2026-11-22 03:30"))                                     # the next slot has come
    accounts.set_setting("autobackup.last_ok", str(stamp("2026-11-18 03:05")))
    assert autobackup.is_due(now)                                                        # the server was off for days: catch up at once
    turn_on(every="weekly")
    accounts.set_setting("autobackup.last_ok", str(stamp("2026-11-15 03:05")))
    assert not autobackup.is_due(at("2026-11-21 12:00")) and autobackup.is_due(at("2026-11-22 03:30"))


def test_a_failed_run_is_not_repeated_every_minute(client):
    turn_on()
    now = at("2026-11-21 12:00")
    accounts.set_setting("autobackup.last_run", str(now.timestamp() - 120))
    accounts.set_setting("autobackup.last_error", "something went wrong")
    assert not autobackup.is_due(now)                                                    # tried two minutes ago
    assert autobackup.is_due(datetime.fromtimestamp(now.timestamp() + autobackup.RETRY_AFTER))


# ---------------------------------------------------------------------- files

def test_a_backup_is_a_private_restorable_file_with_a_clean_name(client):
    make_item(client)
    name = autobackup.run("metadata")
    assert autobackup.NAME.match(name) and name.endswith("-metadata.tgz")
    path = autobackup.folder() / name
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(autobackup.folder().stat().st_mode) == 0o700     # nobody else may read it
    assert not list(autobackup.folder().glob("*.part"))
    with path.open("rb") as f:
        summary = restore.restore(f, apply=False)                                        # the same file the restore accepts
    assert summary.items == 1 and summary.users == 1
    st = autobackup.status()
    assert st["last_ok"] and not st["error"] and not st["running"]


def test_a_full_backup_holds_the_files_but_not_the_other_backups(client):
    make_item(client)
    autobackup.run("full")
    second = autobackup.run("full")
    with tarfile.open(autobackup.folder() / second) as t:
        names = t.getnames()
    assert any(n.startswith("media/") and n.endswith(".png") for n in names) and not any("backups" in n or "drollery-auto" in n for n in names)


def test_only_the_newest_are_kept_and_only_our_own_files_are_touched(client):
    folder = autobackup.folder()
    foreign = ["notes.txt", "drollery-backup-20250101-000000.tgz", "drollery-auto-garbage.tgz", "drollery-auto-20250101-000000-metadata.tgz.part"]
    for name in foreign:
        (folder / name).write_text("mine")
    for n in range(5):
        (folder / f"drollery-auto-2026110{n + 1}-030000-metadata.tgz").write_bytes(b"x")
    assert autobackup.prune(3) == 2
    assert [b["name"] for b in autobackup.listing()] == [f"drollery-auto-2026110{n}-030000-metadata.tgz" for n in (5, 4, 3)]     # newest first
    assert all((folder / name).read_text() == "mine" for name in foreign)


def test_the_run_keeps_as_many_as_the_setting_says(client):
    turn_on(keep=2)
    for _ in range(4):
        autobackup.run()
        time.sleep(1.05)                                                                 # the name has the second in it
    assert len(autobackup.listing()) == 2


def test_names_that_are_not_ours_never_reach_a_file(client):
    name = autobackup.run("metadata")
    assert autobackup.path_of(name) is not None
    for bad in ("../drollery.db", "drollery.db", "x.tgz", name + ".part", name.replace("auto", "AUTO"), f"../{name}", "", None):
        assert autobackup.path_of(bad) is None and not autobackup.delete(bad)
    assert (get_settings().data_dir / "drollery.db").exists()
    assert autobackup.delete(name) and autobackup.path_of(name) is None


# ------------------------------------------------------------------- failures

def test_a_failing_backup_leaves_no_half_made_file_and_says_why(client, monkeypatch):
    def broken(kind):
        yield b"some bytes"
        raise OSError("the disk went away")
    monkeypatch.setattr(backup, "stream", broken)
    with pytest.raises(autobackup.AutoBackupError, match="the disk went away"):
        autobackup.run("metadata")
    assert not list(autobackup.folder().iterdir())
    st = autobackup.status()
    assert "the disk went away" in st["error"] and st["last_ok"] is None and not st["running"]
    monkeypatch.undo()
    autobackup.run("metadata")                                                           # and the next one works and clears the message
    assert autobackup.status()["error"] == "" and autobackup.status()["last_ok"]


def test_not_enough_disk_space_is_said_before_anything_is_written(client, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(autobackup.AutoBackupError, match="not enough free disk space"):
        autobackup.run("metadata")
    assert not list(autobackup.folder().iterdir()) and "not enough free disk space" in autobackup.status()["error"]


def test_two_backups_do_not_run_at_the_same_time(client):
    assert autobackup._lock.acquire(blocking=False)
    try:
        assert autobackup.status()["running"]
        with pytest.raises(autobackup.AutoBackupError, match="already running"):
            autobackup.run()
        assert not autobackup.run_in_background() and not autobackup.tick(at("2026-11-21 12:00"))
    finally:
        autobackup._lock.release()


def test_the_tick_makes_a_backup_only_when_one_is_due(client):
    now = at("2026-11-21 12:00")
    assert not autobackup.tick(now) and not autobackup.listing()                         # switched off
    turn_on()
    assert autobackup.tick(now) and len(autobackup.listing()) == 1
    assert not autobackup.tick(datetime.now()) and len(autobackup.listing()) == 1        # made just now: nothing more today


def test_the_scheduler_ends_at_once_when_the_app_stops(client):
    from drollery import main
    stop = asyncio.Event()
    stop.set()
    asyncio.run(asyncio.wait_for(main._backup_scheduler(stop), timeout=5))


# ----------------------------------------------------------------------- folder

def test_the_folder_can_be_moved_by_the_config(tmp_path):
    from drollery.config import Settings
    assert Settings(data_dir=tmp_path).backups_dir == tmp_path / "backups"
    assert Settings(data_dir=tmp_path, backup_dir=str(tmp_path / "elsewhere")).backups_dir == tmp_path / "elsewhere"
    assert Settings(data_dir=tmp_path, backup_dir="  ").backups_dir == tmp_path / "backups"


# ------------------------------------------------------------------------- page

def test_the_page_offers_the_settings_the_list_and_the_actions(client):
    page = client.get("/settings/backup").text
    assert "Automatic backup" in page and str(get_settings().backups_dir) in page and "No automatic backup has been made yet" in page
    assert 'name="enabled"' in page and 'name="every"' in page and 'name="hour"' in page and 'name="kind"' in page and 'name="keep"' in page
    assert "Server time, now" in page and "Back up now" in page
    r = client.post("/settings/backup/auto", data={"enabled": "1", "every": "weekly", "hour": "5", "kind": "full", "keep": "4"})
    assert "Automatic backup saved" in r.text and autobackup.config() == {"enabled": True, "every": "weekly", "hour": 5, "kind": "full", "keep": 4}
    page = client.get("/settings/backup").text
    assert '<option value="weekly" selected>' in page and '<option value="5" selected>' in page and 'value="4"' in page
    assert "The next one starts within a minute" in page or "Next:" in page
    client.post("/settings/backup/auto", data={"every": "daily", "hour": "x", "kind": "metadata", "keep": ""})        # no tick: switched off, defaults for junk
    assert not autobackup.config()["enabled"] and autobackup.config()["hour"] == 3 and autobackup.config()["keep"] == 7
    assert "Choose how often" in client.post("/settings/backup/auto", data={"every": "monthly"}).text


def test_back_up_now_makes_a_file_that_can_be_downloaded_and_deleted(client):
    make_item(client)
    r = client.post("/settings/backup/auto/run")
    assert "The backup has started" in r.text
    for _ in range(100):
        if autobackup.listing() and not autobackup.status()["running"]:
            break
        time.sleep(0.1)
    (entry,) = autobackup.listing()
    page = client.get("/settings/backup").text
    assert entry["name"] in page and "Last backup:" in page and f'/settings/backup/auto/{entry["name"]}' in page
    r = client.get(f'/settings/backup/auto/{entry["name"]}')
    assert r.status_code == 200 and r.headers["content-type"] == "application/gzip" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith("attachment") and entry["name"] in r.headers["content-disposition"]
    assert "drollery.db" in tarfile.open(fileobj=io.BytesIO(r.content)).getnames()
    assert client.get("/settings/backup/auto/../../drollery.db").status_code in (404, 405)
    assert client.get("/settings/backup/auto/notes.txt").status_code == 404
    assert "Backup deleted" in client.post(f'/settings/backup/auto/{entry["name"]}/delete').text and not autobackup.listing()
    assert "does not exist any more" in client.post(f'/settings/backup/auto/{entry["name"]}/delete').text


def test_only_a_signed_in_person_reaches_the_backups(client):
    name = autobackup.run("metadata")
    from test_share import anon_client
    other = anon_client()
    for method, url in (("get", f"/settings/backup/auto/{name}"), ("post", f"/settings/backup/auto/{name}/delete"), ("post", "/settings/backup/auto/run"),
                        ("post", "/settings/backup/auto")):
        r = getattr(other, method)(url, follow_redirects=False)
        assert r.status_code in (303, 401), url
    assert autobackup.path_of(name) is not None
