"""The online album lookup, with the network replaced by a fake: no test here talks to a real service."""
import re
import time

import httpx
import pytest

from drollery import __version__, albums, db, metadata
from drollery.config import get_settings
from test_album import album_id, mp3s, upload  # noqa: F401  (mp3s is a fixture)
from test_app import png

REL = "4f2c7a10-8d2e-4a63-9b61-0a1b2c3d4e5f"
OTHER = "11111111-2222-4333-8444-555555555555"

SEARCH = {"releases": [
    {"id": REL, "title": "Satire Hits (Deluxe)", "score": 100, "date": "1999-05-01", "country": "DE", "track-count": 4, "disambiguation": "deluxe edition",
     "artist-credit": [{"name": "The Court", "joinphrase": " & "}, {"name": "Jesters", "joinphrase": ""}], "label-info": [{"label": {"name": "Royal Records"}}]},
    {"id": "not-a-uuid", "title": "Broken entry", "artist-credit": []},
    {"id": OTHER, "title": "<script>alert(1)</script>", "score": 60, "artist-credit": [{"name": "Eve"}], "track-count": 2},
]}
RELEASE = {"id": REL, "title": "Satire Hits (Deluxe)", "date": "1999-05-01", "country": "DE", "artist-credit": [{"name": "The Court Jesters"}],
           "label-info": [{"label": {"name": "Royal Records"}, "catalog-number": "RR 4711"}, {"label": {"name": "Royal Records"}, "catalog-number": "RR 4711"}],
           "barcode": "4012345678905", "status": "Official", "text-representation": {"language": "eng", "script": "Latn"},
           "release-group": {"primary-type": "Album", "secondary-types": ["Compilation", "Live"], "first-release-date": "1995-03-02",
                             "genres": [{"name": "satire", "count": 5}, {"name": "<b>comedy</b>", "count": 9}, {"name": "kabarett", "count": 1}]},
           "media": [{"position": 1, "format": "CD", "tracks": [
               {"position": 1, "number": "1", "title": "Opening Fanfare (Remastered)", "length": 1000},
               {"position": 2, "number": "2", "title": "The King's Tax Return", "length": 1000},
               {"position": 3, "number": "3", "title": "Ballad of the Cheese Wizard", "length": 1000},
               {"position": 4, "number": "4", "title": "Bonus: The Fool", "length": 90000}]}]}


class Fake:
    """Answers like MusicBrainz and the Cover Art Archive, and remembers every request that was made."""

    def __init__(self):
        self.calls = []
        self.cover = png(77)
        self.cover_status = 307
        self.search_status = 200
        self.fail = None

    def __call__(self, url, params, accept):
        self.calls.append({"url": url, "params": dict(params or {}), "accept": accept, "ua": metadata.user_agent()})
        if self.fail:
            raise self.fail
        req = httpx.Request("GET", url)
        if url == f"{metadata.MB}/release/":
            return httpx.Response(self.search_status, json=SEARCH, request=req)
        if url == f"{metadata.MB}/release/{REL}":
            return httpx.Response(200, json=RELEASE, request=req)
        if url.startswith(f"{metadata.CAA}/release/{REL}"):
            if self.cover_status == 404:
                return httpx.Response(404, request=req)
            return httpx.Response(307, headers={"location": "https://archive.org/download/mbid-x/cover.png"}, request=req)
        if url == "https://archive.org/download/mbid-x/cover.png":
            return httpx.Response(302, headers={"location": "https://ia800000.us.archive.org/0/items/mbid-x/cover.png"}, request=req)
        if url == "https://ia800000.us.archive.org/0/items/mbid-x/cover.png":
            return httpx.Response(200, content=self.cover, headers={"content-type": "image/png"}, request=req)
        return httpx.Response(404, request=req)


@pytest.fixture(autouse=True)
def fresh_cache():
    metadata._cache.clear()
    metadata._last[0] = 0.0
    yield
    metadata._cache.clear()


@pytest.fixture()
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(metadata, "_send", f)
    monkeypatch.setattr(metadata, "_sleep", lambda s: None)
    return f


