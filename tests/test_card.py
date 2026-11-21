import re
import struct
import subprocess
import zlib

import pytest

from drollery import db, pipeline


def two_color_png(w=200, h=100) -> bytes:
    """Left half red, right half blue."""
    row = b"\x00" + (b"\xff\x00\x00" * (w // 2)) + (b"\x00\x00\xff" * (w // 2))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b""))


def red_then_blue_video(path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x120:d=2:r=10", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=2:r=10",
                    "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path.read_bytes()


def colour(data: bytes) -> str:
    """Dominant colour of an image given as bytes: 'red', 'blue' or 'other'."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], input=data, capture_output=True).stdout
    r, g, b = out[:3]
    return "red" if r > 200 and b < 60 else "blue" if b > 200 and r < 60 else "other"


@pytest.fixture()
def image_id(client):
    return client.post("/api/v1/items", files={"file": ("halves.png", two_color_png(), "image/png")}).json()["id"]


@pytest.fixture()
def video_id(client, tmp_path):
    return client.post("/api/v1/items", files={"file": ("redblue.mp4", red_then_blue_video(tmp_path / "rb.mp4"), "video/mp4")}).json()["id"]


def card_file(item_id):
    with db.tx() as c:
        return pipeline.card_path(db.get_item(c, item_id))


# ------------------------------------------------------------- picture

def test_crop_a_picture_for_the_card(client, image_id):
    fr = client.get(f"/items/{image_id}/frame")
    assert fr.status_code == 200 and fr.headers["content-type"] == "image/jpeg"

    r = client.post(f"/items/{image_id}/card", data={"x": "0.8", "y": "0.25", "s": "0.5"})    # a square inside the blue half
    assert r.status_code == 200 and "Card image saved" in r.text
    assert card_file(image_id).exists()
    got = client.get(f"/card/{image_id}")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg" and colour(got.content) == "blue"

    client.post(f"/items/{image_id}/card", data={"x": "0.02", "y": "0.25", "s": "0.5"})        # now the red half
    assert colour(client.get(f"/card/{image_id}").content) == "red"


def test_card_is_square_480(client, image_id):
    client.post(f"/items/{image_id}/card", data={"x": "0", "y": "0", "s": "1"})
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(card_file(image_id))], capture_output=True, text=True).stdout.strip()
    assert out == "480,480"


def test_library_uses_the_custom_card_and_the_original_is_untouched(client, image_id):
    before = client.get("/").text
    assert f"/thumb/{image_id}" in before and f"/card/{image_id}" not in before
    sha = db.get_item(db.connect(), image_id)["sha256"]
    original = pipeline.media_path({"sha256": sha, "ext": ".png"}).read_bytes()
    client.post(f"/items/{image_id}/card", data={"x": "0.8", "y": "0", "s": "0.6"})
    after = client.get("/").text
    assert re.search(rf'/card/{image_id}\?v=\d+', after) and f"/thumb/{image_id}" not in after
    assert pipeline.media_path({"sha256": sha, "ext": ".png"}).read_bytes() == original          # the file itself never changes
    item = client.get(f"/api/v1/items/{image_id}").json()
    assert item["card_url"] == f"/card/{image_id}" and "card_x" not in item and "has_card" not in item
    assert client.get(f"/thumb/{image_id}").status_code == 200                                     # AI/preview thumbnail is separate


def test_reset_returns_to_the_automatic_card(client, image_id):
    client.post(f"/items/{image_id}/card", data={"x": "0.8", "y": "0", "s": "0.5"})
    assert card_file(image_id).exists()
    r = client.post(f"/items/{image_id}/card/reset")
    assert "reset to automatic" in r.text and not card_file(image_id).exists()
    assert client.get(f"/card/{image_id}").status_code == 404
    assert f"/thumb/{image_id}" in client.get("/").text


def test_the_page_remembers_a_saved_crop(client, image_id):
    client.post(f"/items/{image_id}/card", data={"x": "0.8", "y": "0.25", "s": "0.5"})
    page = client.get(f"/items/{image_id}/card").text
    assert 'data-x="0.8"' in page and 'data-y="0.25"' in page and 'data-s="0.5"' in page and "Reset to automatic" in page
    assert "(custom)" not in client.get(f"/items/{image_id}").text


def test_deleting_the_item_removes_its_card_file(client, image_id):
    client.post(f"/items/{image_id}/card", data={"x": "0", "y": "0", "s": "1"})
    path = card_file(image_id)
    assert path.exists()
    client.post(f"/items/{image_id}/delete")
    assert not path.exists()


# --------------------------------------------------------------- video

def test_pick_a_moment_in_a_video(client, video_id):
    early = client.get(f"/items/{video_id}/frame", params={"t": "0.5"})
    late = client.get(f"/items/{video_id}/frame", params={"t": "3.0"})
    assert colour(early.content) == "red" and colour(late.content) == "blue"
    assert "Use this frame" in client.get(f"/items/{video_id}/card").text

    client.post(f"/items/{video_id}/card", data={"t": "3.0", "x": "0", "y": "0", "s": "1"})
    assert colour(client.get(f"/card/{video_id}").content) == "blue"
    client.post(f"/items/{video_id}/card", data={"t": "0.5", "x": "0", "y": "0", "s": "1"})
    assert colour(client.get(f"/card/{video_id}").content) == "red"
    page = client.get(f"/items/{video_id}/card").text
    assert 'name="t" id="f-t" value="0.5"' in page                                               # the chosen moment is remembered


def test_a_time_past_the_end_is_clamped_not_an_error(client, video_id):
    assert client.get(f"/items/{video_id}/frame", params={"t": "9999"}).status_code == 200
    assert client.post(f"/items/{video_id}/card", data={"t": "9999", "x": "0", "y": "0", "s": "1"}).status_code == 200


# ---------------------------------------------------------- validation

@pytest.mark.parametrize("data", [{"x": "0", "y": "0", "s": "0.001"}, {"x": "0", "y": "0", "s": "1.5"}, {"x": "-0.1", "y": "0", "s": "0.5"},
                                  {"x": "nan", "y": "0", "s": "0.5"}, {"x": "0", "y": "2", "s": "0.5"}, {"x": "inf", "y": "0", "s": "0.5"}])
def test_bad_crop_values_are_rejected(client, image_id, data):
    assert client.post(f"/items/{image_id}/card", data=data).status_code == 422
    assert not card_file(image_id).exists()


def test_bad_times_are_rejected(client, video_id):
    assert client.get(f"/items/{video_id}/frame", params={"t": "-1"}).status_code == 422
    assert client.get(f"/items/{video_id}/frame", params={"t": "nan"}).status_code == 422
    assert client.post(f"/items/{video_id}/card", data={"t": "-3", "x": "0", "y": "0", "s": "1"}).status_code == 422


def test_audio_has_no_card_image(client):
    import subprocess as sp
    wav = sp.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=1", "-f", "mp3", "-"], capture_output=True).stdout
    aid = client.post("/api/v1/items", files={"file": ("tone.mp3", wav, "audio/mpeg")}).json()["id"]
    assert client.get(f"/items/{aid}/card").status_code == 404
    assert client.get(f"/items/{aid}/frame").status_code == 404
    assert "Card image" not in client.get(f"/items/{aid}").text


# -------------------------------------------------------------- access

def test_card_tools_need_a_login(client, image_id):
    from fastapi.testclient import TestClient
    from drollery.main import app
    client.post(f"/items/{image_id}/card", data={"x": "0", "y": "0", "s": "1"})
    v = TestClient(app, follow_redirects=False)
    assert v.get(f"/items/{image_id}/card").headers["location"] == "/login"
    assert v.get(f"/items/{image_id}/frame").headers["location"] == "/login"
    assert v.post(f"/items/{image_id}/card", data={"x": "0", "y": "0", "s": "1"}).headers["location"] == "/login"
    assert v.post(f"/items/{image_id}/card/reset").headers["location"] == "/login"
    assert v.get(f"/card/{image_id}").status_code == 401                                           # files: key or session
    from conftest import PASSWORD
    key = re.search(r'id="new-key">(drl_[\w-]+)<', client.post("/settings/keys", data={"name": "app", "kind": "app"}).text).group(1)
    assert v.get(f"/card/{image_id}", headers={"Authorization": f"Bearer {key}"}).status_code == 200


# ------------------------------------------------------------ migration

def test_an_older_database_gets_the_card_columns(client, image_id):
    """Installs from before this feature have no card columns; startup must add them and keep the data."""
    with db.tx() as c:
        for col in ("has_card", "card_t", "card_x", "card_y", "card_s"):
            c.execute(f"ALTER TABLE items DROP COLUMN {col}")
        assert "has_card" not in {r["name"] for r in c.execute("SELECT name FROM pragma_table_info('items')")}
    db.init()
    with db.tx() as c:
        cols = {r["name"] for r in c.execute("SELECT name FROM pragma_table_info('items')")}
        assert {"has_card", "card_t", "card_x", "card_y", "card_s"} <= cols
        item = db.get_item(c, image_id)
    assert item["title"] == "halves" and item["has_card"] == 0
    assert client.post(f"/items/{image_id}/card", data={"x": "0", "y": "0", "s": "1"}).status_code == 200


def test_item_facts_sit_in_a_details_box_not_under_the_picture(client, image_id):
    client.post(f"/items/{image_id}/edit", data={"title": "Halves", "description": "", "tags": ""})
    with db.tx() as c:
        c.execute("UPDATE items SET source_url='https://example.org/halves.png' WHERE id=?", (image_id,))
    page = client.get(f"/items/{image_id}").text
    box = page.split('id="details"')[1].split("</section>")[0]
    for want in ("<dt>Type</dt><dd>Image</dd>", "<dt>Format</dt><dd>image/png</dd>", "<dt>Size</dt>", "<dt>Dimensions</dt><dd>200×100</dd>", "<dt>Source</dt>", "example.org/halves.png"):
        assert want in box, want
    line = page.split('class="meta-line"')[1].split("</p>")[0]
    assert "image/png" not in line and "Source" not in line and "Download" in line


def test_card_image_is_a_popup_on_item_pages_and_not_labelled_custom(client, image_id):
    client.post(f"/items/{image_id}/card", data={"t": 0, "x": 0, "y": 0, "s": 0.5})        # a custom crop exists now
    page = client.get(f"/items/{image_id}").text
    assert f'href="/items/{image_id}/card" data-popup="Card image"' in page and "(custom)" not in page
    assert 'id="popup-dialog"' in page and "/static/popup.js" in page


def test_an_own_picture_becomes_the_card_and_can_be_cropped(client, video_id):
    own = two_color_png(120, 60)
    r = client.post(f"/items/{video_id}/card/picture", files={"image": ("mine.png", own, "image/png")})
    assert r.status_code == 200 and "card image now" in r.text
    assert 'data-kind="image"' in r.text and 'id="snap"' not in r.text                   # no video moments any more
    assert colour(client.get(f"/card/{video_id}").content) == "other"                     # centred square of red|blue halves
    assert client.get(f"/items/{video_id}/frame").headers["content-type"] == "image/jpeg"
    r = client.post(f"/items/{video_id}/card", data={"t": 0, "x": 0, "y": 0, "s": 0.4})   # crop inside the left (red) half
    assert colour(client.get(f"/card/{video_id}").content) == "red"
    with db.tx() as c:
        item = db.get_item(c, video_id)
    assert pipeline.card_source_path(item).exists()
    assert client.get(f"/media/{video_id}").status_code == 200                           # the item itself is untouched
    assert "Choose a video frame again" in client.get(f"/items/{video_id}/card").text      # offered without a confirmation box
    back = client.post(f"/items/{video_id}/card/reset")
    assert 'id="snap"' in back.text and "automatic" in back.text                            # lands on the frame chooser, not the item page
    assert not pipeline.card_source_path(item).exists() and not card_file(video_id).exists()
    assert 'id="snap"' in client.get(f"/items/{video_id}/card").text                     # back to choosing a video frame


def test_the_own_card_picture_must_be_a_picture(client, image_id):
    for name, data in (("notes.txt", b"hello"), ("fake.png", b"not really a png")):
        r = client.post(f"/items/{image_id}/card/picture", files={"image": (name, data, "image/png")})
        assert "not a picture" in r.text
    with db.tx() as c:
        item = db.get_item(c, image_id)
    assert not pipeline.card_source_path(item).exists() and item["has_card"] == 0


def test_resetting_never_asks_the_browser_for_confirmation(client, image_id):
    client.post(f"/items/{image_id}/card", data={"x": "0.8", "y": "0", "s": "0.5"})
    page = client.get(f"/items/{image_id}/card").text
    assert "/card/reset" in page and "confirm(" not in page.split("/card/reset")[1].split("</form>")[0]
