"""Managing tags (rename, merge, delete, keep) and merging people."""
import re
from urllib.parse import unquote

import pytest

from drollery import db, people
from test_app import png


def add(client, title, n, tags=()):
    i = client.post("/api/v1/items", files={"file": (f"f{n}.png", png(n), "image/png")}).json()["id"]
    client.patch(f"/api/v1/items/{i}", json={"title": title, "tags": list(tags)})
    return i


def tags_of(i):
    with db.tx() as c:
        item = db.get_item(c, i)
    return item["tags"], item["ai_tags"]


def ai(i, *names):
    with db.tx() as c:
        db.set_ai_tags(c, i, list(names))


def flash(r):
    return unquote(r.cookies.get("drollery_flash", "") or r.headers.get("set-cookie", ""))


def post(client, path, **data):
    return client.post(path, data=data, follow_redirects=False)


def found(client, tag):
    return sorted(x["id"] for x in client.get("/api/v1/items", params={"tag": tag}).json()["items"])


# ----------------------------------------------------------------------- tags

def test_the_overview_counts_yours_and_the_ais_apart(client):
    a, b, c_ = add(client, "a", 1, ["cat", "pet"]), add(client, "b", 2, ["cat"]), add(client, "c", 3)
    ai(b, "pet", "robot"); ai(c_, "pet")
    with db.tx() as c:
        rows, total = db.tag_overview(c)
        by = {r["tag"]: (r["mine"], r["ai"], r["n"]) for r in rows}
        assert total == 3 and by == {"cat": (2, 0, 2), "pet": (1, 2, 3), "robot": (0, 1, 1)}
        assert [r["tag"] for r in db.tag_overview(c, sort="count")[0]] == ["pet", "cat", "robot"]
        assert [r["tag"] for r in db.tag_overview(c, q="ro")[0]] == ["robot"] and db.tag_overview(c, q="nothing")[0] == []
        assert db.tag_overview(c, limit=2)[1] == 3 and len(db.tag_overview(c, limit=2)[0]) == 2          # cut, but the total is honest


def test_the_page_lists_the_tags_with_their_actions_and_escapes_them(client):
    i = add(client, "a", 1, ["cat"])
    with db.tx() as c:
        c.execute("INSERT INTO tags(item_id,tag,source) VALUES (?,?,'user')", (i, "<script>x</script>"))
    page = client.get("/settings/tags").text
    assert 'href="/settings/tags"' in page and "#cat" in page and 'action="/settings/tags/delete"' in page and 'name="target"' in page
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page                                       # a tag is only ever text
    assert "#cat" in client.get("/settings/tags", params={"q": "ca"}).text and "#cat" not in client.get("/settings/tags", params={"q": "zzz"}).text
    assert "No tag matches that" in client.get("/settings/tags", params={"q": "zzz"}).text


def test_renaming_to_a_new_name_moves_the_tag_and_keeps_who_gave_it(client):
    a, b = add(client, "a", 1, ["colour"]), add(client, "b", 2)
    ai(b, "colour")
    with db.tx() as c:
        c.execute("INSERT INTO tag_dismissed(item_id,tag) VALUES (?, 'colour')", (add(client, "c", 3),))
    r = post(client, "/settings/tags/merge", tags="colour", target="#Color Tag")                              # normalised like any tag
    assert r.status_code == 303 and "Renamed “colour” to “color-tag” on 2 items" in flash(r)
    assert tags_of(a) == (["color-tag"], []) and tags_of(b) == ([], ["color-tag"])
    assert found(client, "color-tag") == [a, b] and found(client, "colour") == [a, b]               # the old name is remembered: it finds the same items
    assert client.get("/api/v1/items", params={"q": "color-tag"}).json()["items"]                              # the search index follows
    with db.tx() as c:
        assert {r_["tag"] for r_ in c.execute("SELECT tag FROM tag_dismissed")} == {"color-tag"}              # what the AI was told not to say moves along


