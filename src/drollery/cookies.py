"""Cookies for downloads: a site that wants you signed in (YouTube's age check, a members-only gallery) is fetched with the
cookies of a browser that is signed in. The person pastes a cookies.txt (the Netscape format every browser exporter writes)
into Settings; it is stored on this server, never shown again, and only sent to the sites it names. yt-dlp and gallery-dl read
it as a file (a copy for each job, because yt-dlp writes back to the file it is given); direct downloads get it as a cookie jar."""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from . import accounts

SETTING = "download_cookies"
MAX_BYTES = 512 * 1024
HEADER = "# Netscape HTTP Cookie File"
_HTTPONLY = "#HttpOnly_"


class Cookie(NamedTuple):
    domain: str
    subdomains: str
    path: str
    secure: str
    expires: str
    name: str
    value: str


def parse(text: str) -> list[Cookie]:
    """The valid cookie lines of a cookies.txt. Comments, blank lines and anything that is not a cookie are skipped."""
    out: list[Cookie] = []
    for raw in text.splitlines():
        line = raw.strip("\r\n")
        if line.startswith(_HTTPONLY):                       # a cookie the page's scripts cannot read: still a cookie
            line = line[len(_HTTPONLY):]
        elif not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            parts = re.split(r"\s+", line.strip(), maxsplit=6)       # pasted with spaces instead of tabs
        if len(parts) != 7:
            continue
        domain, subdomains, path, secure, expires, name, value = (p.strip() for p in parts)
        if not re.fullmatch(r"\.?[A-Za-z0-9][A-Za-z0-9.\-]*", domain) or "." not in domain.lstrip("."):
            continue
        if subdomains.upper() not in ("TRUE", "FALSE") or secure.upper() not in ("TRUE", "FALSE") or not path.startswith("/") or not expires.isdigit() or not name:
            continue
        out.append(Cookie(domain, subdomains.upper(), path, secure.upper(), expires, name, value))
    return out


def normalize(text: str) -> str:
    """The cookies.txt to store: the header yt-dlp insists on, then only the valid lines."""
    return HEADER + "\n" + "\n".join("\t".join(c) for c in parse(text)) + "\n"


def stored() -> str:
    return accounts.get_setting(SETTING) or ""


def save(text: str) -> int:
    """Store pasted cookies. Returns how many were valid; 0 means nothing was stored."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        return 0
    cookies = parse(text)
    if not cookies:
        return 0
    accounts.set_setting(SETTING, normalize(text))
    return len(cookies)


def remove() -> None:
    accounts.set_setting(SETTING, None)


def sites() -> list[str]:
    """The sites the stored cookies belong to (the names are shown, the values never)."""
    return sorted({c.domain.lstrip(".").removeprefix("www.") for c in parse(stored())})


def write_file(folder: Path) -> Path | None:
    """A private copy of the cookies for one job (yt-dlp rewrites the file it is given), or None when there are none."""
    text = stored()
    if not text:
        return None
    path = folder / "cookies.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def apply_to_client(client) -> None:
    """Put the stored cookies on an httpx client; a cookie is only sent to the domain it was made for."""
    for c in parse(stored()):
        client.cookies.set(c.name, c.value, domain=c.domain if c.domain.startswith(".") or c.subdomains == "FALSE" else "." + c.domain, path=c.path)
