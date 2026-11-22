"""People: the global list, the popup to add one, a page per person, and linking people to items."""
from __future__ import annotations

import asyncio
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from . import albums, db, movies, people
from .config import get_settings
from .deps import api_auth, web_auth
from .i18n import N_, t
from .web import flash_redirect, jpeg_response, render

router = APIRouter(dependencies=[Depends(web_auth)])
files = APIRouter(dependencies=[Depends(api_auth)])

GENDER_LABELS = {"female": N_("Female"), "male": N_("Male"), "nonbinary": N_("Non-binary"), "other": N_("Other")}


def _person(person_id: int) -> dict:
    with db.tx() as c:
        p = people.get(c, person_id)
    if p is None:
        raise HTTPException(404, "person not found")
    return p


def _item_exists(item_id: int) -> dict:
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


async def _save_picture(person_id: int, up: UploadFile | None) -> bool:
    """Take an uploaded picture for the person; True if there was one and it worked, False if none was sent."""
    if up is None or not up.filename:
        return False
    s = get_settings()
    s.tmp_dir.mkdir(parents=True, exist_ok=True)
    name = Path(up.filename).name
    if not albums._is_image(name):
        raise people.PersonError(N_("That is not a picture"))
    limit = s.max_upload_mb * 1024 * 1024
    with tempfile.TemporaryDirectory(dir=s.tmp_dir) as td:
        raw = Path(td) / ("upload" + Path(name).suffix.lower())
        size = 0
        with raw.open("wb") as f:
            while chunk := await up.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"upload exceeds {s.max_upload_mb} MB")
                f.write(chunk)
        if not await asyncio.to_thread(people.set_picture, person_id, raw):
            raise people.PersonError(N_("That is not a picture"))
    return True


def _form(p: dict | None = None, **over) -> dict:
    base = {"name": "", "first_name": "", "surname": "", "birthday": "", "gender": "", "link": ""}      # "name" is the alias
    if p:
        base.update({k: p[k] for k in base})
    base.update(over)
    return base


# ------------------------------------------------------------------ pages

@router.get("/people")
def people_page(request: Request):
    with db.tx() as c:
        rows = people.everyone(c)
    return render(request, "people.html", rows=rows, tab="people")


@router.get("/people/new")
def new_page(request: Request, item: int = 0, name: str = ""):
    return render(request, "person_new.html", form=_form(name=name[:people.MAX_NAME]), item=item if item > 0 else 0, genders=GENDER_LABELS, today=date.today().isoformat())


@router.get("/suggest")
def suggest(q: str = ""):
    """What the search bar offers while typing: matching tags and people."""
    with db.tx() as c:
        tags = db.suggest_tags(c, q.lstrip("#"), 5)
        found = people.search(c, q, 5)
    return JSONResponse({
        "tags": tags,
        "people": [{"id": p["id"], "name": p["name"], "note": _note(p), "picture": f"/people/{p['id']}/picture?v={int(p['updated_at'] * 1000)}" if p["has_picture"] else ""} for p in found],
    }, headers={"Cache-Control": "no-store"})


def _note(p: dict) -> str:
    return " · ".join(x for x in (people.full_name(p) if people.full_name(p) != p["name"] else "", str(p["age"]) if p["age"] is not None else "", t(GENDER_LABELS[p["gender"]]) if p["gender"] in GENDER_LABELS else "") if x)


@router.get("/people/search")
def search(q: str = ""):
    with db.tx() as c:
        found = people.search(c, q)
    return JSONResponse([{"id": p["id"], "name": p["name"],
                          "note": _note(p),
                          "picture": f"/people/{p['id']}/picture?v={int(p['updated_at'] * 1000)}" if p["has_picture"] else ""} for p in found],
                        headers={"Cache-Control": "no-store"})


