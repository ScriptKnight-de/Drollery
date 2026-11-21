import io
import sqlite3
import time
import zipfile

import pytest

from drollery import albums, db, shares
from test_album import album_id, make_mp3, mp3s, upload  # noqa: F401  (mp3s is a fixture)
from test_share import anon_client


@pytest.fixture()
def album(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]], title="Satire Hits", artist="The Jesters")
    aid = album_id(client)
    with db.tx() as c:
        tracks = albums.tracks_of(c, aid)
    return aid, tracks


def share(client, aid, track=None, **form):
    data = {"preset": "never", "label": "", "next": f"/items/{aid}", **form}
    if track is not None:
        data["track"] = str(track)
    assert client.post(f"/items/{aid}/shares", data=data).status_code == 200
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM shares ORDER BY id DESC LIMIT 1").fetchone())


def test_the_album_page_offers_whole_or_single_track_sharing(client, album):
    aid, tracks = album
    html = client.get(f"/items/{aid}").text
    assert 'id="share"' in html and 'name="track"' in html and "The whole album" in html
    assert all(f'<option value="{t["id"]}">' in html for t in tracks)                  # every track can be picked
    assert html.count("data-share-track=") == 3                                         # and has its own share button
    assert "sharepanel.js" in html and 'src="/static/player.js"' in html


def test_share_the_whole_album(client, album):
    aid, tracks = album
    sh = share(client, aid)
    assert sh["track_id"] is None
    pub = anon_client()
    page = pub.get(f"/s/{sh['token']}")
    assert page.status_code == 200 and "Satire Hits" in page.text and "The Jesters" in page.text
    for t in tracks:                                                                    # every track is listed and playable
        assert t["title"].replace("'", "&#39;") in page.text and f"/s/{sh['token']}/track/{t['id']}" in page.text
    assert f"/s/{sh['token']}/download" in page.text and 'content="music.album"' in page.text
    assert pub.get(f"/s/{sh['token']}/track/{tracks[1]['id']}").status_code == 200
    got = pub.get(f"/s/{sh['token']}/track/{tracks[0]['id']}", headers={"range": "bytes=0-49"})
    assert got.status_code == 206 and len(got.content) == 50
    assert "attachment" in pub.get(f"/s/{sh['token']}/track/{tracks[0]['id']}?download=1").headers["content-disposition"]
    z = pub.get(f"/s/{sh['token']}/download")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 3
    assert "sandbox" in z.headers["content-security-policy"]


def test_share_just_one_track_and_nothing_else_leaks(client, album):
    aid, tracks = album
    sh = share(client, aid, track=tracks[1]["id"])
    assert sh["track_id"] == tracks[1]["id"]
    pub = anon_client()
    page = pub.get(f"/s/{sh['token']}")
    assert page.status_code == 200 and "The King&#39;s Tax Return" in page.text and 'content="music.song"' in page.text
    assert "Satire Hits" in page.text                                                    # named as the album it came from
    for other in (tracks[0], tracks[2]):                                                 # the other tracks are neither listed nor reachable
        assert other["title"].replace("'", "&#39;") not in page.text
        assert pub.get(f"/s/{sh['token']}/track/{other['id']}").status_code == 404
    assert 'id="tracklist"' not in page.text and f"/s/{sh['token']}/download" not in page.text
    assert pub.get(f"/s/{sh['token']}/download").status_code == 404                      # no ZIP of the whole album
    assert pub.get(f"/s/{sh['token']}/track/{tracks[1]['id']}").status_code == 200
    assert f'property="og:audio" content="http://testserver/s/{sh["token"]}/track/{tracks[1]["id"]}"' in page.text


def test_the_links_the_owner_copies_point_at_the_right_thing(client, album):
    aid, tracks = album
    whole, one = share(client, aid), share(client, aid, track=tracks[2]["id"])
    with db.tx() as c:
        item = db.get_item(c, aid)
    u_whole = shares.urls(type("R", (), {"base_url": "http://x/"})(), shares.decorate(whole), item)
    u_one = shares.urls(type("R", (), {"base_url": "http://x/"})(), shares.decorate(one), item)
    assert u_whole["raw"].endswith(f"/s/{whole['token']}/download") and u_one["raw"].endswith(f"/s/{one['token']}/track/{tracks[2]['id']}")
    html = client.get(f"/items/{aid}").text
    assert "Copy ZIP link" in html and "Copy file link" in html and "The whole album" in html and f"Track: {tracks[2]['title']}" in html


def test_tracks_of_other_albums_are_not_reachable_through_a_share(client, mp3s, album):
    aid, tracks = album
    upload(client, [mp3s["art"]])
    other = album_id(client)
    with db.tx() as c:
        foreign = albums.tracks_of(c, other)[0]["id"]
    sh = share(client, aid)
    pub = anon_client()
    assert pub.get(f"/s/{sh['token']}/track/{foreign}").status_code == 404
    assert pub.get(f"/s/{sh['token']}/track/999999").status_code == 404


