"""The library's one upload zone: what the page offers and how each type reaches the server route it always used."""
import re


from drollery import db
from test_album import make_mp3
from test_app import png
from test_card import red_then_blue_video


def home(client):
    return client.get("/").text


def test_one_zone_replaces_the_four_entry_points(client):
    page = home(client)
    assert page.count('id="uz"') == 1 and "Drop files here, browse, or paste a link" in page and 'id="uz-url"' in page
    visible = re.sub(r"<noscript>.*?</noscript>", "", page, flags=re.S)
    for gone in ('class="add"', "Add an album", "Add a movie", 'href="/albums/new"', 'href="/movies/new"'):
        assert gone not in visible, gone                                                  # no separate buttons any more


def test_without_scripts_the_old_ways_are_still_offered(client):
    noscript = re.search(r"<noscript>(.*?)</noscript>", home(client), re.S).group(1)
    assert 'action="/add"' in noscript and 'href="/albums/new"' in noscript and 'href="/movies/new"' in noscript
    assert client.get("/albums/new").status_code == 200 and client.get("/movies/new").status_code == 200


def test_the_panel_offers_the_three_types_and_the_fields_of_each(client):
    page = home(client)
    panel = page.split('id="uz-form"')[1].split("</form>")[0]
    for value in ("items", "album", "movie"):
        assert f'name="uz-type" value="{value}"' in panel
    for text in ("What should this become?", "Separate items", "Album or audiobook", "Movie, parody or synchro", "Music album", "Audiobook", "Parody", "Synchro (dub)",
                 "Original film", "becomes the cover", "look up the album online", "look the movie up on IMDb"):
        assert text in panel, text
    assert page.count("data-f=\"title\"") == 2 and 'data-for="album"' in panel and 'data-for="movie"' in panel and 'data-for="link"' in panel


def test_the_limits_are_handed_to_the_script_and_the_lookup_boxes_follow_the_switch(client):
    page = home(client)
    assert 'data-max-upload="2048"' in page and 'data-max-movie="16384"' in page and 'data-lookup="1"' in page
    from drollery.config import get_settings
    s = get_settings()
    old = s.metadata_lookup
    s.metadata_lookup = False
    try:
        off = home(client)
    finally:
        s.metadata_lookup = old
    assert 'data-lookup="0"' in off and 'data-f="lookup"' not in off


def test_the_texts_of_the_script_are_translated(client):
    page = home(client)
    assert '"selected": "Selected: {n} \\u00b7 {size}"' in page and '"suggested": "Suggested"' in page
    client.post("/language", data={"language": "de", "next": "/"})
    assert "Was soll daraus werden?" in client.get("/").text and "Vorgeschlagen" in client.get("/").text


# ---- the routes each type goes to (what the script builds is exactly what these forms always sent)

def test_separate_items_go_to_add_as_files(client, tmp_path):
    clip = red_then_blue_video(tmp_path / "f.mp4")
    r = client.post("/add", files=[("files", ("a.png", png(10), "image/png")), ("files", ("b.png", png(20), "image/png")), ("files", ("c.mp4", clip, "video/mp4"))])
    assert r.status_code == 200
    with db.tx() as c:
        assert sorted(x["kind"] for x in c.execute("SELECT kind FROM items")) == ["image", "image", "video"]


def test_an_album_goes_to_albums_with_tracks_cover_and_details(client, tmp_path):
    t1, t2 = make_mp3(tmp_path / "1.mp3", "One", 1), make_mp3(tmp_path / "2.mp3", "Two", 2)
    r = client.post("/albums", files=[("files", ("1.mp3", t1.read_bytes(), "audio/mpeg")), ("files", ("2.mp3", t2.read_bytes(), "audio/mpeg")),
                                       ("cover", ("front.png", png(33), "image/png"))],
                    data={"title": "Frog Opera", "artist": "Kermit", "subtype": "audiobook", "description": "d", "tags": "frog green", "lookup": ""})
    assert r.status_code == 200
    with db.tx() as c:
        item = c.execute("SELECT * FROM items WHERE kind='album'").fetchone()
        album = c.execute("SELECT * FROM albums").fetchone()
    assert item["title"] == "Frog Opera" and album["subtype"] == "audiobook" and album["artist"] == "Kermit" and item["has_thumb"] == 1


def test_a_movie_goes_to_movies_with_one_file_and_its_details(client, tmp_path):
    clip = red_then_blue_video(tmp_path / "f.mp4")
    r = client.post("/movies", files={"file": ("f.mp4", clip, "video/mp4")},
                    data={"title": "Spaced Balls", "original_title": "Space Quest", "subtype": "parody", "description": "", "tags": "space", "lookup": ""})
    assert r.status_code == 200
    with db.tx() as c:
        assert c.execute("SELECT kind FROM items").fetchone()["kind"] == "movie" and c.execute("SELECT subtype FROM movies").fetchone()["subtype"] == "parody"


def test_a_link_goes_to_add_as_a_background_job(client):
    r = client.post("/add", data={"url": "https://example.org/funny.gif"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/jobs"
    with db.tx() as c:
        assert c.execute("SELECT type FROM jobs").fetchone()["type"] == "fetch"


def test_the_script_knows_the_rules_for_what_can_become_what():
    js = open("src/drollery/static/uploader.js").read()
    for rule in ('can.items = !has("zip")', "can.movie = files.length === 1", 'count("image") <= 1', "files[0].size >= MOVIE_HINT", 'target = "/movies"', 'target = "/albums"',
                 'fd.append("cover"', 'fd.append("file", files[0]', "window.drolleryUpload.send"):
        assert rule in js, rule


def test_the_engine_is_loaded_before_the_zone_that_uses_it(client):
    page = home(client)
    assert page.count("/static/upload.js") == 1 and page.count("/static/uploader.js") == 1
    assert page.index("/static/upload.js") < page.index("/static/uploader.js")             # deferred scripts run in this order


def test_the_reason_stays_visible_when_nothing_can_be_added():
    js = open("src/drollery/static/uploader.js").read()
    assert 'note.textContent = limit ? fmt(text.toolarge' in js and ": why;" in js and "why = a.why;" in js          # the explanation is not wiped by the type step


def test_while_uploading_the_panel_shrinks_to_the_summary_and_the_bar():
    css = open("src/drollery/static/style.css").read()
    assert ".uz-panel.uploading > :not(#uz-progress):not(.uz-sum) { display: none; }" in css


def test_the_cancel_button_inside_the_panel_stays_clickable_while_uploading():
    css = open("src/drollery/static/style.css").read()
    assert "form.uploading { opacity: .55; pointer-events: none; }" in css                 # the generic form lock ...
    assert css.rindex(".uz-panel.uploading { opacity: 1; pointer-events: auto; }") > css.index("form.uploading { opacity: .55")    # ... is undone for this panel