@pytest.fixture()
def album(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]], title="My Satire Album", artist="Someone")
    aid = album_id(client)
    with db.tx() as c:
        return aid, albums.tracks_of(c, aid)


# ------------------------------------------------------------ the service layer

def test_search_builds_a_safe_query_and_skips_broken_entries(fake):
    out = metadata.search('He said "hi" (live) + more', "A/C: D*C")
    q = fake.calls[0]["params"]["query"]
    assert q == r'release:"He said \"hi\" \(live\) \+ more" AND artist:"A\/C\: D\*C"'          # Lucene characters cannot break out
    assert [c.mbid for c in out] == [REL, OTHER]                                                  # the entry without a valid id is dropped
    first = out[0]
    assert (first.title, first.artist, first.date, first.country, first.label, first.tracks, first.score, first.note) == \
        ("Satire Hits (Deluxe)", "The Court & Jesters", "1999-05-01", "DE", "Royal Records", 4, 100, "deluxe edition")
    with pytest.raises(metadata.MetadataError):
        metadata.search("  ", " ")


def test_release_details_are_read(fake):
    rel = metadata.release(REL)
    assert (rel.title, rel.artist, rel.year, rel.label, rel.url) == ("Satire Hits (Deluxe)", "The Court Jesters", "1999", "Royal Records", f"https://musicbrainz.org/release/{REL}")
    assert (rel.catalog, rel.barcode, rel.status, rel.format, rel.discs, rel.language, rel.original_date) == \
        ("RR 4711", "4012345678905", "Official", "CD", 1, "eng", "1995-03-02")                       # a repeated catalog number is listed once
    assert rel.type == ["Album", "Compilation", "Live"] and rel.genres == ["<b>comedy</b>", "satire", "kabarett"]            # most voted genre first
    assert fake.calls[0]["params"]["inc"] == "recordings+artist-credits+labels+release-groups+genres"
    d = rel.details()
    assert d["tracks"] == 4 and d["catalog"] == "RR 4711" and "status" in d and all(v not in ("", [], None) for v in d.values())
    assert [(t.disc, t.position, t.title, t.length) for t in rel.tracks][:2] == [(1, 1, "Opening Fanfare (Remastered)", 1.0), (1, 2, "The King's Tax Return", 1.0)]
    for bad in ("", "../../etc/passwd", REL + "/x", "abc"):                                       # an id is checked before it goes into a URL
        with pytest.raises(metadata.MetadataError):
            metadata.release(bad)
    assert len(fake.calls) == 1


def test_the_cover_is_followed_only_through_the_archive_hosts(fake):
    assert metadata.cover(REL) == fake.cover
    assert [c["url"].split("/")[2] for c in fake.calls] == ["coverartarchive.org", "archive.org", "ia800000.us.archive.org"]
    metadata._cache.clear()
    fake.cover_status = 404
    assert metadata.cover(REL) is None

    fake.cover_status = 307
    real = fake.__call__

    def evil(url, params, accept):                                   # a redirect to somewhere else is refused, not followed
        if url.startswith(metadata.CAA):
            return httpx.Response(307, headers={"location": "https://evil.example/cover.png"}, request=httpx.Request("GET", url))
        return real(url, params, accept)

    def internal(url, params, accept):
        if url.startswith(metadata.CAA):
            return httpx.Response(307, headers={"location": "http://169.254.169.254/latest/meta-data"}, request=httpx.Request("GET", url))
        return real(url, params, accept)

    def lookalike(url, params, accept):
        return httpx.Response(307, headers={"location": "https://archive.org.evil.example/x.png"}, request=httpx.Request("GET", url))

    for hostile in (evil, internal, lookalike):
        metadata._send = hostile
        with pytest.raises(metadata.MetadataError):
            metadata.cover(REL)