@router.post("/people")
async def create(request: Request, name: str = Form(""), first_name: str = Form(""), surname: str = Form(""), birthday: str = Form(""),
                 gender: str = Form(""), link: str = Form(""), item: int = Form(0), picture: UploadFile | None = File(default=None)):
    form = _form(name=name, first_name=first_name, surname=surname, birthday=birthday, gender=gender, link=link)
    if item > 0:
        _item_exists(item)
    try:
        data = people.clean(name, birthday, gender, link, first_name, surname)
        with db.tx() as c:
            pid = people.create(c, data)
        try:
            if await _save_picture(pid, picture):
                with db.tx() as c:
                    c.execute("UPDATE people SET has_picture=1 WHERE id=?", (pid,))
        except people.PersonError:
            with db.tx() as c:
                people.delete(c, pid)                       # nothing half-made is left behind
            raise
    except people.PersonError as e:
        return render(request, "person_new.html", status_code=422, form=form, item=item if item > 0 else 0, genders=GENDER_LABELS, today=date.today().isoformat(), error=t(str(e)))
    if item > 0:
        with db.tx() as c:
            people.link(c, item, pid)
        return flash_redirect(f"/items/{item}", t("{name} added", name=data["name"]))
    return flash_redirect(f"/people/{pid}", t("{name} added", name=data["name"]))


@router.get("/people/{person_id}")
def person_page(request: Request, person_id: int):
    p = _person(person_id)
    with db.tx() as c:
        items = db.search(c, "", "", "", 200, 0, "", person_id)
        album_info = albums.summaries(c, [i["id"] for i in items if i["kind"] == "album"])
        movie_info = movies.summaries(c, [i["id"] for i in items if i["kind"] == "movie"])
    return render(request, "person.html", person=p, full_name=people.full_name(p), form=_form(p), items=items, album_info=album_info, movie_info=movie_info, genders=GENDER_LABELS, today=date.today().isoformat(),
                  q="", tag="", kind="", src="", track_hits={}, more=False, page=0)


@router.post("/people/{person_id}")
async def save(request: Request, person_id: int, name: str = Form(""), first_name: str = Form(""), surname: str = Form(""), birthday: str = Form(""),
               gender: str = Form(""), link: str = Form(""), remove_picture: str = Form(""), picture: UploadFile | None = File(default=None)):
    p = _person(person_id)
    try:
        data = people.clean(name, birthday, gender, link, first_name, surname)
        got = await _save_picture(person_id, picture)
    except people.PersonError as e:
        return flash_redirect(f"/people/{person_id}", t(str(e)), "error")
    with db.tx() as c:
        people.update(c, person_id, data)
        if got:
            c.execute("UPDATE people SET has_picture=1 WHERE id=?", (person_id,))
        elif remove_picture and p["has_picture"]:
            c.execute("UPDATE people SET has_picture=0 WHERE id=?", (person_id,))
            people.picture_path(person_id).unlink(missing_ok=True)
    return flash_redirect(f"/people/{person_id}", t("Person saved"))


@router.post("/people/{person_id}/delete")
def remove(person_id: int):
    p = _person(person_id)
    with db.tx() as c:
        people.delete(c, person_id)
    return flash_redirect("/people", t("{name} deleted", name=p["name"]))


@files.get("/people/{person_id}/picture")
def picture(person_id: int):
    p = _person(person_id)
    path = people.picture_path(person_id)
    if not p["has_picture"] or not path.exists():
        raise HTTPException(404, "no picture")
    return jpeg_response(path)


# --------------------------------------------------- linking people to an item

@router.post("/items/{item_id}/people")
def add_to_item(item_id: int, name: str = Form(""), person_id: int = Form(0)):
    _item_exists(item_id)
    back = f"/items/{item_id}"
    with db.tx() as c:
        if person_id > 0:
            p = people.get(c, person_id)
            if p is None:
                return flash_redirect(back, t("That person no longer exists"), "error")
        else:
            if not name.strip():
                return flash_redirect(back, t("Type a name, or add a new person"), "error")
            found = people.by_name(c, name)
            if not found:
                return flash_redirect(back, t("Nobody is called “{name}” yet. Use “New person” to add them", name=name.strip()), "error")
            if len(found) > 1:
                return flash_redirect(back, t("Several people are called “{name}”. Pick one from the list", name=name.strip()), "error")
            p = found[0]
        added = people.link(c, item_id, p["id"])
    return flash_redirect(back, t("{name} added", name=p["name"]) if added else t("{name} is already there", name=p["name"]))


@router.post("/items/{item_id}/people/{person_id}/remove")
def remove_from_item(item_id: int, person_id: int):
    _item_exists(item_id)
    with db.tx() as c:
        people.unlink(c, item_id, person_id)
    return flash_redirect(f"/items/{item_id}", t("Person removed from this item"))
