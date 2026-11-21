# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com), and the project
uses [Semantic Versioning](https://semver.org) (while it is 0.x, minor versions may still change behaviour).

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

### Interface
- Light, dark or system theme, ten highlight colours, English and German, and an optional Impressum page.
