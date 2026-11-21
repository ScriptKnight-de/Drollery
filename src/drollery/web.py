"""Shared template rendering and flash messages for the web UI."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import accounts, aisettings

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


def flash_redirect(url: str, text: str, kind: str = "ok") -> RedirectResponse:
    """Redirect and show a one-time message on the next page. kind: ok | error."""
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(FLASH, quote(f"{kind}|{text}"), max_age=60, httponly=True, samesite="lax")
    return resp


def render(request: Request, name: str, status_code: int = 200, **ctx):
    raw = request.cookies.get(FLASH)
    flash = None
    if raw:
        kind, _, text = unquote(raw).partition("|")
        flash = {"kind": kind if kind in ("ok", "error") else "ok", "text": text}
    base = {"user": getattr(request.state, "user", None), "flash": flash,
            "providers": {cap: aisettings.enabled(cap) for cap in aisettings.CAPS}}
    resp = templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status_code)
    if raw:
        resp.delete_cookie(FLASH)
    return resp
