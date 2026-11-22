"""Downloading a backup from Settings, and getting back into the library after losing the password."""
from conftest import create_user
import io
import json
import sqlite3
import tarfile
import threading

import httpx
import pytest

from drollery import accounts, backup, db, providers, security
from drollery.config import get_settings
from drollery.__main__ import reset_admin
from test_app import png


def upload(client, n=1):
    return client.post("/api/v1/items", files={"file": (f"pic{n}.png", png(100 + n), "image/png")}).json()["id"]


def unpack(tar, dest):
    """tarfile's safe-extraction filter exists from Python 3.11.4 / 3.12; older interpreters extract our own archive as is."""
    tar.extractall(dest, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def download(client, kind):
    r = client.post("/settings/backup/download", data={"kind": kind})
    assert r.status_code == 200, r.text[:200]
    return r, tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz")


# ------------------------------------------------------------------ the backup

def test_the_backup_page_is_in_the_settings_menu_and_offers_both_kinds(client):
    page = client.get("/settings/backup").text
    assert 'href="/settings/backup"' in page and "Back up your library" in page
    assert page.count('action="/settings/backup/download"') == 2 and 'value="full"' in page and 'value="metadata"' in page
    assert "Keep the file private" in page and "python -m drollery restore" in page and "Or restore a backup" in page      # how to bring it back


def test_a_full_backup_holds_the_database_and_the_files_laid_out_like_the_data_folder(client):
    item = upload(client)
    r, tar = download(client, "full")
    names = tar.getnames()
    assert "drollery.db" in names and any(n.startswith("media/") and n.endswith(".png") for n in names)
    assert r.headers["content-type"] == "application/gzip" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith('attachment; filename="drollery-backup-') and r.headers["content-disposition"].endswith('.tgz"')
    stored = next(n for n in names if n.startswith("media/") and n.endswith(".png"))
    assert tar.extractfile(stored).read() == (get_settings().data_dir / stored).read_bytes()          # byte for byte
    assert not [n for n in names if n.startswith(("tmp", "setup-code")) or n.endswith(("-wal", "-shm"))]
    assert item


def test_the_database_in_a_backup_is_a_consistent_copy_that_opens_and_has_the_library(client, tmp_path):
    item = upload(client)
    client.patch(f"/api/v1/items/{item}", json={"tags": ["backed-up"], "title": "Kept safe"})
    _, tar = download(client, "full")
    out = tmp_path / "restored"
    unpack(tar, out)
    conn = sqlite3.connect(out / "drollery.db")
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT title FROM items WHERE id=?", (item,)).fetchone()[0] == "Kept safe"
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM items_fts WHERE items_fts MATCH 'backed'").fetchone()[0] == 1   # search index survives


def test_a_metadata_backup_has_no_media_and_is_much_smaller(client):
    upload(client)
    r_full, _ = download(client, "full")
    r_meta, tar = download(client, "metadata")
    assert "drollery.db" in tar.getnames() and not [n for n in tar.getnames() if n.startswith(("media", "thumbs", "cards"))]
    assert r_meta.headers["content-disposition"].count("drollery-metadata-") == 1
    assert len(r_meta.content) < len(r_full.content)


def test_the_restore_command_in_the_readme_style_gives_a_working_library(client, tmp_path, monkeypatch):
    """Unpack into an empty data folder and start the app on it: the item, its file and the login come back."""
    item = upload(client)
    _, tar = download(client, "full")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    unpack(tar, fresh)
    monkeypatch.setenv("DROLLERY_DATA", str(fresh))
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from drollery.main import app
    with TestClient(app, follow_redirects=True) as c:
        assert c.post("/login", data={"username": "admin", "password": "correct horse battery"}).status_code == 200
        shown = c.get(f"/api/v1/items/{item}").json()
        assert shown["id"] == item
        original = c.get(f"/media/{item}")
        assert original.status_code == 200 and original.content.startswith(b"\x89PNG")     # the file itself came back too


def test_symlinks_are_never_followed_out_of_the_data_folder(client, tmp_path):
    upload(client)
    secret = tmp_path.parent / "outside-secret.txt"
    secret.write_text("do not leak")
    (get_settings().media_dir / "link.txt").symlink_to(secret)
    _, tar = download(client, "full")
    assert not [n for n in tar.getnames() if n.endswith("link.txt")]
    assert all(b"do not leak" not in (tar.extractfile(m).read() if m.isfile() else b"") for m in tar.getmembers())


def test_the_backup_needs_a_signed_in_user_and_only_accepts_known_kinds(anon, client):
    assert anon.post("/settings/backup/download", data={"kind": "full"}).status_code in (303, 401, 403)
    assert anon.get("/settings/backup").status_code in (303, 401, 403)
    bad = client.post("/settings/backup/download", data={"kind": "../../etc"})
    assert "Choose what to back up" in bad.text and bad.headers["content-type"].startswith("text/html")
    assert client.get("/settings/backup/download").status_code == 405                       # not a link anyone can plant


def test_no_temporary_snapshot_is_left_behind_even_when_the_download_is_abandoned(client):
    upload(client)
    gen = backup.stream("full")
    next(gen)                                                                                # start, then walk away
    gen.close()
    assert not list(get_settings().tmp_dir.glob("backup-*.db"))
    for _ in backup.stream("metadata"):
        pass
    assert not list(get_settings().tmp_dir.glob("backup-*.db")) and threading.active_count() < 20


def test_a_download_nobody_reads_any_more_cleans_up_by_itself(client, monkeypatch):
    """The server does not always close the stream when a browser disconnects, so the writer gives up on its own."""
    import os, time
    monkeypatch.setattr(backup, "STALL_SECONDS", 1)
    (get_settings().media_dir / "big.bin").write_bytes(os.urandom(6 * 1024 * 1024))          # more than the queue can hold
    gen = backup.stream("full")
    next(gen)                                                                                  # the reader takes one chunk and vanishes, still referenced
    assert list(get_settings().tmp_dir.glob("backup-*.db"))                                    # the snapshot exists while it waits
    for _ in range(100):
        if not list(get_settings().tmp_dir.glob("backup-*.db")):
            break
        time.sleep(0.1)
    assert not list(get_settings().tmp_dir.glob("backup-*.db"))
    for _ in range(60):                                                                        # and the writer thread ends too
        if not [t for t in threading.enumerate() if "_write" in t.name]:
            break
        time.sleep(0.1)
    assert not [t for t in threading.enumerate() if "_write" in t.name]
    gen.close()


def test_a_browser_that_goes_away_cancels_the_response_body_and_the_writer_stops_at_once(client):
    """The route serves an async body: when the server cancels it (disconnect), its finally stops the writer immediately."""
    import asyncio
    import os
    from drollery import routes_settings
    (get_settings().media_dir / "big.bin").write_bytes(os.urandom(6 * 1024 * 1024))

    async def scenario():
        body = routes_settings._backup_body("full")
        first = await body.__anext__()
        assert first[:2] == b"\x1f\x8b"                                                       # a gzip stream has started
        assert list(get_settings().tmp_dir.glob("backup-*.db"))
        await body.aclose()                                                                    # what the server does on a disconnect

    asyncio.run(scenario())
    assert not list(get_settings().tmp_dir.glob("backup-*.db"))                                # gone immediately, no waiting
    assert not [t for t in threading.enumerate() if "_write" in t.name and t.is_alive()]


def test_a_failure_while_making_the_archive_fails_the_download_instead_of_looking_complete(client, monkeypatch):
    def boom(dest):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(backup, "snapshot_db", boom)
    with pytest.raises(sqlite3.OperationalError):
        b"".join(backup.stream("full"))


def test_sizes_are_shown_in_readable_units(client):
    upload(client)
    page = client.get("/settings/backup").text
    assert " KB" in page or " B</span>" in page or " MB" in page
    from drollery.web import _bytes
    assert [_bytes(x) for x in (0, 1023, 1024, 1536, 5 * 1024**2, 3 * 1024**3)] == ["0 B", "1023 B", "1.0 KB", "1.5 KB", "5.0 MB", "3.0 GB"]


# ----------------------------------------------------------- getting back in

def test_reset_admin_sets_a_new_password_turns_2fa_off_and_signs_everyone_out(client):
    admin = accounts.get_user_by_name("admin")
    secret = accounts.start_2fa(admin["id"])
    accounts.enable_2fa(admin["id"], secret, 1)
    assert accounts.get_user(admin["id"])["totp_enabled"]
    lines = []
    assert reset_admin(out=lines.append) == 0
    new = lines[0].rsplit(": ", 1)[1]
    user = accounts.get_user(admin["id"])
    assert security.verify_password(new, user["password_hash"]) and not security.verify_password("correct horse battery", user["password_hash"])
    assert not user["totp_enabled"] and user["backup_codes"] in ("[]", "")
    assert accounts.list_sessions(admin["id"]) == []
    assert len(new) >= security.MIN_PASSWORD and not security.password_problem(new, "admin")
    assert "Settings > Security" in " ".join(lines)


def test_the_new_password_really_signs_in_through_the_web(client, anon):
    lines = []
    reset_admin(out=lines.append)
    new = lines[0].rsplit(": ", 1)[1]
    assert anon.post("/login", data={"username": "admin", "password": "correct horse battery"}).status_code in (401, 422, 200)
    assert "drollery_session" not in anon.cookies
    r = anon.post("/login", data={"username": "admin", "password": new})
    assert r.status_code == 303 and "drollery_session" in anon.cookies


def test_each_reset_gives_a_different_password(client):
    seen = set()
    for _ in range(3):
        lines = []
        reset_admin(out=lines.append)
        seen.add(lines[0].rsplit(": ", 1)[1])
    assert len(seen) == 3


def test_reset_admin_with_several_accounts_needs_a_name_and_touches_only_that_one(client):
    other = create_user("second", "another-long-pass")
    lines = []
    assert reset_admin(out=lines.append) == 1 and "--user" in lines[0] and "admin" in lines[0] and "second" in lines[0]
    before = accounts.get_user(other)["password_hash"]
    lines = []
    assert reset_admin("ADMIN", out=lines.append) == 0                                       # not case sensitive
    assert accounts.get_user(other)["password_hash"] == before
    assert reset_admin("nobody", out=lines.append) == 1 and "no account called" in lines[-1]


def test_reset_admin_before_setup_points_to_the_setup_page(anon):
    lines = []
    assert reset_admin(out=lines.append) == 1 and "setup code" in lines[0]


def test_the_command_line_entry_point_runs(client, capsys):
    from drollery.__main__ import main
    assert main(["reset-admin"]) == 0
    assert "New password for “admin”" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main([])


# ------------------------------------------------------- provider errors (the 503 from Gemini)

def reply(status, body, reason=None):
    req = httpx.Request("POST", "https://llm.example.test/v1/chat/completions")
    return httpx.Response(status, json=body, request=req) if isinstance(body, (dict, list)) else httpx.Response(status, text=body, request=req)


def test_an_overloaded_service_is_reported_with_its_own_words_and_marked_temporary():
    with pytest.raises(providers.ProviderError) as e:
        providers._check(reply(503, {"error": {"code": 503, "message": "The model is overloaded.\nPlease try again later.", "status": "UNAVAILABLE"}}))
    msg = str(e.value)
    assert "HTTP 503 Service Unavailable from llm.example.test: The model is overloaded. Please try again later." in msg
    assert "try again later (Retry on the Jobs page)" in msg and e.value.transient is True


def test_not_found_and_key_problems_say_what_to_check_and_are_not_retried_blindly():
    with pytest.raises(providers.ProviderError) as e:
        providers._check(reply(404, {"error": {"message": "models/x is not found"}}))
    assert "models/x is not found" in str(e.value) and "model name" in str(e.value) and e.value.transient is False
    with pytest.raises(providers.ProviderError) as e:
        providers._check(reply(401, "nope"))
    assert "API key" in str(e.value) and not e.value.transient
    for status in (429, 500, 502, 504):
        with pytest.raises(providers.ProviderError) as e:
            providers._check(reply(status, "busy"))
        assert e.value.transient


def test_an_unreadable_error_body_is_trimmed_and_success_passes():
    providers._check(reply(200, {"ok": True}))
    with pytest.raises(providers.ProviderError) as e:
        providers._check(reply(502, "<html>" + "x" * 5000))
    assert len(str(e.value)) < 600


def test_a_busy_service_makes_the_job_wait_minutes_before_the_next_try(client, monkeypatch):
    from drollery import pipeline
    item = upload(client)
    client.post("/settings/ai/models", data={"name": "m", "type": "openai", "base_url": "http://x/v1", "model": "m", "api_key": "", "command": "",
                                             "langs": "eng", "language": "", "prompt": "", "timeout": 60, "send_image": "1"})
    mid = str(accounts.list_models()[0]["id"])
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": mid})
    monkeypatch.setattr(providers, "describe", lambda *a, **k: (_ for _ in ()).throw(providers.ProviderError("HTTP 503", transient=True)))
    client.post(f"/items/{item}/reprocess")
    job = db.claim_job()
    import time
    now = time.time()
    pipeline.run_job(job)
    with db.tx() as c:
        row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone())
    assert row["status"] == "queued" and row["run_after"] - now >= 290                      # 300 s, not 30 s
    monkeypatch.setattr(providers, "describe", lambda *a, **k: (_ for _ in ()).throw(providers.ProviderError("HTTP 400")))
    client.post(f"/items/{item}/reprocess")
    job = db.claim_job()
    now = time.time()
    pipeline.run_job(job)
    with db.tx() as c:
        row = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone())
    assert row["status"] == "queued" and row["run_after"] - now < 60                         # an ordinary failure keeps the short pause