def test_a_cover_that_is_not_an_image_or_too_big_is_refused(fake, monkeypatch):
    fake.cover = b"<html>nope</html>"
    real = fake.__call__

    def not_image(url, params, accept):
        r = real(url, params, accept)
        return httpx.Response(200, content=r.content, headers={"content-type": "text/html"}, request=r.request) if r.status_code == 200 else r

    monkeypatch.setattr(metadata, "_send", not_image)
    with pytest.raises(metadata.MetadataError):
        metadata.cover(REL)
    monkeypatch.setattr(metadata, "MAX_COVER", 10)
    monkeypatch.setattr(metadata, "_send", real)
    fake.cover = png(5)
    with pytest.raises(metadata.MetadataError):
        metadata.cover(REL)


def test_requests_are_spaced_out_and_retried_politely(monkeypatch):
    sleeps = []
    monkeypatch.setattr(metadata, "_sleep", sleeps.append)
    metadata._last[0] = 0.0
    answers = iter([503, 200])
    monkeypatch.setattr(metadata, "_send", lambda u, p, a: httpx.Response(next(answers), json={"releases": []}, request=httpx.Request("GET", u)))
    metadata.search("x")                                     # first try 503, second 200: one retry with a pause
    assert sleeps and all(s > 0 for s in sleeps)
    sleeps.clear()
    monkeypatch.setattr(metadata, "_send", lambda u, p, a: httpx.Response(200, json={"releases": []}, request=httpx.Request("GET", u)))
    metadata.search("a")
    metadata.search("b")                                     # straight after the previous one: it has to wait about a second
    assert any(0.5 < s <= metadata.MIN_INTERVAL for s in sleeps)


def test_a_busy_service_is_waited_for_as_long_as_it_asks(monkeypatch):
    sleeps = []
    monkeypatch.setattr(metadata, "_sleep", sleeps.append)
    metadata._last[0] = 0.0
    seen = []

    def send(u, p, a):
        seen.append(1)
        if len(seen) < 4:                                      # busy three times, with a Retry-After that grows, then fine
            return httpx.Response(503, headers={"retry-after": str(len(seen) * 2)}, json={"error": "busy"}, request=httpx.Request("GET", u))
        return httpx.Response(200, json={"releases": []}, request=httpx.Request("GET", u))

    monkeypatch.setattr(metadata, "_send", send)
    assert metadata.search("busy day") == [] and len(seen) == 4
    waits = [s for s in sleeps if s >= 1.5]
    assert waits[:3] == [2.2, 4.2, 6.2]                          # it waited what was asked (plus a little), not a fixed pause
    seen.clear()
    monkeypatch.setattr(metadata, "_send", lambda u, p, a: seen.append(1) or httpx.Response(503, request=httpx.Request("GET", u)))
    with pytest.raises(metadata.MetadataError, match="busy right now"):                    # still busy after every try: a clear message
        metadata.search("never works")
    assert len(seen) == metadata.ATTEMPTS
    assert metadata._retry_wait(httpx.Response(503, headers={"retry-after": "9999"}, request=httpx.Request("GET", "x")), 0) <= 8.2     # never an endless wait


def test_answers_are_kept_for_a_while(fake):
    metadata.search("Same Album", "Same Artist")
    metadata.search("same album", "SAME ARTIST")                # same question, any capitalisation
    metadata.release(REL)
    metadata.release(REL)
    metadata.cover(REL)
    n = len(fake.calls)
    metadata.cover(REL)
    assert [c["url"] for c in fake.calls].count(f"{metadata.MB}/release/") == 1 and [c["url"] for c in fake.calls].count(f"{metadata.MB}/release/{REL}") == 1
    assert len(fake.calls) == n                                  # the second cover came from memory
    fake.cover_status = 404
    metadata._cache.clear()
    assert metadata.cover(REL) is None
    fake.cover_status = 307
    assert metadata.cover(REL) == fake.cover                     # a missing cover is not remembered, so one added later is found
    metadata.search("A different album")
    assert [c["url"] for c in fake.calls].count(f"{metadata.MB}/release/") == 2