def test_revoked_and_expired_album_shares_close_every_door(client, album):
    aid, tracks = album
    sh = share(client, aid)
    one = share(client, aid, track=tracks[0]["id"])
    pub = anon_client()
    client.post(f"/shares/{sh['id']}/revoke", data={"next": f"/items/{aid}"})
    assert pub.get(f"/s/{sh['token']}").status_code == 410
    assert pub.get(f"/s/{sh['token']}/track/{tracks[0]['id']}").status_code == 410 and pub.get(f"/s/{sh['token']}/download").status_code == 410
    assert pub.get(f"/s/{one['token']}/track/{tracks[0]['id']}").status_code == 200       # the other link is untouched
    with db.tx() as c:
        c.execute("UPDATE shares SET expires_at=? WHERE id=?", (time.time() - 5, one["id"]))
    assert pub.get(f"/s/{one['token']}/track/{tracks[0]['id']}").status_code == 410 and pub.get(f"/s/{one['token']}").status_code == 410


def test_views_are_counted_for_album_shares(client, album):
    aid, tracks = album
    sh = share(client, aid)
    pub = anon_client()
    pub.get(f"/s/{sh['token']}")                                                          # the page
    pub.get(f"/s/{sh['token']}/track/{tracks[0]['id']}", headers={"referer": f"http://testserver/s/{sh['token']}"})   # played from the page: not a new view
    pub.get(f"/s/{sh['token']}/track/{tracks[0]['id']}")                                  # a direct hit
    pub.get(f"/s/{sh['token']}/download")
    assert shares.get(sh["id"])["views"] == 3


def test_an_unknown_or_malformed_token_gets_nothing(client, album):
    aid, tracks = album
    pub = anon_client()
    for path in ("track/1", "download"):
        assert pub.get(f"/s/{'x' * 30}/{path}").status_code == 404 and pub.get(f"/s/short/{path}").status_code == 404


def test_a_bad_track_choice_is_refused(client, mp3s, album):
    aid, tracks = album
    upload(client, [mp3s["art"]])
    foreign = album_id(client)
    with db.tx() as c:
        foreign_track = albums.tracks_of(c, foreign)[0]["id"]
    r = client.post(f"/items/{aid}/shares", data={"preset": "never", "next": f"/items/{aid}", "track": str(foreign_track)})
    assert "That track does not exist" in r.text
    r = client.post(f"/items/{aid}/shares", data={"preset": "never", "next": f"/items/{aid}", "track": "banana"})
    assert "That track does not exist" in r.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 0


def test_shares_of_other_items_ignore_the_track_field(client):
    from test_share import make_item
    i = make_item(client)
    client.post(f"/items/{i}/shares", data={"preset": "never", "next": f"/items/{i}", "track": "1"})
    with db.tx() as c:
        assert c.execute("SELECT track_id FROM shares").fetchone()["track_id"] is None


def test_the_api_shares_an_album_or_one_track(client, album):
    aid, tracks = album
    whole = client.post(f"/api/v1/items/{aid}/shares", json={"expires_in": None})
    assert whole.status_code == 201 and whole.json()["track_id"] is None and whole.json()["file_url"].endswith("/download")
    one = client.post(f"/api/v1/items/{aid}/shares", json={"expires_in": 3600, "track_id": tracks[0]["id"]})
    assert one.status_code == 201 and one.json()["track_id"] == tracks[0]["id"] and f"/track/{tracks[0]['id']}" in one.json()["file_url"]
    assert client.post(f"/api/v1/items/{aid}/shares", json={"track_id": 999999}).status_code == 422
    assert client.post(f"/api/v1/items/{aid}/shares", json={"track_id": True}).status_code == 422
    assert len(client.get(f"/api/v1/items/{aid}/shares").json()["shares"]) == 2


def test_the_settings_list_says_what_each_link_shares(client, album):
    aid, tracks = album
    share(client, aid)
    share(client, aid, track=tracks[0]["id"])
    html = client.get("/settings/shares").text
    assert "The whole album" in html and tracks[0]["title"] in html


def test_deleting_the_album_removes_its_shares(client, album):
    aid, tracks = album
    sh = share(client, aid, track=tracks[0]["id"])
    client.post(f"/items/{aid}/delete")
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 0
    assert anon_client().get(f"/s/{sh['token']}").status_code == 404


def test_an_older_database_gets_the_track_column(tmp_path):
    con = sqlite3.connect(tmp_path / "old.db")
    con.executescript("CREATE TABLE shares (id INTEGER PRIMARY KEY, token TEXT, item_id INTEGER, label TEXT, created_at REAL);"
                      "INSERT INTO shares(token,item_id,label,created_at) VALUES ('t',1,'',0);")
    con.row_factory = sqlite3.Row
    db._migrate_shares(con)
    assert "track_id" in {r["name"] for r in con.execute("PRAGMA table_info(shares)")}
    assert con.execute("SELECT track_id FROM shares").fetchone()[0] is None          # existing shares keep working as whole-item shares
