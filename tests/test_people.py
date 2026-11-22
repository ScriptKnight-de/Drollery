from datetime import date

import pytest

from drollery import db, people
from test_album import album_id, mp3s, upload  # noqa: F401  (mp3s is a fixture)
from test_app import png
from test_card import two_color_png


@pytest.fixture()
def item_id(client):
    return client.post("/api/v1/items", files={"file": ("pic.png", png(40), "image/png")}).json()["id"]


def born(years: int) -> str:
    """A birthday that makes someone exactly `years` old today, whatever today is."""
    t = date.today()
    return date(t.year - years, t.month, 1).isoformat()


def make(client, name="Ada Lovelace", **extra):
    data = {"name": name, "birthday": born(36), "gender": "female", "link": "https://social.example/ada", **extra}
    return client.post("/people", data=data, follow_redirects=False)


def pid_of(name):
    with db.tx() as c:
        return c.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()["id"]


# ------------------------------------------------------------- creating

def test_a_person_is_created_with_all_details_and_a_picture(client):
    r = client.post("/people", data={"name": "  Ada   Lovelace ", "birthday": born(36), "gender": "female", "link": "https://social.example/ada"},
                    files={"picture": ("face.png", two_color_png(120, 60), "image/png")})
    assert r.status_code == 200 and "Ada Lovelace added" in r.text
    pid = pid_of("Ada Lovelace")
    with db.tx() as c:
        p = people.get(c, pid)
    assert (p["birthday"], p["age"], p["gender"], p["link"], p["has_picture"]) == (born(36), 36, "female", "https://social.example/ada", 1)
    pic = client.get(f"/people/{pid}/picture")
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/jpeg" and pic.content[:2] == b"\xff\xd8"
    page = client.get(f"/people/{pid}").text
    assert "Ada Lovelace" in page and born(36) in page and "<dt>Age</dt><dd>36</dd>" in page and "Female" in page and 'href="https://social.example/ada"' in page


def test_only_a_name_is_required(client):
    r = client.post("/people", data={"name": "Just A Name"})
    assert r.status_code == 200
    with db.tx() as c:
        p = people.get(c, pid_of("Just A Name"))
    assert p["birthday"] == "" and p["age"] is None and p["gender"] == "" and p["link"] == "" and p["has_picture"] == 0


@pytest.mark.parametrize("data,message", [
    ({"name": "  "}, "Give the person a name"),
    ({"name": "X", "birthday": "not a date"}, "real date"),
    ({"name": "X", "birthday": "2023-02-30"}, "real date"),
    ({"name": "X", "birthday": "2999-01-01"}, "real date"),
    ({"name": "X", "birthday": "1700-01-01"}, "real date"),
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
        client.post("/people", data={"name": n, "birthday": born(30) if n == "Zed" else "", "gender": "male" if n == "Zed" else ""})
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
    client.post(f"/people/{pid}", data={"name": "Ada King", "birthday": born(36), "gender": "female", "link": ""})
    assert found("lovelace") == [] and found("king") == [item_id]
    client.post(f"/items/{item_id}/people/{pid}/remove")
    assert found("king") == []


def test_editing_a_person_keeps_or_replaces_the_picture(client):
    client.post("/people", data={"name": "Ada"}, files={"picture": ("a.png", two_color_png(), "image/png")})
    pid = pid_of("Ada")
    client.post(f"/people/{pid}", data={"name": "Ada", "birthday": born(40)})
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


def test_people_live_in_the_settings_not_in_the_header(client):
    header = client.get("/").text.split("</header>")[0]
    assert 'href="/people"' not in header
    page = client.get("/people").text
    assert 'class="tabs"' in page and 'href="/people" class="on"' in page and "New person" in page


def test_the_age_is_worked_out_from_the_birthday():
    d = date(2025, 6, 15)
    assert people.age_of("2000-06-15", d) == 25 and people.age_of("2000-06-16", d) == 24 and people.age_of("2000-06-14", d) == 25
    assert people.age_of("2024-02-29", date(2025, 2, 28)) == 0 and people.age_of("2024-02-29", date(2025, 3, 1)) == 1
    assert people.age_of("", d) is None and people.age_of("garbage", d) is None


def test_the_date_field_is_offered_instead_of_an_age(client):
    form = client.get("/people/new").text
    assert 'type="date" name="birthday"' in form and 'name="age"' not in form


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


def test_the_people_field_sits_in_the_tile_with_title_and_tags_but_in_its_own_form(client, item_id, mp3s):
    upload(client, [mp3s["one"]], title="Frog Opera")
    for i in (item_id, album_id(client)):
        page = client.get(f"/items/{i}").text
        tile = page.split('id="edit-tile"')[1].split("</section>")[0] if False else page.split('id="edit-tile"')[1]
        before_tags = tile.split('id="tag-fld"')[0]
        assert "person-add" in before_tags and 'name="title"' in before_tags and 'id="tags-in"' in tile
        assert page.count('class="person-add"') == 1 and page.count('id="people"') == 1
        assert page.index('id="people"') > page.index('id="edit-tile"')           # no longer up under the title
        assert 'form="edit-form"' in tile and 'id="edit-form"' in page


def test_the_people_field_has_no_add_button_enter_does_it(client, item_id):
    form = client.get(f"/items/{item_id}").text.split('class="person-add"')[1].split("</form>")[0]
    assert 'type="submit"' not in form and "person-new" in form


def transparent_png(w=40, h=40) -> bytes:
    import struct
    import zlib
    row = b"\x00" + b"\x00\x00\x00\x00" * w                        # fully transparent (and black underneath)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b""))


def mean_rgb(jpeg: bytes) -> tuple[int, int, int]:
    import subprocess
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], input=jpeg, capture_output=True).stdout
    return out[0], out[1], out[2]


def test_a_transparent_picture_is_put_on_white_not_black(client):
    client.post("/people", data={"name": "Ghosty"}, files={"picture": ("clear.png", transparent_png(), "image/png")})
    pid = pid_of("Ghosty")
    r, g, b = mean_rgb(client.get(f"/people/{pid}/picture").content)
    assert min(r, g, b) > 240
    client.post(f"/people/{pid}", data={"name": "Ghosty"}, files={"picture": ("clear2.png", transparent_png(60, 20), "image/png")})
    assert min(mean_rgb(client.get(f"/people/{pid}/picture").content)) > 240


def test_an_opaque_picture_keeps_its_colours(client):
    client.post("/people", data={"name": "Solid"}, files={"picture": ("halves.png", two_color_png(120, 60), "image/png")})
    r, g, b = mean_rgb(client.get(f"/people/{pid_of('Solid')}/picture").content)
    assert r > 90 and b > 90 and g < 60                                 # red and blue halves, not washed out to white


def test_save_and_delete_sit_in_one_row_and_delete_still_asks(client):
    make(client)
    page = client.get(f"/people/{pid_of('Ada Lovelace')}").text
    row = page.split('class="actions"')[1].split("</div>")[0]
    assert "Save person" in row and "Delete person" in row and 'form="delete-person"' in row and 'class="btn small' not in row
    assert "data-confirm=" in page.split('id="delete-person"')[1].split(">")[0]
