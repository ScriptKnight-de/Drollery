"""Movies (films, parodies, synchros) and their IMDb lookup, with the network replaced by a fake. Titles here are invented."""
import re

import httpx
import pytest

from drollery import db, imdb, metadata, movies
from test_app import png
from test_card import red_then_blue_video

TT = "tt0000123"
POSTER = "https://m.media-amazon.com/images/M/FAKE.jpg"
SUGGEST = {"d": [
    {"id": TT, "l": "The Invented Quest", "q": "feature", "y": 1987, "s": "Ann Actor, Bob Player", "i": {"imageUrl": POSTER}},
    {"id": "nm0000001", "l": "A Person, not a title", "q": "feature"},                       # not a title id: skipped
    {"id": "tt0000999", "l": "<script>alert(1)</script>", "q": "TV series", "y": 2001, "s": ""},
]}
OMDB = {"Response": "True", "Title": "The Invented Quest", "Year": "1987", "Rated": "PG", "Released": "01 Jan 1987", "Runtime": "94 min",
        "Genre": "Comedy, Adventure", "Director": "Cy Director", "Writer": "Wanda Writer", "Actors": "Ann Actor, Bob Player, Cat Cameo",
        "Plot": "A made-up hero looks for a made-up grail.", "Language": "English, Latin", "Country": "Wales", "Poster": "N/A",
        "imdbRating": "7.9", "imdbVotes": "123,456", "imdbID": TT, "Type": "movie"}


class Fake:
    def __init__(self):
        self.calls = []
        self.omdb = OMDB
        self.omdb_status = 200
        self.poster = png(77)

    def __call__(self, url, params, accept):
        self.calls.append({"url": url, "params": dict(params or {}), "ua": metadata.user_agent()})
        req = httpx.Request("GET", url)
        if url.startswith(imdb.SUGGEST):
            q = url.rsplit("/", 1)[1].removesuffix(".json")
            body = SUGGEST if "quest" in q.lower() or q == TT else {"d": []}
            return httpx.Response(200, json=body, request=req)
        if url == imdb.OMDB:
            return httpx.Response(self.omdb_status, json=self.omdb, request=req)
        if url == POSTER:
            return httpx.Response(200, content=self.poster, headers={"content-type": "image/png"}, request=req)
        return httpx.Response(404, request=req)


@pytest.fixture(autouse=True)
def fresh():
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
def clip_bytes(tmp_path):
    return red_then_blue_video(tmp_path / "film.mp4")


def add(client, clip_bytes, **data):
    return client.post("/movies", files={"file": ("my-film.mp4", clip_bytes, "video/mp4")}, data=data)


def movie_id(client):
    with db.tx() as c:
        return c.execute("SELECT id FROM items WHERE kind='movie'").fetchone()["id"]


# ------------------------------------------------------------- adding

def test_a_movie_is_added_as_one_video_with_its_facts(client, clip_bytes):
    r = add(client, clip_bytes, title="Spaced Balls", subtype="parody", original_title="Space Quest", description="Mel makes fun", tags="satire space")
    assert r.status_code == 200 and "Movie added" in r.text
    mid = movie_id(client)
    with db.tx() as c:
        item, m = db.get_item(c, mid), movies.get(c, mid)
    assert item["kind"] == "movie" and item["title"] == "Spaced Balls" and item["title_locked"] == 1 and item["mime"] == "video/mp4"
    assert (m["subtype"], m["original_title"]) == ("parody", "Space Quest") and sorted(item["tags"]) == ["satire", "space"]
    page = client.get(f"/items/{mid}").text
    assert "<video" in page and "<dt>Type</dt><dd>Parody</dd>" in page and "<dt>Original film</dt><dd>Space Quest</dd>" in page


def test_the_title_comes_from_the_file_name_and_odd_subtypes_become_movie(client, clip_bytes):
    add(client, clip_bytes, subtype="nonsense")
    with db.tx() as c:
        item = db.get_item(c, movie_id(client))
        assert item["title"] == "my-film" and movies.get(c, item["id"])["subtype"] == "movie"


def test_only_a_video_file_can_be_a_movie_and_a_file_is_not_added_twice(client, clip_bytes):
    r = client.post("/movies", files={"file": ("pic.png", png(5), "image/png")}, data={"title": "x"})
    assert r.status_code == 422 and "must be a video" in r.text
    r = client.post("/movies", data={"title": "x"})
    assert r.status_code == 422 and "Choose a video file" in r.text
    add(client, clip_bytes)
    again = add(client, clip_bytes)
    assert "already in the library" in again.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_a_movie_gets_no_automatic_transcription_or_naming(client, clip_bytes):
    add(client, clip_bytes)
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_movies_have_their_own_filter_card_and_add_form(client, clip_bytes):
    add(client, clip_bytes, title="Spaced Balls", subtype="synchro")
    page = client.get("/", params={"kind": "movie"}).text
    assert 'value="movie"' in page and "Movies" in page and "/movies/new" in page
    tile = page.split('class="tile"')[1].split("</a>")[0]
    assert "k-movie" in tile and "Synchro (dub)" in tile and "Spaced Balls" in tile
    assert client.get("/", params={"kind": "video"}).text.count('class="tile"') == 0              # not mixed up with clips
    form = client.get("/movies/new").text
    assert 'name="subtype"' in form and 'accept="video/*"' in form and 'name="lookup"' in form


