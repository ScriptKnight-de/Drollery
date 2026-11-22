"""Managing tags: see them all, rename, merge, delete, and turn the AI's version of a tag into yours (Settings > Tags)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from . import db
from .deps import web_auth
from .i18n import t, tn
from .web import flash_redirect, render

router = APIRouter(prefix="/settings/tags", dependencies=[Depends(web_auth)])
MAX_SOURCES = 200


def _clean(names: list[str]) -> list[str]:
    return [n for n in dict.fromkeys(db.normalize_tag(x) for x in names) if n]


@router.get("")
def tags_page(request: Request, q: str = "", sort: str = ""):
    sort = sort if sort in ("name", "count") else "name"
    with db.tx() as c:
        rows, total = db.tag_overview(c, q, sort)
    return render(request, "settings_tags.html", tab="tags", rows=rows, total=total, q=q, sort=sort)


@router.post("/merge")
def merge(request: Request, tags: list[str] = Form(default=[]), target: str = Form(""), confirmed: str = Form("")):
    """Rename (one tag, a new name) or merge (several tags, or a name that exists). Asks first when it joins tags."""
    sources, new = _clean(tags)[:MAX_SOURCES], db.normalize_tag(target)
    if not new:
        return flash_redirect("/settings/tags", t("Type the tag name to merge into"), "error")
    if not sources:
        return flash_redirect("/settings/tags", t("Choose at least one tag"), "error")
    sources = [s for s in sources if s != new]
    if not sources:
        return flash_redirect("/settings/tags", t("Nothing to change: that is already the name"), "error")
    with db.tx() as c:
        info = db.tag_preview(c, sources, new)
        if not info["items"]:
            return flash_redirect("/settings/tags", t("No item carries that tag"), "error")
        if (info["target_exists"] or len(sources) > 1) and not confirmed:
            return render(request, "settings_tags_confirm.html", tab="tags", sources=sources, target=new, info=info)
        changed = db.merge_tags(c, sources, new)
    if len(sources) == 1 and not info["target_exists"]:
        return flash_redirect("/settings/tags", tn("Renamed “{old}” to “{new}” on {n} item", "Renamed “{old}” to “{new}” on {n} items",
                                                   changed, old=sources[0], new=new))
    return flash_redirect("/settings/tags", tn("Merged {k} tags into “{new}”: {n} item changed", "Merged {k} tags into “{new}”: {n} items changed",
                                               changed, k=len(sources), new=new))


@router.post("/delete")
def delete(tag: str = Form("")):
    name = db.normalize_tag(tag)
    with db.tx() as c:
        n = db.delete_tag(c, name) if name else 0
    if not n:
        return flash_redirect("/settings/tags", t("No item carries that tag"), "error")
    return flash_redirect("/settings/tags", tn("Deleted “{tag}” from {n} item", "Deleted “{tag}” from {n} items", n, tag=name))


@router.post("/keep")
def keep(tag: str = Form("")):
    name = db.normalize_tag(tag)
    with db.tx() as c:
        n = db.keep_ai_tag_everywhere(c, name) if name else 0
    if not n:
        return flash_redirect("/settings/tags", t("The AI has not given that tag to any item"), "error")
    return flash_redirect("/settings/tags", tn("“{tag}” is now your own tag on {n} item", "“{tag}” is now your own tag on {n} items", n, tag=name))
