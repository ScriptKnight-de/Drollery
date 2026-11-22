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

## Releases and the Docker image

`.forgejo/workflows/build.yml` (the same pipeline the other ScriptKnight projects use) does three things:

1. **Tests** on every push to `main` and on every `v*` tag. The runner installs `ffmpeg`, and the job **fails if any test is
   skipped**, because the suite skips whatever needs ffmpeg when it is missing and would otherwise look green.
2. **Builds and publishes the image** for `linux/amd64` and `linux/arm64` (so a Raspberry Pi can run it) to the Forgejo
   registry (`forgejo.scriptknight.de/scriptknight/drollery`) and to GitHub Container Registry
   (`ghcr.io/scriptknight-de/drollery`). A push to `main` gives `latest` and `sha-<commit>`; a tag `v1.2.3` gives `1.2.3`
   and `1.2`.
3. **Publishes a release** on Forgejo and GitHub for a `v*` tag, with that version's section of `CHANGELOG.md` as the notes
   (the GitHub step is skipped if that repository does not exist).

Every Monday (and on demand: *Actions › build-image › Run workflow › rebuild*) it **rebuilds the newest release tag from
scratch**, so the base image and the Debian packages (ffmpeg) stay current, and scans the result with Trivy; the run fails
on a CRITICAL vulnerability that already has a fix.

### One-time setup

Add these secrets under *Settings › Actions › Secrets* of the repository (the same four the other projects use):

| Secret | What |
|---|---|
| `REGISTRY_USER` | the Forgejo user that owns the package (`scriptknight`) |
| `REGISTRY_TOKEN` | a Forgejo access token with `write:package` and `write:repository` (releases) |
| `GH_USER` | the GitHub user that owns the repository (`ScriptKnight-de`) |
| `GH_TOKEN` | a GitHub **classic** personal access token with `write:packages` and `repo` (GHCR does not take fine-grained tokens) |

The runner needs the label `docker` and a docker-in-docker daemon reachable as `dind` (see the comment at the top of the
workflow). Afterwards, make the GHCR package public (*GitHub › Packages › drollery › Package settings*) if strangers
should be able to pull it.

### Making a release

1. Raise the version in `pyproject.toml` and in `src/drollery/__init__.py` (they must match), and add the section
   `## [x.y.z] - date` to `CHANGELOG.md`. The tests check all three.
2. Commit, push, and tag: `git tag v0.2.8 && git push origin v0.2.8`.
3. The workflow tests, publishes `0.2.8` and `0.2`, and creates the releases.

To run a published image instead of building it, pull it and point the compose service at it
(`image: ghcr.io/scriptknight-de/drollery:latest`).

