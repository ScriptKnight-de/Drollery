"""Shared template rendering and flash messages for the web UI."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import accounts, aisettings, i18n
from .config import get_settings

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")
FLASH = "drollery_flash"


def _timestamp(value) -> str:
    import time
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(value)))
    except (TypeError, ValueError, OverflowError):
        return "-"


templates.env.filters["timestamp"] = _timestamp


def _clock(seconds) -> str:
    """72 -> '1:12', 3725 -> '1:02:05'."""
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return "-"
    h, rest = divmod(total, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


templates.env.filters["clock"] = _clock
def _job_type(name: str) -> str:
    """The name of a kind of job: translated when there is a translation, else readable (transcribe_track -> transcribe track)."""
    shown = i18n.t(name)
    return shown if shown != name else name.replace("_", " ")


from .movies import SUBTYPES as _SUBTYPES

KIND_NAMES = {"image": i18n.N_("Image"), "gif": i18n.N_("GIF"), "video": i18n.N_("Clip"), "audio": i18n.N_("Sound"), "album": i18n.N_("Album"), "movie": i18n.N_("Movie")}


def _kind_label(kind: str) -> str:
    """What one item of a kind is called in the interface. (The kinds themselves stay image, video, audio and album in the data and the API.)"""
    return i18n.t(KIND_NAMES.get(kind, kind))


templates.env.globals.update({"_": i18n.t, "job_type": _job_type, "kind_label": _kind_label, "_n": i18n.tn, "lang": i18n.current, "available_languages": i18n.languages, "flag_of": i18n.flag, "subtype_names": _SUBTYPES})


def flash_redirect(url: str, text: str, kind: str = "ok") -> RedirectResponse:
    """Redirect and show a one-time message on the next page. kind: ok | error."""
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(FLASH, quote(f"{kind}|{i18n.t(text)}"), max_age=60, httponly=True, samesite="lax")
    return resp


def render(request: Request, name: str, status_code: int = 200, **ctx):
    user = getattr(request.state, "user", None)
    if user and user.get("language"):                      # a signed-in user's own choice beats the browser's
        i18n.set_language(user["language"])
    for key in ("error", "ok"):
        if isinstance(ctx.get(key), str):
            ctx[key] = i18n.t(ctx[key])
    embed = request.headers.get("sec-fetch-dest") == "iframe" or "drollery_embed" in request.cookies     # shown inside a popup (browsers send no frame header on plain http, so popup.js also sets a cookie while the popup is open)
    if embed and name in ("album.html", "item.html") and status_code == 200:
        return templates.TemplateResponse(request, "embed_done.html", {})      # the popup's job is done; leaves the flash message for the page behind
    raw = request.cookies.get(FLASH)
    flash = None
    if raw:
        kind, _, text = unquote(raw).partition("|")
        flash = {"kind": kind if kind in ("ok", "error") else "ok", "text": text}
    base = {"embed": embed, "user": getattr(request.state, "user", None), "flash": flash, "impressum_live": accounts.impressum()[1], "metadata_lookup": get_settings().metadata_lookup,
            "providers": {cap: aisettings.enabled(cap) for cap in aisettings.CAPS}}
    resp = templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status_code)
    if raw:
        resp.delete_cookie(FLASH)
    return resp
