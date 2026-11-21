import re

import pytest

from drollery import db, people
from test_album import album_id, mp3s, upload  # noqa: F401  (mp3s is a fixture)
from test_app import png
from test_card import two_color_png


@pytest.fixture()
def item_id(client):
    return client.post("/api/v1/items", files={"file": ("pic.png", png(40), "image/png")}).json()["id"]


def make(client, name="Ada Lovelace", **extra):
    data = {"name": name, "age": "36", "gender": "female", "link": "https://social.example/ada", **extra}
    return client.post("/people", data=data, follow_redirects=False)


def pid_of(name):
    with db.tx() as c:
        return c.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()["id"]


# ------------------------------------------------------------- creating

def test_a_person_is_created_with_all_details_and_a_picture(client):
    r = client.post("/people", data={"name": "  Ada   Lovelace ", "age": "36", "gender": "female", "link": "https://social.example/ada"},
                    files={"picture": ("face.png", two_color_png(120, 60), "image/png")})
    assert r.status_code == 200 and "Ada Lovelace added" in r.text
    pid = pid_of("Ada Lovelace")
    with db.tx() as c:
        p = people.get(c, pid)
    assert (p["age"], p["gender"], p["link"], p["has_picture"]) == (36, "female", "https://social.example/ada", 1)
    pic = client.get(f"/people/{pid}/picture")
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/jpeg" and pic.content[:2] == b"\xff\xd8"
    page = client.get(f"/people/{pid}").text
    assert "Ada Lovelace" in page and "36" in page and "Female" in page and 'href="https://social.example/ada"' in page


def test_only_a_name_is_required(client):
    r = client.post("/people", data={"name": "Just A Name"})
    assert r.status_code == 200
    with db.tx() as c:
        p = people.get(c, pid_of("Just A Name"))
    assert p["age"] is None and p["gender"] == "" and p["link"] == "" and p["has_picture"] == 0


@pytest.mark.parametrize("data,message", [
    ({"name": "  "}, "Give the person a name"),
    ({"name": "X", "age": "abc"}, "whole number"),
    ({"name": "X", "age": "131"}, "whole number"),
    ({"name": "X", "age": "-1"}, "whole number"),
    ({"name": "X", "link": "javascript:alert(1)"}, "must start with http"),
    ({"name": "X", "link": "ftp://example.org"}, "must start with http"),
])
def test_bad_details_are_refused_and_nothing_is_stored(client, data, message):
    r = client.post("/people", data=data)
    assert r.status_code == 422 and message in r.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0


def test_a_file_that_is_not_a_picture_leaves_no_half_made_person(client):
    for name, blob in (("notes.txt", b"hello"), ("fake.png", b"not really a png")):
        r = client.post("/people", data={"name": "Ghost"}, files={"picture": (name, blob, "image/png")})
        assert r.status_code == 422 and "not a picture" in r.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0


def test_names_are_shown_escaped(client):
    client.post("/people", data={"name": "<script>alert(1)</script>"})
    pid = pid_of("<script>alert(1)</script>")
    for url in ("/people", f"/people/{pid}"):
        assert "<script>alert(1)</script>" not in client.get(url).text


# ------------------------------------------------------- the popup flow

