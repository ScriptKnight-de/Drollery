"""Translations. The English text is the key: `t("Save")` returns the German catalog's entry for it, or the English
text itself when there is none, so a missing translation never breaks a page.

    t("Profile saved")                      plain text
    t("Showing {n} of {total}", n=3, total=9)    placeholders (the catalog entry keeps the same {names})
    tn("{n} item", "{n} items", count)      plural; the catalog entry is a tuple of forms (two by default; a locale
                                            with more sets FORMS and a plural(n) -> index function)

Templates use the same function as `_()` and `_n()`. The language of a request is chosen once, in the
middleware, and lives in a context variable, so code deep in a handler needs no request object.

To add a language: create `locales/<code>.py` with `NAME`, `FLAG` (a country code; add `templates/flags/<code>.svg`) and `MESSAGES`, and list it in `LOCALES` below.
`tests/test_i18n.py` fails when a catalog lacks a string used in the code, or when placeholders differ.
"""
from __future__ import annotations

import contextvars
import importlib

LOCALES = ("de", "es", "fr", "it", "nl", "pl", "sv", "el")
DEFAULT = "en"
COOKIE = "drollery_lang"

_catalogs: dict[str, dict] = {}
_current: contextvars.ContextVar[str] = contextvars.ContextVar("drollery_lang", default=DEFAULT)


def _load() -> None:
    if _catalogs:
        return
    for code in LOCALES:
        mod = importlib.import_module(f"{__package__}.locales.{code}")
        _catalogs[code] = {"name": mod.NAME, "messages": mod.MESSAGES}


def languages() -> dict[str, str]:
    """code -> the language's own name, English first."""
    _load()
    return {DEFAULT: "English", **{code: c["name"] for code, c in _catalogs.items()}}


def flag(code: str) -> str:
    """Country code of the flag shown for a language (English uses the British flag)."""
    _load()
    return "gb" if code == DEFAULT else getattr(importlib.import_module(f"{__package__}.locales.{code}"), "FLAG", code)


def catalog(code: str) -> dict:
    _load()
    return _catalogs[code]["messages"]


def normalize(code: str | None) -> str:
    """'de-AT' -> 'de'; anything we do not have -> ''."""
    _load()
    code = (code or "").strip().lower().replace("_", "-").split("-")[0]
    return code if code == DEFAULT or code in _catalogs else ""


def from_accept_language(header: str) -> str:
    """Best supported language of an Accept-Language header, else the default."""
    ranked = []
    for part in (header or "").split(","):
        tag, _, q = part.strip().partition(";q=")
        try:
            weight = float(q) if q else 1.0
        except ValueError:
            weight = 0.0
        if tag and weight > 0:
            ranked.append((weight, tag))
    for _, tag in sorted(ranked, key=lambda r: -r[0]):
        code = normalize(tag)
        if code:
            return code
    return DEFAULT


def set_language(code: str):
    return _current.set(normalize(code) or DEFAULT)


def current() -> str:
    return _current.get()


def t(text: str, **kw) -> str:
    _load()
    entry = _catalogs.get(_current.get(), {}).get("messages", {}).get(text, text)
    if isinstance(entry, tuple):                  # a plural entry used without a count: take the singular
        entry = entry[0]
    return entry.format(**kw) if kw else entry


def N_(text: str) -> str:
    """Mark a string for translation without translating it now (module-level constants); translate it where it is shown."""
    return text


def forms(code: str) -> int:
    """How many plural forms a language's catalog entries carry (2 unless the locale says FORMS)."""
    _load()
    return getattr(importlib.import_module(f"{__package__}.locales.{code}"), "FORMS", 2) if code != DEFAULT else 2


def plural_index(code: str, n: int) -> int:
    """Which form of a plural entry to use for n. A locale can define plural(n) -> int; the default is 0 for 1, else 1."""
    if code == DEFAULT:
        return 0 if n == 1 else 1
    rule = getattr(importlib.import_module(f"{__package__}.locales.{code}"), "plural", None)
    return rule(n) if rule else (0 if n == 1 else 1)


def tn(one: str, other: str, n: int, **kw) -> str:
    _load()
    code = _current.get()
    entry = _catalogs.get(code, {}).get("messages", {}).get(one)
    if isinstance(entry, tuple) and len(entry) == forms(code):
        text = entry[min(plural_index(code, n), len(entry) - 1)]
    else:
        text = one if n == 1 else other
    return text.format(n=n, **kw)