def test_failures_become_readable_errors(monkeypatch):
    monkeypatch.setattr(metadata, "_sleep", lambda s: None)
    monkeypatch.setattr(metadata, "_send", lambda u, p, a: (_ for _ in ()).throw(httpx.ConnectError("down")))
    with pytest.raises(metadata.MetadataError, match="Could not reach"):
        metadata.search("x")
    monkeypatch.setattr(metadata, "_send", lambda u, p, a: httpx.Response(500, request=httpx.Request("GET", u)))
    with pytest.raises(metadata.MetadataError, match="answered 500"):
        metadata.search("x")
    monkeypatch.setattr(metadata, "_send", lambda u, p, a: httpx.Response(200, content=b"not json", request=httpx.Request("GET", u)))
    with pytest.raises(metadata.MetadataError, match="unexpected"):
        metadata.search("x")


def test_matching_copes_with_a_missing_track_and_odd_titles():
    local = [{"id": i, "title": t, "duration": d} for i, (t, d) in enumerate(
        [("Intro", 40), ("Song One", 180), ("Song Two", 200), ("Song Four", 210), ("Outro", 60)], 1)]
    remote = [metadata.RemoteTrack(1, n, str(n), t, d) for n, (t, d) in enumerate(
        [("Intro", 41), ("Song One", 181), ("Song Two", 199), ("Song Three", 300), ("Song Four", 211), ("Outro", 61)], 1)]
    m = metadata.match_tracks(local, remote)
    assert m == {1: 0, 2: 1, 3: 2, 4: 4, 5: 5}                                           # "Song Three" has no counterpart here
    renamed = [{"id": 1, "title": "01 - the kings tax return.mp3", "duration": 100}, {"id": 2, "title": "Zzzz", "duration": 5}]
    rem = [metadata.RemoteTrack(1, 1, "1", "The King's Tax Return", 100), metadata.RemoteTrack(1, 2, "2", "Completely Different", 400)]
    assert metadata.match_tracks(renamed, rem) == {1: 0}                                 # a number prefix does not matter; nonsense stays unmatched


def test_nothing_personal_goes_out_with_a_lookup(client, album, fake):
    aid, _ = album
    client.get(f"/albums/{aid}/lookup", params={"q": "Hello", "artist": "World", "run": 1})
    client.get(f"/albums/{aid}/lookup/{REL}")
    assert fake.calls and all(c["ua"] == f"Drollery/{__version__}" for c in fake.calls)                  # a generic client name, no contact details
    assert fake.calls[0]["params"] == {"query": 'release:"Hello" AND artist:"World"', "fmt": "json", "limit": 8}
    sent = repr(fake.calls)
    for secret in ("@", "My Satire Album", "Opening Fanfare", "mp3", "admin"):
        assert secret not in sent, secret


# ----------------------------------------------------------------- in the app

def test_search_page_lists_results_and_escapes_them(client, album, fake):
    aid, _ = album
    page = client.get(f"/albums/{aid}/lookup", params={"run": 1})
    assert page.status_code == 200 and 'value="My Satire Album"' in page.text and 'value="Someone"' in page.text          # prefilled from the album
    assert "Satire Hits (Deluxe)" in page.text and "Royal Records" in page.text and "Tracks: 4 online, 3 here" in page.text
    assert f'href="/albums/{aid}/lookup/{REL}"' in page.text
    assert "<script>alert(1)</script>" not in page.text and "&lt;script&gt;" in page.text                              # scraped text is never trusted
    plain = client.get(f"/albums/{aid}/lookup")
    assert plain.status_code == 200 and not fake.calls[1:] and "Matching releases" not in plain.text                   # opening the page searches nothing


def test_search_errors_and_empty_results_are_shown(client, album, fake):
    aid, _ = album
    fake.fail = httpx.ConnectError("offline")
    assert "Could not reach the lookup service" in client.get(f"/albums/{aid}/lookup", params={"run": 1}).text
    fake.fail = None
    assert "Enter an album title or an artist" in client.get(f"/albums/{aid}/lookup", params={"run": 1, "q": "", "artist": ""}).text


