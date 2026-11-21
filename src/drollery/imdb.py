"""Online movie lookup: IMDb's search and OMDb in English, TMDB in the language the tool is set to.

IMDb's own title pages sit behind a bot check, so they are not read. What works without any account is the search box
service that imdb.com itself uses (id, title, year, main cast, poster); it only knows the English titles. OMDb serves
IMDb's data (plot, genres, directors, cast, rating, runtime), also only in English, for a free key. TMDB serves all of that
in the language chosen for Drollery (German titles, plots, genres and posters) and finds a movie by its IMDb id, for a
free key. A key is entered in the settings and used when there is one. Nothing is ever sent on its own: a lookup runs when
someone presses the button and sends only the title they can see in the search field (and the id of the picked title;
with a key, the key as well). The client name is just `Drollery/<version>`.
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
TMDB = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w500"
TMDB_PAGE = "https://www.themoviedb.org/"
TMDB_KEY_SETTING = "tmdb_key"
TMDB_KEY = re.compile(r"^[0-9a-f]{32}$")
REF = re.compile(r"^(tt\d{6,10}|[mt]\d{1,9})$")      # an IMDb id, or a TMDB movie (m603) or series (t1399)
LOCALES = {"en": "en-US", "de": "de-DE", "es": "es-ES", "fr": "fr-FR", "it": "it-IT", "nl": "nl-NL", "pl": "pl-PL", "sv": "sv-SE", "el": "el-GR"}
OMDB = "https://www.omdbapi.com/"
TITLE_PAGE = "https://www.imdb.com/title/"
IMDB_ID = re.compile(r"^tt\d{6,10}$")
IMAGE_HOSTS = ("media-amazon.com", "tmdb.org")       # a poster may only come from there (and their subdomains)
MAX_POSTER = 8 * 1024 * 1024
KEY_SETTING = "omdb_key"


@dataclass
class Candidate:
    ref: str                             # an IMDb id (tt...) or a TMDB reference (m603, t1399)
    title: str
    year: str = ""
    kind: str = ""                       # IMDb's wording ("feature", "TV movie" ...) or "Movie" / "TV series"
    cast: str = ""                       # the main cast as IMDb's search shows it
    poster: str = ""
    original: str = ""                   # the original title, when TMDB shows a translated one
    overview: str = ""

    @property
    def imdb_id(self) -> str:
        return self.ref if self.ref.startswith("tt") else ""


@dataclass
class Title:
    imdb_id: str                         # empty when the title is known by TMDB only
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
    full: bool = False                   # True when OMDb or TMDB supplied the details, False when only the search data is known
    source: str = "IMDb"                 # where the details came from: IMDb (search only), OMDb or TMDB
    rating_source: str = "IMDb"
    original_title: str = ""
    tmdb_ref: str = ""                   # m603 / t1399 when TMDB knows the title

    @property
    def url(self) -> str:
        if self.imdb_id:
            return TITLE_PAGE + self.imdb_id + "/"
        return TMDB_PAGE + ("movie/" if self.tmdb_ref.startswith("m") else "tv/") + self.tmdb_ref[1:] if self.tmdb_ref else ""

    def details(self) -> dict:
        """What is kept on the movie besides the year and the IMDb id."""
        return {k: v for k, v in {
            "kind": self.kind, "plot": self.plot, "genres": self.genres, "directors": self.directors, "writers": self.writers,
            "cast": self.cast, "rating": self.rating, "rating_source": self.rating_source if self.rating is not None else "", "votes": self.votes,
            "runtime": self.runtime, "language": self.language, "country": self.country, "rated": self.rated, "released": self.released}.items() if v not in ("", [], None)}


# ------------------------------------------------------------------ keys

def key() -> str:
    return (accounts.get_setting(KEY_SETTING) or "").strip()


def has_key() -> bool:
    return bool(key())


def tmdb_key() -> str:
    return (accounts.get_setting(TMDB_KEY_SETTING) or "").strip()


def has_tmdb() -> bool:
    return bool(tmdb_key())


def locale(language: str) -> str:
    """The language code TMDB wants for one of Drollery's languages (English when it is one we do not know)."""
    return LOCALES.get(language, "en-US")


# ---------------------------------------------------------------- search

def valid_id(imdb_id: str) -> bool:
    return bool(IMDB_ID.match(imdb_id or ""))


