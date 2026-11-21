"""Sharing: public pages and files behind unguessable links, plus the owner's tools to create, list and revoke them."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from . import accounts, db, pipeline, shares
from .deps import api_auth, client_ip, web_auth
from .i18n import t, tn
from .web import flash_redirect, render

public = APIRouter()
manage = APIRouter(dependencies=[Depends(web_auth)])
api = APIRouter(prefix="/api/v1", dependencies=[Depends(api_auth)])

PAGE_HEADERS = {"X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store"}
# Shared files are served from the same origin as the admin UI, so they are sandboxed: even a hostile file can't run script.
FILE_HEADERS = {"X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; media-src 'self'", "Cache-Control": "private, max-age=300"}


# ---------------------------------------------------------------- public

def _resolve(request: Request, token: str) -> tuple[dict, dict]:
    ip = client_ip(request)
    if shares.share_throttle.blocked(ip):
        raise HTTPException(429, "Too many requests")
    share, item = shares.lookup(token)
    if share is None or item is None:
        shares.share_throttle.fail(ip)
        raise HTTPException(404, "Not found")
    return share, item


def _gone(request: Request, share: dict):
    resp = render(request, "share_gone.html", status_code=410, share=share)
    resp.headers.update(PAGE_HEADERS)
    return resp


@public.api_route("/s/{token}", methods=["GET", "HEAD"])
def share_page(request: Request, token: str):
    share, item = _resolve(request, token)
    if not shares.is_open(share):
        return _gone(request, share)
    if request.method == "GET":
        shares.count_view(share["id"])
    resp = render(request, "share.html", share=share, item=item, urls=shares.urls(request, share, item), slug=shares.file_slug(item))
    resp.headers.update(PAGE_HEADERS)
    return resp


@public.api_route("/s/{token}/raw/{name}", methods=["GET", "HEAD"])
def share_raw(request: Request, token: str, name: str, download: int = 0):
    share, item = _resolve(request, token)
    if not shares.is_open(share):
        raise HTTPException(410, "This link has expired or was revoked")
    path = pipeline.media_path(item)
    if not path.exists():
        raise HTTPException(404, "File missing")
    rng = request.headers.get("range", "")
    from_our_page = f"/s/{token}" in request.headers.get("referer", "")
    if request.method == "GET" and (not rng or rng.startswith("bytes=0-")) and not from_our_page:
        shares.count_view(share["id"])                    # a direct hit (embed, chat preview, download); not the page's own <img>
    resp = FileResponse(path, media_type=item["mime"], filename=item["original_name"] or shares.file_slug(item),
                        content_disposition_type="attachment" if download else "inline")
    resp.headers.update(FILE_HEADERS)
    return resp


@public.api_route("/s/{token}/thumb", methods=["GET", "HEAD"])
def share_thumb(request: Request, token: str):
    share, item = _resolve(request, token)
    if not shares.is_open(share):
        raise HTTPException(410, "This link has expired or was revoked")
    path = pipeline.thumb_path(item)
    if not item["has_thumb"] or not path.exists():
        raise HTTPException(404, "No preview")
    resp = FileResponse(path, media_type="image/jpeg")
    resp.headers.update(FILE_HEADERS)
    return resp


# --------------------------------------------------------- owner (web UI)

def share_context(request: Request, item: dict) -> dict:
    items_shares = shares.for_item(item["id"])
    for sh in items_shares:
        sh["urls"] = shares.urls(request, sh, item)
    return {"shares": items_shares, "share_presets": shares.PRESET_LABELS, "public_base": shares.public_base(request)}


@manage.post("/items/{item_id}/shares")
def create_share(request: Request, item_id: int, preset: str = Form("7d"), amount: int = Form(0), unit: str = Form("hours"),
                 label: str = Form(""), next: str = Form("")):
    back = shares.safe_next(next, f"/items/{item_id}")
    with db.tx() as c:
        if db.get_item(c, item_id) is None:
            raise HTTPException(404, "item not found")
    seconds, err = shares.expiry_seconds(preset, amount, unit)
    if err:
        return flash_redirect(back + "#share", err, "error")
    shares.create(item_id, request.state.user["id"], seconds, label)
    return flash_redirect(back + "#share", t("Link created. Copy it below") if seconds else t("Permanent link created. Copy it below"))


@manage.post("/shares/{share_id}/revoke")
def revoke_share(share_id: int, next: str = Form("/settings/shares")):
    share = shares.get(share_id)
    shares.revoke(share_id)
    return flash_redirect(shares.safe_next(next, "/settings/shares") + ("#share" if share and f"/items/{share['item_id']}" in next else ""), t("Link revoked. It no longer works"))


@manage.post("/shares/{share_id}/delete")
def delete_share(share_id: int, next: str = Form("/settings/shares")):
    share = shares.get(share_id)
    shares.delete(share_id)
    return flash_redirect(shares.safe_next(next, "/settings/shares") + ("#share" if share and f"/items/{share['item_id']}" in next else ""), t("Link removed"))


@manage.get("/settings/shares")
def shares_page(request: Request):
    rows = shares.all_shares()
    with db.tx() as c:
        items = {r["id"]: db.get_item(c, r["id"]) for r in c.execute("SELECT id FROM items WHERE id IN (SELECT item_id FROM shares)")}
    for sh in rows:
        sh["urls"] = shares.urls(request, sh, items[sh["item_id"]])
    return render(request, "settings_shares.html", tab="shares", rows=rows, public_url=accounts.get_setting("public_url") or "",
                  env_public=bool(__import__("os").environ.get("DROLLERY_PUBLIC_URL")), public_base=shares.public_base(request))


@manage.post("/settings/shares/public-url")
def set_public_url(request: Request, public_url: str = Form("")):
    value = public_url.strip().rstrip("/")
    if value and not shares.valid_public_url(value):
        return flash_redirect("/settings/shares", t("Enter an address like https://memes.example.org (no spaces)"), "error")
    accounts.set_setting("public_url", value or None)
    return flash_redirect("/settings/shares", t("Public address saved") if value else t("Public address cleared; links use the address you browse with"))


@manage.post("/settings/shares/purge")
def purge(request: Request):
    n = shares.purge_inactive()
    return flash_redirect("/settings/shares", tn("Removed {n} expired or revoked link", "Removed {n} expired or revoked links", n))


# ---------------------------------------------------------------- API

def _share_json(request: Request, share: dict, item: dict) -> dict:
    u = shares.urls(request, share, item)
    return {"id": share["id"], "item_id": share["item_id"], "label": share["label"], "url": u["page"], "file_url": u["raw"],
            "created_at": share["created_at"], "expires_at": share["expires_at"], "permanent": share["expires_at"] is None,
            "status": share["state"]["kind"], "views": share["views"]}


def _item_or_404(item_id: int) -> dict:
    with db.tx() as c:
        item = db.get_item(c, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


@api.get("/items/{item_id}/shares")
def api_list_shares(request: Request, item_id: int):
    item = _item_or_404(item_id)
    return {"shares": [_share_json(request, s, item) for s in shares.for_item(item_id)]}


@api.post("/items/{item_id}/shares", status_code=201)
async def api_create_share(request: Request, item_id: int):
    """Body: {"expires_in": seconds or null for a permanent link, "label": "optional"}."""
    item = _item_or_404(item_id)
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    expires_in = body.get("expires_in")
    if expires_in is not None:
        if not isinstance(expires_in, int) or isinstance(expires_in, bool) or not shares.MIN_SECONDS <= expires_in <= shares.MAX_SECONDS:
            raise HTTPException(422, "expires_in must be a number of seconds between 60 and 31536000, or null for a permanent link")
    share = shares.create(item_id, request.state.user["id"], expires_in, str(body.get("label", "")))
    return JSONResponse(_share_json(request, share, item), status_code=201)


@api.delete("/shares/{share_id}", status_code=204)
def api_delete_share(share_id: int):
    if not shares.delete(share_id):
        raise HTTPException(404, "share not found")
