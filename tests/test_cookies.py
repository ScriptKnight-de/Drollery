"""Cookies for downloads: pasted as a cookies.txt, kept write-only, handed to yt-dlp, gallery-dl and direct downloads."""
import json

import httpx
import pytest

from drollery import cookies, netguard, pipeline
from test_app import png

SAMPLE = "\n".join([
    "# Netscape HTTP Cookie File",
    ".example.com\tTRUE\t/\tTRUE\t2000000000\tsession\tabc123",
    "#HttpOnly_.video.example\tTRUE\t/\tFALSE\t0\tsid\tsecret-sid",
    "# a comment", "", "not a cookie line",
    "other.example\tFALSE\t/\tFALSE\t2000000000\tflag\t1",
])


def test_parse_keeps_valid_lines_and_the_httponly_ones():
    got = cookies.parse(SAMPLE)
    assert [(c.domain, c.name) for c in got] == [(".example.com", "session"), (".video.example", "sid"), ("other.example", "flag")]
    assert cookies.parse("a\tb\tc") == [] and cookies.parse("") == []
    spaced = cookies.parse(".example.com TRUE / FALSE 2000000000 token xyz")                   # pasted with spaces instead of tabs
    assert len(spaced) == 1 and spaced[0].value == "xyz"


def test_normalize_adds_the_header_yt_dlp_insists_on():
    text = cookies.normalize(".example.com\tTRUE\t/\tFALSE\t0\ta\tb\njunk")
    assert text.startswith("# Netscape HTTP Cookie File\n") and "junk" not in text


def test_the_settings_page_saves_lists_sites_and_never_shows_values(client):
    page = client.get("/settings/cookies")
    assert page.status_code == 200 and "No cookies yet" in page.text
    r = client.post("/settings/cookies", data={"text": SAMPLE})
    assert "3 cookies saved" in r.text
    page = client.get("/settings/cookies").text
    assert "example.com" in page and "video.example" in page
    assert "abc123" not in page and "secret-sid" not in page                                    # write-only
    assert "Cookies removed" in client.post("/settings/cookies", data={"remove": "1"}).text
    assert cookies.stored() == ""


def test_text_without_cookies_is_refused_and_keeps_what_was_there(client):
    client.post("/settings/cookies", data={"text": SAMPLE})
    r = client.post("/settings/cookies", data={"text": "hello world"})
    assert "No cookies found" in r.text and "example.com" in client.get("/settings/cookies").text


def test_a_copy_for_each_job_is_private(client, tmp_path):
    assert cookies.write_file(tmp_path) is None
    cookies.save(SAMPLE)
    path = cookies.write_file(tmp_path)
    assert path.read_text().startswith("# Netscape HTTP Cookie File") and oct(path.stat().st_mode & 0o777) == "0o600"


def test_the_downloaders_get_the_cookie_file_and_it_is_not_imported_as_a_download(client, monkeypatch):
    cookies.save(SAMPLE)
    monkeypatch.setattr(pipeline, "_direct_download", lambda url, td, referer="": [])
    monkeypatch.setattr(pipeline.netguard, "check_url", lambda url: None)
    monkeypatch.setattr(pipeline.netguard, "check_redirects", lambda url: None)
    seen = []

    def fake(cmd, timeout):
        seen.append(cmd)
        import subprocess
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: Sign in to confirm your age. Use --cookies")

    monkeypatch.setattr(pipeline, "_run_tool", fake)
    with pytest.raises(pipeline.FetchError) as e:
        pipeline.job_fetch({"id": 1, "type": "fetch", "item_id": None, "payload": json.dumps({"url": "https://video.example/watch"}), "attempts": 1})
    assert [c[0] for c in seen] == ["yt-dlp", "gallery-dl"]
    assert all("--cookies" in c for c in seen)
    assert str(e.value).startswith("nothing downloadable found (the saved cookies were not accepted")         # said first: the rest of the message is long


def test_without_cookies_the_error_points_to_the_setting(client, monkeypatch):
    monkeypatch.setattr(pipeline, "_direct_download", lambda url, td, referer="": [])
    monkeypatch.setattr(pipeline.netguard, "check_url", lambda url: None)
    monkeypatch.setattr(pipeline.netguard, "check_redirects", lambda url: None)
    import subprocess
    monkeypatch.setattr(pipeline, "_run_tool", lambda cmd, timeout: subprocess.CompletedProcess(cmd, 1, "", "ERROR: Sign in to confirm your age. Use --cookies"))
    with pytest.raises(pipeline.FetchError) as e:
        pipeline.job_fetch({"id": 1, "type": "fetch", "item_id": None, "payload": json.dumps({"url": "https://video.example/watch"}), "attempts": 1})
    assert str(e.value).startswith("nothing downloadable found (the site wants you signed in: add the cookies") and "Settings > Cookies" in str(e.value)


def test_a_direct_download_sends_cookies_only_to_their_site(client, monkeypatch, tmp_path):
    cookies.save(SAMPLE)
    monkeypatch.setattr(netguard, "_resolve", lambda host: ["93.184.216.34"])
    sent = {}

    def handler(request):
        sent[request.url.host] = request.headers.get("cookie", "")
        return httpx.Response(200, content=png(3), headers={"content-type": "image/png"})

    monkeypatch.setattr(netguard, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    pipeline._direct_download("https://cdn.example.com/a.png", tmp_path)
    pipeline._direct_download("https://elsewhere.example/b.png", tmp_path)
    assert "session=abc123" in sent["cdn.example.com"] and sent["elsewhere.example"] == ""
