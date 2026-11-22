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


# ------------------------------------------- videos stored before the size was right

def upload(client, tmp_path, name, rotation=None):
    return client.post("/api/v1/items", files={"file": (f"{name}.mp4", make(tmp_path, name, rotation).read_bytes(), "video/mp4")}).json()["id"]


def old_sizes(vid, width, height):
    """Put a video back in the state of an older version: the size of the stored frames, and the check not done yet."""
    from drollery import accounts
    with db.tx() as c:
        c.execute("UPDATE items SET width=?, height=? WHERE id=?", (width, height, vid))
    accounts.set_setting(pipeline.VIDEO_SIZES_DONE, None)


def run_upkeep():
    with db.tx() as c:
        pipeline.plan_upkeep(c)
    job = db.claim_job()
    if job:
        pipeline.run_job(job)
    return job


def size(vid):
    with db.tx() as c:
        item = db.get_item(c, vid)
    return (item["width"], item["height"], item["updated_at"])


def test_old_videos_get_the_size_people_see_once(client, tmp_path, monkeypatch):
    from drollery import accounts
    monkeypatch.setattr(accounts, "worker_limit", lambda: 0)                  # the app's own workers must not take the job
    upright, plain = upload(client, tmp_path, "upright", 90), upload(client, tmp_path, "plain")
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
    old_sizes(upright, 320, 180)                                              # how an older version stored the upright one
    before = size(plain)
    job = run_upkeep()
    assert job and job["type"] == "check_video_sizes"
    assert size(upright)[:2] == (180, 320)                                    # corrected
    assert size(plain) == before                                              # a video that was right is not touched, nor is its date
    assert accounts.get_setting(pipeline.VIDEO_SIZES_DONE) == "1"
    with db.tx() as c:
        assert c.execute("SELECT status FROM jobs WHERE type='check_video_sizes'").fetchone()["status"] == "done"
    assert run_upkeep() is None                                               # done once: nothing is queued again


def test_the_check_skips_a_missing_file_and_does_not_queue_without_videos(client, tmp_path, monkeypatch):
    from drollery import accounts
    monkeypatch.setattr(accounts, "worker_limit", lambda: 0)
    accounts.set_setting(pipeline.VIDEO_SIZES_DONE, None)
    assert run_upkeep() is None                                               # a library without videos has nothing to check
    gone, upright = upload(client, tmp_path, "gone"), upload(client, tmp_path, "upright", 90)
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
        item = db.get_item(c, gone)
    pipeline.media_path(item).unlink()
    old_sizes(upright, 320, 180)
    assert run_upkeep() is not None
    assert size(upright)[:2] == (180, 320) and size(gone)[:2] == (320, 180)    # the missing one is left as it was, the rest is still done
    with db.tx() as c:
        assert c.execute("SELECT status FROM jobs WHERE type='check_video_sizes'").fetchone()["status"] == "done"


def test_the_check_is_queued_when_the_app_starts_with_old_videos(client, tmp_path, monkeypatch):
    from drollery import accounts
    from drollery.main import app
    monkeypatch.setattr(accounts, "worker_limit", lambda: 0)
    vid = upload(client, tmp_path, "upright", 90)
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
    old_sizes(vid, 320, 180)
    import asyncio
    async def start_and_stop():
        async with app.router.lifespan_context(app):
            pass
    asyncio.run(start_and_stop())                                              # what the server does at start
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE type='check_video_sizes' AND status='queued'").fetchone()[0] == 1
