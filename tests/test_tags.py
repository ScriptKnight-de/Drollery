"""The user's tags and the AI's tags are kept strictly apart."""
import re

from drollery import db, pipeline
from test_app import png


def make_item(client, n=1):
    return client.post("/api/v1/items", files={"file": (f"meme{n}.png", png(100 + n), "image/png")}).json()["id"]


def tags(item_id):
    with db.tx() as c:
        item = db.get_item(c, item_id)
    return item["tags"], item["ai_tags"]


def test_user_and_ai_tags_are_reported_separately(client):
    i = make_item(client)
    client.patch(f"/api/v1/items/{i}", json={"tags": ["Mine", "#cats"]})
    with db.tx() as c:
        db.set_ai_tags(c, i, ["feline", "funny"])
    item = client.get(f"/api/v1/items/{i}").json()
    assert item["tags"] == ["cats", "mine"] and item["ai_tags"] == ["feline", "funny"]


def test_editing_your_tags_never_changes_the_ai_tags(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_ai_tags(c, i, ["feline", "funny"])
    client.patch(f"/api/v1/items/{i}", json={"tags": ["mine"]})                          # API
    client.post(f"/items/{i}/edit", data={"title": "t", "description": "", "tags": "mine other"})   # the item page form
    assert tags(i) == (["mine", "other"], ["feline", "funny"])
    client.patch(f"/api/v1/items/{i}", json={"tags": []})                                # clearing yours leaves the AI's
    assert tags(i) == ([], ["feline", "funny"])


def test_rerunning_the_ai_replaces_its_tags_and_leaves_yours(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_user_tags(c, i, ["mine"])
        db.set_ai_tags(c, i, ["one", "two"])
        db.set_ai_tags(c, i, ["three"])
    assert tags(i) == (["mine"], ["three"])                                              # replaced, not accumulated


def test_ai_does_not_duplicate_a_tag_you_already_have(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_user_tags(c, i, ["cats"])
        db.set_ai_tags(c, i, ["cats", "feline"])
    assert tags(i) == (["cats"], ["feline"])


def test_typing_a_tag_the_ai_suggested_promotes_it(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_ai_tags(c, i, ["feline", "funny"])
    client.patch(f"/api/v1/items/{i}", json={"tags": ["feline"]})
    assert tags(i) == (["feline"], ["funny"])                                            # one copy, now yours


def test_keep_and_remove_actions_on_the_item_page(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_ai_tags(c, i, ["feline", "funny", "cursed"])
    client.post(f"/items/{i}/ai-tags/keep", data={"tag": "funny"})
    assert tags(i) == (["funny"], ["cursed", "feline"])
    client.post(f"/items/{i}/ai-tags/remove", data={"tag": "cursed"})
    assert tags(i) == (["funny"], ["feline"])
    client.post(f"/items/{i}/ai-tags/keep")                                              # no tag = all
    assert tags(i) == (["feline", "funny"], [])


def test_a_removed_ai_tag_is_never_suggested_again(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_ai_tags(c, i, ["feline", "cursed"])
    client.post(f"/items/{i}/ai-tags/remove", data={"tag": "cursed"})
    with db.tx() as c:
        db.set_ai_tags(c, i, ["feline", "cursed", "new"])                                # the AI runs again and repeats itself
    assert tags(i) == ([], ["feline", "new"])
    client.patch(f"/api/v1/items/{i}", json={"tags": ["cursed"]})                        # but you may add it yourself, which un-dismisses it
    assert tags(i)[0] == ["cursed"]
    client.patch(f"/api/v1/items/{i}", json={"tags": []})
    with db.tx() as c:
        db.set_ai_tags(c, i, ["cursed"])
    assert tags(i)[1] == ["cursed"]


def test_remove_all_ai_tags_on_an_item(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_user_tags(c, i, ["mine"])
        db.set_ai_tags(c, i, ["a", "b"])
    client.post(f"/items/{i}/ai-tags/remove")
    assert tags(i) == (["mine"], [])
    with db.tx() as c:
        db.set_ai_tags(c, i, ["a", "c"])
    assert tags(i) == (["mine"], ["c"])                                                  # "a" stays dismissed


def test_the_ai_only_learns_vocabulary_from_your_tags(client):
    i, j = make_item(client, 1), make_item(client, 2)
    with db.tx() as c:
        db.set_user_tags(c, i, ["mine", "cats"])
        db.set_ai_tags(c, j, ["robot-noise", "cats"])
        popular = db.popular_tags(c)
    assert sorted(popular) == ["cats", "mine"]                                           # not "robot-noise"


def test_clear_all_ai_tags_in_settings(client):
    i, j = make_item(client, 1), make_item(client, 2)
    with db.tx() as c:
        db.set_user_tags(c, i, ["mine"])
        db.set_ai_tags(c, i, ["a", "b"])
        db.set_ai_tags(c, j, ["c"])
    assert "3 AI tags in the library" in client.get("/settings/ai").text
    r = client.post("/settings/ai/clear-tags")
    assert "Removed 3 AI tags" in r.text and "Your own tags were not touched" in r.text
    assert tags(i) == (["mine"], []) and tags(j) == ([], [])
    assert client.get("/api/v1/items", params={"q": "a"}).json()["items"] == []        # search index follows


# ---------------------------------------------------------------- search

def test_search_finds_both_kinds_ranks_yours_first_and_can_filter_by_source(client):
    mine, ai = make_item(client, 1), make_item(client, 2)
    with db.tx() as c:
        db.set_user_tags(c, mine, ["wizard"])
        db.set_ai_tags(c, ai, ["wizard"])
    hits = [x["id"] for x in client.get("/api/v1/items", params={"q": "wizard"}).json()["items"]]
    assert hits == [mine, ai]                                                            # both found, your tag outranks the AI's
    only_user = client.get("/api/v1/items", params={"tag": "wizard", "tag_source": "user"}).json()["items"]
    only_ai = client.get("/api/v1/items", params={"tag": "wizard", "tag_source": "ai"}).json()["items"]
    either = client.get("/api/v1/items", params={"tag": "wizard"}).json()["items"]
    assert [x["id"] for x in only_user] == [mine] and [x["id"] for x in only_ai] == [ai] and len(either) == 2
    assert only_user[0]["tags"] == ["wizard"] and only_user[0]["ai_tags"] == []


def test_library_filter_pill_says_which_kind_of_tag(client):
    i = make_item(client)
    with db.tx() as c:
        db.set_ai_tags(c, i, ["wizard"])
    page = client.get("/", params={"tag": "wizard", "src": "ai"}).text
    assert "AI tag" in page and "#wizard" in page
    assert client.get("/", params={"tag": "wizard", "src": "user"}).text.count("meme1") == 0     # no user tag "wizard" here


def test_item_page_shows_two_separate_groups(client):
    i = make_item(client)
    client.patch(f"/api/v1/items/{i}", json={"tags": ["mine"]})
    with db.tx() as c:
        db.set_ai_tags(c, i, ["robotic"])
    html = client.get(f"/items/{i}").text
    mine_part = html[html.index("Your tags"):html.index("AI tags")]
    ai_part = html[html.index("AI tags"):html.index("id=\"edit-tile\"")]
    assert "#mine" in mine_part and "#robotic" not in mine_part
    assert "#robotic" in ai_part and "#mine" not in ai_part
    assert f"/items/{i}/ai-tags/keep" in html and f"/items/{i}/ai-tags/remove" in html
    assert "AI tags are kept apart" in html


def test_a_describe_job_writes_ai_tags_only(client, monkeypatch):
    from drollery import accounts, providers
    client.post("/settings/ai/models", data={"name": "m", "type": "openai", "base_url": "http://x/v1", "model": "m", "api_key": "", "command": "",
                                              "langs": "eng", "language": "", "prompt": "", "timeout": 60, "send_image": "1"})
    mid = str(accounts.list_models()[0]["id"])
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": mid})
    monkeypatch.setattr(providers, "describe", lambda *a, **k: {"name": "n", "description": "d", "tags": ["Alpha", "beta"]})
    i = make_item(client)
    client.patch(f"/api/v1/items/{i}", json={"tags": ["mine"]})
    pipeline.run_job(db.claim_job())
    assert tags(i) == (["mine"], ["alpha", "beta"])
    seen = {}
    monkeypatch.setattr(providers, "describe", lambda cfg, image, transcript, existing: seen.setdefault("vocab", list(existing)) and {"name": "", "description": "", "tags": []})
    client.post(f"/items/{i}/reprocess")
    pipeline.run_job(db.claim_job())
    assert seen["vocab"] == ["mine"]                                                     # the vocabulary offered to the AI is yours alone


# ------------------------------------------------------------- migration

def test_an_old_search_index_is_rebuilt_with_the_ai_tags_column(client):
    """A database created before the split has a 6-column index; startup must rebuild it without losing search."""
    i = make_item(client)
    client.patch(f"/api/v1/items/{i}", json={"tags": ["oldtag"]})
    with db.tx() as c:
        db.set_ai_tags(c, i, ["aitag"])
        c.execute("DROP TABLE items_fts")
        c.execute("CREATE VIRTUAL TABLE items_fts USING fts5(title, description, tags, transcript, ocr, source, "
                  "tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3')")
        c.execute("INSERT INTO items_fts(rowid,title,description,tags,transcript,ocr,source) VALUES (?,?,?,?,?,?,?)", (i, "t", "", "oldtag aitag", "", "", ""))
    db.init()
    with db.tx() as c:
        assert "ai_tags" in db._fts_columns(c)
    assert [x["id"] for x in client.get("/api/v1/items", params={"q": "oldtag"}).json()["items"]] == [i]
    assert [x["id"] for x in client.get("/api/v1/items", params={"q": "aitag"}).json()["items"]] == [i]
