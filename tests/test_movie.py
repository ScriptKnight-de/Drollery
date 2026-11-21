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


TMDB_KEY = "0123456789abcdef0123456789abcdef"
TMDB_SEARCH = {"results": [
    {"media_type": "movie", "id": 603, "title": "Das Leben des Brian", "original_title": "Monty Quest's Life of Gwyn", "release_date": "1979-11-17",
     "overview": "Ein Mann wird fuer einen Messias gehalten. " * 6, "poster_path": "/poster.jpg"},
    {"media_type": "tv", "id": 1399, "name": "Die erfundene Serie", "original_name": "Die erfundene Serie", "first_air_date": "2011-04-17", "overview": "x"},
    {"media_type": "person", "id": 5, "name": "Not a title"},
    {"media_type": "movie", "id": "bad", "title": "Broken"},
]}
TMDB_MOVIE = {"id": 603, "title": "Das Leben des Brian", "original_title": "Monty Quest's Life of Gwyn", "release_date": "1979-11-17", "runtime": 94,
              "overview": "Ein Mann wird aus Versehen fuer einen Messias gehalten.", "genres": [{"id": 35, "name": "Komoedie"}, {"id": 12, "name": "Abenteuer"}],
              "spoken_languages": [{"english_name": "English", "name": "Englisch"}], "production_countries": [{"name": "Vereinigtes Koenigreich"}],
              "vote_average": 7.84, "vote_count": 5000, "poster_path": "/poster.jpg", "imdb_id": TT,
              "credits": {"cast": [{"name": f"Darsteller {n}"} for n in range(12)], "crew": [{"name": "Cy Director", "job": "Director"}, {"name": "Wanda Writer", "job": "Writer"}]},
              "external_ids": {"imdb_id": TT}}


class Fake:
    def tmdb(self, path, params, req):
        self.tmdb_calls.append({"path": path, "params": dict(params)})
        if params.get("api_key") != TMDB_KEY:
            return httpx.Response(401, json={"status_message": "Invalid API key"}, request=req)
        if path == "/search/multi":
            return httpx.Response(200, json=TMDB_SEARCH, request=req)
        if path == f"/find/{TT}":
            return httpx.Response(200, json={"movie_results": [{"id": 603}], "tv_results": []}, request=req)
        if path.startswith("/find/"):
            return httpx.Response(200, json={"movie_results": [], "tv_results": []}, request=req)
        if path == "/movie/603":
            return httpx.Response(200, json=self.tmdb_movie, request=req)
        if path == "/movie/999":                                           # known to TMDB only: no IMDb id
            return httpx.Response(200, json={**self.tmdb_movie, "id": 999, "imdb_id": "", "external_ids": {}, "title": "Nur TMDB"}, request=req)
        if path == "/tv/1399":
            return httpx.Response(200, json={"id": 1399, "name": "Die erfundene Serie", "first_air_date": "2011-04-17", "episode_run_time": [55], "created_by": [{"name": "Serien Macher"}],
                                             "genres": [{"name": "Drama"}], "overview": "Serie", "vote_count": 0, "external_ids": {"imdb_id": ""}, "credits": {}}, request=req)
        return httpx.Response(404, json={}, request=req)

    def __init__(self):
        self.tmdb_calls = []
        self.tmdb_movie = TMDB_MOVIE
        self.calls = []
        self.omdb = OMDB
        self.omdb_status = 200
        self.poster = png(77)

    def __call__(self, url, params, accept):
        self.calls.append({"url": url, "params": dict(params or {}), "ua": metadata.user_agent()})
        req = httpx.Request("GET", url)
        if url.startswith(imdb.SUGGEST):
            q = url.rsplit("/", 1)[1].removesuffix(".json")
            body = SUGGEST if "quest" in q.lower() or q in (TT, "tt0000999") else {"d": []}
            return httpx.Response(200, json=body, request=req)
        if url == imdb.OMDB:
            return httpx.Response(self.omdb_status, json=self.omdb, request=req)
        if url.startswith(imdb.TMDB):
            return self.tmdb(url[len(imdb.TMDB):], params or {}, req)
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
    assert 'value="movie"' in page and "Movies" in page
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

def test_search_reads_the_suggestion_service_and_skips_things_that_are_not_titles(client, fake):
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


# ------------------------------------------------------------ sharing

def share_movie(client, clip_bytes, **data):
    add(client, clip_bytes, **data)
    mid = movie_id(client)
    page = client.post(f"/items/{mid}/shares", data={"preset": "7d", "label": "for a friend"}).text
    token = re.search(r"/s/([\w-]{8,})", page).group(1)
    return mid, token


