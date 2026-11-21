"""The library's categories are called Images, Clips, Sounds and Albums; what is stored (video, audio) does not change."""
import subprocess

import pytest

from test_album import make_mp3
from test_app import png


@pytest.fixture()
def library(client, tmp_path):
    client.post("/api/v1/items", files={"file": ("a.png", png(5), "image/png")})
    mp3 = make_mp3(tmp_path / "s.mp3", "A Sound", 1)
    client.post("/api/v1/items", files={"file": ("s.mp3", mp3.read_bytes(), "audio/mpeg")})
    clip = tmp_path / "c.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5", "-c:v", "libvpx", str(clip)], check=True)
    client.post("/api/v1/items", files={"file": ("c.webm", clip.read_bytes(), "video/webm")})
    return client


def test_the_filter_says_clips_and_sounds(library):
    html = library.get("/").text
    assert "Clips <i>1</i>" in html and "Sounds <i>1</i>" in html and "Images <i>1</i>" in html and "Albums <i>0</i>" in html
    assert ">Video<" not in html and "Video <i>" not in html and "Audio <i>" not in html


def test_the_data_and_the_api_still_use_video_and_audio(library):
    assert library.get("/", params={"kind": "video"}).text.count('class="tile"') == 1                  # the filter keeps its value
    assert library.get("/", params={"kind": "audio"}).text.count('class="tile sound"') == 1
    kinds = sorted(i["kind"] for i in library.get("/api/v1/items").json()["items"])
    assert kinds == ["audio", "image", "video"]
    assert [i["kind"] for i in library.get("/api/v1/items", params={"kind": "video"}).json()["items"]] == ["video"]


def test_a_single_item_is_a_clip_or_a_sound(library):
    tiles = library.get("/").text
    assert 'title="Clip"' in tiles and 'title="Sound"' in tiles and 'title="Image"' in tiles and 'title="Video"' not in tiles
    items = {i["kind"]: i["id"] for i in library.get("/api/v1/items").json()["items"]}
    assert "<dt>Type</dt><dd>Clip</dd>" in library.get(f"/items/{items['video']}").text and "<dt>Type</dt><dd>Sound</dd>" in library.get(f"/items/{items['audio']}").text


def test_the_new_names_are_translated(library):
    library.post("/settings/profile", data={"email": "", "language": "de"})
    html = library.get("/").text
    assert "Clips <i>1</i>" in html and "Sounds <i>1</i>" in html and "Bilder <i>1</i>" in html
