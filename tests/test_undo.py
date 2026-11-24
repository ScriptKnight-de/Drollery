"""Deleting an item in the web UI can be taken back for a minute (checklist UI-11)."""
import time
from urllib.parse import unquote

import pytest

from drollery import db, pipeline, trash
from test_app import png


def add(client, n=1, title="keep me"):
    i = client.post("/api/v1/items", files={"file": (f"f{n}.png", png(n), "image/png")}).json()["id"]
    client.patch(f"/api/v1/items/{i}", json={"title": title, "tags": ["castle"]})
    return i


def count():
    with db.tx() as c:
        return c.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def item(i):
    with db.tx() as c:
        return db.get_item(c, i)


def undo_cookie(r):
    return r.cookies.get("drollery_undo")


def test_a_deleted_item_comes_back_with_its_tags_file_and_place_in_search(client):
    i = add(client)
    path = pipeline.media_path(item(i))
    r = client.post(f"/items/{i}/delete", follow_redirects=False)
    token = undo_cookie(r)
    assert r.status_code == 303 and token and count() == 0 and not path.exists()
    assert client.get("/", params={"q": "keep"}).text.count('class="tile"') == 0      # gone from search
    back = client.post(f"/undo/{token}", follow_redirects=False)
    assert "Brought back 1 item" in unquote(back.cookies.get("drollery_flash", ""))
    assert count() == 1 and path.exists()
    assert item(i)["title"] == "keep me" and item(i)["tags"] == ["castle"]
    assert client.get("/", params={"q": "keep"}).text.count('class="tile"') == 1       # found again


def test_the_message_after_deleting_has_an_undo_button(client):
    i = add(client)
    client.post(f"/items/{i}/delete", follow_redirects=False)
    page = client.get("/").text
    assert 'data-undo' in page and 'action="/undo/' in page
    assert 'action="/undo/' not in client.get("/").text                                  # shown once


def test_a_bulk_delete_is_undone_as_one(client):
    ids = [add(client, n, f"t{n}") for n in (1, 2, 3)]
    r = client.post("/items/bulk", data={"ids": ",".join(map(str, ids)), "action": "delete", "next": "/"}, follow_redirects=False)
    assert count() == 0
    client.post(f"/undo/{undo_cookie(r)}")
    assert count() == 3


def test_it_is_too_late_after_the_time_is_up_and_a_batch_comes_back_only_once(client):
    i = add(client)
    token = undo_cookie(client.post(f"/items/{i}/delete", follow_redirects=False))
    old = time.time() - trash.UNDO_SECONDS - 5
    import os
    os.utime(trash._root() / token, (old, old))
    assert "Too late" in unquote(client.post(f"/undo/{token}", follow_redirects=False).cookies.get("drollery_flash", ""))
    assert count() == 0
    j = add(client, 2)
    token = undo_cookie(client.post(f"/items/{j}/delete", follow_redirects=False))
    client.post(f"/undo/{token}")
    client.post(f"/undo/{token}")
    assert count() == 1


def test_a_made_up_token_does_nothing_and_cannot_leave_the_trash_folder(client):
    assert client.post("/undo/../../etc", follow_redirects=False).status_code in (404, 405)
    for token in ("x" * 16, "short", "a.b.c.d.e.f.g.h."):
        assert "Too late" in unquote(client.post(f"/undo/{token}", follow_redirects=False).cookies.get("drollery_flash", ""))


def test_a_new_delete_clears_out_old_batches_and_start_clears_all(client):
    a = add(client)
    first = undo_cookie(client.post(f"/items/{a}/delete", follow_redirects=False))
    old = time.time() - trash.UNDO_SECONDS - 5
    import os
    os.utime(trash._root() / first, (old, old))
    b = add(client, 2)
    client.post(f"/items/{b}/delete")
    assert not (trash._root() / first).exists()
    trash.purge_old(everything=True)
    assert not any(trash._root().iterdir())


def test_the_api_delete_stays_immediate(client):
    i = add(client)
    assert client.delete(f"/api/v1/items/{i}").status_code == 204
    assert not trash._root().exists() or not any(trash._root().iterdir())


def test_undo_needs_a_signed_in_user(anon):
    assert anon.post("/undo/abcdefghijklmnop", follow_redirects=False).status_code in (303, 401, 403)
