"""GIFs are told apart from other pictures: their own kind, their own filter, their own tile mark."""
import subprocess

import pytest

from drollery import db, media
from test_app import png


@pytest.fixture()
def gif_bytes(tmp_path):
    out = tmp_path / "loop.gif"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=5", str(out)], check=True)
    return out.read_bytes()


@pytest.fixture()
def library(client, gif_bytes):
    a = client.post("/api/v1/items", files={"file": ("photo.png", png(9), "image/png")}).json()["id"]
    g = client.post("/api/v1/items", files={"file": ("funny.gif", gif_bytes, "image/gif")}).json()["id"]
    return client, a, g


def test_a_gif_is_stored_as_its_own_kind(library):
    client, a, g = library
    with db.tx() as c:
        assert db.get_item(c, g)["kind"] == "gif" and db.get_item(c, g)["mime"] == "image/gif" and db.get_item(c, g)["has_thumb"] == 1
        assert db.get_item(c, a)["kind"] == "image"
    assert media.guess("x.gif") == ("gif", "image/gif") and media.guess("x.png")[0] == "image" and media.guess("x.webp")[0] == "image"
    assert media.guess("x.GIF")[0] == "gif"


def test_the_filter_has_a_gifs_button(library):
    client, a, g = library
    html = client.get("/").text
    assert "Images <i>1</i>" in html and "GIFs <i>1</i>" in html and "All <i>2</i>" in html
    assert html.index("Images <i>") < html.index("GIFs <i>") < html.index("Clips <i>")                 # in this order
    only = client.get("/", params={"kind": "gif"}).text
    assert only.count('class="tile"') == 1 and f'href="/items/{g}"' in only and f'href="/items/{a}"' not in only
    images = client.get("/", params={"kind": "image"}).text
    assert images.count('class="tile"') == 1 and f'href="/items/{a}"' in images and f'href="/items/{g}"' not in images        # a GIF is not an "image" any more


def test_tiles_and_pages_mark_a_gif(library):
    client, a, g = library
    tiles = client.get("/").text
    assert 'class="chip k-gif" title="GIF"' in tiles and 'class="chip k-image" title="Image"' in tiles
    page = client.get(f"/items/{g}").text
    assert f'<img src="/media/{g}"' in page and "<dt>Type</dt><dd>GIF</dd>" in page and "<video" not in page         # shown as a picture, so it keeps moving
    assert client.get(f"/media/{g}").headers["content-type"] == "image/gif"


def test_the_api_has_the_kind_gif(library):
    client, a, g = library
    assert [i["kind"] for i in client.get("/api/v1/items", params={"kind": "gif"}).json()["items"]] == ["gif"]
    assert [i["kind"] for i in client.get("/api/v1/items", params={"kind": "image"}).json()["items"]] == ["image"]
    assert sorted(i["kind"] for i in client.get("/api/v1/items").json()["items"]) == ["gif", "image"]


def test_a_gif_can_be_shared_and_cropped_like_a_picture(library):
    client, a, g = library
    client.post(f"/items/{g}/shares", data={"preset": "never", "next": f"/items/{g}"})
    with db.tx() as c:
        token = c.execute("SELECT token FROM shares").fetchone()[0]
    from test_share import anon_client
    page = anon_client().get(f"/s/{token}")
    assert page.status_code == 200 and "<img " in page.text and "<video" not in page.text
    assert client.get(f"/items/{g}/card").status_code == 200 and client.get(f"/items/{g}/frame").status_code == 200
    assert client.post(f"/items/{g}/card", data={"t": 0, "x": 0, "y": 0, "s": 0.5}).status_code == 200
    with db.tx() as c:
        assert db.get_item(c, g)["has_card"] == 1


def test_gifs_get_no_transcription_job(library, monkeypatch):
    from drollery import aisettings, pipeline
    client, a, g = library
    monkeypatch.setattr(aisettings, "enabled", lambda cap: cap == "transcribe")
    with db.tx() as c:
        assert pipeline.plan_jobs(c, g) == []


def test_the_new_name_is_translated(library):
    client, _, _ = library
    client.post("/settings/profile", data={"email": "", "language": "de"})
    page = client.get("/").text
    assert "GIFs <i>1</i>" in page and "Bilder <i>1</i>" in page            # GIFs have their own filter, apart from the pictures


def test_a_gif_plays_on_its_tile_unless_it_has_a_card_image_of_its_own(library):
    client, a, g = library
    home = client.get("/").text
    tile = home.split(f'href="/items/{g}"')[1].split("</a>")[0]
    assert f'src="/media/{g}?v=' in tile                                                          # the GIF itself, so it loops
    assert f'media="(prefers-reduced-motion: reduce)" srcset="/thumb/{g}?v=' in tile              # a still for people who asked for less motion
    still = home.split(f'href="/items/{a}"')[1].split("</a>")[0]
    assert f'src="/thumb/{a}?v=' in still and "<picture>" not in still                           # other pictures stay as they were
    assert client.get(f"/media/{g}").headers["content-type"] == "image/gif"
    client.post(f"/items/{g}/card", data={"t": 0, "x": 0, "y": 0, "s": 0.5})                       # a crop the owner made is kept
    tile = client.get("/").text.split(f'href="/items/{g}"')[1].split("</a>")[0]
    assert f'src="/card/{g}?v=' in tile and f"/media/{g}" not in tile
