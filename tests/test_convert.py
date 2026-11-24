"""The browser-friendly copy of a film: made on request, played instead of the original, never replaces it."""
import json
import re
import subprocess

import pytest

from drollery import db, pipeline, trash
from test_card import red_then_blue_video


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,pix_fmt,width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


@pytest.fixture()
def odd_video(client, tmp_path):
    """A film a browser would struggle with: 10-bit, odd width and height, 5.1 sound, in an MKV."""
    src = tmp_path / "odd.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=161x121:r=10:d=2", "-f", "lavfi", "-i", "sine=f=300:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-c:a", "aac", "-ac", "6", "-channel_layout", "5.1", str(src)], check=True)
    r = client.post("/api/v1/items", files={"file": ("odd.mkv", src.read_bytes(), "video/x-matroska")})
    return r.json()["id"]


def run_convert(item_id):
    with db.tx() as c:
        job = db.enqueue(c, "convert", item_id)
        job = dict(c.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())
    pipeline.run_job(job)
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone())


def item(i):
    with db.tx() as c:
        return db.get_item(c, i)


def test_the_copy_is_h264_even_sided_stereo_and_the_original_is_untouched(client, odd_video):
    before = pipeline.media_path(item(odd_video)).read_bytes()
    job = run_convert(odd_video)
    assert job["status"] == "done" and job["progress"] == 100
    web = pipeline.web_path(item(odd_video))
    streams = probe(web)
    assert streams["video"]["codec_name"] == "h264" and streams["video"]["pix_fmt"] == "yuv420p"
    assert streams["video"]["width"] % 2 == 0 and streams["video"]["height"] % 2 == 0
    assert streams["audio"]["codec_name"] == "aac"
    assert pipeline.media_path(item(odd_video)).read_bytes() == before


def test_the_player_gets_the_copy_and_a_download_gets_the_original(client, odd_video):
    run_convert(odd_video)
    played = client.get(f"/media/{odd_video}")
    assert played.headers["content-type"] == "video/mp4" and played.content == pipeline.web_path(item(odd_video)).read_bytes()
    original = client.get(f"/media/{odd_video}?original=1")
    assert original.headers["content-type"] == "video/x-matroska" and original.content == pipeline.media_path(item(odd_video)).read_bytes()
    page = client.get(f"/items/{odd_video}").text
    assert "Remove browser-friendly copy" in page and f"/media/{odd_video}?original=1" in page


def test_a_shared_link_plays_the_copy_and_downloads_the_original(client, odd_video):
    run_convert(odd_video)
    client.post(f"/items/{odd_video}/shares", data={"preset": "never", "label": "", "next": f"/items/{odd_video}"})
    with db.tx() as c:
        token = c.execute("SELECT token FROM shares").fetchone()["token"]
    src = re.search(r'<video src="([^"]+)"', client.get(f"/s/{token}").text).group(1)
    assert client.get(src).headers["content-type"] == "video/mp4"
    assert client.get(src + "?download=1").headers["content-type"] == "video/x-matroska"


def test_the_button_queues_one_job_only_and_removing_the_copy_goes_back_to_the_original(client, odd_video):
    page = client.get(f"/items/{odd_video}").text
    assert f'action="/items/{odd_video}/convert"' in page and "Make browser-friendly copy" in page
    client.post(f"/items/{odd_video}/convert")
    client.post(f"/items/{odd_video}/convert")
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE type='convert'").fetchone()[0] == 1
    assert "Converting" in client.get(f"/items/{odd_video}").text
    with db.tx() as c:
        job = dict(c.execute("SELECT * FROM jobs WHERE type='convert'").fetchone())
    pipeline.run_job(job)
    assert pipeline.web_path(item(odd_video)).exists()
    client.post(f"/items/{odd_video}/convert/delete")
    assert not pipeline.web_path(item(odd_video)).exists()
    assert client.get(f"/media/{odd_video}").headers["content-type"] == "video/x-matroska"


def test_only_videos_and_movies_can_be_converted(client):
    from test_app import png
    i = client.post("/api/v1/items", files={"file": ("a.png", png(1), "image/png")}).json()["id"]
    assert "Make browser-friendly copy" not in client.get(f"/items/{i}").text
    client.post(f"/items/{i}/convert")
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE type='convert'").fetchone()[0] == 0


def test_a_broken_file_fails_the_job_at_once_and_leaves_no_copy(client, odd_video):
    pipeline.media_path(item(odd_video)).write_bytes(b"not a video at all")
    job = run_convert(odd_video)
    assert job["status"] == "failed" and job["error"]                              # at once: no second and third try of a long job
    assert not pipeline.web_path(item(odd_video)).exists()
    assert not any(pipeline.get_settings().tmp_dir.iterdir())          # nothing is left in the temporary folder


def test_deleting_an_item_takes_its_copy_with_it_and_undo_brings_it_back(client, odd_video):
    run_convert(odd_video)
    web = pipeline.web_path(item(odd_video))
    token = client.post(f"/items/{odd_video}/delete", follow_redirects=False).cookies.get("drollery_undo")
    assert not web.exists()
    client.post(f"/undo/{token}")
    assert web.exists()
    client.delete(f"/api/v1/items/{odd_video}")
    assert not web.exists()