def test_the_popup_creates_and_links_in_one_step_and_then_tells_the_page(client, item_id):
    assert 'data-popup="Add a new person"' in client.get(f"/items/{item_id}").text
    form = client.get(f"/people/new?item={item_id}&name=Grace", headers={"Sec-Fetch-Dest": "iframe"}).text
    assert '<body class="embed">' in form and 'value="Grace"' in form and f'name="item" value="{item_id}"' in form
    r = client.post("/people", data={"name": "Grace Hopper", "item": item_id}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/items/{item_id}"
    framed = client.get(f"/items/{item_id}", headers={"Sec-Fetch-Dest": "iframe"}).text
    assert "drollery-done" in framed                                      # the popup closes and the page behind reloads
    assert "Grace Hopper" in client.get(f"/items/{item_id}").text


def test_creating_for_a_missing_item_is_a_404(client):
    assert client.post("/people", data={"name": "X", "item": 999}).status_code == 404


# ---------------------------------------------------- lookup and linking

def test_search_matches_anywhere_in_the_name_and_starts_first(client):
    for n in ("Ada Lovelace", "Lovely Rita", "Mike Love", "50% Off", "Zed"):
        client.post("/people", data={"name": n, "age": "30" if n == "Zed" else "", "gender": "male" if n == "Zed" else ""})
    names = lambda q: [p["name"] for p in client.get("/people/search", params={"q": q}).json()]
    assert names("love") == ["Lovely Rita", "Ada Lovelace", "Mike Love"]
    assert names("LOVE")[0] == "Lovely Rita" and names("") == [] and names("nobody") == []
    assert names("%") == ["50% Off"] and names("_") == []                 # wildcards are plain characters
    zed = client.get("/people/search", params={"q": "zed"}).json()[0]
    assert zed["note"] == "30 · Male"


def test_an_existing_person_is_added_by_id_or_by_exact_name(client, item_id):
    make(client)
    pid = pid_of("Ada Lovelace")
    r = client.post(f"/items/{item_id}/people", data={"person_id": pid})
    assert "Ada Lovelace added" in r.text and f'href="/people/{pid}"' in r.text
    again = client.post(f"/items/{item_id}/people", data={"name": "ada lovelace"})
    assert "already there" in again.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM item_people").fetchone()[0] == 1


def test_unknown_or_ambiguous_names_are_explained(client, item_id):
    assert "Type a name" in client.post(f"/items/{item_id}/people", data={"name": " "}).text
    assert "Nobody is called" in client.post(f"/items/{item_id}/people", data={"name": "Nobody"}).text
    make(client, "Sam Same"), make(client, "Sam Same")
    assert "Several people are called" in client.post(f"/items/{item_id}/people", data={"name": "Sam Same"}).text
    assert "no longer exists" in client.post(f"/items/{item_id}/people", data={"person_id": 999}).text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM item_people").fetchone()[0] == 0


def test_a_person_can_be_removed_from_an_item_and_stays_in_the_store(client, item_id):
    make(client)
    pid = pid_of("Ada Lovelace")
    client.post(f"/items/{item_id}/people", data={"person_id": pid})
    r = client.post(f"/items/{item_id}/people/{pid}/remove")
    assert "removed from this item" in r.text
    with db.tx() as c:
        assert people.get(c, pid) is not None and c.execute("SELECT COUNT(*) FROM item_people").fetchone()[0] == 0


def test_one_person_can_be_on_many_items(client, item_id):
    other = client.post("/api/v1/items", files={"file": ("pic2.png", png(90), "image/png")}).json()["id"]
    make(client)
    pid = pid_of("Ada Lovelace")
    for i in (item_id, other):
        client.post(f"/items/{i}/people", data={"person_id": pid})
    page = client.get(f"/people/{pid}").text
    assert f'href="/items/{item_id}"' in page and f'href="/items/{other}"' in page
    assert "Items: 2" in client.get("/people").text


# ------------------------------------------------------ pages and search

def test_people_show_on_item_and_album_pages(client, item_id, mp3s):
    upload(client, [mp3s["one"]], title="Frog Opera")
    mp3_album = album_id(client)
    make(client)
    pid = pid_of("Ada Lovelace")
    for i in (item_id, mp3_album):
        assert "Creators and people involved" in client.get(f"/items/{i}").text
        client.post(f"/items/{i}/people", data={"person_id": pid})
        page = client.get(f"/items/{i}").text
        assert f'href="/people/{pid}"' in page and 'class="person-add"' in page and "/static/people.js" in page


def test_items_are_found_by_the_names_of_their_people_and_follow_renames(client, item_id):
    make(client)
    pid = pid_of("Ada Lovelace")
    client.post(f"/items/{item_id}/people", data={"person_id": pid})
    found = lambda q: [i["id"] for i in client.get("/api/v1/items", params={"q": q}).json()["items"]]
    assert found("lovelace") == [item_id]
    client.post(f"/people/{pid}", data={"name": "Ada King", "age": "36", "gender": "female", "link": ""})
    assert found("lovelace") == [] and found("king") == [item_id]
    client.post(f"/items/{item_id}/people/{pid}/remove")
    assert found("king") == []


def test_editing_a_person_keeps_or_replaces_the_picture(client):
    client.post("/people", data={"name": "Ada"}, files={"picture": ("a.png", two_color_png(), "image/png")})
    pid = pid_of("Ada")
    client.post(f"/people/{pid}", data={"name": "Ada", "age": "40"})
    with db.tx() as c:
        p = people.get(c, pid)
    assert p["age"] == 40 and p["has_picture"] == 1                       # untouched when no new file is sent
    r = client.post(f"/people/{pid}", data={"name": "Ada", "remove_picture": "1"})
    with db.tx() as c:
        assert people.get(c, pid)["has_picture"] == 0 and people.get(c, pid)["age"] is None
    assert client.get(f"/people/{pid}/picture").status_code == 404 and not people.picture_path(pid).exists()
    assert "Person saved" in r.text
    assert "not a picture" in client.post(f"/people/{pid}", data={"name": "Ada"}, files={"picture": ("x.txt", b"hi", "text/plain")}).text


def test_deleting_a_person_keeps_the_items_and_deleting_an_item_keeps_the_person(client, item_id):
    make(client)
    pid = pid_of("Ada Lovelace")
    client.post(f"/items/{item_id}/people", data={"person_id": pid})
    client.post(f"/people/{pid}/delete")
    with db.tx() as c:
        assert people.get(c, pid) is None and db.get_item(c, item_id) is not None
        assert c.execute("SELECT COUNT(*) FROM item_people").fetchone()[0] == 0
    make(client, "Linus")
    pid = pid_of("Linus")
    client.post(f"/items/{item_id}/people", data={"person_id": pid})
    client.post(f"/items/{item_id}/delete")
    with db.tx() as c:
        assert people.get(c, pid) is not None and c.execute("SELECT COUNT(*) FROM item_people").fetchone()[0] == 0


def test_deleting_asks_in_the_app(client):
    make(client)
    page = client.get(f"/people/{pid_of('Ada Lovelace')}").text
    assert "data-confirm=" in page.split("/delete")[1].split(">")[0] and "onsubmit" not in page


def test_the_header_links_to_the_people_list(client):
    assert 'href="/people"' in client.get("/").text


def test_people_need_a_login(client):
    from fastapi.testclient import TestClient
    from drollery.main import app
    make(client)
    v = TestClient(app, follow_redirects=False)
    for method, url in (("get", "/people"), ("get", "/people/new"), ("get", "/people/search?q=a"), ("get", "/people/1"),
                        ("post", "/people"), ("post", "/people/1"), ("post", "/people/1/delete"), ("post", "/items/1/people"), ("post", "/items/1/people/1/remove")):
        r = getattr(v, method)(url)
        assert r.status_code in (303, 307) and r.headers["location"] == "/login", (method, url, r.status_code)
    assert v.get("/people/1/picture").status_code == 401                 # files: key or session
