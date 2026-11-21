import re
import time

from drollery import accounts, db, shares
from test_app import png


def make_item(client, n=1, name=None):
    return client.post("/api/v1/items", files={"file": (name or f"funny{n}.png", png(150 + n), "image/png")}).json()["id"]


def anon_client():
    from fastapi.testclient import TestClient
    from drollery.main import app
    return TestClient(app, follow_redirects=False)


def link_token(client, item_id, **form):
    data = {"preset": "never", "label": "", "next": f"/items/{item_id}", **form}
    r = client.post(f"/items/{item_id}/shares", data=data)
    assert r.status_code == 200
    return re.search(r"/s/([A-Za-z0-9_-]{20,})", client.get(f"/items/{item_id}").text).group(1)


# -------------------------------------------------------------- creating

def test_permanent_and_temporary_links(client):
    i = make_item(client)
    client.post(f"/items/{i}/shares", data={"preset": "never", "label": "forever", "next": f"/items/{i}"})
    client.post(f"/items/{i}/shares", data={"preset": "1h", "label": "short", "next": f"/items/{i}"})
    client.post(f"/items/{i}/shares", data={"preset": "custom", "amount": "3", "unit": "days", "next": f"/items/{i}"})
    rows = {s["label"] or "custom": s for s in shares.for_item(i)}
    assert rows["forever"]["expires_at"] is None and rows["forever"]["state"]["kind"] == "permanent"
    assert abs(rows["short"]["expires_at"] - (time.time() + 3600)) < 5
    assert abs(rows["custom"]["expires_at"] - (time.time() + 3 * 86400)) < 5
    html = client.get(f"/items/{i}").text
    assert "Permanent" in html and "Expires in 59 minutes" in html or "Expires in 1 hour" in html
    assert "Expires in 2 days" in html or "Expires in 3 days" in html
    assert rows["forever"]["token"] not in rows["short"]["token"] and len(rows["forever"]["token"]) >= 30


def test_invalid_expiry_is_rejected(client):
    i = make_item(client)
    for bad in ({"preset": "custom", "amount": "0", "unit": "hours"}, {"preset": "custom", "amount": "99999", "unit": "days"},
                {"preset": "custom", "amount": "5", "unit": "weeks"}, {"preset": "forever-and-ever"}):
        r = client.post(f"/items/{i}/shares", data={**bad, "next": f"/items/{i}"})
        assert "drollery.png" not in r.text and shares.for_item(i) == [], bad


