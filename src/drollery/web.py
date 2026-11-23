"""Shared template rendering and flash messages for the web UI."""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from . import __version__, accounts, aisettings, i18n
from .config import get_settings

BASE = Path(__file__).parent
def security_headers(nonce: str) -> dict[str, str]:
    """Headers every response carries. The page may run its own scripts (those with this request's nonce) and the files of /static,
    and load nothing from another site: no outside script, image, font, frame or connection. Pages of this site may be framed by
    this site only (the popups of the item and album pages do that). The inline style attributes are allowed because the tiles set
    a colour variable with one."""
    csp = "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ])
    return {"Content-Security-Policy": csp, "X-Frame-Options": "SAMEORIGIN", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
            "Cross-Origin-Opener-Policy": "same-origin"}


IMAGE_HEADERS = {"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"}
templates = Jinja2Templates(directory=BASE / "templates")
FLASH = "drollery_flash"
PAGE = 40                       # tiles per page of the library (and of a person's items)


def _timestamp(value) -> str:
    import time
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(value)))
    except (TypeError, ValueError, OverflowError):
        return "-"


def _bytes(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


templates.env.filters["timestamp"] = _timestamp
templates.env.filters["bytes"] = _bytes


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


_ORN = json.loads((Path(__file__).parent / "static" / "pixel-orn" / "pieces.json").read_text())


GAP_MIN, GAP_MAX = 4, 10            # empty dots between two pieces (2 px each)


def orn_row(cells: int = 450) -> list[dict]:
    """The pieces of one ornament strip of the Pixel style, mixed anew for every page: a shuffled walk through the pool (no piece
    twice before every piece has been used, never the same one twice in a row), each with a random gap of 4 to 10 dots (8 to 20 px), enough to fill
    `cells` dots (2 px each). The strip clips what does not fit, so a wide screen is simply filled further."""
    row, total, last = [], 0, None
    while total < cells:
        deck = random.sample(_ORN["pieces"], len(_ORN["pieces"]))
        if deck[0]["n"] == last:
            deck.append(deck.pop(0))
        for piece in deck:
            gap = random.randint(GAP_MIN, GAP_MAX)
            row.append({"x": piece["x"], "w": piece["w"], "g": gap, "n": piece["n"]})
            total += piece["w"] + gap
            last = piece["n"]
            if total >= cells:
                break
    return row


templates.env.globals.update({"asset_v": __version__, "orn_row": orn_row, "orn_sheet": _ORN["width"], "_": i18n.t, "job_type": _job_type, "kind_label": _kind_label, "_n": i18n.tn, "lang": i18n.current, "available_languages": i18n.languages, "flag_of": i18n.flag, "subtype_names": _SUBTYPES})


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
    base = {"embed": embed, "user": getattr(request.state, "user", None), "flash": flash, "impressum_live": accounts.impressum()[1], "privacy_live": accounts.privacy()[1], "metadata_lookup": get_settings().metadata_lookup, "max_upload_mb": get_settings().max_upload_mb, "max_movie_mb": get_settings().max_movie_mb,
            "providers": {cap: aisettings.enabled(cap) for cap in aisettings.CAPS}}
    resp = templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status_code)
    if raw:
        resp.delete_cookie(FLASH)
    return resp


def jpeg_response(path: Path) -> FileResponse:
    """A stored picture (thumbnail, cover, card, portrait): kept by the browser for a day, never sniffed as another type."""
    return FileResponse(path, media_type="image/jpeg", headers=IMAGE_HEADERS)


def zip_response(item: dict, tracks: list[dict]) -> FileResponse:
    """The album as one ZIP, built in a temporary file that is removed once it has been sent."""
    from . import albums
    tmp = tempfile.NamedTemporaryFile(dir=get_settings().tmp_dir, suffix=".zip", delete=False)
    tmp.close()
    albums.build_zip(item, tracks, Path(tmp.name))
    return FileResponse(tmp.name, media_type="application/zip", filename=f"{albums.safe_filename(item['title'])}.zip",
                        background=BackgroundTask(lambda: Path(tmp.name).unlink(missing_ok=True)))
