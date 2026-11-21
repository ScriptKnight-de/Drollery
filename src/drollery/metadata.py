"""Online album lookup: release details from MusicBrainz and the front cover from the Cover Art Archive.

Both are public, free and need no account. Nothing is ever sent on its own: a lookup runs only when someone presses
the button, and then it sends exactly what they can see on the search form (an album title and an artist), plus the
release id when they pick a result. MusicBrainz allows one request per second, so requests are spaced out.
"""
from __future__ import annotations

import difflib
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from . import __version__
from .config import get_settings
from .i18n import t

MB = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
RELEASE_PAGE = "https://musicbrainz.org/release/"
MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
IMAGE_HOSTS = ("coverartarchive.org", "archive.org")            # a cover may only come from these (and their subdomains)
MAX_COVER = 8 * 1024 * 1024
MIN_INTERVAL = 1.1                                              # seconds between requests to MusicBrainz

_lock = threading.Lock()
_last = [0.0]


class MetadataError(Exception):
    """The lookup could not be done; the message is meant for the person and already translated."""


@dataclass
class Candidate:
    mbid: str
    title: str
    artist: str
    date: str = ""
    country: str = ""
    label: str = ""
    tracks: int = 0
    score: int = 0
    note: str = ""                       # MusicBrainz's "disambiguation", e.g. "deluxe edition"


@dataclass
class RemoteTrack:
    disc: int
    position: int
    number: str
    title: str
    length: float | None = None          # seconds


@dataclass
class Release:
    mbid: str
    title: str
    artist: str
    date: str = ""
    label: str = ""
    country: str = ""
    tracks: list[RemoteTrack] = field(default_factory=list)

    @property
    def year(self) -> str:
        return self.date[:4] if re.match(r"\d{4}", self.date) else ""

    @property
    def url(self) -> str:
        return RELEASE_PAGE + self.mbid


# ------------------------------------------------------------------ http

def user_agent() -> str:
    return get_settings().metadata_user_agent.strip() or f"Drollery/{__version__}"


def _sleep(seconds: float) -> None:        # a seam for tests
    time.sleep(seconds)


def _send(url: str, params: dict | None, accept: str) -> httpx.Response:        # a seam for tests
    with httpx.Client(timeout=15, headers={"User-Agent": user_agent(), "Accept": accept}, follow_redirects=False) as c:
        return c.get(url, params=params)