def valid_ref(ref: str) -> bool:
    return bool(REF.match(ref or ""))


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
    return Candidate(ref=e["id"], title=str(e.get("l") or ""), year=str(year) if year else "", kind=str(e.get("q") or ""),
                     cast=str(e.get("s") or ""), poster=str((e.get("i") or {}).get("imageUrl") or ""))


def search(title: str, language: str = "en", limit: int = 10) -> list[Candidate]:
    """Matching titles: from TMDB in `language` when a TMDB key is set, else from IMDb's search (English)."""
    title = re.sub(r"\s+", " ", title or "").strip()[:100]
    if not title:
        raise MetadataError(t("Enter a movie title to search for"))
    tk = tmdb_key()
    if tk:
        loc = locale(language)
        return metadata._cached(("tmdb-search", title.casefold(), loc, limit), lambda: _tmdb_search(title, loc, tk, limit))
    return metadata._cached(("imdb-search", title.casefold(), limit), lambda: [_candidate(e) for e in _suggest(title)[:limit]])


def basic(imdb_id: str) -> Candidate | None:
    """What the search service knows about one id (it finds titles by their id as well)."""
    if not valid_id(imdb_id):
        raise MetadataError(t("That is not a valid IMDb title"))
    found = metadata._cached(("imdb-basic", imdb_id), lambda: [_candidate(e) for e in _suggest(imdb_id) if e["id"] == imdb_id])
    return found[0] if found else None


# ------------------------------------------------------------------ TMDB

def _tmdb(path: str, params: dict, api_key: str) -> dict:
    r = metadata._get(TMDB + path, {**params, "api_key": api_key}, "application/json", mb=False)
    if r.status_code == 401:
        raise MetadataError(t("TMDB did not accept the key. Check it in the settings"))
    if r.status_code == 404:
        raise MetadataError(t("The lookup service answered {status}", status="no match"))
    if r.status_code != 200:
        raise MetadataError(t("The lookup service answered {status}", status=r.status_code))
    try:
        data = r.json()
    except ValueError:
        raise MetadataError(t("The lookup service sent something unexpected")) from None
    return data if isinstance(data, dict) else {}


def _tmdb_search(query: str, loc: str, api_key: str, limit: int) -> list[Candidate]:
    data = _tmdb("/search/multi", {"query": query, "language": loc, "include_adult": "false", "page": 1}, api_key)
    out = []
    for e in data.get("results") or []:
        kind = e.get("media_type")
        if kind not in ("movie", "tv") or not isinstance(e.get("id"), int):
            continue
        shown = str(e.get("title") or e.get("name") or "")
        original = str(e.get("original_title") or e.get("original_name") or "")
        poster = e.get("poster_path") or ""
        out.append(Candidate(ref=("m" if kind == "movie" else "t") + str(e["id"]), title=shown, year=str(e.get("release_date") or e.get("first_air_date") or "")[:4],
                             kind=t("Movie") if kind == "movie" else t("TV series"), original=original if original and original != shown else "",
                             overview=str(e.get("overview") or "")[:160], poster=(TMDB_IMAGE + poster) if poster.startswith("/") else ""))
        if len(out) >= limit:
            break
    return out


def _find_tmdb(imdb_id: str, loc: str, api_key: str) -> str:
    """The TMDB reference (m603 / t1399) of an IMDb id, or "" when TMDB does not know it."""
    data = _tmdb(f"/find/{imdb_id}", {"external_source": "imdb_id", "language": loc}, api_key)
    for kind, tag in (("movie_results", "m"), ("tv_results", "t")):
        for e in data.get(kind) or []:
            if isinstance(e.get("id"), int):
                return tag + str(e["id"])
    return ""


