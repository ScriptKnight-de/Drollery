"""Tags that remember merges, a people list you can search and sort, and a person page with all of their items."""
import re
from urllib.parse import unquote

import pytest

from drollery import db, people
from test_app import png
from test_manage import add, ai, found, flash, link, person, post, tags_of


# ---------------------------------------------------------- tag redirects (C)

def merge(client, sources, target):
    data = {"tags": sources if isinstance(sources, list) else [sources], "target": target, "confirmed": "1"}
    return client.post("/settings/tags/merge", data=data, follow_redirects=False)


def redirects():
    with db.tx() as c:
        return {r["old"]: r["new"] for r in db.list_redirects(c)}


def test_a_merge_is_remembered_and_the_old_name_becomes_the_new_one(client):
    a, b = add(client, "a", 1, ["cats"]), add(client, "b", 2)
    merge(client, "cats", "cat")
    assert redirects() == {"cats": "cat"}
    client.patch(f"/api/v1/items/{b}", json={"tags": ["Cats", "sofa"]})                           # you type the old name again
    assert tags_of(b) == (["cat", "sofa"], [])
    client.post(f"/items/{b}/edit", data={"title": "b", "description": "", "tags": "cats #sofa"})   # in the item form too
    assert tags_of(b) == (["cat", "sofa"], [])
    ai(a, "cats", "kitten")                                                                           # and the AI suggests it again
    assert tags_of(a) == (["cat"], ["kitten"])                                                       # "cat" is yours already: not repeated as the AI's


def test_the_ai_s_old_name_becomes_the_new_tag_on_other_items_too(client):
    a = add(client, "a", 1, ["cat"])
    b = add(client, "b", 2)
    with db.tx() as c:
        c.execute("INSERT INTO tags(item_id,tag,source) VALUES (?, 'cats', 'user')", (a,))
    merge(client, "cats", "cat")
    ai(b, "cats", "fluffy")
    assert tags_of(b) == ([], ["cat", "fluffy"])
    assert found(client, "cat") == [a, b]


def test_the_bulk_action_and_the_library_filter_follow_the_redirect(client):
    a, b = add(client, "a", 1, ["cats"]), add(client, "b", 2)
    merge(client, "cats", "cat")
    post(client, "/items/bulk", ids=str(b), action="tag_add", tags="cats", next="/")
    assert tags_of(b) == (["cat"], [])
    assert found(client, "cats") == [a, b] and found(client, "cat") == [a, b]                        # an old link or bookmark still finds them
    assert client.get("/", params={"tag": "cats"}).text.count('class="tile"') == 2


def test_redirects_follow_each_other_and_a_name_that_is_real_again_redirects_nowhere(client):
    a = add(client, "a", 1, ["cats"])
    merge(client, "cats", "cat")
    merge(client, "cat", "kitty")
    assert redirects() == {"cats": "kitty", "cat": "kitty"}                                           # the first one now points at the end of the chain
    client.patch(f"/api/v1/items/{a}", json={"tags": ["cats"]})
    assert tags_of(a) == (["kitty"], [])
    merge(client, "kitty", "cat")                                                                     # back again: "cat" is a real tag, not a redirect
    assert redirects() == {"cats": "cat", "kitty": "cat"}
    with db.tx() as c:
        assert db.resolve_tags(c, ["cats", "kitty", "cat", "dog"]) == ["cat", "dog"]


def test_many_tags_merged_at_once_are_all_remembered(client):
    add(client, "a", 1, ["katze"]); add(client, "b", 2, ["cat"]); add(client, "c", 3, ["katzen"])
    merge(client, ["cat", "katzen"], "katze")
    assert redirects() == {"cat": "katze", "katzen": "katze"}


def test_the_tags_page_lists_the_remembered_renames_and_can_forget_one(client):
    add(client, "a", 1, ["cats"])
    merge(client, "cats", "cat")
    page = client.get("/settings/tags").text
    assert "Remembered renames" in page and "#cats" in page and "#cat" in page and 'action="/settings/tags/forget"' in page
    r = post(client, "/settings/tags/forget", old="cats")
    assert "Forgotten: “cats” is an ordinary tag name again" in flash(r) and redirects() == {}
    assert "Remembered renames" not in client.get("/settings/tags").text
    assert "not remembered any more" in flash(post(client, "/settings/tags/forget", old="cats"))
    i = add(client, "b", 2, ["cats"])
    assert tags_of(i) == (["cats"], [])                                                               # forgotten: it is just a tag again


def test_the_question_before_a_merge_says_the_names_are_remembered(client):
    add(client, "a", 1, ["cat", "cats"])
    page = post(client, "/settings/tags/merge", tags="cats", target="cat")
    assert "The old names are remembered" in page.text


def test_a_rename_to_a_new_name_is_remembered_too(client):
    a = add(client, "a", 1, ["colour"])
    post(client, "/settings/tags/merge", tags="colour", target="color")
    assert redirects() == {"colour": "color"}
    client.patch(f"/api/v1/items/{a}", json={"tags": ["Colour"]})
    assert tags_of(a) == (["color"], [])


# ----------------------------------------------------------- the people list (B)

