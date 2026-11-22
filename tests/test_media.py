"""What is stored about a video's size: the size people see, also when the phone recorded it on its side."""
import subprocess

import pytest

from drollery import db, media, pipeline


def make(tmp_path, name, rotation=None):
    plain = tmp_path / f"{name}-plain.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=1", "-f", "lavfi", "-i", "sine=f=300:d=1",
                    "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(plain)], check=True)
    if rotation is None:
        return plain
    out = tmp_path / f"{name}.mp4"                                       # the same frames plus a flag that says "turn them"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", str(rotation), "-i", str(plain), "-c", "copy", str(out)], check=True)
    return out


@pytest.mark.parametrize("rotation, size", [(None, (320, 180)), (90, (180, 320)), (-90, (180, 320)), (270, (180, 320)), (180, (320, 180))])
def test_the_size_is_the_one_people_see(tmp_path, rotation, size):
    info = media.probe(make(tmp_path, f"clip{rotation}", rotation))
    assert (info["width"], info["height"]) == size


def test_an_old_style_rotate_tag_counts_too():
    assert media._turned({"tags": {"rotate": "90"}}) and media._turned({"tags": {"rotate": "270"}})
    assert not media._turned({"tags": {"rotate": "180"}}) and not media._turned({}) and not media._turned({"tags": {"rotate": "x"}})
    assert media._turned({"side_data_list": [{"rotation": -90}], "tags": {"rotate": "0"}})          # the display matrix wins


def test_an_upright_phone_video_is_stored_portrait_and_the_player_is_given_that_shape(client, tmp_path):
    data = make(tmp_path, "upright", 90).read_bytes()
    vid = client.post("/api/v1/items", files={"file": ("upright.mp4", data, "video/mp4")}).json()["id"]
    with db.tx() as c:
        item = db.get_item(c, vid)
    assert (item["width"], item["height"]) == (180, 320)
    page = client.get(f"/items/{vid}").text
    assert "180×320" in page and 'style="--ar: 0.5625"' in page                                       # a tall player from the first moment
    thumb = media.probe(pipeline.thumb_path(item))
    assert thumb["width"] < thumb["height"]                                                         # the preview picture is upright as well