def _tmdb_title(ref: str, loc: str, api_key: str) -> Title:
    movie = ref.startswith("m")
    d = _tmdb(f"/{'movie' if movie else 'tv'}/{ref[1:]}", {"language": loc, "append_to_response": "credits,external_ids"}, api_key)
    credits = d.get("credits") or {}
    names = lambda rows: [str(x.get("name")) for x in rows if isinstance(x, dict) and x.get("name")]
    directors = names([c for c in credits.get("crew") or [] if c.get("job") == "Director"]) if movie else names(d.get("created_by") or [])
    cast = names(credits.get("cast") or [])[:8]
    runtime = d.get("runtime") if movie else ((d.get("episode_run_time") or [None])[0])
    imdb_id = str(d.get("imdb_id") or (d.get("external_ids") or {}).get("imdb_id") or "")
    votes = d.get("vote_count") or 0
    poster = d.get("poster_path") or ""
    shown = str(d.get("title") or d.get("name") or "")
    original = str(d.get("original_title") or d.get("original_name") or "")
    return Title(imdb_id=imdb_id if valid_id(imdb_id) else "", title=shown, year=str(d.get("release_date") or d.get("first_air_date") or "")[:4],
                 kind=t("Movie") if movie else t("TV series"), plot=str(d.get("overview") or "").strip(), genres=names(d.get("genres") or []),
                 directors=directors, cast=cast, rating=round(float(d["vote_average"]), 1) if votes and d.get("vote_average") else None, votes=votes or None,
                 runtime=int(runtime) if isinstance(runtime, int) and runtime > 0 else None,
                 language=", ".join(str(x.get("name") or x.get("english_name")) for x in d.get("spoken_languages") or [] if x.get("name") or x.get("english_name")),
                 country=", ".join(str(x.get("name")) for x in d.get("production_countries") or [] if x.get("name")),
                 poster=(TMDB_IMAGE + poster) if poster.startswith("/") else "", full=True, source="TMDB", rating_source="TMDB",
                 original_title=original if original != shown else "", tmdb_ref=ref)


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


def title(ref: str, language: str = "en") -> Title:
    """Everything known about one title. With a TMDB key it comes from TMDB in `language` (an IMDb id is looked up there, and
    the IMDb rating is added when an OMDb key is set). Otherwise from OMDb when a key is set, else just what IMDb's search shows."""
    if not valid_ref(ref):
        raise MetadataError(t("That is not a valid IMDb title"))
    tk = tmdb_key()
    if tk:
        loc = locale(language)
        got = metadata._cached(("tmdb-title", ref, loc, bool(key())), lambda: _tmdb_full(ref, loc, tk))
        if got is not None:
            return got
    if not valid_id(ref):
        raise MetadataError(t("The lookup service answered {status}", status="no match"))          # a TMDB reference needs the key it came from
    api_key = key()
    if api_key:
        return metadata._cached(("imdb-title", ref, True), lambda: _full(ref, api_key))
    c = basic(ref)
    if c is None:
        raise MetadataError(t("The lookup service answered {status}", status="no match"))
    return Title(imdb_id=c.imdb_id, title=c.title, year=c.year, kind=c.kind, cast=[x.strip() for x in c.cast.split(",") if x.strip()], poster=c.poster)


def _tmdb_full(ref: str, loc: str, tk: str) -> Title | None:
    if valid_id(ref):
        found = _find_tmdb(ref, loc, tk)
        if not found:
            return None                                          # TMDB does not know this one: the caller falls back to IMDb / OMDb
        ref_tmdb, imdb_hint = found, ref
    else:
        ref_tmdb, imdb_hint = ref, ""
    info = _tmdb_title(ref_tmdb, loc, tk)
    if not info.imdb_id and imdb_hint:
        info.imdb_id = imdb_hint
    omdb_key = key()
    if omdb_key and info.imdb_id:                                # the IMDb rating is the one people know; OMDb has it
        try:
            d = _omdb(info.imdb_id, omdb_key)
            rating = _clean(d.get("imdbRating"))
            if re.match(r"^\d+(\.\d+)?$", rating):
                info.rating, info.votes, info.rating_source = float(rating), _int(d.get("imdbVotes")), "IMDb"
        except MetadataError:
            pass
    return info


def _full(imdb_id: str, api_key: str) -> Title:
    d = _omdb(imdb_id, api_key)
    c = basic(imdb_id)                                           # the poster of the search is the better one, OMDb's is a copy of it
    rating = _clean(d.get("imdbRating"))
    return Title(imdb_id=imdb_id, title=_clean(d.get("Title")), year=_clean(d.get("Year"))[:4], kind=(c.kind if c else _clean(d.get("Type"))),
                 plot=_clean(d.get("Plot")), genres=_list(d.get("Genre")), directors=_list(d.get("Director")), writers=_list(d.get("Writer")),
                 cast=_list(d.get("Actors")), rating=float(rating) if re.match(r"^\d+(\.\d+)?$", rating) else None, votes=_int(d.get("imdbVotes")),
                 runtime=_int(d.get("Runtime")), language=_clean(d.get("Language")), country=_clean(d.get("Country")), rated=_clean(d.get("Rated")),
                 released=_clean(d.get("Released")), poster=(c.poster if c and c.poster else _clean(d.get("Poster"))), full=True, source="OMDb")


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