def test_subtype_and_original_title_can_be_edited_on_the_page(client, clip_bytes):
    add(client, clip_bytes)
    mid = movie_id(client)
    client.post(f"/items/{mid}/edit", data={"title": "T", "description": "", "tags": "", "subtype": "synchro", "original_title": "Old Film"})
    with db.tx() as c:
        m = movies.get(c, mid)
    assert (m["subtype"], m["original_title"]) == ("synchro", "Old Film")
    assert mid in [i["id"] for i in client.get("/api/v1/items", params={"q": "old film"}).json()["items"]]      # found by the film it dubs


def test_a_movie_can_be_shared_and_cropped_like_a_video(client, clip_bytes):
    add(client, clip_bytes)
    mid = movie_id(client)
    assert 'id="snap"' in client.get(f"/items/{mid}/card").text                                    # frame chooser, like a clip
    r = client.post(f"/items/{mid}/card", data={"t": 0.5, "x": 0, "y": 0, "s": 1})
    assert r.status_code == 200 and client.get(f"/card/{mid}").status_code == 200
    assert client.get(f"/items/{mid}/frame", params={"t": 1}).headers["content-type"] == "image/jpeg"


# ---------------------------------------------------------- the lookup

def test_search_reads_the_suggestion_service_and_skips_things_that_are_not_titles(fake):
    found = imdb.search("The Invented Quest")
    assert [c.imdb_id for c in found] == [TT, "tt0000999"]
    first = found[0]
    assert (first.title, first.year, first.kind, first.cast, first.poster) == ("The Invented Quest", "1987", "feature", "Ann Actor, Bob Player", POSTER)
    call = fake.calls[0]
    assert call["url"] == f"{imdb.SUGGEST}/t/The%20Invented%20Quest.json" and call["ua"] == f"Drollery/{__import__('drollery').__version__}"
    assert call["params"] == {}                                                                  # nothing but the title leaves the server
    assert imdb.search("the invented quest") is not None and len(fake.calls) == 1                # answered from the cache


def test_the_search_page_lists_results_escaped(client, clip_bytes, fake):
    add(client, clip_bytes, title="The Invented Quest")
    mid = movie_id(client)
    page = client.get(f"/movies/{mid}/lookup", params={"run": 1}).text
    assert f'href="/movies/{mid}/lookup/{TT}"' in page and "The Invented Quest" in page and "1987" in page and "Ann Actor" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "Add a key" in page                                                                   # no OMDb key yet
    assert client.get(f"/movies/{mid}/lookup").text.count("lookup-pick") == 0                    # nothing is searched until asked


