import io
import subprocess
import zipfile
from pathlib import Path

import pytest

from drollery import albums, db
from drollery.config import get_settings
from test_app import png


def make_mp3(path: Path, title: str, track: int, album="Satire Hits", artist="The Jesters", cover: bytes | None = None, seconds=1) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={200 + track * 40}:duration={seconds}"]
    if cover:
        pic = path.with_suffix(".png")
        pic.write_bytes(cover)
        cmd += ["-i", str(pic), "-map", "0:a", "-map", "1:0", "-c:v", "copy", "-id3v2_version", "3"]
    cmd += ["-metadata", f"title={title}", "-metadata", f"track={track}", "-metadata", f"album={album}", "-metadata", f"artist={artist}", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="module")
def mp3s(tmp_path_factory):
    d = tmp_path_factory.mktemp("mp3")
    return {
        "one": make_mp3(d / "zz-last-file.mp3", "Opening Fanfare", 1),
        "two": make_mp3(d / "aa-first-file.mp3", "The King's Tax Return", 2),
        "three": make_mp3(d / "mm.mp3", "Ballad of the Cheese Wizard", 3),
        "art": make_mp3(d / "cover-track.mp3", "Singing Frog", 4, album="Embedded", artist="Frogs", cover=png(200)),
        "plain": make_mp3(d / "plain.mp3", "Plain", 1, album="", artist=""),
    }


def upload(client, paths, **data):
    files = [("files", (Path(p).name, Path(p).read_bytes(), "audio/mpeg")) for p in paths]
    return client.post("/albums", files=files, data=data)


def make_zip(entries: dict[str, bytes], compress: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def album_id(client):
    with db.tx() as c:
        return c.execute("SELECT id FROM items WHERE kind='album' ORDER BY id DESC LIMIT 1").fetchone()["id"]


# ----------------------------------------------------------------- creating

def test_tracks_are_ordered_by_track_number_not_by_file_name(client, mp3s):
    r = upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]], title="", tags="satire music")
    assert r.status_code == 200 and "Album created" in r.text
    aid = album_id(client)
    with db.tx() as c:
        item = db.get_item(c, aid)
        tracks = albums.tracks_of(c, aid)
        info = albums.get(c, aid)
        jobs = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert item["kind"] == "album" and item["title"] == "Satire Hits" and info["artist"] == "The Jesters"   # both from the files' tags
    assert [t["title"] for t in tracks] == ["Opening Fanfare", "The King's Tax Return", "Ballad of the Cheese Wizard"]
    assert [t["position"] for t in tracks] == [1, 2, 3] and item["tags"] == ["music", "satire"]
    assert item["duration"] and item["duration"] > 2 and jobs == 0                                           # no transcription for an album
    page = client.get(f"/items/{aid}")
    assert page.status_code == 200 and "The King&#39;s Tax Return" in page.text and "3 tracks" in page.text


