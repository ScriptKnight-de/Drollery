"""Online movie lookup: IMDb's search, and OMDb for the full details.

IMDb's own title pages sit behind a bot check, so they are not read. What works without any account is the search box
service that imdb.com itself uses (id, title, year, main cast, poster). The rest (plot, genres, directors, cast, rating,
runtime) comes from OMDb, which serves IMDb's data for a free API key that you enter in the settings. Nothing is ever
sent on its own: a lookup runs when someone presses the button and sends only the title they can see in the search field
(and the IMDb id of the picked title; with a key, the key as well). The client name is just `Drollery/<version>`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

from . import accounts, metadata
from .i18n import t
from .metadata import MetadataError

SUGGEST = "https://v3.sg.media-imdb.com/suggestion"
OMDB = "https://www.omdbapi.com/"
TITLE_PAGE = "https://www.imdb.com/title/"
IMDB_ID = re.compile(r"^tt\d{6,10}$")
IMAGE_HOSTS = ("media-amazon.com",)                  # a poster may only come from there (and its subdomains)
MAX_POSTER = 8 * 1024 * 1024
KEY_SETTING = "omdb_key"


@dataclass
class Candidate:
    imdb_id: str
    title: str
    year: str = ""
    kind: str = ""                       # IMDb's wording: "feature", "TV movie", "TV series" ...
    cast: str = ""                       # the main cast as IMDb's search shows it
    poster: str = ""


@dataclass
class Title:
    imdb_id: str
    title: str
    year: str = ""
    kind: str = ""
    plot: str = ""
    genres: list = field(default_factory=list)
    directors: list = field(default_factory=list)
    writers: list = field(default_factory=list)
    cast: list = field(default_factory=list)
    rating: float | None = None
    votes: int | None = None
    runtime: int | None = None           # minutes
    language: str = ""
    country: str = ""
    rated: str = ""
    released: str = ""
    poster: str = ""
    full: bool = False                   # True when OMDb supplied the details, False when only the search data is known

    @property
    def url(self) -> str:
        return TITLE_PAGE + self.imdb_id + "/"

    def details(self) -> dict:
        """What is kept on the movie besides the year and the IMDb id."""
        return {k: v for k, v in {
            "kind": self.kind, "plot": self.plot, "genres": self.genres, "directors": self.directors, "writers": self.writers,
            "cast": self.cast, "rating": self.rating, "votes": self.votes, "runtime": self.runtime, "language": self.language,
            "country": self.country, "rated": self.rated, "released": self.released}.items() if v not in ("", [], None)}


# ------------------------------------------------------------------ key

def key() -> str:
    return (accounts.get_setting(KEY_SETTING) or "").strip()


def has_key() -> bool:
    return bool(key())


# ---------------------------------------------------------------- search

def valid_id(imdb_id: str) -> bool:
    return bool(IMDB_ID.match(imdb_id or ""))


def _suggest(query: str) -> list[dict]:
    letter = (re.sub(r"[^a-z0-9]", "", query.lower())[:1]) or "x"
    r = metadata._get(f"{SUGGEST}/{letter}/{quote(query, safe='')}.json", None, "application/json", mb=False)
    if r.status_code != 200:
        raise MetadataError(t("The lookup service answered {status}", status=r.status_code))
    try:
        return [e for e in (r.json().get("d") or []) if isinstance(e, dict) and valid_id(str(e.get("id", "")))]
    except ValueError:
        raise MetadataError(t("The lookup service sent something unexpected")) from None


def _candidate(e: dict) -> Candidate:
    year = e.get("y")
    return Candidate(imdb_id=e["id"], title=str(e.get("l") or ""), year=str(year) if year else "", kind=str(e.get("q") or ""),
                     cast=str(e.get("s") or ""), poster=str((e.get("i") or {}).get("imageUrl") or ""))


def search(title: str, limit: int = 10) -> list[Candidate]:
    title = re.sub(r"\s+", " ", title or "").strip()[:100]
    if not title:
        raise MetadataError(t("Enter a movie title to search for"))
    return metadata._cached(("imdb-search", title.casefold(), limit), lambda: [_candidate(e) for e in _suggest(title)[:limit]])


def basic(imdb_id: str) -> Candidate | None:
    """What the search service knows about one id (it finds titles by their id as well)."""
    if not valid_id(imdb_id):
        raise MetadataError(t("That is not a valid IMDb title"))
    found = metadata._cached(("imdb-basic", imdb_id), lambda: [_candidate(e) for e in _suggest(imdb_id) if e["id"] == imdb_id])
    return found[0] if found else None


# --------------------------------------------------------------- details

def _clean(value) -> str:
    v = str(value or "").strip()
    return "" if v.upper() == "N/A" else v


def _list(value) -> list:
    return [x.strip() for x in _clean(value).split(",") if x.strip()]


def _int(value) -> int | None:
    digits = re.sub(r"[^\d]", "", _clean(value))
    return int(digits) if digits else None


def _omdb(imdb_id: str, api_key: str) -> dict:
    r = metadata._get(OMDB, {"i": imdb_id, "plot": "full", "apikey": api_key}, "application/json", mb=False)
    try:
        data = r.json()
    except ValueError:
        raise MetadataError(t("The lookup service sent something unexpected")) from None
    if r.status_code == 401 or "invalid api key" in str(data.get("Error", "")).lower():
        raise MetadataError(t("OMDb did not accept the key. Check it in the settings"))
    if "limit" in str(data.get("Error", "")).lower():
        raise MetadataError(t("The OMDb daily limit is used up. Try again tomorrow"))
    if r.status_code != 200 or str(data.get("Response")) != "True":
        raise MetadataError(t("The lookup service answered {status}", status=r.status_code if r.status_code != 200 else "no match"))
    return data


def title(imdb_id: str) -> Title:
    """Everything known about one title: from OMDb when a key is set, otherwise just what the search shows."""
    if not valid_id(imdb_id):
        raise MetadataError(t("That is not a valid IMDb title"))
    api_key = key()
    if api_key:
        return metadata._cached(("imdb-title", imdb_id), lambda: _full(imdb_id, api_key))
    c = basic(imdb_id)
    if c is None:
        raise MetadataError(t("The lookup service answered {status}", status="no match"))
    return Title(imdb_id=c.imdb_id, title=c.title, year=c.year, kind=c.kind, cast=[x.strip() for x in c.cast.split(",") if x.strip()], poster=c.poster)


def _full(imdb_id: str, api_key: str) -> Title:
    d = _omdb(imdb_id, api_key)
    c = basic(imdb_id)                                           # the poster of the search is the better one, OMDb's is a copy of it
    rating = _clean(d.get("imdbRating"))
    return Title(imdb_id=imdb_id, title=_clean(d.get("Title")), year=_clean(d.get("Year"))[:4], kind=(c.kind if c else _clean(d.get("Type"))),
                 plot=_clean(d.get("Plot")), genres=_list(d.get("Genre")), directors=_list(d.get("Director")), writers=_list(d.get("Writer")),
                 cast=_list(d.get("Actors")), rating=float(rating) if re.match(r"^\d+(\.\d+)?$", rating) else None, votes=_int(d.get("imdbVotes")),
                 runtime=_int(d.get("Runtime")), language=_clean(d.get("Language")), country=_clean(d.get("Country")), rated=_clean(d.get("Rated")),
                 released=_clean(d.get("Released")), poster=(c.poster if c and c.poster else _clean(d.get("Poster"))), full=True)


# ---------------------------------------------------------------- poster

def _host_ok(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS)


def poster(url: str) -> bytes | None:
    """The poster as image bytes, or None if there is none. Only the image host of IMDb is ever contacted, and redirects
    are followed by hand to the same hosts, so an answer of a lookup service cannot make this server fetch anything else."""
    if not url or not _host_ok(url):
        return None
    hit = metadata._cache.get(("poster", url))
    if hit and time.monotonic() - hit[0] < metadata.CACHE_SECONDS:
        return hit[1]
    for _ in range(4):
        r = metadata._get(url, None, "image/*", mb=False)
        if r.status_code in (301, 302, 303, 307, 308):
            url = r.headers.get("location", "")
            if not _host_ok(url):
                raise MetadataError(t("The lookup service sent something unexpected"))
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200 or len(r.content) > MAX_POSTER or not r.headers.get("content-type", "").startswith("image/"):
            raise MetadataError(t("The lookup service sent something unexpected"))
        if len(metadata._cache) < metadata.CACHE_ENTRIES:
            metadata._cache[("poster", url)] = (time.monotonic(), r.content)
        return r.content
    raise MetadataError(t("The lookup service sent something unexpected"))