def test_without_a_key_only_the_basics_are_offered(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    page = client.get(f"/movies/{mid}/lookup/{TT}").text
    assert "without an OMDb key" in page and "Ann Actor, Bob Player" in page and 'name="plot"' not in page and 'name="poster"' in page
    assert not any(c["url"] == imdb.OMDB for c in fake.calls)


def test_with_a_key_the_details_come_from_omdb_and_the_key_stays_secret(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    r = client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    assert "OMDb key saved" in r.text and "abc12345" not in r.text
    assert "abc12345" not in client.get("/settings/lookup").text and "A key is saved" in client.get("/settings/lookup").text
    page = client.get(f"/movies/{mid}/lookup/{TT}").text
    for want in ("Cy Director", "Ann Actor, Bob Player, Cat Cameo", "Comedy, Adventure", "7.9 / 10", "94 min", "A made-up hero", 'name="plot"'):
        assert want in page, want
    assert "abc12345" not in page
    call = next(c for c in fake.calls if c["url"] == imdb.OMDB)
    assert call["params"] == {"i": TT, "plot": "full", "apikey": "abc12345"}


def test_a_bad_key_shape_is_refused_and_the_key_can_be_removed(client):
    assert "does not look like" in client.post("/settings/lookup", data={"omdb_key": "bad key!"}).text
    client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    assert imdb.has_key()
    assert "key removed" in client.post("/settings/lookup", data={"remove": "1"}).text and not imdb.has_key()


def test_omdb_problems_are_explained_without_the_key(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    fake.omdb, fake.omdb_status = {"Response": "False", "Error": "Invalid API key!"}, 401
    page = client.get(f"/movies/{mid}/lookup/{TT}", follow_redirects=True).text
    assert "did not accept the key" in page and "abc12345" not in page
    metadata._cache.clear()
    fake.omdb, fake.omdb_status = {"Response": "False", "Error": "Request limit reached!"}, 200
    assert "daily limit" in client.get(f"/movies/{mid}/lookup/{TT}", follow_redirects=True).text


def apply(client, mid, **ticks):
    return client.post(f"/movies/{mid}/lookup/{TT}", data={k: "1" for k in ticks})


def test_applying_takes_over_exactly_what_was_ticked(client, clip_bytes, fake):
    client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    r = apply(client, mid, title=True, plot=True, details=True, poster=True)
    assert "Details taken over from IMDb" in r.text
    with db.tx() as c:
        item, m = db.get_item(c, mid), movies.get(c, mid)
    assert item["title"] == "The Invented Quest" and item["description"] == "A made-up hero looks for a made-up grail."
    assert (m["year"], m["imdb_id"], m["original_title"]) == ("1987", TT, "The Invented Quest") and item["source_url"] == f"https://www.imdb.com/title/{TT}/"
    f = movies.facts(m)
    assert f["directors"] == ["Cy Director"] and f["genres"] == ["Comedy", "Adventure"] and f["rating"] == 7.9 and f["runtime"] == 94 and f["votes"] == 123456
    assert item["has_card"] == 1 and client.get(f"/card/{mid}").status_code == 200              # the poster is the card now
    page = client.get(f"/items/{mid}").text
    assert "<dt>Directors</dt><dd>Cy Director</dd>" in page and "7.9 / 10" in page and f'href="https://www.imdb.com/title/{TT}/"' in page
    assert "Look up on IMDb" in page and 'data-popup="Look up on IMDb"' in page


def test_unticked_parts_stay_as_they_were(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine", description="keep me")
    mid = movie_id(client)
    assert "Nothing was ticked" in apply(client, mid).text
    apply(client, mid, details=True)
    with db.tx() as c:
        item, m = db.get_item(c, mid), movies.get(c, mid)
    assert item["title"] == "Mine" and item["description"] == "keep me" and item["has_card"] == 0 and m["imdb_id"] == TT


def test_a_parody_keeps_its_own_title_and_remembers_the_original(client, clip_bytes, fake):
    add(client, clip_bytes, title="Spaced Balls", subtype="parody")
    mid = movie_id(client)
    page = client.get(f"/movies/{mid}/lookup/{TT}").text
    assert re.search(r'name="title" value="1"\s*>', page)                                        # not pre-ticked for a parody
    apply(client, mid, details=True)
    with db.tx() as c:
        assert db.get_item(c, mid)["title"] == "Spaced Balls" and movies.get(c, mid)["original_title"] == "The Invented Quest"


def test_the_looked_up_facts_make_the_movie_searchable(client, clip_bytes, fake):
    client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    apply(client, mid, details=True)
    found = lambda q: [i["id"] for i in client.get("/api/v1/items", params={"q": q}).json()["items"]]
    for q in ("Cat Cameo", "director", "adventure", "invented", "1987", TT):
        assert found(q) == [mid], q


def test_the_poster_is_passed_through_and_only_from_amazon_hosts(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    r = client.get(f"/movies/{mid}/lookup/{TT}/poster")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert imdb.poster("https://evil.example/x.jpg") is None and imdb.poster("http://m.media-amazon.com/x.jpg") is None
    assert not any("evil" in c["url"] for c in fake.calls)


def test_the_lookup_can_be_switched_off_and_needs_a_valid_id(client, clip_bytes, fake, monkeypatch):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    assert "not a valid IMDb title" in client.get(f"/movies/{mid}/lookup/nm123", follow_redirects=True).text
    from drollery.config import get_settings
    monkeypatch.setattr(get_settings(), "metadata_lookup", False)
    assert client.get(f"/movies/{mid}/lookup").status_code == 404
    assert "Look up on IMDb" not in client.get(f"/items/{mid}").text


def test_the_lookup_only_works_on_movies(client, clip_bytes, fake):
    clip = client.post("/api/v1/items", files={"file": ("clip.mp4", clip_bytes, "video/mp4")}).json()["id"]
    assert client.get(f"/movies/{clip}/lookup").status_code == 404
    assert client.get("/movies/999/lookup").status_code == 404


def test_the_lookup_and_add_pages_need_a_login(client):
    from fastapi.testclient import TestClient
    from drollery.main import app
    v = TestClient(app, follow_redirects=False)
    for method, url in (("get", "/movies/new"), ("post", "/movies"), ("get", "/movies/1/lookup"), ("get", f"/movies/1/lookup/{TT}"),
                        ("post", f"/movies/1/lookup/{TT}"), ("get", "/settings/lookup"), ("post", "/settings/lookup")):
        r = getattr(v, method)(url)
        assert r.status_code in (303, 307) and r.headers["location"] == "/login", (method, url)


def test_the_settings_tab_and_the_old_data_still_work(client):
    page = client.get("/settings/lookup").text
    assert 'href="/settings/lookup" class="on"' in page and "No key yet" in page and "MusicBrainz" in page
