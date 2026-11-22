"""'Check the latest backup': an automatic backup is unpacked into a scratch folder and checked like a restore, and the library is not touched."""
import io
import tarfile
from urllib.parse import unquote

from drollery import autobackup, db
from drollery.config import get_settings
from test_app import png


def flash(r):
    return unquote(r.cookies.get("drollery_flash", "") or r.headers.get("set-cookie", ""))


def check(client, name=None):
    return client.post(f"/settings/backup/auto/{name}/check" if name else "/settings/backup/auto/check", follow_redirects=False)


def item(client, n=1):
    return client.post("/api/v1/items", files={"file": (f"p{n}.png", png(n), "image/png")}).json()["id"]


def test_without_a_backup_the_page_has_no_button_and_the_route_says_so(client):
    assert "Check the latest backup" not in client.get("/settings/backup").text
    r = check(client)
    assert r.status_code == 303 and "There is no automatic backup to check yet" in flash(r) and "error" in flash(r)


def test_the_newest_backup_is_checked_and_the_library_stays_as_it_is(client):
    item(client, 1); item(client, 2)
    client.post("/people", data={"name": "Ann Example"})
    autobackup.run("metadata")
    page = client.get("/settings/backup").text
    assert "Check the latest backup" in page and 'action="/settings/backup/auto/check"' in page
    before = sorted(p.name for p in get_settings().data_dir.iterdir())
    r = check(client)
    assert "This backup is fine and can be restored. Items: 2, people: 1, accounts: 1" in flash(r) and "error" not in flash(r).split("|")[0]
    assert sorted(p.name for p in get_settings().data_dir.iterdir()) == before                 # no scratch folder is left behind
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


def test_the_latest_means_the_newest_one(client):
    item(client, 1)
    autobackup.run("metadata")
    import time; time.sleep(1.1)
    item(client, 2)
    autobackup.run("metadata")
    assert "Items: 2," in flash(check(client))
    oldest = autobackup.listing()[-1]["name"]
    assert "Items: 1," in flash(check(client, oldest))                                           # and a single one can be picked


def test_a_damaged_backup_is_reported_and_not_called_fine(client):
    item(client)
    name = autobackup.run("metadata")
    path = autobackup.path_of(name)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])                                                    # cut in half
    r = check(client)
    f = flash(r)
    assert "fine" not in f and ("cannot be restored" in f or "could not be read" in f) and f.startswith("error|")
    assert sorted(p.name for p in get_settings().data_dir.iterdir() if p.name.startswith(".restore")) == []


def test_a_file_that_is_not_a_backup_is_reported(client):
    autobackup.run("metadata")
    name = autobackup.listing()[0]["name"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("notes.txt"); info.size = 3; t.addfile(info, io.BytesIO(b"hey"))
    autobackup.path_of(name).write_bytes(buf.getvalue())
    f = flash(check(client))
    assert "cannot be restored" in f and "fine" not in f


def test_an_unknown_or_foreign_name_is_refused(client):
    for bad in ("nope.tgz", "..%2F..%2Fetc%2Fpasswd", "drollery-auto-20200101-000000-full.tgz"):
        r = check(client, bad)
        assert r.status_code in (303, 404) and "is fine" not in flash(r)


def test_a_full_backup_with_missing_files_is_called_out(client):
    item(client)
    name = autobackup.run("full")
    assert "fine" in flash(check(client, name))
    # a metadata-only file renamed as a full one: the items are there, the files are not
    meta = autobackup.run("metadata")
    p = autobackup.path_of(meta)
    fake = p.with_name(p.name.replace("-metadata", "-full").replace(p.name[14:29], "20990101-000000"))
    p.rename(fake)
    f = flash(check(client, fake.name))
    assert "1 item has no file in it" in f and f.startswith("error|")


def test_only_a_signed_in_person_can_check(client, anon):
    autobackup.run("metadata")
    r = anon.post("/settings/backup/auto/check", follow_redirects=False)
    assert r.status_code in (303, 401, 403) and "is fine" not in flash(r)
