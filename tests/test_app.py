import struct
import subprocess
import zlib

import pytest

from drollery import db, providers


def png(color: int = 0) -> bytes:
    """A valid 8x8 PNG; `color` makes files differ so SHA-256 dedupe doesn't merge them."""
    raw = b"".join(b"\x00" + bytes([color, 80, 160]) * 8 for _ in range(8))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def upload(client, name="distracted_boyfriend.png", data=None):
    return client.post("/api/v1/items", files={"file": (name, data or png(), "image/png")})


def test_fts_query_is_safe():
    assert db.fts_query('foo "bar" OR baz*') == '"foo"* "bar"* "OR"* "baz"*'
    assert db.fts_query("   ") == ""


def test_upload_search_edit_delete(client):
    r = upload(client)
    assert r.status_code == 201
    item_id = r.json()["id"]

    # duplicate content is not added twice
    again = upload(client, name="copy.png")
    assert again.status_code == 200 and again.json() == {"id": item_id, "created": False}

    # filename became the title and is searchable (prefix match)
    found = client.get("/api/v1/items", params={"q": "distrac"}).json()["items"]
    assert [i["id"] for i in found] == [item_id]
    assert found[0]["thumb_url"]
    assert client.get(f"/thumb/{item_id}").status_code == 200
    assert client.get(f"/media/{item_id}").headers["content-type"] == "image/png"

    # editing tags + description updates the search index
    client.patch(f"/api/v1/items/{item_id}", json={"title": "Wandering eye", "tags": ["Girlfriend", "#jealousy"],
                                                    "description": "man looks at another woman"})
    assert client.get("/api/v1/items", params={"q": "jealous"}).json()["items"][0]["id"] == item_id
    assert client.get("/api/v1/items", params={"q": "another woman"}).json()["items"][0]["id"] == item_id
    assert client.get("/api/v1/items", params={"tag": "girlfriend"}).json()["items"][0]["id"] == item_id
    assert client.get("/api/v1/items", params={"q": "wander"}).json()["items"][0]["id"] == item_id   # new title
    assert client.get("/api/v1/items", params={"q": "distrac"}).json()["items"][0]["id"] == item_id  # original filename stays searchable
    assert client.get("/api/v1/items", params={"q": "nomatchxyz"}).json()["items"] == []

    assert client.delete(f"/api/v1/items/{item_id}").status_code == 204
    assert client.get(f"/api/v1/items/{item_id}").status_code == 404
    assert client.get("/api/v1/items").json()["items"] == []


