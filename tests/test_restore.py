"""Restoring a backup on the first-run page: the round trip, and everything that must be refused."""
import io
import sqlite3
import tarfile
import time

import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD, _boot, create_user
from drollery import accounts, db
from test_app import png


def make_backup(tmp_path, monkeypatch, kind="full", items=2):
    """A real backup, made by a running Drollery with some content in it (then shut down)."""
    _boot(tmp_path / "source", monkeypatch)
    from drollery.main import app
    with TestClient(app, follow_redirects=False) as c:
        create_user("admin", PASSWORD)
        c.post("/login", data={"username": "admin", "password": PASSWORD})
        c.follow_redirects = True
        for n in range(items):
            i = c.post("/api/v1/items", files={"file": (f"pic{n}.png", png(30 + n), "image/png")}).json()["id"]
            c.patch(f"/api/v1/items/{i}", json={"title": f"Picture {n}", "tags": ["kept"]})
        c.post("/people", data={"name": "Pixel Pete", "first_name": "Max", "surname": "Mustermann"})
        c.post("/items/1/people", data={"name": "Pixel Pete"})
        data = c.post("/settings/backup/download", data={"kind": kind}).content
    from drollery import config
    config.get_settings.cache_clear()
    return data


def fresh(tmp_path, monkeypatch, name="target"):
    """A new instance where nobody has signed up yet. Returns the client (inside its lifespan) as a context manager."""
    _boot(tmp_path / name, monkeypatch)
    from drollery.main import app
    return TestClient(app, follow_redirects=False)


def post_restore(c, data, code=None, filename="drollery-backup.tgz"):
    return c.post("/setup/restore", data={"code": code if code is not None else accounts.get_setup_code()},
                  files={"backup": (filename, data, "application/gzip")})


