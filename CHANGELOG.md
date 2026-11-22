# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com), and the project
uses [Semantic Versioning](https://semver.org) (while it is 0.x, minor versions may still change behaviour).

## [0.1.3] - 2026-11-22

### Added
- **Settings › Backup**: download the library as one `.tgz`, either everything or metadata only. It is streamed (no extra
  disk space, the download starts at once), consistent while Drollery runs, and restores with the documented steps.
- **`python -m drollery reset-admin`**: a way back in when the password (and the two-factor device) are lost. It sets a new
  one-time password, turns two-factor off and signs the account out everywhere.
- **Custom provider** preset for any OpenAI-compatible service.
- The model is **chosen from the list the server offers** (queried automatically once the address is known), with
  *Other…* for a name that is not listed. Gemini's `models/` prefix is removed from the names.
- **Delete** a failed background job, or **Delete failed** to clear them all, on the jobs page (after a confirmation).
  Only failed jobs can be deleted; nothing is retried and no item is touched.

### Changed
- A failed AI call now says what the service answered (for example Google's "model is overloaded") and what to check.
  A busy or rate-limited service (HTTP 429 or 5xx) makes the job wait five minutes per attempt instead of 30 seconds.

## [0.1.2] - 2026-11-22

### Fixed
- The optional Whisper stack no longer fails with `Permission denied` (HTTP 500 from the model download) when the model
  volume already holds root-owned files: a small one-shot step (`whisper-permissions`) hands the volume to the Whisper
  user before the server starts. The model helper's failure hint now names this cause as well.

## [0.1.1] - 2026-11-22

### Changed
- `docker-compose.yml` now pulls the ready-made image by default (`ghcr.io/scriptknight-de/drollery:latest`);
  `DROLLERY_IMAGE` in `.env` pins a version, and `docker compose up -d --build` still builds from the source folder.

### Fixed
- The optional Whisper model helper no longer hides why a download failed: it prints the HTTP code, what the Whisper
  server answered and the usual cause (for example that the server cannot reach `huggingface.co`), and retries when the
  problem might pass.

### Documentation
- How to run the ready-made image with `docker run` or Compose, and what to do when the Whisper model does not download.

## [0.1.0] - 2026-11-21

First public release.

### Library
- Self-hosted library for **images, GIFs, clips, sounds, albums/audiobooks and movies** (films, parodies, synchros),
  with fast full-text search (SQLite FTS5), tags, custom card images and public share links.
- **One upload zone** for everything: drop or choose files, or paste a link; it suggests what the files should become and
  shows a progress bar with speed, time left and cancel.
- **Sound cards** with a round play button in a colour of their own, playing right on the card.
- **People** (creators and everyone involved) stored once and linked to any item; items are found by their names.

### Lookups (only when you ask)
- Albums from **MusicBrainz** and the Cover Art Archive; movies from **IMDb**'s search, with details from **OMDb** or,
  in the language chosen for the page, from **TMDB** (optional keys under *Settings › Online lookup*).

### AI (optional, nothing bundled)
- Naming, tagging and transcription through any OpenAI-compatible API or a local command; an optional Whisper container.

### Accounts and security
- First-run setup code, scrypt password hashing, optional two-factor authentication with backup codes, login
  throttling, per-device API keys, and confirmation dialogs inside the app.

### Distribution
- A ready-made Docker image for `linux/amd64` and `linux/arm64` is built by CI and published to
  `ghcr.io/scriptknight-de/drollery` (and the Forgejo registry): `latest`, the version (`0.1.0`) and the minor (`0.1`).

### Hardening
- Links to private, loopback and link-local addresses are not fetched by default (checked when a link is added, when the
  download runs and on redirects); `allow_private_fetch` and `fetch_allow_hosts` in `config.toml` relax it on purpose.
- The interactive API docs and the schema are not served, and the public health check no longer reports the version.

### Interface
- Light, dark or system theme, ten highlight colours, English and German, and an optional Impressum page.