def test_preview_shows_what_would_change_and_changes_nothing(client, album, fake):
    aid, tracks = album
    with db.tx() as c:
        before = (db.get_item(c, aid)["title"], [t["title"] for t in albums.tracks_of(c, aid)])
    page = client.get(f"/albums/{aid}/lookup/{REL}")
    assert page.status_code == 200
    for text in ("Satire Hits (Deluxe)", "Royal Records", "Opening Fanfare (Remastered)"):
        assert text in page.text
    assert "Bonus: The Fool" not in page.text                                            # the fourth online track has no local counterpart
    assert f'name="track_{tracks[0]["id"]}"' in page.text and f'/albums/{aid}/lookup/{REL}/cover' in page.text
    assert 'id="pick-all"' in page.text and 'name="tracks"' not in page.text                  # one "All" box in the table head, no separate master switch
    with db.tx() as c:
        assert (db.get_item(c, aid)["title"], [t["title"] for t in albums.tracks_of(c, aid)]) == before


def test_applying_everything(client, album, fake):
    aid, tracks = album
    r = client.post(f"/albums/{aid}/lookup/{REL}", data={"title": "1", "artist": "1", "details": "1", "cover": "1", "tracks": "1",
                                                          **{f"track_{t['id']}": "1" for t in tracks}})
    assert r.status_code == 200 and "Details taken over from MusicBrainz" in r.text
    with db.tx() as c:
        item, info, now = db.get_item(c, aid), albums.get(c, aid), albums.tracks_of(c, aid)
    assert item["title"] == "Satire Hits (Deluxe)" and item["title_locked"] == 1 and item["source_url"] == f"https://musicbrainz.org/release/{REL}"
    assert (info["artist"], info["year"], info["label"], info["mbid"]) == ("The Court Jesters", "1999", "Royal Records", REL)
    assert [t["title"] for t in now] == ["Opening Fanfare (Remastered)", "The King's Tax Return", "Ballad of the Cheese Wizard"]
    assert [t["id"] for t in now] == [t["id"] for t in tracks]                           # same tracks, same order, shares keep working
    page = client.get(f"/items/{aid}").text
    assert 'id="details"' in page and f'href="https://musicbrainz.org/release/{REL}"' in page and "Look up details online" in page
    for text in ("Release date", "1999-05-01", "Original release", "1995-03-02", "Record label", "Royal Records", "Catalog number", "RR 4711", "Country", ">DE<",
                 "Format", ">CD<", "Album · Compilation · Live", "Genres", "Language", "English", "Barcode", "4012345678905"):
        assert text in page, text
    assert "<b>comedy</b>" not in page and "&lt;b&gt;comedy&lt;/b&gt;" in page                  # scraped text is escaped
    assert f'href="/?q=satire"' in page                                                          # a genre leads to the library search
    with db.tx() as c:
        assert albums.facts(albums.get(c, aid))["tracks"] == 4
    for q in ("RR 4711", "satire", "4012345678905"):                                              # the new facts are searchable
        assert f'href="/items/{aid}' in client.get("/", params={"q": q}).text, q
    assert f'href="/items/{aid}' in client.get("/", params={"q": "Remastered"}).text and f'href="/items/{aid}' in client.get("/", params={"q": "royal records"}).text


def test_the_details_panel_is_for_albums_that_have_details(client, album, fake):
    aid, _ = album
    page = client.get(f"/items/{aid}").text                                                      # nothing was looked up yet: only what the album itself knows
    box = page.split('id="details"')[1].split("</section>")[0]
    assert "<dd>Album</dd>" in box and "<dt>Tracks</dt><dd>3 tracks</dd>" in box and "<dt>Duration</dt>" in box and "<dt>Size</dt>" in box and " MB</dd>" in box
    for lookup_only in ("Release date", "Record label", "Catalog number", "Genres", "Barcode", "MusicBrainz"):
        assert lookup_only not in box
    assert "<span>3 tracks</span>" not in page and "3 tracks" not in page.split('class="meta-line"')[1].split("</p>")[0]          # no longer under the cover
    with db.tx() as c:                                                                           # an album looked up in the first version: only year and label
        c.execute("UPDATE albums SET year='1987', label='Old Label', mbid=? WHERE item_id=?", (REL, aid))
    page = client.get(f"/items/{aid}").text
    assert 'id="details"' in page and "1987" in page and "Old Label" in page and "Catalog number" not in page and "Genres" not in page
    with db.tx() as c:
        c.execute("UPDATE albums SET details='{broken' WHERE item_id=?", (aid,))
        assert albums.facts(albums.get(c, aid))["date"] == "1987"                                # damaged details do not break the page
    assert client.get(f"/items/{aid}").status_code == 200