def test_the_people_list_can_be_searched_sorted_and_filtered(client):
    one = add(client, "one", 1); two = add(client, "two", 2)
    zed = person(client, "Zed Zebra"); amy = person(client, "Amy Ant", first_name="Anna", surname="Smith"); ben = person(client, "Ben Bee")
    link(client, one, ben); link(client, two, ben); link(client, one, amy)
    with db.tx() as c:
        names = lambda **kw: [p["name"] for p in people.everyone(c, **kw)]
        assert names() == ["Amy Ant", "Ben Bee", "Zed Zebra"]
        assert names(sort="items") == ["Ben Bee", "Amy Ant", "Zed Zebra"]
        assert names(sort="new") == ["Ben Bee", "Amy Ant", "Zed Zebra"]                                  # created last to first
        assert names(q="smith") == ["Amy Ant"] and names(q="ANT") == ["Amy Ant"] and names(q="anna s") == ["Amy Ant"] and names(q="nobody") == []
        assert names(unused=True) == ["Zed Zebra"] and names(q="b", unused=True) == ["Zed Zebra"]
        assert names(q="%") == [] and names(q="_") == []                                                   # wildcards are plain characters
    page = client.get("/people", params={"q": "ben"}).text
    assert page.count('class="person-card') == 1 and "Ben Bee" in page and "Amy Ant" not in page and "1 person of 3" in page
    order = lambda sort: re.findall(r'<span class="pc-name">([^<]*)</span>', client.get("/people", params={"sort": sort}).text)
    assert order("items") == ["Ben Bee", "Amy Ant", "Zed Zebra"] and order("name") == ["Amy Ant", "Ben Bee", "Zed Zebra"] and order("bogus") == order("name")
    assert order("new")[0] == "Ben Bee"
    only = client.get("/people", params={"filter": "unused"}).text
    assert "Zed Zebra" in only and "Ben Bee" not in only and 'name="filter" value="unused" checked' in only


def test_a_few_people_need_no_toolbar_but_the_page_says_when_nothing_matches(client):
    person(client, "Only One")
    assert 'name="q"' not in client.get("/people").text
    page = client.get("/people", params={"q": "zzz"}).text
    assert 'name="q"' in page and "Nobody matches that" in page


def test_people_on_no_item_can_be_deleted_together_and_nobody_else(client):
    one = add(client, "one", 1)
    used, idle1, idle2 = person(client, "Used"), person(client, "Idle One"), person(client, "Idle Two")
    link(client, one, used)
    page = client.get("/people").text
    assert 'action="/people/delete-unused"' in page and "Delete the 2 people on no item" in page and "Delete the 2 people who are on no item?" in page
    r = post(client, "/people/delete-unused")
    assert "Deleted 2 people who were on no item" in flash(r)
    with db.tx() as c:
        assert [p["name"] for p in people.everyone(c)] == ["Used"]
    assert client.get(f"/items/{one}").status_code == 200
    assert "Everybody is on at least one item" in flash(post(client, "/people/delete-unused"))
    assert 'action="/people/delete-unused"' not in client.get("/people").text


def test_deleting_the_idle_people_takes_their_pictures_along(client):
    r = client.post("/people", data={"name": "With Picture"}, files={"picture": ("p.png", png(9), "image/png")})
    with db.tx() as c:
        pid = c.execute("SELECT id FROM people").fetchone()["id"]
    assert people.picture_path(pid).exists()
    post(client, "/people/delete-unused")
    assert not people.picture_path(pid).exists()


def test_only_a_signed_in_person_deletes_the_idle_people(client):
    person(client, "Idle")
    from test_share import anon_client
    r = anon_client().post("/people/delete-unused", follow_redirects=False)
    assert r.status_code in (303, 401)
    with db.tx() as c:
        assert len(people.everyone(c)) == 1


# ------------------------------------------------------------- the person page (A)

def test_a_person_page_pages_through_all_of_their_items(client):
    pid = person(client, "Busy Person")
    ids = [add(client, f"item {n:02d}", n) for n in range(1, 46)]
    with db.tx() as c:
        for i in ids:
            people.link(c, i, pid)
    page = client.get(f"/people/{pid}").text
    assert page.count('class="tile"') == 40 and "45 items" in page
    assert 'class="more"' in page and f"person={pid}" in page.split('class="more"')[1][:300]        # the rest is fetched like on the library page
    nxt = client.get("/", params={"person": pid, "page": 1}, headers={"hx-request": "true"}).text
    assert nxt.count('class="tile"') == 5 and 'class="more"' not in nxt
    seen = set(re.findall(r'data-id="(\d+)"', page)) | set(re.findall(r'data-id="(\d+)"', nxt))
    assert seen == {str(i) for i in ids}                                                              # every item, once


def test_a_person_with_few_items_loads_nothing_more(client):
    pid = person(client, "Quiet")
    i = add(client, "x", 1)
    link(client, i, pid)
    page = client.get(f"/people/{pid}").text
    assert page.count('class="tile"') == 1 and 'class="more"' not in page and "1 item" in page
    assert "Not added to any item yet" in client.get(f"/people/{person(client, 'Empty')}").text
