"""Searching and sorting the library: German spellings, the sort menu, the empty page at the end, the address bar."""
import re

from conftest import pause_workers
from drollery import db, pipeline
from test_app import png


def add(client, title, n, **columns):
    i = client.post("/api/v1/items", files={"file": (f"f{n}.png", png(n % 250), "image/png")}).json()["id"]
    client.patch(f"/api/v1/items/{i}", json={"title": title})
    if columns:
        with db.tx() as c:
            for name, value in columns.items():
                c.execute(f"UPDATE items SET {name}=? WHERE id=?", (value, i))
    return i


def titles(client, **params):
    return [x["title"] for x in client.get("/", params=params).text.split('class="tile"')[1:] and
            [{"title": t} for t in re.findall(r'<span class="t">([^<]*)</span>', client.get("/", params=params).text)]]


# ------------------------------------------------------------ German spellings

def test_either_spelling_of_umlauts_and_sharp_s_finds_the_item(client):
    add(client, "Straße am Meer", 1); add(client, "München Skyline", 2); add(client, "Über den Wolken", 3); add(client, "Mädchen mit Hut", 4)
    add(client, "Maedchen am See", 5)                                                    # written the other way round
    find = lambda q: sorted(titles(client, q=q))
    assert find("Strasse") == ["Straße am Meer"] and find("Straße") == ["Straße am Meer"] and find("strass") == ["Straße am Meer"]
    assert find("Muenchen") == ["München Skyline"] and find("München") == ["München Skyline"] and find("munchen") == ["München Skyline"]
    assert find("Ueber") == ["Über den Wolken"] and find("Uber") == ["Über den Wolken"]
    assert find("Mädchen") == ["Maedchen am See", "Mädchen mit Hut"] and find("Maedchen") == ["Maedchen am See", "Mädchen mit Hut"]
    assert find("wolken hut") == []                                                       # still every word must be there


def test_the_other_spelling_works_in_tags_descriptions_and_track_titles(client, tmp_path):
    i = add(client, "plain", 1)
    client.patch(f"/api/v1/items/{i}", json={"description": "Ein Fußballspiel in Köln", "tags": ["grüße"]})
    for q in ("Fussball", "Koeln", "gruesse"):
        assert titles(client, q=q) == ["plain"], q
    from test_album import make_mp3
    from test_album import upload
    mp3 = make_mp3(tmp_path / "a.mp3", "Süße Träume", 1)
    upload(client, [mp3], title="Plain Album", artist="X")
    assert "Plain Album" in titles(client, q="Suesse Traeume") and "Plain Album" in titles(client, q="süße")


def test_the_words_of_the_helpers():
    assert db.german_forms("Über ÖL Mädchen ok") == "maedchen oel ueber" and db.german_forms("plain") == ""
    assert db.spread("Straße") == "Straße strasse" and db.spread("plain") == "plain" and db.spread("") == ""
    assert db.fts_query("Muenchen straße") == '"Muenchen"* ("straße"* OR "strasse"*)'


def test_an_older_search_index_gets_the_other_spellings_in_the_background(client, monkeypatch):
    from drollery import accounts
    pause_workers(monkeypatch)
    add(client, "Straße am Meer", 1)
    with db.tx() as c:
        c.execute("DELETE FROM items_fts")                                              # how an older version indexed it: the text as it is
        c.execute("INSERT INTO items_fts(rowid,title,description,tags,ai_tags,transcript,source) SELECT id,title,'','','','','' FROM items")
        c.execute("DELETE FROM jobs")
    accounts.set_setting(pipeline.SEARCH_SPELLINGS_DONE, None)
    assert titles(client, q="Strasse") == []
    with db.tx() as c:
        pipeline.plan_upkeep(c)
    job = db.claim_job()
    assert job["type"] == "rebuild_search"
    pipeline.run_job(job)
    assert titles(client, q="Strasse") == ["Straße am Meer"] and accounts.get_setting(pipeline.SEARCH_SPELLINGS_DONE) == "1"
    with db.tx() as c:
        pipeline.plan_upkeep(c)
    assert db.claim_job() is None                                                        # once is enough


def test_an_empty_library_is_marked_without_a_job(client, monkeypatch):
    from drollery import accounts
    pause_workers(monkeypatch)
    accounts.set_setting(pipeline.SEARCH_SPELLINGS_DONE, None)
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
        pipeline.plan_upkeep(c)
    assert accounts.get_setting(pipeline.SEARCH_SPELLINGS_DONE) == "1" and db.claim_job() is None


# --------------------------------------------------------------------- sorting

def test_the_sort_menu_orders_the_library(client):
    a = add(client, "banana", 1, size=300, duration=10, created_at=1000)
    b = add(client, "Äpfel", 2, size=100, duration=None, created_at=3000)
    c_ = add(client, "cherry", 3, size=200, duration=30, created_at=2000)
    order = lambda sort: titles(client, sort=sort)
    assert order("") == ["Äpfel", "cherry", "banana"] and order("new") == ["Äpfel", "cherry", "banana"]    # automatic: newest first
    assert order("old") == ["banana", "cherry", "Äpfel"]
    assert order("title") == ["Äpfel", "banana", "cherry"] and order("title_desc") == ["cherry", "banana", "Äpfel"]    # Ä sorts with A
    assert order("size") == ["banana", "cherry", "Äpfel"]
    assert order("long") == ["cherry", "banana", "Äpfel"]                                            # no duration last
    assert order("nonsense") == order("") and order("best") == order("")                              # unknown, or no search for "best": automatic


def test_sorting_a_search_and_keeping_relevance_as_the_default(client):
    add(client, "wizard", 1, created_at=1000)                                                          # the best match, but the oldest
    old_other = add(client, "something else", 2, created_at=2000)
    client.patch(f"/api/v1/items/{old_other}", json={"description": "a wizard appears here", "tags": []})
    add(client, "wizard hat", 3, created_at=3000)
    assert titles(client, q="wizard")[0] in ("wizard", "wizard hat")                                    # relevance: titles before descriptions
    assert titles(client, q="wizard", sort="old") == ["wizard", "something else", "wizard hat"]
    assert titles(client, q="wizard", sort="new") == ["wizard hat", "something else", "wizard"]
    assert titles(client, q="wizard", sort="best") == titles(client, q="wizard")


def test_the_menu_is_on_the_page_and_kept_for_the_next_page(client):
    add(client, "x", 1)
    page = client.get("/", params={"sort": "title"}).text
    assert 'name="sort"' in page and '<option value="title" selected>' in page and "Sort: automatic" in page
    for n in range(2, 43):
        add(client, f"item {n}", n)
    first = client.get("/", params={"sort": "old"}).text
    assert "sort=old&amp;page=1" in first or "sort=old&page=1" in first                                 # the next page is fetched with the same order


# ------------------------------------------------ the empty page, the address bar

def test_a_page_that_comes_back_empty_adds_nothing(client):
    for n in range(1, 41):
        add(client, f"Bulk {n}", n)
    full = client.get("/", headers={"hx-request": "true"}).text
    assert full.count('class="tile"') == 40 and 'class="more"' in full                                # exactly one page: the next fetch will be empty
    after = client.get("/", params={"page": 1}, headers={"hx-request": "true"}).text
    assert 'class="empty"' not in after and "treasury" not in after and 'class="more"' not in after
    assert 'class="empty"' in client.get("/", params={"q": "nothing like this"}).text                   # the first page still says so


def test_the_address_bar_follows_the_search(client):
    page = client.get("/").text
    assert "/static/searchstate.js" in page
    script = client.get("/static/searchstate.js").text
    assert "replaceState" in script and "FormData" in script
