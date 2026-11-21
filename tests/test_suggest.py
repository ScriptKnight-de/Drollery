import pytest

from drollery import db
from test_app import png


def item(client, color, tags=(), title=""):
    r = client.post("/api/v1/items", files={"file": (f"{title or color}.png", png(color), "image/png")}).json()["id"]
    if tags:
        client.patch(f"/api/v1/items/{r}", json={"tags": list(tags)})
    return r


def ask(client, q):
    return client.get("/suggest", params={"q": q}).json()


@pytest.fixture()
def library(client):
    a = item(client, 10, ["funny-cat", "cat", "catalog"])
    b = item(client, 20, ["cat", "dog"])
    c = item(client, 30, ["concatenate"])
    with db.tx() as cx:
        db.set_ai_tags(cx, c, ["scary-cat"])
    client.post("/people", data={"name": "Catherine Howard", "birthday": "1990-05-01", "gender": "female"})
    client.post("/people", data={"name": "Bob Cates"})
    client.post("/people", data={"name": "Zed"})
    return a, b, c


def test_typing_suggests_tags_and_people(client, library):
    d = ask(client, "cat")
    names = [t["tag"] for t in d["tags"]]
    assert set(names) == {"cat", "catalog", "funny-cat", "concatenate", "scary-cat"} and len(names) == 5
    assert names[0] == "cat"                                              # starts with what was typed, and carried by the most items
    assert next(t for t in d["tags"] if t["tag"] == "cat")["n"] == 2
    assert [p["name"] for p in d["people"]] == ["Catherine Howard", "Bob Cates"]


def test_both_kinds_of_tags_are_offered_and_counted_once_per_item(client, library):
    assert "scary-cat" in [t["tag"] for t in ask(client, "scary")["tags"]]           # an AI tag
    with db.tx() as c:
        db.set_ai_tags(c, library[0], ["cat"])                                        # the user's own tag wins, so one row
    assert next(t for t in ask(client, "cat")["tags"] if t["tag"] == "cat")["n"] == 2


def test_the_hash_sign_spaces_and_capitals_are_forgiven(client, library):
    assert [t["tag"] for t in ask(client, "#FUNNY cat")["tags"]] == ["funny-cat"]


def test_people_carry_a_note_and_nothing_matches_nothing(client, library):
    cath = ask(client, "cath")["people"][0]
    assert cath["note"].endswith("Female") and cath["id"] > 0
    assert ask(client, "") == {"tags": [], "people": []} and ask(client, "qqqq") == {"tags": [], "people": []}


def test_the_lists_are_short_and_wildcards_are_plain_characters(client):
    for n in range(8):
        item(client, n + 1, [f"tag{n}"])
    assert len(ask(client, "tag")["tags"]) == 5
    assert ask(client, "%")["tags"] == [] and ask(client, "_")["tags"] == []


def test_the_suggestions_need_a_login(client):
    from fastapi.testclient import TestClient
    from drollery.main import app
    r = TestClient(app, follow_redirects=False).get("/suggest?q=a")
    assert r.status_code in (303, 307) and r.headers["location"] == "/login"


def test_the_library_can_be_filtered_by_a_person(client, library):
    a, b, c = library
    with db.tx() as cx:
        pid = cx.execute("SELECT id FROM people WHERE name='Catherine Howard'").fetchone()["id"]
    client.post(f"/items/{a}/people", data={"person_id": pid})
    page = client.get("/", params={"person": pid}).text
    assert f'href="/items/{a}"' in page and f'href="/items/{b}"' not in page and f'href="/items/{c}"' not in page
    assert 'class="pill"' in page and "Catherine Howard" in page and 'name="person" value="%d"' % pid in page
    assert f'href="/items/{b}"' in client.get("/", params={"person": 99999}).text           # an unknown person is not a filter
    both = client.get("/", params={"person": pid, "tag": "cat"}).text                       # filters combine
    assert f'href="/items/{a}"' in both and f'href="/items/{b}"' not in both


def test_the_search_bar_is_wired_for_suggestions(client):
    page = client.get("/").text
    assert 'data-suggest="/suggest"' in page and "/static/searchsuggest.js" in page and 'role="combobox"' in page


@pytest.mark.parametrize("value", ["", " ", "abc", "-3", "0", "1.5"])
def test_an_empty_or_odd_person_value_is_just_no_filter(client, library, value):
    # the search form always sends person=; an empty value must not break the page or the live search
    for headers in ({}, {"HX-Request": "true"}):
        r = client.get("/", params={"q": "", "kind": "", "tag": "", "src": "", "person": value}, headers=headers)
        assert r.status_code == 200 and f'href="/items/{library[0]}"' in r.text and f'href="/items/{library[1]}"' in r.text


def test_the_links_that_clear_a_filter_never_carry_a_broken_value(client, library):
    page = client.get("/", params={"tag": "cat"}).text
    assert "&person=" in page                                              # they do carry the (empty) value ...
    assert client.get("/?q=&kind=&person=").status_code == 200              # ... and that works
