"""One action for several items at once: the selection on the library page."""
import re

import pytest

from conftest import pause_workers
from drollery import accounts, db
from test_app import png


def add(client, title, n, tags=()):
    i = client.post("/api/v1/items", files={"file": (f"f{n}.png", png(n), "image/png")}).json()["id"]
    client.patch(f"/api/v1/items/{i}", json={"title": title, "tags": list(tags)})
    return i


def bulk(client, ids, action, **extra):
    return client.post("/items/bulk", data={"ids": ",".join(str(i) for i in ids), "action": action, "next": "/?q=x", **extra}, follow_redirects=False)


def flash(r):
    from urllib.parse import unquote
    return unquote(r.cookies.get("drollery_flash", "") or r.headers.get("set-cookie", ""))


def tags(i):
    with db.tx() as c:
        return db.get_item(c, i)["tags"], db.get_item(c, i)["ai_tags"]


@pytest.fixture()
def three(client):
    return [add(client, f"item {n}", n, tags=["old"] if n == 1 else []) for n in (1, 2, 3)]


def test_tags_are_added_to_all_selected_items_and_only_yours_change(client, three):
    a, b, c_ = three
    with db.tx() as c:
        db.set_ai_tags(c, a, ["robotic"])
    r = bulk(client, [a, b], "tag_add", tags="#Funny new, funny")
    assert r.status_code == 303 and r.headers["location"] == "/?q=x" and "Tags added to 2 items" in flash(r)
    assert tags(a) == (["funny", "new", "old"], ["robotic"])                         # the old tag stays, the AI's tags are not touched
    assert tags(b) == (["funny", "new"], []) and tags(c_) == ([], [])                 # not selected: nothing
    assert client.get("/", params={"tag": "funny"}).text.count('class="tile"') == 2    # and the search index follows


def test_tags_are_removed_and_items_without_them_are_not_counted(client, three):
    a, b, c_ = three
    r = bulk(client, [a, b, c_], "tag_remove", tags="old nothing")
    assert "Tags removed from 1 item" in flash(r) and tags(a) == ([], [])


def test_a_person_is_added_and_removed_for_all_selected_items(client, three):
    a, b, c_ = three
    client.post("/people", data={"name": "Pixel Pete", "first_name": "Max"})
    with db.tx() as c:
        pid = c.execute("SELECT id FROM people").fetchone()["id"]
    client.post(f"/items/{a}/people", data={"person_id": pid})                        # already there on one of them
    r = bulk(client, [a, b, c_], "person_add", person_id=str(pid))
    assert "Pixel Pete added to 2 items" in flash(r)                                  # the one that had her is not counted again
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM item_people WHERE person_id=?", (pid,)).fetchone()[0] == 3
    r = bulk(client, [a, b], "person_remove", person_id=str(pid))
    assert "Pixel Pete removed from 2 items" in flash(r)
    with db.tx() as c:
        assert [x["item_id"] for x in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (pid,))] == [c_]
    assert "Choose a person" in flash(bulk(client, [a], "person_add", person_id=""))
    assert "Choose a person" in flash(bulk(client, [a], "person_add", person_id="9999"))


def test_ai_is_queued_for_the_selected_items_that_are_not_busy(client, three, monkeypatch):
    from test_accounts import MODEL
    pause_workers(monkeypatch)
    a, b, c_ = three
    client.post("/settings/ai/models", data={**MODEL, "name": "llm", "model": "chat-1"})
    mid = str(next(m["id"] for m in accounts.list_models() if m["name"] == "llm"))
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": mid})
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
    r = bulk(client, [a, b], "ai")
    assert "Queued AI processing for 2 items" in flash(r)
    with db.tx() as c:
        assert sorted(x["item_id"] for x in c.execute("SELECT item_id FROM jobs WHERE type='describe'")) == [a, b]
    assert "Nothing to queue" in flash(bulk(client, [a, b], "ai"))                    # they are waiting already: no duplicates
    assert "Queued AI processing for 1 item" in flash(bulk(client, [a, c_], "ai", step="describe"))


def test_selected_items_are_deleted_with_their_files(client, three):
    a, b, c_ = three
    from drollery import pipeline
    with db.tx() as c:
        files = [pipeline.media_path(db.get_item(c, i)) for i in (a, b)]
    assert all(f.exists() for f in files)
    r = bulk(client, [a, b], "delete")
    assert "Deleted 2 items" in flash(r)
    with db.tx() as c:
        assert [r_["id"] for r_ in c.execute("SELECT id FROM items")] == [c_]
    assert not any(f.exists() for f in files)
    assert client.get(f"/items/{a}").status_code == 404


def test_unknown_ids_are_skipped_and_said_so(client, three):
    a, b, c_ = three
    r = bulk(client, [a, 9998, 9999, a], "tag_add", tags="x")                         # a twice, two that do not exist
    assert "Tags added to 1 item" in flash(r) and "2 items were not found" in flash(r)
    assert tags(a)[0] == ["old", "x"]


