"""What a browser extension needs from the API: tags and people to pick from, people on an item, and a link that arrives with its title, tags and people."""
import json

from drollery import db, pipeline, people
from test_app import png


def add(client, n=1, tags=()):
    i = client.post("/api/v1/items", files={"file": (f"p{n}.png", png(n), "image/png")}).json()["id"]
    if tags:
        client.patch(f"/api/v1/items/{i}", json={"tags": list(tags)})
    return i


def person(client, name, **kw):
    client.post("/people", data={"name": name, **kw})
    with db.tx() as c:
        return c.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()["id"]


def test_the_tags_endpoint_offers_the_most_used_and_filters_while_typing(client):
    add(client, 1, ["cats", "sofa"]); add(client, 2, ["cats"]); add(client, 3, ["catalog"])
    top = client.get("/api/v1/tags").json()
    assert top[0] == {"tag": "cats", "n": 2} and {t["tag"] for t in top} == {"cats", "sofa", "catalog"}
    assert [t["tag"] for t in client.get("/api/v1/tags", params={"q": "cat"}).json()][:2] == ["cats", "catalog"]
    assert client.get("/api/v1/tags", params={"q": "zzz"}).json() == []
    assert len(client.get("/api/v1/tags", params={"limit": 1}).json()) == 1
    assert len(client.get("/api/v1/tags", params={"limit": 9999}).json()) <= 50


def test_the_people_endpoint_lists_and_searches(client):
    a, b = person(client, "Ann Example", first_name="Anna", surname="Smith"), person(client, "Bob Example")
    i = add(client); client.patch(f"/api/v1/items/{i}", json={"people": [b]})
    rows = client.get("/api/v1/people").json()
    assert [p["id"] for p in rows] == [b, a]                                       # the one on most items first
    assert set(rows[0]) == {"id", "name", "first_name", "surname", "picture_url"} and rows[0]["picture_url"] is None
    assert [p["id"] for p in client.get("/api/v1/people", params={"q": "smith"}).json()] == [a]
    assert client.get("/api/v1/people", params={"q": "nobody"}).json() == []


def test_the_endpoints_work_with_an_api_key_and_not_without(client):
    import re
    from fastapi.testclient import TestClient
    from drollery.main import app
    token = re.search(r'id="new-key">(drl_[\w-]+)<', client.post("/settings/keys", data={"name": "Browser clipper", "kind": "browser"}).text).group(1)
    with TestClient(app, follow_redirects=False) as bare:                          # no session cookie
        for path in ("/api/v1/tags", "/api/v1/people"):
            assert bare.get(path).status_code == 401 and bare.get(path, headers={"Authorization": "Bearer drl_nope"}).status_code == 401
            assert bare.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_patch_sets_exactly_these_people_and_ignores_unknown_ids(client):
    a, b = person(client, "Ann Example"), person(client, "Bob Example")
    i = add(client)
    client.patch(f"/api/v1/items/{i}", json={"people": [a, b, 9999, "x", True]})
    with db.tx() as c:
        assert sorted(p["id"] for p in people.of_item(c, i)) == [a, b]
    client.patch(f"/api/v1/items/{i}", json={"people": [b]})
    with db.tx() as c:
        assert [p["id"] for p in people.of_item(c, i)] == [b]
    client.patch(f"/api/v1/items/{i}", json={"title": "x"})                       # not mentioning people leaves them alone
    with db.tx() as c:
        assert [p["id"] for p in people.of_item(c, i)] == [b]
    client.patch(f"/api/v1/items/{i}", json={"people": []})
    with db.tx() as c:
        assert people.of_item(c, i) == []


def fetch(monkeypatch, tmp_path, payload):
    def direct(url, td):
        f = td / "pic.png"; f.write_bytes(png(7)); return [f]
    monkeypatch.setattr(pipeline, "_direct_download", direct)
    monkeypatch.setattr(pipeline.netguard, "check_url", lambda url: None)
    pipeline.job_fetch({"id": 1, "type": "fetch", "item_id": None, "payload": json.dumps(payload), "attempts": 1})


def test_a_link_arrives_with_its_title_description_tags_and_people(client, monkeypatch, tmp_path):
    a = person(client, "Ann Example")
    r = client.post("/api/v1/ingest", json={"url": "https://example.org/pic.png", "title": " My clip ", "description": "From a page",
                                             "tags": ["Cats", "sofa", ""], "people": [a, 9999, "x"]})
    assert r.status_code == 202
    with db.tx() as c:
        payload = json.loads(c.execute("SELECT payload FROM jobs WHERE id=?", (r.json()["job_id"],)).fetchone()["payload"])
    assert payload["clip"] == {"title": "My clip", "description": "From a page", "tags": ["Cats", "sofa"], "people": [a, 9999]}
    fetch(monkeypatch, tmp_path, payload)
    with db.tx() as c:
        item = db.search(c, "")[0]
        assert item["title"] == "My clip" and item["description"] == "From a page"
        assert sorted(item["tags"]) == ["cats", "sofa"] and [p["id"] for p in people.of_item(c, item["id"])] == [a]       # the unknown id is skipped


def test_a_link_without_extras_is_as_before(client):
    r = client.post("/api/v1/ingest", json={"url": "https://example.org/pic.png"})
    with db.tx() as c:
        assert json.loads(c.execute("SELECT payload FROM jobs WHERE id=?", (r.json()["job_id"],)).fetchone()["payload"]) == {"url": "https://example.org/pic.png"}


def test_an_item_that_was_already_there_keeps_its_title_and_gains_the_tags(client, monkeypatch, tmp_path):
    i = client.post("/api/v1/items", files={"file": ("pic.png", png(7), "image/png")}).json()["id"]
    client.patch(f"/api/v1/items/{i}", json={"title": "Mine", "description": "keep", "tags": ["old"]})
    fetch(monkeypatch, tmp_path, {"url": "https://example.org/pic.png", "clip": {"title": "Other", "description": "other", "tags": ["new"]}})
    with db.tx() as c:
        item = db.get_item(c, i) if hasattr(db, "get_item") else dict(c.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone())
        tags = sorted(r["tag"] for r in c.execute("SELECT tag FROM tags WHERE item_id=? AND source='user'", (i,)))
    assert item["title"] == "Mine" and item["description"] == "keep" and tags == ["new", "old"]