def test_rejects_unsupported_type(client):
    r = client.post("/api/v1/items", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_web_pages_render(client):
    item_id = upload(client).json()["id"]
    assert client.get("/").status_code == 200
    assert "distracted" in client.get("/", headers={"hx-request": "true"}).text
    assert client.get(f"/items/{item_id}").status_code == 200
    assert client.get("/jobs").status_code == 200


def test_friendly_404_for_browsers_json_for_api(client):
    page = client.get("/items/999", headers={"accept": "text/html"})
    assert page.status_code == 404 and "Nothing here" in page.text
    api = client.get("/api/v1/items/999", headers={"accept": "text/html"})
    assert api.status_code == 404 and api.json()["detail"] == "item not found"


def test_empty_state_has_a_doodle(client):
    html = client.get("/").text
    assert "treasury is empty" in html and "<svg" in html


def test_describe_job_with_mock_provider(tmp_path, monkeypatch):
    """Enable the describe provider against a fake OpenAI-compatible endpoint and run the worker job."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[describe]\ntype="openai"\nbase_url="http://llm.test/v1"\nmodel="tiny"\n')
    monkeypatch.setenv("DROLLERY_DATA", str(tmp_path))
    monkeypatch.delenv("DROLLERY_TOKEN", raising=False)
    from drollery import config, pipeline
    config.get_settings.cache_clear()

    calls = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": 'Sure!\n```json\n{"name":"Picard facepalm","description":"Captain Picard covers his face.","tags":["Star Trek","reaction"]}\n```'}}]}

    def fake_post(url, **kw):
        calls["url"], calls["json"] = url, kw["json"]
        return FakeResp()

    monkeypatch.setattr(providers.httpx, "post", fake_post)
    db.init()
    src = tmp_path / "incoming.png"
    src.write_bytes(png(7))
    item_id, created = pipeline.import_file(src, "incoming.png")
    assert created

    job = db.claim_job()
    assert job["type"] == "describe"
    pipeline.run_job(job)

    assert calls["url"] == "http://llm.test/v1/chat/completions"
    parts = calls["json"]["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    with db.tx() as c:
        item = db.get_item(c, item_id)
        hits = db.search(c, "picard")
    assert item["title"] == "Picard facepalm" and item["tags"] == ["reaction", "star-trek"]
    assert [h["id"] for h in hits] == [item_id]
    config.get_settings.cache_clear()


def test_user_title_is_not_overwritten_by_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("DROLLERY_DATA", str(tmp_path))
    (tmp_path / "config.toml").write_text('[describe]\ntype="openai"\nbase_url="http://x/v1"\nmodel="m"\n')
    from drollery import config, pipeline
    config.get_settings.cache_clear()
    monkeypatch.setattr(providers, "describe", lambda *a, **k: {"name": "ai name", "description": "d", "tags": []})
    db.init()
    src = tmp_path / "a.png"
    src.write_bytes(png(9))
    item_id, _ = pipeline.import_file(src, "a.png", title="My own title")
    pipeline.run_job(db.claim_job())
    with db.tx() as c:
        assert db.get_item(c, item_id)["title"] == "My own title"
    config.get_settings.cache_clear()


def test_failed_job_is_retried_then_marked_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("DROLLERY_DATA", str(tmp_path))
    (tmp_path / "config.toml").write_text('job_max_attempts=2\n[describe]\ntype="openai"\nbase_url="http://x/v1"\nmodel="m"\n')
    from drollery import config, pipeline
    config.get_settings.cache_clear()
    def boom(*a, **k): raise providers.ProviderError("server down")
    monkeypatch.setattr(providers, "describe", boom)
    db.init()
    src = tmp_path / "b.png"
    src.write_bytes(png(11))
    pipeline.import_file(src, "b.png")
    with db.tx() as c:
        c.execute("UPDATE jobs SET run_after=0")
    pipeline.run_job(db.claim_job())
    with db.tx() as c:
        j = c.execute("SELECT * FROM jobs").fetchone()
        assert j["status"] == "queued" and "server down" in j["error"]
        c.execute("UPDATE jobs SET run_after=0")
    pipeline.run_job(db.claim_job())
    with db.tx() as c:
        assert c.execute("SELECT status FROM jobs").fetchone()["status"] == "failed"
    config.get_settings.cache_clear()


def test_every_doodle_is_packaged_and_renders():
    """The Docker image installs the package, so subfolders must be listed in package-data."""
    import re
    import tomllib
    from pathlib import Path
    root = Path(__file__).parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert "templates/doodles/*" in data["tool"]["setuptools"]["package-data"]["drollery"]
    grid = (root / "src/drollery/templates/grid.html").read_text()
    names = re.search(r'\[("knight-snail".*?)\]\|random', grid).group(1)
    for name in re.findall(r'"([a-z-]+)"', names):
        assert (root / f"src/drollery/templates/doodles/{name}.svg").exists(), name


def test_every_static_asset_referenced_by_css_exists():
    """Backdrop tiles and the skyline mask are referenced by url(); a missing file would silently break the look."""
    import re
    from pathlib import Path
    static = Path(__file__).parent.parent / "src/drollery/static"
    css = (static / "style.css").read_text()
    urls = set(re.findall(r'url\("/static/([^"]+)"\)', css))
    assert {"stone-dark.svg", "stone-light.svg"} <= urls
    for name in urls:
        assert (static / name).exists(), name