def test_next_cannot_redirect_off_site(client):
    i = make_item(client)
    r = client.post(f"/items/{i}/shares", data={"preset": "never", "next": "https://evil.example/x"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/items/{i}")
    r = client.post(f"/items/{i}/shares", data={"preset": "never", "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/items/{i}")


# ----------------------------------------------------------- public access

def test_a_link_works_without_logging_in(client):
    i = make_item(client, name="Wise Owl.png")
    client.patch(f"/api/v1/items/{i}", json={"title": "Wise owl", "description": "An owl", "tags": ["secret-private-tag"]})
    tok = link_token(client, i)
    visitor = anon_client()
    assert visitor.get(f"/items/{i}").headers["location"] == "/login"                    # the library itself stays private
    page = visitor.get(f"/s/{tok}")
    assert page.status_code == 200 and "Wise owl" in page.text and "An owl" in page.text
    assert "secret-private-tag" not in page.text and "Settings" not in page.text         # no tags, no navigation
    assert 'property="og:title" content="Wise owl"' in page.text and "og:image" in page.text
    raw = visitor.get(f"/s/{tok}/raw/wise-owl.png")
    assert raw.status_code == 200 and raw.headers["content-type"] == "image/png" and raw.content[:4] == b"\x89PNG"
    assert visitor.get(f"/s/{tok}/thumb").headers["content-type"] == "image/jpeg"
    assert visitor.get(f"/media/{i}").status_code == 401 and visitor.get(f"/api/v1/items/{i}").status_code == 401


def test_only_the_shared_item_is_reachable(client):
    a, b = make_item(client, 1), make_item(client, 2)
    tok = link_token(client, a)
    visitor = anon_client()
    assert visitor.get(f"/s/{tok}").status_code == 200
    assert visitor.get(f"/media/{b}").status_code == 401
    assert visitor.get(f"/s/{tok}x").status_code == 404                                  # tokens can't be guessed by tweaking
    assert visitor.get("/s/not-a-real-token-at-all-123").status_code == 404


def test_public_responses_are_private_and_sandboxed(client):
    i = make_item(client)
    tok = link_token(client, i)
    visitor = anon_client()
    for url in (f"/s/{tok}", f"/s/{tok}/raw/x.png", f"/s/{tok}/thumb"):
        h = visitor.get(url).headers
        assert "noindex" in h["x-robots-tag"] and h["referrer-policy"] == "no-referrer" and h["x-content-type-options"] == "nosniff", url
    h = visitor.get(f"/s/{tok}/raw/x.png").headers
    assert "sandbox" in h["content-security-policy"] and "default-src 'none'" in h["content-security-policy"]
    assert visitor.get(f"/s/{tok}").headers["cache-control"] == "no-store"
    own = client.get(f"/media/{i}")
    assert "sandbox" in own.headers["content-security-policy"]                           # the owner's own media route is sandboxed too


def test_range_requests_and_download_disposition(client):
    i = make_item(client, name="clip.png")
    tok = link_token(client, i)
    v = anon_client()
    part = v.get(f"/s/{tok}/raw/clip.png", headers={"range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10
    assert "inline" in v.get(f"/s/{tok}/raw/clip.png").headers["content-disposition"]
    dl = v.get(f"/s/{tok}/raw/clip.png?download=1").headers["content-disposition"]
    assert "attachment" in dl and "clip.png" in dl
    assert v.head(f"/s/{tok}").status_code == 200                                        # link-preview bots often use HEAD


# ------------------------------------------------------------- expiry etc.

def test_expired_links_stop_working(client):
    i = make_item(client)
    tok = link_token(client, i, preset="1h")
    v = anon_client()
    assert v.get(f"/s/{tok}").status_code == 200
    with db.tx() as c:
        c.execute("UPDATE shares SET expires_at=?", (time.time() - 5,))
    page = v.get(f"/s/{tok}")
    assert page.status_code == 410 and "expired" in page.text
    assert v.get(f"/s/{tok}/raw/x.png").status_code == 410 and v.get(f"/s/{tok}/thumb").status_code == 410
    assert "Expired" in client.get(f"/items/{i}").text


def test_revoking_kills_the_link_immediately_and_keeps_others(client):
    i = make_item(client)
    t1, t2 = link_token(client, i), None
    client.post(f"/items/{i}/shares", data={"preset": "never", "label": "second", "next": f"/items/{i}"})
    t2 = next(s["token"] for s in shares.for_item(i) if s["label"] == "second")
    first = next(s for s in shares.for_item(i) if s["token"] == t1)
    v = anon_client()
    client.post(f"/shares/{first['id']}/revoke", data={"next": f"/items/{i}"})
    page = v.get(f"/s/{t1}")
    assert page.status_code == 410 and "revoked" in page.text and v.get(f"/s/{t1}/raw/x.png").status_code == 410
    assert v.get(f"/s/{t2}").status_code == 200


def test_views_are_counted_for_page_opens_and_direct_hits_not_the_pages_own_image(client):
    i = make_item(client)
    tok = link_token(client, i)
    v = anon_client()
    v.get(f"/s/{tok}")
    v.get(f"/s/{tok}/raw/x.png", headers={"referer": f"http://testserver/s/{tok}"})      # the page loading its own <img>
    assert shares.for_item(i)[0]["views"] == 1
    v.get(f"/s/{tok}/raw/x.png")                                                          # a chat app fetching the file directly
    v.get(f"/s/{tok}/raw/x.png", headers={"range": "bytes=100-"})                         # a later chunk of the same download
    assert shares.for_item(i)[0]["views"] == 2


def test_deleting_the_item_removes_its_links(client):
    i = make_item(client)
    tok = link_token(client, i)
    client.post(f"/items/{i}/delete")
    assert anon_client().get(f"/s/{tok}").status_code == 404
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 0


def test_guessing_tokens_is_throttled(client):
    v = anon_client()
    for _ in range(60):
        assert v.get("/s/aaaaaaaaaaaaaaaaaaaaaaaaaaaa").status_code == 404
    assert v.get("/s/aaaaaaaaaaaaaaaaaaaaaaaaaaaa").status_code == 429
    shares.share_throttle.reset()


# --------------------------------------------------------------- settings

def test_settings_overview_public_url_and_cleanup(client):
    a, b = make_item(client, 1), make_item(client, 2)
    link_token(client, a)
    client.post(f"/items/{b}/shares", data={"preset": "1h", "label": "old", "next": f"/items/{b}"})
    with db.tx() as c:
        c.execute("UPDATE shares SET expires_at=? WHERE label='old'", (time.time() - 5,))
    page = client.get("/settings/shares").text
    assert "Permanent" in page and "Expired" in page and "funny1" in page and "funny2" in page

    bad = client.post("/settings/shares/public-url", data={"public_url": "javascript:alert(1)"})
    assert "Enter an address like" in bad.text and accounts.get_setting("public_url") is None
    ok = client.post("/settings/shares/public-url", data={"public_url": "https://memes.example.org/"})
    assert "Public address saved" in ok.text and accounts.get_setting("public_url") == "https://memes.example.org"
    assert "https://memes.example.org/s/" in client.get(f"/items/{a}").text                # links now use it
    assert "Removed 1 expired or revoked link" in client.post("/settings/shares/purge").text


# -------------------------------------------------------------------- API

def test_api_create_list_and_delete_with_an_api_key(client):
    i = make_item(client)
    key = re.search(r'id="new-key">(drl_[\w-]+)<', client.post("/settings/keys", data={"name": "phone", "kind": "app"}).text).group(1)
    auth = {"Authorization": f"Bearer {key}"}
    app = anon_client()
    r = app.post(f"/api/v1/items/{i}/shares", headers=auth, json={"expires_in": 3600, "label": "from phone"})
    assert r.status_code == 201
    body = r.json()
    assert body["permanent"] is False and body["status"] == "active" and body["label"] == "from phone"
    assert body["url"].startswith("http://testserver/s/") and body["file_url"].endswith(".png")
    forever = app.post(f"/api/v1/items/{i}/shares", headers=auth, json={"expires_in": None}).json()
    assert forever["permanent"] is True and forever["expires_at"] is None
    assert app.post(f"/api/v1/items/{i}/shares", headers=auth, json={"expires_in": 5}).status_code == 422
    assert app.post(f"/api/v1/items/{i}/shares", headers=auth, json={"expires_in": "soon"}).status_code == 422
    assert len(app.get(f"/api/v1/items/{i}/shares", headers=auth).json()["shares"]) == 2
    assert app.get(body["url"].replace("http://testserver", "")).status_code == 200      # and the link itself opens
    assert app.delete(f"/api/v1/shares/{body['id']}", headers=auth).status_code == 204
    assert app.get(body["url"].replace("http://testserver", "")).status_code == 404
    assert app.post(f"/api/v1/items/{i}/shares", json={"expires_in": None}).status_code == 401   # no key, no sharing
    assert app.post("/api/v1/items/9999/shares", headers=auth, json={}).status_code == 404


def test_sharing_requires_login_in_the_web_ui(client):
    i = make_item(client)
    v = anon_client()
    assert v.post(f"/items/{i}/shares", data={"preset": "never"}).headers["location"] == "/login"
    assert v.post("/shares/1/revoke").headers["location"] == "/login"
    assert v.get("/settings/shares").headers["location"] == "/login"


# ---------------------------------------------------------------- hardening

def test_svg_uploads_are_refused(client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = client.post("/api/v1/items", files={"file": ("evil.svg", svg, "image/svg+xml")})
    assert r.status_code == 415
