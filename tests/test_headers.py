"""The security headers every answer carries, and the rule that makes the content policy hold: no inline script without this request's nonce."""
import re

import pytest

from drollery.web import security_headers
from test_app import png

PAGES = ["/", "/login", "/people", "/settings/tags", "/settings/backup", "/settings/ai", "/settings/keys", "/settings/security", "/jobs", "/albums/new", "/people/new"]


def policy(r) -> dict[str, str]:
    return {p.split(" ", 1)[0]: p.split(" ", 1)[1] if " " in p else "" for p in r.headers["content-security-policy"].split("; ")}


def test_every_answer_carries_the_headers(client, anon):
    for r in (client.get("/"), anon.get("/login"), anon.get("/static/style.css"), client.get("/nope")):
        h = r.headers
        assert h["x-frame-options"] == "SAMEORIGIN" and h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "same-origin" and "camera=()" in h["permissions-policy"] and h["cross-origin-opener-policy"] == "same-origin"
        assert "content-security-policy" in h


def test_the_policy_allows_nothing_from_outside(client):
    p = policy(client.get("/"))
    assert p["default-src"] == "'self'" and p["object-src"] == "'none'" and p["base-uri"] == "'self'" and p["form-action"] == "'self'"
    assert p["frame-ancestors"] == "'self'"                                        # the popups frame this site's own pages
    assert re.fullmatch(r"'self' 'nonce-[\w-]{16,}'", p["script-src"])             # no 'unsafe-inline', no 'unsafe-eval' for scripts
    assert "unsafe-eval" not in client.get("/").headers["content-security-policy"]
    assert all("http:" not in v and "https:" not in v and "*" not in v for v in p.values())


def test_the_nonce_is_new_for_every_request_and_the_page_uses_it(client):
    a, b = client.get("/"), client.get("/")
    na, nb = re.search(r"'nonce-([\w-]+)'", a.headers["content-security-policy"]).group(1), re.search(r"'nonce-([\w-]+)'", b.headers["content-security-policy"]).group(1)
    assert na != nb
    assert f'nonce="{na}"' in a.text and f'nonce="{nb}"' not in a.text


@pytest.mark.parametrize("url", PAGES)
def test_no_page_has_an_inline_script_without_the_nonce_or_an_inline_handler(client, url):
    for name in ("Ann Example", "Bob Example"):
        client.post("/people", data={"name": name})
    r = client.get(url)
    assert r.status_code == 200, url
    nonce = re.search(r"'nonce-([\w-]+)'", r.headers["content-security-policy"]).group(1)
    for tag in re.findall(r"<script\b[^>]*>", r.text):
        if "src=" in tag or 'type="application/json"' in tag:
            continue
        assert f'nonce="{nonce}"' in tag, (url, tag)
    assert not re.search(r"\son(?:click|change|submit|input|load|error|focus|blur|keydown|keyup|mouseover)\s*=", r.text, re.I), url
    assert "javascript:" not in r.text.lower(), url


def test_a_sorting_field_sends_its_form_without_an_inline_handler(client):
    for name in ("Ann Example", "Bob Example"):                                    # the people toolbar shows from two people on
        client.post("/people", data={"name": name})
    for url in ("/people", "/settings/tags"):
        page = client.get(url).text
        assert "data-autosubmit" in page and "onchange" not in page
    assert 'closest("[data-autosubmit]")' in client.get("/").text


def test_the_headers_are_the_same_function_for_every_route():
    h = security_headers("abc")
    assert "'nonce-abc'" in h["Content-Security-Policy"] and set(h) >= {"X-Frame-Options", "Referrer-Policy", "Content-Security-Policy"}


def test_an_answer_that_sets_its_own_header_keeps_it(client):
    i = client.post("/api/v1/items", files={"file": ("a.png", png(1), "image/png")}).json()["id"]
    assert client.get(f"/thumb/{i}").headers["x-content-type-options"] == "nosniff"


def test_static_files_are_always_revalidated_so_an_update_never_leaves_an_old_stylesheet_behind(client, anon):
    for path in ("/static/style.css", "/static/style-pixel.css", "/static/bulk.js", "/static/favicon.svg"):
        r = anon.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers.get("etag"), path
        again = anon.get(path, headers={"if-none-match": r.headers["etag"]})
        assert again.status_code == 304                                       # asking again is cheap
    assert "no-cache" not in client.get("/").headers.get("cache-control", "")     # pages keep whatever they said before