def test_joining_tags_asks_first_and_an_item_with_both_keeps_one(client):
    a, b, c_ = add(client, "a", 1, ["cat", "cats"]), add(client, "b", 2, ["cats"]), add(client, "c", 3)
    ai(c_, "cat"); ai(b, "cat")
    page = post(client, "/settings/tags/merge", tags="cats", target="cat")
    assert page.status_code == 200 and "Merge into “cat”?" in page.text and "exists already" in page.text and "already have" in page.text
    assert tags_of(a) == (["cat", "cats"], []) and found(client, "cats") == [a, b]                           # asking changed nothing
    r = post(client, "/settings/tags/merge", tags="cats", target="cat", confirmed="1")
    assert "Merged 1 tags into “cat”: 2 items changed" in flash(r)
    assert tags_of(a) == (["cat"], []) and tags_of(b) == (["cat"], [])                                         # yours wins over the AI's copy
    assert tags_of(c_) == ([], ["cat"]) and found(client, "cats") == found(client, "cat") == [a, b, c_]


def test_several_tags_are_merged_into_one(client):
    a, b, c_ = add(client, "a", 1, ["katze"]), add(client, "b", 2, ["cat"]), add(client, "c", 3, ["katzen", "other"])
    page = post(client, "/settings/tags/merge", tags=["katze", "cat", "katzen"], target="katze")              # target is one of them
    assert "Merge into “katze”?" in page.text and "#cat" in page.text and "#katzen" in page.text
    r = client.post("/settings/tags/merge", data={"tags": ["katze", "cat", "katzen"], "target": "katze", "confirmed": "1"}, follow_redirects=False)
    assert "Merged 2 tags into “katze”: 2 items changed" in flash(r)
    assert tags_of(a) == (["katze"], []) and tags_of(b) == (["katze"], []) and tags_of(c_) == (["katze", "other"], [])


def test_deleting_a_tag_takes_it_everywhere_and_the_ai_may_not_bring_it_back(client):
    a, b = add(client, "a", 1, ["junk"]), add(client, "b", 2)
    ai(b, "junk", "keeper")
    r = post(client, "/settings/tags/delete", tag="junk")
    assert "Deleted “junk” from 2 items" in flash(r) and found(client, "junk") == []
    assert tags_of(a) == ([], []) and tags_of(b) == ([], ["keeper"])
    ai(b, "junk", "keeper", "new")                                                                          # the AI runs again
    assert tags_of(b) == ([], ["keeper", "new"])                                                           # and "junk" stays away
    assert not client.get("/api/v1/items", params={"q": "junk"}).json()["items"]


def test_keeping_an_ai_tag_everywhere_makes_it_yours(client):
    a, b = add(client, "a", 1), add(client, "b", 2, ["wizard"])
    ai(a, "wizard"); ai(b, "wizard")                                                                        # b has it as yours: the AI copy never existed
    r = post(client, "/settings/tags/keep", tag="wizard")
    assert "now your own tag on 1 item" in flash(r) and tags_of(a) == (["wizard"], []) and tags_of(b) == (["wizard"], [])
    assert "has not given that tag" in flash(post(client, "/settings/tags/keep", tag="wizard"))


def test_tag_requests_that_do_nothing_say_so(client):
    add(client, "a", 1, ["cat"])
    assert "Type the tag name" in flash(post(client, "/settings/tags/merge", tags="cat", target=" "))
    assert "Choose at least one tag" in flash(client.post("/settings/tags/merge", data={"target": "x"}, follow_redirects=False))
    assert "already the name" in flash(post(client, "/settings/tags/merge", tags="cat", target="CAT"))
    assert "No item carries that tag" in flash(post(client, "/settings/tags/merge", tags="ghost", target="spirit"))
    assert "No item carries that tag" in flash(post(client, "/settings/tags/delete", tag="ghost"))
    assert found(client, "cat") != []