def test_names_given_by_the_person_win_over_the_tags(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"]], title="My Title", artist="Me", subtype="audiobook", description="satire")
    with db.tx() as c:
        item = db.get_item(c, album_id(client))
        info = albums.get(c, item["id"])
    assert item["title"] == "My Title" and info["artist"] == "Me" and info["subtype"] == "audiobook" and item["description"] == "satire"
    page = client.get(f"/items/{item['id']}").text
    assert "Audiobook" in page and "2 chapters" in page and "Chapters" in page


def test_cover_comes_from_the_first_track_that_carries_one(client, mp3s):
    upload(client, [mp3s["art"], mp3s["one"]])
    aid = album_id(client)
    with db.tx() as c:
        assert db.get_item(c, aid)["has_thumb"] == 1
    cover = client.get(f"/albums/{aid}/cover")
    assert cover.status_code == 200 and cover.headers["content-type"] == "image/jpeg" and cover.content[:2] == b"\xff\xd8"
    assert client.get(f"/thumb/{aid}").status_code == 200


def test_an_uploaded_cover_beats_embedded_art(client, mp3s):
    files = [("files", (mp3s["art"].name, mp3s["art"].read_bytes(), "audio/mpeg")), ("cover", ("front.png", png(10), "image/png"))]
    r = client.post("/albums", files=files, data={})
    assert r.status_code == 200
    aid = album_id(client)
    first = client.get(f"/albums/{aid}/cover").content
    r2 = client.post("/albums", files=[("files", (mp3s["art"].name, mp3s["art"].read_bytes(), "audio/mpeg")), ("files", ("x.mp3", mp3s["one"].read_bytes(), "audio/mpeg"))],
                     data={})
    assert r2.status_code == 200 and album_id(client) != aid and first != client.get(f"/albums/{album_id(client)}/cover").content


def test_a_zip_with_folders_a_cover_and_junk(client, mp3s):
    z = make_zip({
        "My Album/10 - Tenth.mp3": mp3s["plain"].read_bytes(),
        "My Album/2 - Second.mp3": mp3s["two"].read_bytes().replace(b"The King", b"The King"),
        "My Album/cover.jpg": png(30),
        "My Album/notes.txt": b"not audio",
        "__MACOSX/My Album/._2 - Second.mp3": b"junk",
        "My Album/.hidden.mp3": b"junk",
    })
    # tags would order them (plain has none), so check the zip path with tag-less copies
    r = client.post("/albums", files=[("files", ("Great Satire.zip", z, "application/zip"))], data={})
    assert r.status_code == 200
    aid = album_id(client)
    with db.tx() as c:
        item, tracks = db.get_item(c, aid), albums.tracks_of(c, aid)
    assert len(tracks) == 2 and item["has_thumb"] == 1 and item["original_name"] == "Great Satire.zip"
    assert client.get(f"/albums/{aid}/cover").status_code == 200


def test_zip_members_cannot_write_outside_the_album(client, mp3s):
    z = make_zip({"../../evil.mp3": mp3s["plain"].read_bytes(), "a/../../b.mp3": mp3s["one"].read_bytes()})
    r = client.post("/albums", files=[("files", ("evil.zip", z, "application/zip"))], data={})
    assert r.status_code == 200
    root = get_settings().data_dir
    assert not list(root.parent.glob("evil.mp3")) and not (root / "evil.mp3").exists()
    assert all(root in p.parents for p in (root / "media" / "albums").rglob("*"))


def test_a_zip_bomb_is_stopped_by_the_size_counted_while_unpacking(client, mp3s, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_album_mb", 1)
    z = make_zip({"big.mp3": b"\0" * (3 * 1024 * 1024)}, compress=True)      # a few KB on the wire, 3 MB unpacked
    r = client.post("/albums", files=[("files", ("bomb.zip", z, "application/zip"))], data={})
    assert r.status_code == 422 and "size limit" in r.text


def test_bad_uploads_are_refused_with_a_reason(client, mp3s):
    r = client.post("/albums", files=[("files", ("notes.txt", b"hello", "text/plain"))], data={})
    assert r.status_code == 422 and "Only audio files" in r.text
    r = client.post("/albums", files=[("files", ("fake.mp3", b"this is not audio at all", "audio/mpeg"))], data={})
    assert r.status_code == 422 and "could not be read as audio" in r.text
    r = client.post("/albums", files=[("files", ("broken.zip", b"PK nope", "application/zip"))], data={})
    assert r.status_code == 422 and "ZIP file could not be read" in r.text
    r = client.post("/albums", files=[("files", (mp3s["one"].name, mp3s["one"].read_bytes(), "audio/mpeg")), ("cover", ("c.txt", b"x", "text/plain"))], data={})
    assert r.status_code == 422 and "cover must be a picture" in r.text
    r = client.post("/albums", data={})
    assert r.status_code == 422 and "Add at least one audio file" in r.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0           # nothing half-made is left behind
    assert not list((get_settings().media_dir / "albums").glob("*"))


def test_the_same_tracks_make_the_same_album(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"]])
    again = upload(client, [mp3s["two"], mp3s["one"]], title="Other title")
    assert "already in the library" in again.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM items WHERE kind='album'").fetchone()[0] == 1


# ------------------------------------------------------------ the library

def test_the_library_shows_one_card_per_album_and_finds_it(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]], tags="satire")
    aid = album_id(client)
    home = client.get("/").text
    assert f'href="/items/{aid}"' in home and "3 tracks" in home and "k-album" in home and "Albums <i>1</i>" in home
    assert client.get("/", params={"kind": "album"}).text.count('class="tile"') == 1
    assert client.get("/", params={"kind": "video"}).text.count('class="tile"') == 0
    for q in ("Cheese Wizard", "jesters", "satire", "fanfare"):                       # track title, artist, tag
        assert f'href="/items/{aid}"' in client.get("/", params={"q": q}).text, q
    assert client.get("/api/v1/items").json()["items"][0]["url"] is None


def test_albums_have_no_single_file_and_cannot_be_shared(client, mp3s):
    upload(client, [mp3s["one"]])
    aid = album_id(client)
    assert client.get(f"/media/{aid}").status_code == 404
    blocked = client.post(f"/items/{aid}/shares", data={"preset": "never", "next": f"/items/{aid}"})
    assert "cannot be shared" in blocked.text
    assert client.post(f"/api/v1/items/{aid}/shares", json={}).status_code == 422


def test_play_a_track_download_all_and_the_auth_wall(client, anon, mp3s):
    upload(client, [mp3s["one"], mp3s["two"]])
    aid = album_id(client)
    with db.tx() as c:
        tracks = albums.tracks_of(c, aid)
    t = client.get(f"/albums/{aid}/track/{tracks[0]['id']}")
    assert t.status_code == 200 and t.headers["content-type"].startswith("audio/") and len(t.content) > 1000
    assert client.get(f"/albums/{aid}/track/999999").status_code == 404
    other = client.get(f"/albums/{aid}/track/{tracks[0]['id']}", headers={"range": "bytes=0-99"})
    assert other.status_code == 206 and len(other.content) == 100                        # seeking works
    z = client.get(f"/albums/{aid}/download")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names[0].startswith("01 - Opening Fanfare") and names[1].startswith("02 - The King") and len(names) == 2
    for url in (f"/albums/{aid}/track/{tracks[0]['id']}", f"/albums/{aid}/cover", f"/albums/{aid}/download"):
        assert anon.get(url).status_code in (401, 303)
    assert anon.get("/albums/new").status_code == 303 and anon.post("/albums", data={}).status_code in (303, 401)


def test_rename_and_reorder_tracks(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]])
    aid = album_id(client)
    with db.tx() as c:
        ids = [t["id"] for t in albums.tracks_of(c, aid)]
    r = client.post(f"/albums/{aid}/tracks", data={f"pos_{ids[0]}": "3", f"pos_{ids[1]}": "1", f"pos_{ids[2]}": "2",
                                                      f"title_{ids[1]}": "Taxes Are Funny", f"title_{ids[0]}": "   "})
    assert r.status_code == 200 and "Tracks saved" in r.text
    with db.tx() as c:
        tracks = albums.tracks_of(c, aid)
    assert [t["id"] for t in tracks] == [ids[1], ids[2], ids[0]] and [t["position"] for t in tracks] == [1, 2, 3]
    assert tracks[0]["title"] == "Taxes Are Funny" and tracks[2]["title"] == "Opening Fanfare"      # a blank title keeps the old one
    assert f'href="/items/{aid}"' in client.get("/", params={"q": "Taxes Funny"}).text           # the search sees the new title
    r = client.post(f"/albums/{aid}/tracks", data={f"pos_{ids[0]}": "banana"})
    assert r.status_code == 200
    assert client.post("/albums/99999/tracks", data={}).status_code == 404