def _spaced() -> None:
    with _lock:
        wait = _last[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            _sleep(wait)
        _last[0] = time.monotonic()


def _get(url: str, params: dict | None = None, accept: str = "application/json", mb: bool = True) -> httpx.Response:
    """One GET with a polite pause, and a retry when MusicBrainz says it is busy (503)."""
    last_error = ""
    for attempt in range(3):
        if mb:
            _spaced()
        try:
            r = _send(url, params, accept)
        except httpx.HTTPError as e:
            last_error = type(e).__name__
            _sleep(1.5)
            continue
        if r.status_code in (429, 503) and attempt < 2:
            _sleep(2.0)
            continue
        return r
    raise MetadataError(t("Could not reach the lookup service ({error})", error=last_error or "busy"))


def _json(url: str, params: dict) -> dict:
    r = _get(url, params)
    if r.status_code != 200:
        raise MetadataError(t("The lookup service answered {status}", status=r.status_code))
    try:
        return r.json()
    except ValueError:
        raise MetadataError(t("The lookup service sent something unexpected")) from None


# ---------------------------------------------------------------- search

_LUCENE = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def _q(text: str) -> str:
    return _LUCENE.sub(r"\\\1", text.strip())


def _credit(credits) -> str:
    return "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in (credits or [])).strip()


def search(title: str, artist: str = "", limit: int = 8) -> list[Candidate]:
    title, artist = title.strip()[:200], artist.strip()[:200]
    if not title and not artist:
        raise MetadataError(t("Enter an album title or an artist to search for"))
    parts = [f'release:"{_q(title)}"'] if title else []
    if artist:
        parts.append(f'artist:"{_q(artist)}"')
    data = _json(f"{MB}/release/", {"query": " AND ".join(parts), "fmt": "json", "limit": limit})
    out = []
    for r in data.get("releases", []):
        if not MBID.match(r.get("id", "")):
            continue
        labels = [li["label"]["name"] for li in r.get("label-info", []) if li.get("label") and li["label"].get("name")]
        out.append(Candidate(mbid=r["id"], title=r.get("title", ""), artist=_credit(r.get("artist-credit")), date=r.get("date", ""),
                             country=r.get("country", ""), label=labels[0] if labels else "", tracks=int(r.get("track-count") or 0),
                             score=int(r.get("score") or 0), note=r.get("disambiguation", "")))
    return out


def release(mbid: str) -> Release:
    if not MBID.match(mbid or ""):
        raise MetadataError(t("That is not a valid release"))
    d = _json(f"{MB}/release/{mbid}", {"inc": "recordings+artist-credits+labels", "fmt": "json"})
    labels = [li["label"]["name"] for li in d.get("label-info", []) if li.get("label") and li["label"].get("name")]
    rel = Release(mbid=mbid, title=d.get("title", ""), artist=_credit(d.get("artist-credit")), date=d.get("date", ""),
                  label=labels[0] if labels else "", country=d.get("country", ""))
    for disc_no, medium in enumerate(d.get("media", []), 1):
        for tr in medium.get("tracks", []):
            length = tr.get("length") or (tr.get("recording") or {}).get("length")
            rel.tracks.append(RemoteTrack(disc=int(medium.get("position") or disc_no), position=int(tr.get("position") or 0), number=str(tr.get("number") or ""),
                                          title=(tr.get("title") or (tr.get("recording") or {}).get("title") or "").strip(),
                                          length=length / 1000 if length else None))
    return rel


# ----------------------------------------------------------------- cover

def _host_ok(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS)


def cover(mbid: str) -> bytes | None:
    """The front cover (500 px) as image bytes, or None if there is none. Redirects are followed by hand and only
    to the Cover Art Archive and archive.org, so the answer of a lookup service cannot make the server fetch anything else."""
    if not MBID.match(mbid or ""):
        raise MetadataError(t("That is not a valid release"))
    url = f"{CAA}/release/{mbid}/front-500"
    for hop in range(6):
        r = _get(url, accept="image/*", mb=(hop == 0))
        if r.status_code in (301, 302, 303, 307, 308):
            url = r.headers.get("location", "")
            if not _host_ok(url):
                raise MetadataError(t("The lookup service sent something unexpected"))
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise MetadataError(t("The lookup service answered {status}", status=r.status_code))
        if len(r.content) > MAX_COVER or not r.headers.get("content-type", "").startswith("image/"):
            raise MetadataError(t("The lookup service sent something unexpected"))
        return r.content
    raise MetadataError(t("The lookup service sent something unexpected"))


# -------------------------------------------------------------- matching

def _norm(text: str) -> str:
    text = re.sub(r"^\s*\d{1,3}\s*[-._)\]:]+\s*", "", text.casefold())
    return re.sub(r"[^\w]+", " ", text).strip()


def match_tracks(local: list[dict], remote: list[RemoteTrack]) -> dict[int, int]:
    """Which online track belongs to which of the album's own tracks: local track id -> index into `remote`.
    Titles count most, lengths help, and when both lists are equally long the same position gets a small bonus.
    A pair is only accepted when it is convincing, so a track the release does not have simply keeps its title."""
    pairs = []
    same_count = len(local) == len(remote)
    for i, lt in enumerate(local):
        for j, rt in enumerate(remote):
            ratio = difflib.SequenceMatcher(None, _norm(lt["title"]), _norm(rt.title)).ratio()
            if lt.get("duration") and rt.length:
                dur = max(0.0, 1 - abs(lt["duration"] - rt.length) / 30)
            else:
                dur = 0.5
            score = 0.65 * ratio + 0.35 * dur + (0.08 if same_count and i == j else 0)
            pairs.append((score, i, j))
    pairs.sort(reverse=True)
    out, used_l, used_r = {}, set(), set()
    for score, i, j in pairs:
        if score < 0.55 or i in used_l or j in used_r:
            continue
        out[local[i]["id"]] = j
        used_l.add(i)
        used_r.add(j)
    return out