def test_a_movie_can_be_shared_with_a_public_link(client, clip_bytes):
    mid, token = share_movie(client, clip_bytes, title="Spaced Balls", subtype="parody", original_title="Space Quest", description="Mel makes fun")
    from fastapi.testclient import TestClient
    from drollery.main import app
    guest = TestClient(app, follow_redirects=False)                                  # no login
    page = guest.get(f"/s/{token}")
    assert page.status_code == 200 and "<video" in page.text and "Spaced Balls" in page.text and "Mel makes fun" in page.text
    assert "Parody · Space Quest" not in page.text and "Parody" in page.text and "Original film: Space Quest" in page.text
    assert 'property="og:type" content="video.other"' in page.text and 'property="og:video:type" content="video/mp4"' in page.text
    raw = re.search(r'<video src="(/s/[^"]+)"', page.text).group(1)
    assert guest.get(raw).status_code == 200 and guest.get(raw).headers["content-type"] == "video/mp4"
    part = guest.get(raw, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100                       # a viewer can seek in a long film
    assert guest.get(raw + "?download=1").headers["content-disposition"].startswith("attachment")


def test_the_public_page_shows_the_type_year_and_original_but_never_the_tags_or_people(client, clip_bytes, fake):
    client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    mid, token = share_movie(client, clip_bytes, title="Mine", subtype="synchro", tags="secret-tag")
    client.post(f"/movies/{mid}/lookup/{TT}", data={"details": "1"})
    client.post("/people", data={"name": "Private Person", "item": mid})
    page = client.get(f"/s/{token}").text
    assert "Synchro (dub)" in page and "1987" in page and "Original film: The Invented Quest" in page
    assert "secret-tag" not in page and "Private Person" not in page and "abc12345" not in page


def test_a_plain_movie_share_has_no_facts_line_and_other_kinds_are_unchanged(client, clip_bytes):
    mid, token = share_movie(client, clip_bytes, title="Plain")
    page = client.get(f"/s/{token}").text
    assert "Original film" not in page and ">Movie" in page
    clip = client.post("/api/v1/items", files={"file": ("clip.mp4", clip_bytes, "video/mp4")}).json()["id"]
    cpage = client.get("/s/" + re.search(r"/s/([\w-]{8,})", client.post(f"/items/{clip}/shares", data={"preset": "7d"}).text).group(1)).text
    assert "<video" in cpage and "Original film" not in cpage and "text-muted small" not in cpage


def test_the_poster_is_the_link_preview_of_a_shared_movie(client, clip_bytes, fake):
    mid, token = share_movie(client, clip_bytes, title="Mine")
    plain = client.get(f"/s/{token}/thumb").content
    client.post(f"/movies/{mid}/lookup/{TT}", data={"poster": "1"})
    page = client.get(f"/s/{token}").text
    assert 'property="og:image"' in page and f'poster="/s/{token}/thumb"' in page
    poster = client.get(f"/s/{token}/thumb")
    assert poster.status_code == 200 and poster.headers["content-type"] == "image/jpeg" and poster.content != plain     # the card, not the video frame
    with db.tx() as c:
        card = c.execute("SELECT sha256 FROM items WHERE id=?", (mid,)).fetchone()["sha256"]
    assert poster.content == client.get(f"/card/{mid}").content


def test_an_expired_or_revoked_movie_link_is_gone(client, clip_bytes):
    mid, token = share_movie(client, clip_bytes)
    with db.tx() as c:
        sid = c.execute("SELECT id FROM shares").fetchone()["id"]
    client.post(f"/shares/{sid}/revoke", data={"next": f"/items/{mid}"})
    assert client.get(f"/s/{token}").status_code == 410 and client.get(f"/s/{token}/thumb").status_code == 410


def test_every_item_page_has_a_share_button_that_jumps_to_the_share_panel(client, clip_bytes):
    add(client, clip_bytes)
    page = client.get(f"/items/{movie_id(client)}").text
    bar = page.split('class="toolbar"')[1].split("</div>")[0]
    assert 'href="#share"' in bar and "Share" in bar and 'id="share"' in page


# ------------------------------------------------- the lookup in the language of the tool (TMDB)

def set_language(client, code):
    client.post("/language", data={"language": code, "next": "/"})


def use_tmdb(client, key=TMDB_KEY):
    return client.post("/settings/lookup/tmdb", data={"tmdb_key": key})


def test_the_languages_map_to_tmdbs_codes():
    assert [imdb.locale(c) for c in ("de", "en", "fr", "xx")] == ["de-DE", "en-US", "en-US", "en-US"]      # Drollery speaks English and German


def test_the_tmdb_key_is_checked_stored_and_never_shown(client):
    assert "does not look like a TMDB key" in client.post("/settings/lookup/tmdb", data={"tmdb_key": "short"}).text
    r = use_tmdb(client)
    assert "TMDB key saved" in r.text and TMDB_KEY not in r.text and imdb.has_tmdb()
    page = client.get("/settings/lookup").text
    assert TMDB_KEY not in page and "Movies in your language (TMDB)" in page and "A key is saved. Movies are looked up in English" in page
    assert "key removed" in client.post("/settings/lookup/tmdb", data={"remove": "1"}).text and not imdb.has_tmdb()


def test_without_a_tmdb_key_a_german_tool_says_the_results_are_english(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    set_language(client, "de")
    page = client.get(f"/movies/{mid}/lookup", params={"run": 1, "q": "The Invented Quest"}).text
    assert "Diese Ergebnisse sind auf Englisch" in page and "Deutsch" in page and "The Invented Quest" in page
    set_language(client, "en")
    assert "These results are in English" not in client.get(f"/movies/{mid}/lookup", params={"run": 1, "q": "The Invented Quest"}).text


def test_with_a_tmdb_key_the_search_is_in_the_selected_language(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    set_language(client, "de")
    page = client.get(f"/movies/{mid}/lookup", params={"run": 1, "q": "Brian"}).text
    call = fake.tmdb_calls[0]
    assert call["path"] == "/search/multi" and call["params"]["language"] == "de-DE" and call["params"]["query"] == "Brian"
    assert not any(c["url"].startswith(imdb.SUGGEST) for c in fake.calls)                      # IMDb's English search is not used
    assert "Das Leben des Brian" in page and "(1979)" in page and "Monty Quest&#39;s Life of Gwyn" in page and "Die erfundene Serie" in page
    assert f'href="/movies/{mid}/lookup/m603"' in page and f'href="/movies/{mid}/lookup/t1399"' in page and "Not a title" not in page and "Broken" not in page
    assert "Serie" in page and "These results are in English" not in page and "Diese Ergebnisse sind auf Englisch" not in page
    assert TMDB_KEY not in page


def test_the_language_follows_the_tool_and_answers_are_cached_per_language(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    for code in ("de", "en", "de"):
        set_language(client, code)
        client.get(f"/movies/{mid}/lookup", params={"run": 1, "q": "Brian"})
    assert [c["params"]["language"] for c in fake.tmdb_calls] == ["de-DE", "en-US"]            # the second German search came from the cache


def test_the_review_shows_german_details_with_a_tmdb_rating(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    set_language(client, "de")
    page = client.get(f"/movies/{mid}/lookup/m603").text
    for want in ("Ein Mann wird aus Versehen", "Komoedie, Abenteuer", "Cy Director", "Darsteller 0", "Darsteller 7", "7.8 / 10", "TMDB-Bewertung", "94", "Englisch", "Vereinigtes Koenigreich", "Von TMDB"):
        assert want in page, want
    assert "Darsteller 8" not in page and TMDB_KEY not in page                                  # the cast is cut at eight
    call = next(c for c in fake.tmdb_calls if c["path"] == "/movie/603")
    assert call["params"]["language"] == "de-DE" and call["params"]["append_to_response"] == "credits,external_ids"


def test_an_imdb_id_is_found_on_tmdb_and_keeps_its_imdb_link(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    set_language(client, "de")
    client.post(f"/movies/{mid}/lookup/{TT}", data={"details": "1", "title": "1", "plot": "1"})
    assert any(c["path"] == f"/find/{TT}" for c in fake.tmdb_calls)
    with db.tx() as c:
        item, m = db.get_item(c, mid), movies.get(c, mid)
    assert item["title"] == "Das Leben des Brian" and "Messias" in item["description"] and m["imdb_id"] == TT and item["source_url"] == f"https://www.imdb.com/title/{TT}/"
    f = movies.facts(m)
    assert f["genres"] == ["Komoedie", "Abenteuer"] and f["rating"] == 7.8 and f["rating_source"] == "TMDB" and f["runtime"] == 94
    page = client.get(f"/items/{mid}").text
    assert "<dt>TMDB-Bewertung</dt>" in page and f'href="https://www.imdb.com/title/{TT}/"' in page


def test_an_omdb_key_adds_the_imdb_rating_to_tmdb_details(client, clip_bytes, fake):
    use_tmdb(client)
    client.post("/settings/lookup", data={"omdb_key": "abc12345"})
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    page = client.get(f"/movies/{mid}/lookup/m603").text
    assert "7.9 / 10" in page and "IMDb rating" in page and "TMDB rating" not in page and "Ein Mann wird" in page     # German plot, IMDb's rating
    assert "abc12345" not in page


def test_a_title_tmdb_does_not_know_falls_back_to_imdb(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    page = client.get(f"/movies/{mid}/lookup/tt0000999").text                                # TMDB's find has nothing for this id
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)</script>" not in page


def test_a_title_only_tmdb_knows_is_kept_with_a_tmdb_link(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    client.post(f"/movies/{mid}/lookup/m999", data={"details": "1"})
    with db.tx() as c:
        item, m = db.get_item(c, mid), movies.get(c, mid)
    assert m["imdb_id"] == "" and item["source_url"] == "https://www.themoviedb.org/movie/999"
    page = client.get(f"/items/{mid}").text
    assert 'href="https://www.themoviedb.org/movie/999"' in page and "<dt>Source</dt>" in page


def test_a_series_is_looked_up_too(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    page = client.get(f"/movies/{mid}/lookup/t1399").text
    assert "Serien Macher" in page and "55" in page and "Drama" in page


def test_a_tmdb_reference_needs_the_key_and_only_valid_references_are_accepted(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    assert "no match" in client.get(f"/movies/{mid}/lookup/m603", follow_redirects=True).text          # no key: nothing to ask
    use_tmdb(client)
    for bad in ("m0x", "x603", "603", "tt12", "m1234567890", "tv1"):
        assert "not a valid IMDb title" in client.get(f"/movies/{mid}/lookup/{bad}", follow_redirects=True).text, bad
    assert client.get(f"/movies/{mid}/lookup/../etc").status_code == 404


def test_tmdb_problems_are_explained_without_the_key(client, clip_bytes, fake):
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    use_tmdb(client, "ffffffffffffffffffffffffffffffff")                                              # well formed, but not the key the fake knows
    page = client.get(f"/movies/{mid}/lookup", params={"run": 1, "q": "Brian"}).text
    assert "TMDB did not accept the key" in page and "ffffffffffffffffffffffffffffffff" not in page


def test_the_poster_comes_only_from_the_image_hosts(client, clip_bytes, fake):
    assert imdb._host_ok("https://image.tmdb.org/t/p/w500/x.jpg") and imdb._host_ok("https://m.media-amazon.com/x.jpg")
    assert not imdb._host_ok("https://tmdb.org.evil.example/x.jpg") and not imdb._host_ok("http://image.tmdb.org/x.jpg")


def test_tmdb_is_credited_where_its_data_is_shown(client, clip_bytes, fake):
    credit = "This product uses the TMDB API but is not endorsed or certified by TMDB."
    assert credit in client.get("/settings/lookup").text
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    assert credit in client.get(f"/movies/{mid}/lookup/m603").text


def test_the_scraper_uses_the_language_chosen_for_the_page_on_every_step(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    for code, locale_code, hint in (("de", "de-DE", "Ergebnisse auf Deutsch"), ("en", "en-US", "Results in English")):
        fake.tmdb_calls.clear()
        metadata._cache.clear()
        set_language(client, code)
        page = client.get(f"/movies/{mid}/lookup", params={"run": 1, "q": "Brian"}).text
        client.get(f"/movies/{mid}/lookup/m603")
        client.post(f"/movies/{mid}/lookup/m603", data={"details": "1"})
        assert {c["params"]["language"] for c in fake.tmdb_calls if c["path"] in ("/search/multi", "/movie/603")} == {locale_code}, code
        assert hint in page


def test_missing_translations_are_filled_from_the_english_text(client, clip_bytes, fake):
    use_tmdb(client)
    add(client, clip_bytes, title="Mine")
    mid = movie_id(client)
    original = fake.tmdb_movie
    def by_language(path, params, req):
        fake.tmdb_calls.append({"path": path, "params": dict(params)})
        if path == "/movie/603" and params.get("language") == "de-DE":
            return httpx.Response(200, json={**original, "overview": "", "genres": []}, request=req)     # no German text for this film
        if path == "/movie/603":
            return httpx.Response(200, json={**original, "overview": "An English plot.", "genres": [{"name": "Comedy"}]}, request=req)
        fake.tmdb_calls.pop()                                              # the original records it itself
        return Fake.tmdb(fake, path, params, req)
    fake.tmdb = by_language
    set_language(client, "de")
    page = client.get(f"/movies/{mid}/lookup/m603").text
    assert "An English plot." in page and "Comedy" in page and "Das Leben des Brian" in page            # the title is still the German one
    fake.tmdb_calls.clear()
    metadata._cache.clear()
    set_language(client, "en")
    client.get(f"/movies/{mid}/lookup/m603")
    assert [c["params"]["language"] for c in fake.tmdb_calls if c["path"] == "/movie/603"] == ["en-US"]   # nothing extra to fetch in English