def test_edit_the_artist_and_the_card_image(client, mp3s):
    upload(client, [mp3s["art"]])
    aid = album_id(client)
    client.post(f"/items/{aid}/edit", data={"title": "Frog Opera", "artist": "Kermit", "description": "", "tags": "frog"})
    with db.tx() as c:
        assert albums.get(c, aid)["artist"] == "Kermit" and db.get_item(c, aid)["title"] == "Frog Opera"
    assert f'href="/items/{aid}"' in client.get("/", params={"q": "kermit"}).text
    page = client.get(f"/items/{aid}/card")
    assert page.status_code == 200 and client.get(f"/items/{aid}/frame").status_code == 200
    r = client.post(f"/items/{aid}/card", data={"t": 0, "x": 0, "y": 0, "s": 0.5})
    assert r.status_code == 200
    with db.tx() as c:
        assert db.get_item(c, aid)["has_card"] == 1
    assert client.get(f"/card/{aid}").status_code == 200
    upload(client, [mp3s["one"]])                                                            # no cover at all
    assert client.get(f"/items/{album_id(client)}/card").status_code == 404


def test_deleting_an_album_removes_its_files(client, mp3s):
    upload(client, [mp3s["art"]])
    aid = album_id(client)
    with db.tx() as c:
        item = db.get_item(c, aid)
    folder = albums.album_dir(item)
    assert folder.exists() and (get_settings().thumbs_dir / f"{item['sha256']}.jpg").exists()
    client.post(f"/items/{aid}/delete")
    assert not folder.exists() and not (get_settings().thumbs_dir / f"{item['sha256']}.jpg").exists()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 0 and c.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 0


def test_the_api_creates_an_album(client, mp3s):
    files = [("files", (p.name, p.read_bytes(), "audio/mpeg")) for p in (mp3s["one"], mp3s["two"])]
    r = client.post("/api/v1/albums", files=files, data={"title": "From the API"})
    assert r.status_code == 201 and r.json()["tracks"] == 2 and r.json()["created"] is True and r.json()["title"] == "From the API"
    bad = client.post("/api/v1/albums", files=[("files", ("x.txt", b"x", "text/plain"))])
    assert bad.status_code == 422


def test_helpers_for_titles_and_ordering():
    assert albums.title_from_name("01 - Opening Fanfare.mp3") == "Opening Fanfare"
    assert albums.title_from_name("Track 04_the_end.mp3") == "the end" and albums.title_from_name("07.mp3") == "07"
    assert sorted(["t10", "t2", "t1"], key=albums.natural_key) == ["t1", "t2", "t10"]
    assert albums.safe_filename('a/b:c*"d') == "a_b_c_d"