def test_country_and_language_codes_are_shown_in_words(client, album, fake):
    aid, _ = album
    import json
    for country, shown in (("XW", "Worldwide"), ("XE", "Europe"), ("GB", ">GB<")):
        with db.tx() as c:
            c.execute("UPDATE albums SET details=?, mbid=? WHERE item_id=?", (json.dumps({"country": country, "language": "deu"}), REL, aid))
        page = client.get(f"/items/{aid}").text
        assert shown in page and "<dd>Deutsch</dd>" in page
    with db.tx() as c:
        c.execute("UPDATE albums SET details=? WHERE item_id=?", (json.dumps({"language": "mul"}), aid))
    assert "<dt>Language</dt>" not in client.get(f"/items/{aid}").text                           # "multiple languages" says nothing


def test_the_review_page_lists_the_release_details(client, album, fake):
    aid, _ = album
    page = client.get(f"/albums/{aid}/lookup/{REL}").text
    assert "Release details" in page and "RR 4711" in page and "Album, Compilation, Live" in page and "&lt;b&gt;comedy&lt;/b&gt;" in page


def test_applying_only_what_was_ticked(client, album, fake):
    aid, tracks = album
    with db.tx() as c:
        before = (db.get_item(c, aid)["title"], albums.get(c, aid)["artist"], [t["title"] for t in albums.tracks_of(c, aid)])
    client.post(f"/albums/{aid}/lookup/{REL}", data={"artist": "1"})
    with db.tx() as c:
        assert (db.get_item(c, aid)["title"], [t["title"] for t in albums.tracks_of(c, aid)]) == (before[0], before[2])
        assert albums.get(c, aid)["artist"] == "The Court Jesters" and albums.get(c, aid)["year"] == ""
    # only the first track: the master box is on, one row ticked
    client.post(f"/albums/{aid}/lookup/{REL}", data={"tracks": "1", f"track_{tracks[0]['id']}": "1"})
    with db.tx() as c:
        titles = [t["title"] for t in albums.tracks_of(c, aid)]
    assert titles[0] == "Opening Fanfare (Remastered)" and titles[1:] == before[2][1:]
    nothing = client.post(f"/albums/{aid}/lookup/{REL}", data={})
    assert "nothing changed" in nothing.text


def test_ticking_all_tracks_and_none(client, album, fake):
    aid, tracks = album
    with db.tx() as c:
        before = [t["title"] for t in albums.tracks_of(c, aid)]
    client.post(f"/albums/{aid}/lookup/{REL}", data={"artist": "1"})                      # no track box ticked: no track is renamed
    with db.tx() as c:
        assert [t["title"] for t in albums.tracks_of(c, aid)] == before
    client.post(f"/albums/{aid}/lookup/{REL}", data={f"track_{t['id']}": "1" for t in tracks})   # every box ticked (what "All" does), no other field
    with db.tx() as c:
        assert [t["title"] for t in albums.tracks_of(c, aid)] == ["Opening Fanfare (Remastered)", "The King's Tax Return", "Ballad of the Cheese Wizard"]


def test_the_all_box_is_not_offered_when_nothing_matches(client, album, fake, monkeypatch):
    aid, _ = album
    monkeypatch.setattr(metadata, "match_tracks", lambda local, remote: {})
    page = client.get(f"/albums/{aid}/lookup/{REL}").text
    assert 'id="pick-all"' not in page and "have no match online" in page


