"""The working signal of the lookups: what is marked so that the page shows a spinner while the server waits for another site."""
import re

import pytest

from drollery import db, metadata
from test_album import album_id, mp3s, upload  # noqa: F401  (mp3s is a fixture)
from test_card import red_then_blue_video


@pytest.fixture()
def album(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"]], title="Frog Opera", artist="Kermit")
    return album_id(client)


@pytest.fixture()
def movie(client, tmp_path):
    clip = red_then_blue_video(tmp_path / "f.mp4")
    client.post("/movies", files={"file": ("f.mp4", clip, "video/mp4")}, data={"title": "Mine"})
    with db.tx() as c:
        return c.execute("SELECT id FROM items WHERE kind='movie'").fetchone()["id"]


def tag(html: str, needle: str) -> str:
    return re.search(r"<(?:form|a)[^>]*%s[^>]*>" % re.escape(needle), html).group(0)


def test_every_page_carries_the_busy_script_and_its_texts(client):
    page = client.get("/").text
    assert "/static/busy.js" in page and 'id="busy-text"' in page
    for key in ('"hint": "This can take a few seconds"', '"slow": "Still working. The service is slow right now"', '"sec": "{n} s"'):
        assert key in page


def test_the_album_lookup_steps_are_marked(client, album):
    search = client.get(f"/albums/{album}/lookup").text
    assert 'data-busy="Searching MusicBrainz…"' in tag(search, f'action="/albums/{album}/lookup"')
    bar = client.get(f"/items/{album}").text.split('class="toolbar"')[1].split("</div>")[0]
    link = tag(bar, "/lookup?run=1")
    assert 'data-popup="Look up details online"' in link and 'data-busy="Searching MusicBrainz…"' in link         # the popup shows it while it opens


def test_the_album_review_and_pick_steps_are_marked(client, album, monkeypatch):
    from test_lookup import REL, Fake
    f = Fake()
    monkeypatch.setattr(metadata, "_send", f)
    monkeypatch.setattr(metadata, "_sleep", lambda s: None)
    metadata._cache.clear()
    results = client.get(f"/albums/{album}/lookup", params={"run": 1}).text
    assert 'data-busy="Loading the release details…"' in tag(results, "lookup-pick")
    review = client.get(f"/albums/{album}/lookup/{REL}").text
    assert 'data-busy="Applying the changes…"' in tag(review, f'action="/albums/{album}/lookup/{REL}"')
    assert 'data-busy="Searching MusicBrainz…"' in tag(review, 'class="back"')


def test_the_movie_lookup_steps_are_marked(client, movie, monkeypatch):
    from test_movie import TT, Fake
    monkeypatch.setattr(metadata, "_send", Fake())
    monkeypatch.setattr(metadata, "_sleep", lambda s: None)
    metadata._cache.clear()
    results = client.get(f"/movies/{movie}/lookup", params={"run": 1, "q": "The Invented Quest"}).text
    assert 'data-busy="Searching IMDb…"' in tag(results, f'action="/movies/{movie}/lookup"')
    assert 'data-busy="Loading the title details…"' in tag(results, "lookup-pick")
    review = client.get(f"/movies/{movie}/lookup/{TT}").text
    assert 'data-busy="Applying the changes…"' in tag(review, f'action="/movies/{movie}/lookup/{TT}"')
    bar = client.get(f"/items/{movie}").text.split('class="toolbar"')[1].split("</div>")[0]
    assert 'data-busy="Searching IMDb…"' in tag(bar, "/lookup?run=1")


def test_the_popup_has_a_loading_text_and_the_scripts_wire_it_up(client, album):
    page = client.get(f"/items/{album}").text
    assert 'id="popup-dialog"' in page and 'data-loading="Loading…"' in page
    popup = client.get("/static/popup.js").text
    assert "drolleryBusy.show(link.dataset.busy" in popup and 'frame.addEventListener("load"' in popup
    busy = client.get("/static/busy.js").text
    assert "a[data-busy]" in busy and "[data-popup]" not in busy.replace('hasAttribute("data-popup")', "")         # popup links are left to popup.js
    assert "pageshow" in busy and "setInterval" in busy
    css = client.get("/static/style.css").text
    assert ".busy-spin" in css and "@keyframes busy-turn" in css and "prefers-reduced-motion" in css


def test_the_upload_bar_says_it_is_opening_the_next_page(client):
    page = client.get("/movies/new").text
    assert '"opening": "Done. Opening the next page\\u2026"' in page and "text.opening" in client.get("/static/upload.js").text
