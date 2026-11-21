# Development

## Run it from source

```bash
git clone https://forgejo.scriptknight.de/scriptknight/drollery.git && cd drollery
uv venv && uv pip install -e '.[dev]'      # Python 3.11 or newer; ffmpeg must be on the PATH
.venv/bin/pytest                           # the whole suite takes about a minute and a half
DROLLERY_DATA=./data .venv/bin/uvicorn drollery.main:app --reload
```

The first request opens the setup page; the one-time setup code is printed in the terminal. Always set `DROLLERY_DATA`
when you run it by hand, otherwise a `data/` folder appears wherever you are.

## How it is built

- **FastAPI** serves everything; pages are **Jinja2** templates with a little **htmx** and plain JavaScript (no build step).
- **SQLite** holds the data, with **FTS5** for full-text search. Files live next to the database in the data folder.
- A single background worker runs the jobs (downloads, transcription, naming) one at a time.
- `ffmpeg` makes thumbnails, reads file details and cuts audio; `yt-dlp` and `gallery-dl` download links.
- Online lookups live in `metadata.py` (MusicBrainz) and `imdb.py` (IMDb, OMDb, TMDB); the address check for links is in
  `netguard.py`.

## Tests

`tests/` uses only invented data, and the network is always replaced by fakes. `tests/test_hygiene.py` keeps the
repository clean (no secrets, no personal content, no stray media, no unused imports, no stale translations).

## Translating

The English text in the code is the key. A language is one file, `src/drollery/locales/<code>.py`, with `NAME` and a
`MESSAGES` dict (copy `de.py`); list the code in `LOCALES` in `src/drollery/i18n.py`, add its flag as
`templates/flags/<country>.svg`, and it appears in the language menu.

- `t("Text")` in Python and `_("Text")` in templates mark a string. `{name}` placeholders keep their names in every
  language, and plurals are `(one, other)` pairs (`tn` / `_n`); a language that needs more forms sets `FORMS` and a
  `plural(n)` function.
- `python scripts/i18n_scan.py` lists what a catalog still lacks, and the tests fail when a string is missing or a
  placeholder differs.
- Titles, tags and the Impressum text are your own content and are never translated.

## Adding an AI provider type

A provider type is one function plus one line in the registry dict at the bottom of the matching section of
`src/drollery/providers.py`.