def test_a_forged_track_id_cannot_rename_someone_elses_track(client, mp3s, album, fake):
    aid, tracks = album
    upload(client, [mp3s["art"]])
    other = album_id(client)
    with db.tx() as c:
        foreign = albums.tracks_of(c, other)[0]
    client.post(f"/albums/{aid}/lookup/{REL}", data={"tracks": "1", f"track_{foreign['id']}": "1", "track_999999": "1"})
    with db.tx() as c:
        assert albums.tracks_of(c, other)[0]["title"] == foreign["title"]


def test_a_new_cover_replaces_the_old_one_and_resets_a_custom_crop(client, album, fake):
    aid, _ = album
    with db.tx() as c:
        item = db.get_item(c, aid)
    assert not item["has_thumb"]                                                         # these test files carry no picture
    client.post(f"/albums/{aid}/lookup/{REL}", data={"cover": "1"})
    cover = albums.cover_path(item)
    assert cover.exists() and client.get(f"/albums/{aid}/cover").status_code == 200 and client.get(f"/thumb/{aid}").status_code == 200
    client.post(f"/items/{aid}/card", data={"t": 0, "x": 0, "y": 0, "s": 0.5})
    with db.tx() as c:
        assert db.get_item(c, aid)["has_card"] == 1
    fake.cover = png(200)
    metadata._cache.clear()                                                              # (answers are remembered for a while)
    client.post(f"/albums/{aid}/lookup/{REL}", data={"cover": "1"})
    with db.tx() as c:
        assert db.get_item(c, aid)["has_card"] == 0                                      # the crop belonged to the old picture
    assert client.get(f"/card/{aid}").status_code == 404
    fake.cover_status = 404                                                              # a release without a cover changes nothing
    metadata._cache.clear()
    r = client.post(f"/albums/{aid}/lookup/{REL}", data={"cover": "1"})
    assert "nothing changed" in r.text


def test_the_cover_preview_passes_through_the_server(client, album, fake):
    aid, _ = album
    r = client.get(f"/albums/{aid}/lookup/{REL}/cover")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == fake.cover
    fake.cover_status = 404
    metadata._cache.clear()
    assert client.get(f"/albums/{aid}/lookup/{REL}/cover").status_code == 404
    assert client.get(f"/albums/{aid}/lookup/not-a-release/cover").status_code == 502


def test_a_bad_release_id_or_a_failed_lookup_goes_back_with_a_message(client, album, fake):
    aid, _ = album
    r = client.get(f"/albums/{aid}/lookup/not-a-release")
    assert r.status_code == 200 and "not a valid release" in r.text and "Look up details online" in r.text
    fake.fail = httpx.ConnectError("offline")
    r = client.post(f"/albums/{aid}/lookup/{REL}", data={"title": "1"})
    assert "Could not reach the lookup service" in r.text


def test_the_form_box_leads_to_the_lookup(client, mp3s, fake):
    assert upload(client, [mp3s["one"]]).status_code == 200
    r = client.post("/albums", files=[("files", ("a.mp3", mp3s["two"].read_bytes(), "audio/mpeg"))], data={"lookup": "1"}, follow_redirects=False)
    aid = album_id(client)
    assert r.status_code == 303 and r.headers["location"] == f"/albums/{aid}/lookup?run=1"
    r = client.post("/albums", files=[("files", ("b.mp3", mp3s["three"].read_bytes(), "audio/mpeg"))], data={}, follow_redirects=False)
    assert r.headers["location"] == f"/items/{album_id(client)}"
    form = client.get("/albums/new").text
    assert 'name="lookup"' in form and "Only the album title and artist are sent" in form
    # opting in to an album that is already there goes nowhere: nothing new was created
    again = client.post("/albums", files=[("files", ("a.mp3", mp3s["two"].read_bytes(), "audio/mpeg"))], data={"lookup": "1"}, follow_redirects=False)
    assert again.headers["location"] == f"/items/{aid}"