def test_bad_requests_change_nothing(client, three):
    a, b, c_ = three
    assert "Select some items" in flash(bulk(client, [], "delete")) and "Select some items" in flash(bulk(client, [a], "explode"))
    assert "Type at least one tag" in flash(bulk(client, [a], "tag_add", tags="  "))
    too_many = bulk(client, range(1, 502), "delete")
    assert "too many at once: 500" in flash(too_many)
    r = client.post("/items/bulk", data={"ids": "abc, ,-3,0", "action": "delete", "next": "/"}, follow_redirects=False)
    assert "Select some items" in flash(r)                                            # nothing usable in the list
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3


def test_the_redirect_stays_on_this_site(client, three):
    for evil in ("https://evil.example/", "//evil.example/", "\\\\evil.example"):
        r = client.post("/items/bulk", data={"ids": str(three[0]), "action": "tag_add", "tags": "x", "next": evil}, follow_redirects=False)
        assert r.headers["location"] == "/"


def test_only_a_signed_in_person_may_use_it(client, three):
    from test_share import anon_client
    other = anon_client()
    r = other.post("/items/bulk", data={"ids": str(three[0]), "action": "delete"}, follow_redirects=False)
    assert r.status_code in (303, 401) and "/login" in r.headers.get("location", "/login")
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3


def test_the_page_has_what_the_selection_needs(client, three):
    page = client.get("/").text
    assert page.count('data-id="') >= 3 and 'id="select-toggle"' in page and 'id="bulkbar"' in page and "/static/bulk.js" in page
    assert 'name="person_id"' in page and 'data-bulk="delete"' in page and "{n}" in page.split('id="bulkbar"')[1][:600]
    only_tiles = client.get("/", headers={"hx-request": "true"}).text
    assert 'data-id="' in only_tiles and 'id="bulkbar"' not in only_tiles            # more tiles carry the ids, the bar is not repeated
    from pathlib import Path
    grid = (Path(__file__).resolve().parents[1] / "src" / "drollery" / "templates" / "grid.html").read_text()
    assert re.search(r'<div class="tile sound" data-id="\{\{ it.id \}\}"', grid) and grid.count('class="pick"') == 2         # sound cards can be chosen too


def _person(client, name):
    client.post("/people", data={"name": name})
    with db.tx() as c:
        return c.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()["id"]


def test_several_people_are_added_and_removed_at_once(client, three):
    a, b, c_ = three
    ann, bob = _person(client, "Ann Archer"), _person(client, "Bob Baker")
    client.post(f"/items/{a}/people", data={"person_id": ann})                          # one of them is already on one item
    r = bulk(client, [a, b], "person_add", person_id=f"{ann},{bob}")
    assert "Ann Archer, Bob Baker added to 2 items" in flash(r)                         # both names, and the item that gained only Bob still counts
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM item_people").fetchone()[0] == 4
    r = bulk(client, [a, b, c_], "person_add", person_id=f"{ann},{bob}")
    assert "added to 1 item" in flash(r)                                                # only the third item had nothing yet
    r = bulk(client, [a, b], "person_remove", person_id=f"{bob}, {ann}")
    assert "Bob Baker, Ann Archer removed from 2 items" in flash(r)
    with db.tx() as c:
        assert [(x["item_id"], x["person_id"]) for x in c.execute("SELECT * FROM item_people ORDER BY person_id")] == [(c_, ann), (c_, bob)]


def test_unknown_and_repeated_person_ids_are_ignored(client, three):
    a, b, c_ = three
    ann = _person(client, "Ann Archer")
    r = bulk(client, [a], "person_add", person_id=f"{ann},{ann},9999,abc,-3")
    assert "Ann Archer added to 1 item" in flash(r)
    assert "Choose a person" in flash(bulk(client, [a], "person_add", person_id="9999,abc"))


def test_the_selection_bar_has_chip_fields_and_a_people_search(client, three):
    html = client.get("/").text
    assert 'id="bulk-tag-fld"' in html and 'id="bulk-tags-in"' in html and 'name="tags"' in html
    assert 'id="bulk-person-fld"' in html and 'data-lookup="/people/search"' in html and 'id="bulk-person-in"' in html and 'role="combobox"' in html
    assert '<select name="person_id"' not in html                                        # no list of every person any more
    assert html.index("/static/tagfield.js") < html.index("/static/bulk.js")             # the chip maker is there before the bar uses it
    js = client.get("/static/bulk.js").text
    assert "makeTagField(" in js and "wrap.dataset.lookup" in js and "tagchip" in js
    assert "function makeTagField" in client.get("/static/tagfield.js").text


def test_the_page_does_not_list_every_person_in_the_selection_bar(client, three):
    _person(client, "Zed Zimmer")
    assert "Zed Zimmer" not in client.get("/").text