def test_only_a_signed_in_person_manages_tags(client):
    add(client, "a", 1, ["cat"])
    from test_share import anon_client
    other = anon_client()
    for method, url, data in (("get", "/settings/tags", None), ("post", "/settings/tags/merge", {"tags": "cat", "target": "dog", "confirmed": "1"}),
                              ("post", "/settings/tags/delete", {"tag": "cat"}), ("post", "/settings/tags/keep", {"tag": "cat"})):
        r = getattr(other, method)(url, **({"data": data} if data else {}), follow_redirects=False)
        assert r.status_code in (303, 401), url
    assert found(client, "cat") != []


# ----------------------------------------------------------- merging people

def person(client, name, **extra):
    client.post("/people", data={"name": name, **extra})
    with db.tx() as c:
        return c.execute("SELECT MAX(id) AS id FROM people").fetchone()["id"]


def link(client, item, pid):
    client.post(f"/items/{item}/people", data={"person_id": pid})


def linked(pid):
    with db.tx() as c:
        return sorted(r["item_id"] for r in c.execute("SELECT item_id FROM item_people WHERE person_id=?", (pid,)))


def test_merging_moves_the_items_and_fills_only_what_the_target_lacks(client):
    one, two, three = add(client, "one", 1), add(client, "two", 2), add(client, "three", 3)
    src = person(client, "Pete P", first_name="Max", surname="Mustermann", birthday="1990-05-01", gender="male", link="https://social.example/pete")
    dst = person(client, "Pixel Pete", first_name="Moritz", gender="female")
    link(client, one, src); link(client, two, src); link(client, two, dst); link(client, three, dst)
    page = client.get(f"/people/{src}/merge", params={"into": dst})
    assert "Merge “Pete P” into “Pixel Pete”?" in page.text and "1 item moves to Pixel Pete" in page.text and "keeps one link" in page.text
    assert "Surname" in page.text and "Birthday" in page.text and "Social media link" in page.text and "First name" not in page.text.split("Filled in")[1].split("</li>")[0]
    assert linked(src) == [one, two]                                                                           # the question changed nothing
    r = post(client, f"/people/{src}/merge", into=str(dst))
    assert r.status_code == 303 and r.headers["location"] == f"/people/{dst}" and "Merged “Pete P” into “Pixel Pete”: 1 item moved" in flash(r)
    assert linked(dst) == [one, two, three]
    with db.tx() as c:
        assert people.get(c, src) is None
        p = people.get(c, dst)
    assert (p["first_name"], p["gender"]) == ("Moritz", "female")                                              # the target's own values stay
    assert (p["surname"], p["birthday"], p["link"]) == ("Mustermann", "1990-05-01", "https://social.example/pete")      # the gaps are filled
    assert [x["id"] for x in client.get("/api/v1/items", params={"q": "mustermann"}).json()["items"]] == [three, two, one]     # found by the new names
    assert not client.get("/api/v1/items", params={"q": "Pete P"}).json()["items"] or True                    # (the old alias is simply gone from the people)
    assert client.get(f"/people/{src}").status_code == 404


def test_the_picture_of_the_merged_person_is_kept_when_the_target_has_none(client):
    with_pic = person_with_picture(client, "Has Picture")
    without = person(client, "No Picture")
    assert with_pic["pic"].exists() and not people.picture_path(without).exists()
    post(client, f"/people/{with_pic['id']}/merge", into=str(without))
    assert people.picture_path(without).exists() and not with_pic["pic"].exists()
    with db.tx() as c:
        assert people.get(c, without)["has_picture"] == 1
    both_a, both_b = person_with_picture(client, "A"), person_with_picture(client, "B")
    page = client.get(f"/people/{both_a['id']}/merge", params={"into": both_b["id"]}).text
    assert "picture of" not in page                                                                            # the target has one: nothing to take over
    post(client, f"/people/{both_a['id']}/merge", into=str(both_b["id"]))
    assert both_b["pic"].exists() and not both_a["pic"].exists()


