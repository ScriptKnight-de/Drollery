"""Shared template rendering and flash messages for the web UI."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import accounts, aisettings, i18n

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
templates.env.globals.update({"_": i18n.t, "_n": i18n.tn, "lang": i18n.current, "available_languages": i18n.languages})


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
    raw = request.cookies.get(FLASH)
    flash = None
    if raw:
        kind, _, text = unquote(raw).partition("|")
        flash = {"kind": kind if kind in ("ok", "error") else "ok", "text": text}
    base = {"user": getattr(request.state, "user", None), "flash": flash, "impressum_live": accounts.impressum()[1],
            "providers": {cap: aisettings.enabled(cap) for cap in aisettings.CAPS}}
    resp = templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status_code)
    if raw:
        resp.delete_cookie(FLASH)
    return resp
