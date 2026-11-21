import re

import pytest

from drollery import db
from test_album import make_mp3
from test_app import png


@pytest.fixture()
def sound_id(client, tmp_path):
    p = make_mp3(tmp_path / "airhorn.mp3", "Air horn", 1)
    return client.post("/api/v1/items", files={"file": ("airhorn.mp3", p.read_bytes(), "audio/mpeg")}).json()["id"]


def tile_of(html: str, item_id: int) -> str:
    return re.search(r'<div class="tile sound"[^>]*>(?:(?!<div class="tile).)*?/items/%d(?:\?[^"]*)?".*?</a>\s*</div>' % item_id, html, re.S).group(0)


def test_a_sound_card_has_a_play_button_that_plays_in_place(client, sound_id):
    tile = tile_of(client.get("/").text, sound_id)
    assert f'class="sound-play" data-src="/media/{sound_id}"' in tile and 'aria-pressed="false"' in tile and "Play: " in tile
    assert f'<a class="cap" href="/items/{sound_id}' in tile                                   # the title still opens the item
    assert "<img" not in tile                                                                  # no picture, so the button is the card
    assert "/static/soundboard.js" in client.get("/").text


def test_a_sound_with_a_picture_keeps_it_and_gets_a_small_overlay_button(client, sound_id):
    with db.tx() as c:                                                   # e.g. a picture that came with the file
        c.execute("UPDATE items SET has_thumb=1 WHERE id=?", (sound_id,))
    tile = tile_of(client.get("/").text, sound_id)
    assert "<img" in tile and 'class="sound-play over"' in tile


def test_other_kinds_keep_their_plain_cards(client, sound_id):
    client.post("/api/v1/items", files={"file": ("pic.png", png(40), "image/png")})
    html = client.get("/").text
    assert html.count('class="sound-play') == 1 and html.count('class="tile"') == 1
    assert 'class="tile sound"' in html


def test_the_sound_file_behind_the_button_plays_for_a_logged_in_user(client, sound_id):
    r = client.get(f"/media/{sound_id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/")


def test_a_persons_page_can_play_their_sounds_too(client, sound_id):
    client.post("/people", data={"name": "Honker", "item": sound_id})
    with db.tx() as c:
        pid = c.execute("SELECT id FROM people").fetchone()["id"]
    page = client.get(f"/people/{pid}").text
    assert 'class="sound-play"' in page and "/static/soundboard.js" in page


def test_the_play_and_pause_icons_never_show_together():
    css = open("src/drollery/static/style.css").read()
    general = css.index(".sound-play .sp-play, .sound-play .sp-pause { display: grid")
    hide = css.index(".sound-play .sp-pause, .sound-play.playing .sp-play { display: none; }")
    show = css.index(".sound-play.playing .sp-pause { display: grid; }")
    assert general < hide < show                      # a later rule must not undo the hiding


def test_every_sound_card_has_its_own_colour_that_stays_the_same(client, tmp_path):
    ids = []
    for n in range(5):
        p = make_mp3(tmp_path / f"s{n}.mp3", f"Sound {n}", n + 1)
        ids.append(client.post("/api/v1/items", files={"file": (f"s{n}.mp3", p.read_bytes(), "audio/mpeg")}).json()["id"])
    html = client.get("/").text
    hues = [int(re.search(r'<div class="tile sound" style="--h: (\d+)"', tile_of(html, i)).group(1)) for i in ids]
    assert len(set(hues)) == 5 and all(0 <= h <= 360 for h in hues)
    gaps = sorted(abs(a - b) for a in hues for b in hues if a < b)
    assert gaps[0] >= 20                                                   # neighbours do not look alike
    again = [int(re.search(r'--h: (\d+)', tile_of(client.get("/").text, i)).group(1)) for i in ids]
    assert again == hues                                                   # a sound keeps its colour from visit to visit


def test_the_colour_animates_while_playing_unless_motion_is_reduced():
    css = open("src/drollery/static/style.css").read()
    assert ".sound-play.playing { animation: sp-colors" in css and "@keyframes sp-colors" in css
    assert ".sound-play.playing { animation: none; }" in css