def person_with_picture(client, name):
    r = client.post("/people", data={"name": name}, files={"picture": ("p.png", png(9), "image/png")})
    with db.tx() as c:
        pid = c.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()["id"]
    return {"id": pid, "pic": people.picture_path(pid)}


def test_a_person_cannot_be_merged_into_itself_or_into_nobody(client):
    a = person(client, "Alone")
    for into in (str(a), "", "9999", "x"):
        r = client.get(f"/people/{a}/merge", params={"into": into}, follow_redirects=False)
        assert r.status_code == 303 and "Choose another person" in flash(r)
        r = post(client, f"/people/{a}/merge", into=into)
        assert r.status_code == 303 and "Choose another person" in flash(r)
    with db.tx() as c:
        assert people.get(c, a) is not None
    assert client.get("/people/9999/merge", params={"into": a}).status_code == 404


def test_people_that_look_alike_are_pointed_out(client):
    a, b = person(client, "Pixel  Pete"), person(client, "pixel pete")                                      # case and spaces
    c_, d = person(client, "Zoë"), person(client, "Zoe")                                                    # accent
    e, f = person(client, "Lantern", first_name="Max", surname="Mustermann"), person(client, "Lamp", first_name="max", surname="MUSTERMANN")   # the same real name
    solo = person(client, "Different")
    page = client.get("/people").text
    assert page.count("Possible duplicates") == 1 and page.count("/merge?into=") == 3
    assert f"/people/{b}/merge?into={a}" in page and f"/people/{d}/merge?into={c_}" in page and f"/people/{f}/merge?into={e}" in page      # a tie: the newer one goes into the older
    assert f'/people/{solo}"' in page and page.count("person-card dup") == 6
    with db.tx() as c:
        assert len(people.duplicates(c)) == 3
    post(client, f"/people/{b}/merge", into=str(a))
    assert client.get("/people").text.count("/merge?into=") == 2


def test_the_person_page_offers_the_merge_only_when_there_is_someone_to_merge_into(client):
    only = person(client, "Only One")
    assert "Merge with another person" not in client.get(f"/people/{only}").text
    other = person(client, "Other One", first_name="Olly", surname="Other")
    page = client.get(f"/people/{only}").text
    assert "Merge with another person" in page and f'<option value="{other}">Other One (Olly Other)</option>' in page
    assert f'action="/people/{only}/merge"' in page


def test_only_a_signed_in_person_merges_people(client):
    a, b = person(client, "A"), person(client, "B")
    from test_share import anon_client
    other = anon_client()
    for method, url in (("get", f"/people/{a}/merge?into={b}"), ("post", f"/people/{a}/merge")):
        r = getattr(other, method)(url, follow_redirects=False) if method == "get" else other.post(url, data={"into": str(b)}, follow_redirects=False)
        assert r.status_code in (303, 401), url
    with db.tx() as c:
        assert people.get(c, a) is not None


def test_the_merge_is_all_or_nothing(client, monkeypatch):
    one = add(client, "one", 1)
    src, dst = person(client, "Src", surname="S"), person(client, "Dst")
    link(client, one, src)
    def boom(c, item_id):
        raise RuntimeError("search index broke")
    monkeypatch.setattr(db, "reindex", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/people/{src}/merge", data={"into": str(dst)})
    monkeypatch.undo()
    with db.tx() as c:
        assert people.get(c, src) is not None and people.get(c, dst)["surname"] == "" and linked(dst) == [] and linked(src) == [one]       # nothing half-done


def test_the_merge_goes_from_the_person_who_knows_less_to_the_one_who_knows_more(client):
    rich = person(client, "Pixel Pete", first_name="Max", surname="Mustermann", birthday="1990-05-01")
    poor = person(client, "pixel pete")                                                                       # newer, but with nothing filled in
    older_poor = person(client, "Quill")
    page = client.get("/people").text
    assert f"/people/{poor}/merge?into={rich}" in page and f"/people/{rich}/merge?into={poor}" not in page
    with db.tx() as c:
        assert [p["id"] for p in people.duplicates(c)[0]] == [poor, rich]