def tgz(members):
    """An archive made of (name, bytes or a TarInfo-making callable) pairs, for the hostile ones."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, content in members:
            if callable(content):
                t.addfile(content(name))
                continue
            info = tarfile.TarInfo(name)
            info.size = len(content)
            t.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def a_database(tmp_path, monkeypatch, users=1, drop=None):
    """The bytes of a Drollery database: the real schema, optionally with an account and with one change made to it."""
    _boot(tmp_path, monkeypatch)
    db.init()
    from drollery.config import get_settings
    path = tmp_path / "copy.db"
    src, dst = sqlite3.connect(get_settings().db_path), sqlite3.connect(path)
    src.backup(dst)
    src.close()
    if users:
        dst.execute("INSERT INTO users(username,password_hash,role,created_at,updated_at) VALUES ('someone','x','admin',0,0)")
    if drop:
        dst.execute(drop)
    dst.commit()
    dst.close()
    return path.read_bytes()


# -------------------------------------------------------------- the round trip

def test_a_full_backup_comes_back_with_its_files_accounts_and_people(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        assert 'action="/setup/restore"' in c.get("/setup").text and "data-upload" in c.get("/setup").text
        r = post_restore(c, backup)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert accounts.user_count() == 1
        c.follow_redirects = True
        page = c.post("/login", data={"username": "admin", "password": PASSWORD})                 # the account from the backup
        assert "Picture 0" in page.text and "Picture 1" in page.text
        assert c.get("/media/1").status_code == 200 and c.get("/thumb/1").status_code == 200       # the files came back too
        assert "Pixel Pete" in c.get("/people").text and "Max Mustermann" in c.get("/people").text
        assert c.get("/", params={"tag": "kept"}).text.count('class="tile"') == 2                  # tags and the search index
        assert c.get("/api/v1/items", params={"q": "Picture"}).json()["items"]
        assert c.get("/setup", follow_redirects=False).status_code == 303                             # the first-run page is closed now
    assert not list((tmp_path / "target").glob(".restore-*"))                                         # no staging folder is left


def test_the_message_after_a_restore_says_what_came_back_and_what_has_no_file(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch, kind="metadata")
    with fresh(tmp_path, monkeypatch) as c:
        c.follow_redirects = True
        page = post_restore(c, backup)
        assert "Backup restored: 2 items" in page.text and "2 items have no file yet" in page.text and "Sign in with an account from the backup" in page.text
        assert accounts.user_count() == 1


def test_a_restored_config_replaces_the_default_and_keeps_the_old_one(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        before = (tmp_path / "target" / "config.toml").read_text() if (tmp_path / "target" / "config.toml").exists() else None
        post_restore(c, backup)
        assert (tmp_path / "target" / "config.toml").exists()
        if before is not None:
            assert (tmp_path / "target" / "config.toml.before-restore").read_text() == before


def test_nobody_stays_signed_in_from_the_backup(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        post_restore(c, backup)
        with db.tx() as con:
            assert con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


# ----------------------------------------------------------------- who may restore

def test_the_setup_code_is_needed_and_wrong_guesses_are_counted(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        r = post_restore(c, backup, code="not-the-code")
        assert r.status_code == 422 and "That setup code is not correct" in r.text and accounts.user_count() == 0
        for _ in range(40):
            r = post_restore(c, backup, code="still-wrong")
            if r.status_code == 429:
                break
        assert r.status_code == 429                                                                  # guessing is throttled, like on the setup form
        assert accounts.user_count() == 0


def test_nothing_is_restored_over_a_library_that_has_an_account(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        create_user("someone", PASSWORD)
        r = post_restore(c, backup, code="anything")
        assert r.status_code == 303 and r.headers["location"] == "/"
        with db.tx() as con:
            assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_a_data_folder_that_already_holds_files_is_refused(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        (tmp_path / "target" / "media" / "stray.bin").write_bytes(b"x")
        r = post_restore(c, backup)
        assert r.status_code == 422 and "already holds files" in r.text and accounts.user_count() == 0


def test_no_file_chosen(tmp_path, monkeypatch):
    with fresh(tmp_path, monkeypatch) as c:
        r = c.post("/setup/restore", data={"code": accounts.get_setup_code()})
        assert r.status_code == 422 and "Choose the backup file" in r.text


# ------------------------------------------------------------ hostile and broken files

@pytest.mark.parametrize("label, members, message", [
    ("a path that leaves the folder", [("drollery.db", b"x"), ("../evil.txt", b"x")], "file name that is not allowed"),
    ("an absolute path", [("/etc/evil", b"x")], "file name that is not allowed"),
    ("a backslash path", [("media\\..\\evil", b"x")], "file name that is not allowed"),
    ("a file that does not belong", [("drollery.db", b"x"), ("evil.sh", b"x")], "do not belong"),
    ("a nested config", [("media/../config.toml", b"x")], "file name that is not allowed"),
    ("no database", [("config.toml", b"x")], "database is missing"),
])
def test_unsafe_or_incomplete_archives_are_refused_and_leave_nothing_behind(tmp_path, monkeypatch, label, members, message):
    with fresh(tmp_path, monkeypatch) as c:
        r = post_restore(c, tgz(members))
        assert r.status_code == 422 and message in r.text, label
        assert accounts.user_count() == 0 and not list((tmp_path / "target").glob(".restore-*"))
        assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "target" / "evil.sh").exists()


def test_links_and_special_files_are_refused(tmp_path, monkeypatch):
    def link(name):
        info = tarfile.TarInfo(name)
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        return info
    with fresh(tmp_path, monkeypatch) as c:
        r = post_restore(c, tgz([("media/pointer", link)]))
        assert r.status_code == 422 and "links or special files" in r.text and accounts.user_count() == 0


def test_a_file_that_is_not_a_backup_is_refused(tmp_path, monkeypatch):
    with fresh(tmp_path, monkeypatch) as c:
        for data in (b"just some text", b"", tgz([("drollery.db", b"x" * 100)])[:40]):                   # text, nothing, a cut-off archive
            r = post_restore(c, data)
            assert r.status_code == 422 and ("not a Drollery backup" in r.text), data[:10]
        r = post_restore(c, tgz([("drollery.db", b"this is not a database at all" * 20)]))
        assert r.status_code == 422 and ("damaged" in r.text or "not one of Drollery" in r.text)
        assert accounts.user_count() == 0


def test_a_database_without_an_account_or_from_before_0_1_0_is_refused(tmp_path, monkeypatch):
    no_account = a_database(tmp_path / "a", monkeypatch, users=0)
    old = a_database(tmp_path / "b", monkeypatch, drop="ALTER TABLE shares DROP COLUMN track_id")
    with fresh(tmp_path, monkeypatch) as c:
        r = post_restore(c, tgz([("drollery.db", no_account)]))
        assert r.status_code == 422 and "no account" in r.text
        r = post_restore(c, tgz([("drollery.db", old)]))
        assert r.status_code == 422 and "before Drollery 0.1.0" in r.text and "0.1.7" in r.text
        assert accounts.user_count() == 0


def test_a_backup_that_does_not_fit_on_the_disk_is_refused(tmp_path, monkeypatch):
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch) as c:
        import shutil
        monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
        r = post_restore(c, backup)
        assert r.status_code == 422 and "not enough free disk space" in r.text and accounts.user_count() == 0
        assert not list((tmp_path / "target").glob(".restore-*"))


def test_the_page_speaks_german_too(tmp_path, monkeypatch):
    with fresh(tmp_path, monkeypatch) as c:
        c.cookies.set("drollery_lang", "de")
        page = c.get("/setup").text
        assert "Oder eine Sicherung wiederherstellen" in page and "Sicherungsdatei" in page


def test_the_restore_itself_refuses_a_library_with_an_account_even_if_the_page_did_not(tmp_path, monkeypatch):
    """The page checks first; this is the second check, taken inside the lock, for two requests that arrive together."""
    from drollery import restore
    backup = make_backup(tmp_path, monkeypatch)
    with fresh(tmp_path, monkeypatch):
        create_user("someone", PASSWORD)
        with pytest.raises(restore.RestoreError, match="already has an account"):
            restore.restore(io.BytesIO(backup))
        with db.tx() as con:
            assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


# ------------------------------------------------- the same on the command line

def run_cli(*args):
    from drollery.__main__ import main
    return main(list(args))


def test_the_command_restores_into_a_fresh_data_folder(tmp_path, monkeypatch, capsys):
    backup = make_backup(tmp_path, monkeypatch)
    (tmp_path / "x.tgz").write_bytes(backup)
    _boot(tmp_path / "target", monkeypatch)                                       # an empty volume: not even a database yet
    assert run_cli("restore", str(tmp_path / "x.tgz")) == 0
    out = capsys.readouterr().out
    assert "Restored: 2 items, 1 people, 1 accounts." in out and "sign in with an account from the backup" in out
    assert accounts.user_count() == 1 and (tmp_path / "target" / "media").is_dir()
    from drollery.main import app
    with TestClient(app, follow_redirects=True) as c:                              # and the app starts on it
        assert "Picture 0" in c.post("/login", data={"username": "admin", "password": PASSWORD}).text
        assert c.get("/media/1").status_code == 200


def test_check_says_what_is_in_the_file_and_changes_nothing(tmp_path, monkeypatch, capsys):
    full = make_backup(tmp_path, monkeypatch)
    meta = make_backup(tmp_path / "meta", monkeypatch, kind="metadata")
    (tmp_path / "full.tgz").write_bytes(full)
    (tmp_path / "meta.tgz").write_bytes(meta)
    _boot(tmp_path / "target", monkeypatch)
    assert run_cli("restore", "--check", str(tmp_path / "full.tgz")) == 0
    assert "fine and can be restored: 2 items, 1 people, 1 accounts." in capsys.readouterr().out
    assert run_cli("restore", "--check", str(tmp_path / "meta.tgz")) == 0
    assert "2 items have no file" in capsys.readouterr().out                       # a metadata-only file says so
    assert not (tmp_path / "target" / "drollery.db").exists() and not list((tmp_path / "target").glob(".restore-*"))
    db.init()
    create_user("someone", PASSWORD)                                              # a library in use can check a file too
    assert run_cli("restore", "--check", str(tmp_path / "full.tgz")) == 0
    capsys.readouterr()
    assert accounts.user_count() == 1 and not (tmp_path / "target" / "media" / "00").exists()


def test_the_command_refuses_a_library_in_use_a_missing_file_and_a_bad_file(tmp_path, monkeypatch, capsys):
    backup = make_backup(tmp_path, monkeypatch)
    (tmp_path / "x.tgz").write_bytes(backup)
    (tmp_path / "bad.tgz").write_bytes(b"not an archive")
    _boot(tmp_path / "target", monkeypatch)
    assert run_cli("restore", str(tmp_path / "nothing.tgz")) == 1 and "There is no file" in capsys.readouterr().out
    assert run_cli("restore", str(tmp_path / "bad.tgz")) == 1 and "not a Drollery backup" in capsys.readouterr().out
    assert accounts.user_count() == 0
    db.init()
    create_user("someone", PASSWORD)
    assert run_cli("restore", str(tmp_path / "x.tgz")) == 1 and "already has an account" in capsys.readouterr().out
    with db.tx() as con:
        assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
