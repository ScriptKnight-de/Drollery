import asyncio
import json
import re

import pytest

from drollery.upload_redirect import UploadRedirects


async def call(app, headers=None, path="/x"):
    """Run an ASGI app once and return (status, headers, body)."""
    scope = {"type": "http", "method": "POST", "path": path, "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()]}
    out = {"status": None, "headers": [], "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        if m["type"] == "http.response.start":
            out["status"], out["headers"] = m["status"], m["headers"]
        elif m["type"] == "http.response.body":
            out["body"] += m.get("body", b"")

    await app(scope, receive, send)
    return out["status"], dict((k.decode(), v.decode()) for k, v in out["headers"] if k != b"set-cookie"), [v for k, v in out["headers"] if k == b"set-cookie"], out["body"]


def redirecting(status=303):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": [(b"location", b"/items/5"), (b"set-cookie", b"flash=hello; Path=/")]})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    return app


def test_a_redirect_becomes_a_json_note_with_the_same_cookies_when_asked():
    status, headers, cookies, body = asyncio.run(call(UploadRedirects(redirecting()), {"x-drollery-upload": "1"}))
    assert status == 200 and headers["content-type"] == "application/json" and json.loads(body) == {"redirect": "/items/5"}
    assert cookies == [b"flash=hello; Path=/"] and headers["content-length"] == str(len(body))
    assert headers["cache-control"] == "no-store"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_kind_of_redirect_is_covered(status):
    assert asyncio.run(call(UploadRedirects(redirecting(status)), {"x-drollery-upload": "1"}))[0] == 200


def test_without_the_header_a_redirect_is_left_alone():
    status, headers, cookies, body = asyncio.run(call(UploadRedirects(redirecting())))
    assert status == 303 and headers["location"] == "/items/5" and cookies == [b"flash=hello; Path=/"] and body == b""


def test_answers_that_are_not_redirects_pass_through_even_with_the_header():
    async def page(scope, receive, send):
        await send({"type": "http.response.start", "status": 422, "headers": [(b"content-type", b"text/html")]})
        await send({"type": "http.response.body", "body": b"<p>fix it</p>", "more_body": True})
        await send({"type": "http.response.body", "body": b"!", "more_body": False})
    status, headers, cookies, body = asyncio.run(call(UploadRedirects(page), {"x-drollery-upload": "1"}))
    assert status == 422 and body == b"<p>fix it</p>!" and headers["content-type"] == "text/html"


def test_a_real_upload_with_the_header_answers_with_the_target_and_keeps_the_message(client, tmp_path):
    from test_card import red_then_blue_video
    clip = red_then_blue_video(tmp_path / "f.mp4")
    r = client.post("/movies", files={"file": ("f.mp4", clip, "video/mp4")}, data={"title": "Big One"}, headers={"X-Drollery-Upload": "1"}, follow_redirects=False)
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    target = r.json()["redirect"]
    from drollery.web import FLASH
    assert re.fullmatch(r"/items/\d+", target) and FLASH in "".join(r.headers.get_list("set-cookie"))
    assert "Movie added" in client.get(target).text                       # the message is still waiting on the next page


def test_the_picture_and_album_forms_report_their_errors_as_a_page(client):
    r = client.post("/movies", data={"title": "x"}, headers={"X-Drollery-Upload": "1"}, follow_redirects=False)
    assert r.status_code == 422 and "Choose a video file" in r.text            # a page the script can show again


def test_the_big_upload_forms_use_the_progress_bar(client):
    for url, form_marker in (("/movies/new", 'action="/movies"'), ("/albums/new", 'action="/albums"')):
        page = client.get(url).text
        tag = re.search(r"<form[^>]*%s[^>]*>" % re.escape(form_marker), page).group(0)
        assert "data-upload" in tag, url
        assert 'id="upload-text"' in page and "/static/upload.js" in page and '"uploading": "Uploading"' in page
    home = client.get("/").text                                                      # the library sends through the unified zone, which uses the same engine
    assert 'id="uz-form"' in home and "/static/uploader.js" in home and 'id="upload-text"' in home and "/static/upload.js" in home


def test_the_script_and_styles_are_served(client):
    js = client.get("/static/upload.js").text
    assert "xhr.upload.onprogress" in js and "X-Drollery-Upload" in js and "beforeunload" in js
    css = client.get("/static/style.css").text
    assert ".upload-panel" in css and ".up-fill" in css