def test_the_lookup_can_be_switched_off(client, album, fake, monkeypatch):
    aid, _ = album
    monkeypatch.setattr(get_settings(), "metadata_lookup", False)
    assert client.get(f"/albums/{aid}/lookup", params={"run": 1}).status_code == 404
    assert client.get(f"/albums/{aid}/lookup/{REL}").status_code == 404 and client.post(f"/albums/{aid}/lookup/{REL}", data={"title": "1"}).status_code == 404
    assert "Look up details online" not in client.get(f"/items/{aid}").text and 'name="lookup"' not in client.get("/albums/new").text
    assert not fake.calls


def test_only_albums_and_only_signed_in_people_can_look_up(client, anon, album, fake):
    from test_share import make_item
    img = make_item(client)
    assert client.get(f"/albums/{img}/lookup", params={"run": 1}).status_code == 404 and client.get("/albums/99999/lookup").status_code == 404
    aid, _ = album
    assert anon.get(f"/albums/{aid}/lookup").status_code == 303 and anon.post(f"/albums/{aid}/lookup/{REL}", data={}).status_code in (303, 401)
    assert not fake.calls


def test_an_older_database_gets_the_new_album_columns(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "old.db")
    con.row_factory = sqlite3.Row
    con.executescript("CREATE TABLE albums (item_id INTEGER PRIMARY KEY, artist TEXT NOT NULL DEFAULT '', subtype TEXT NOT NULL DEFAULT 'album');"
                      "INSERT INTO albums(item_id, artist) VALUES (1, 'x');")
    db._migrate_albums(con)
    row = con.execute("SELECT * FROM albums").fetchone()
    assert (row["year"], row["label"], row["mbid"], row["details"]) == ("", "", "", "") and row["artist"] == "x"


def test_the_basics_sit_in_the_details_box_in_the_right_order(client, mp3s):
    from test_album import make_mp3
    upload(client, [mp3s["one"], mp3s["two"]], subtype="audiobook")
    aid = album_id(client)
    box = client.get(f"/items/{aid}").text.split('id="details"')[1].split("</section>")[0]
    order = [box.index(x) for x in ("<dt>Type</dt>", "<dt>Chapters</dt>", "<dt>Duration</dt>", "<dt>Size</dt>")]
    assert order == sorted(order) and "<dd>Audiobook</dd>" in box and "<dd>2 chapters</dd>" in box
    with db.tx() as c:                                                                           # after a lookup the release's own type replaces the plain one, with no second "Type" row
        c.execute("UPDATE albums SET details=?, mbid=? WHERE item_id=?", ('{"type": ["Album", "Live"], "date": "1999"}', REL, aid))
    box = client.get(f"/items/{aid}").text.split('id="details"')[1].split("</section>")[0]
    assert box.count("<dt>Type</dt>") == 1 and "<dd>Album · Live</dd>" in box and "<dt>Release date</dt>" in box


# ------------------------------------------------------------ the popup windows on the album page

def test_lookup_and_card_image_open_in_a_popup(client, album):
    album = album[0]
    page = client.get(f"/items/{album}").text
    assert f'href="/albums/{album}/lookup?run=1" data-popup=' in page
    assert 'id="popup-dialog"' in page and "/static/popup.js" in page


def test_a_framed_page_has_no_header_and_ends_by_telling_the_page_behind(client, album):
    album = album[0]
    framed = {"Sec-Fetch-Dest": "iframe"}
    lookup = client.get(f"/albums/{album}/lookup", headers=framed).text
    assert '<body class="embed">' in lookup
    assert '<body class="embed">' not in client.get(f"/albums/{album}/lookup").text
    done = client.get(f"/items/{album}", headers=framed).text                    # where Cancel and Save lead
    assert "drollery-done" in done and "tracklist" not in done
    assert "tracklist" in client.get(f"/items/{album}").text                    # opened normally it is still the album page


def test_the_popup_cookie_frames_pages_too(client, album):
    """Browsers send no frame header over plain http, so the popup marks its requests with a cookie."""
    album = album[0]
    assert '<body class="embed">' in client.get(f"/albums/{album}/lookup", cookies={"drollery_embed": "1"}).text
    assert "drollery-done" in client.get(f"/items/{album}", cookies={"drollery_embed": "1"}).text
