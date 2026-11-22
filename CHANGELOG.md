# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com), and the project
uses [Semantic Versioning](https://semver.org) (while it is 0.x, minor versions may still change behaviour).

## [0.8.0] - 2026-11-22

### Added
- **Tags remember merges.** When tags are merged or renamed, the old names are remembered: typed again by you, suggested again
  by the AI, added in bulk, or used in an old link or bookmark, they mean the new tag. The tags page lists these *remembered
  renames* and each one can be forgotten, which makes the old name an ordinary tag again. Chains are followed (a to b to c), and a
  name that is a real tag again redirects nowhere.
- **People list:** search (alias, first name, surname), sort by name, most items or newest, a filter *On no item* and *Delete the N
  people on no item* (after a confirmation with the number; their pictures go too).

### Fixed
- A person's page showed only the first 200 items and silently left out the rest. It now shows the first page and loads more as you
  scroll, like the library, and the heading says how many items the person is on.

## [0.7.0] - 2026-11-22

### Added
- **Settings > Tags:** every tag with its count as yours and as the AI's, searchable and sortable. **Rename** a tag for the whole
  library (to a name that exists, it is a **merge**; an item that had both keeps one copy, and yours wins over the AI's),
  **merge** several ticked tags into one, **delete** a tag everywhere (the AI is told not to bring it back on those items) and
  **keep as mine** the AI's copies of a tag. Joining tags asks first and says how many items it touches; the search follows.
- **Merge people:** on a person's page, *Merge with another person* shows what moves (items, filled-in details, the picture)
  and asks first. The target keeps its own values, gaps are filled from the merged person, which is then deleted. Settings >
  People points out **possible duplicates** (same alias or real name, ignoring case, spaces and accents) and suggests merging the
  one who knows less into the other.
- None of this can be undone, and every action is all-or-nothing: a failure changes nothing.

## [0.6.0] - 2026-11-22

### Added
- **Automatic backups** (Settings > Backup). Every day or every week (Sunday) at an hour you choose, Drollery makes a backup by
  itself: metadata only (the default, small) or everything, and keeps the newest N (7 by default). Off until switched on. The
  files go to the `backups` folder in the data volume, or to `backup_dir` from `config.toml`; they are owner-only and written
  to a `.part` file first, so a half-made one never looks finished. A backup missed while the server was off is made on the
  next start, a failed one shows its reason on the page and is tried again after an hour, and it is skipped with a message when
  the disk has no room. Only files Drollery made itself are ever listed, downloaded, deleted or pruned. The page lists them with
  *Download*, *Delete* and *Back up now*, and they restore like any other backup.

## [0.5.0] - 2026-11-22

### Added
- **Select several items in the library.** *Select* switches a selection mode on: a click marks a tile instead of opening it,
  Shift marks a range, Space or Enter marks a focused tile, Esc leaves the mode. A bar shows the count and offers *Select
  all loaded*, *Clear selection* and one action for all marked items: **add tags**, **remove tags**, **add a person**,
  **remove a person**, **run the AI** (everything, only transcribe or only describe) and **delete** (after a confirmation that
  names the number). The selection survives loading more tiles and changing the search; the count says when some chosen
  items are out of view. At most 500 items per action, items that no longer exist are skipped and counted, and your own tags are
  the only ones that change.

## [0.4.0] - 2026-11-22

### Added
- **Restore a backup in the browser.** On a Drollery that has no account yet, the first page has a second form, *Or restore a
  backup*: choose the `.tgz` from Settings > Backup, enter the setup code, and the library, accounts, settings, files and
  previews come back. The file is checked on the way in (only the parts a backup has, no links, no file name that leaves
  the folder, enough free disk space, an intact Drollery database with an account, not older than 0.1.0) and nothing is changed
  if it fails. The database goes in through SQLite's own backup, so no file is swapped under the running server. Nobody stays
  signed in from the backup, a restored `config.toml` replaces the default (the old one is kept as `config.toml.before-restore`),
  and a library that already has an account is never touched. After a metadata-only backup it says how many items have no file yet.
- **`python -m drollery restore FILE`** does the same on the server, for an empty data volume (`docker compose run --rm -v "$PWD":/backup
  drollery python -m drollery restore /backup/FILE`), with the same checks. `--check` only looks at a file and says what is in it
  (items, people, accounts, items without a file) and changes nothing, so a backup can be tested at any time.

## [0.3.0] - 2026-11-22

### Added
- **Sort menu** next to the type filters: automatic (relevance for a search, otherwise newest), newest, oldest, title A-Z and
  Z-A (Ä sorts with A), largest, longest, best match. The choice is kept while you load more.
- **German spellings in the search:** *Strasse* finds *Straße*, *Muenchen* finds *München*, *Ueber* finds *Über* and the other
  way round, in titles, descriptions, tags, transcripts, album tracks and names. Items you already have are indexed again once,
  in the background (a job called *Rebuild search* on the jobs page).
- The search, the filters and the sort order stay in the **address bar**, so a reload, a bookmark or the back button brings the
  same view back.

### Fixed
- A library with exactly 40 items (or any multiple of 40) no longer shows "The treasury is empty" under its tiles: the page that
  loads next and comes back empty adds nothing.

## [0.2.10] - 2026-11-22

### Fixed
- **0.2.6 to 0.2.9 were never published.** Their tests failed in the CI build: a test made its rotated video with an ffmpeg
  option that only exists from ffmpeg 6, and the build machine has an older one. So no image and no release were built for those
  versions. The tests now write the rotation into the MP4 file themselves and work with any ffmpeg. Nothing in the program
  changed. Everything that is listed under 0.2.6, 0.2.7, 0.2.8 and 0.2.9 below is part of this release.

## [0.2.9] - 2026-11-22

### Fixed
- On a phone the tables in the settings and on the jobs page (API keys, share links, background jobs, AI models, signed-in
  devices) are no longer cut off: they scroll inside their panel, so *Revoke*, *Regenerate*, *Copy*, *Retry* and *Delete* can be
  reached. The jobs page no longer scrolls sideways, and the *this device* mark in the device list is not clipped.
- The hint under the card image cropper and the words of the "nothing here" pages sit on a label plate instead of straight on
  the stone wall.

## [0.2.8] - 2026-11-22

### Fixed
- On a phone the library no longer scrolls sideways: the row of type filters (All, Images, GIFs ...) scrolls inside itself.
  The person page puts the picture above the facts and wraps long links.

### Changed
- The title, artist and tags of an album, and the text of a shared link (title, description, small print), sit on a panel
  or a label plate instead of straight on the stone wall, like the item page since 0.1.7. The same for the intro line of
  the people list and the other pages.
- On an album page the track list stays in view while you scroll the long forms next to it (a long list scrolls inside its
  own column). A closed *Edit details* panel on a person is just its title line.

## [0.2.7] - 2026-11-22

### Fixed
- Videos added before 0.2.6 get the size people see too: once, in the background, Drollery reads every stored video again
  (a job called *Check video sizes* on the jobs page) and corrects the size of those recorded on their side. Nothing else of
  an item changes, a missing or unreadable file is skipped, and the job is not queued again afterwards.

## [0.2.6] - 2026-11-22

### Fixed
- A video recorded on its side (a phone held upright) is stored with the size people see, 1080x1920 and not 1920x1080.
  The item page's *Dimensions* line and the player's shape are right from the start. Videos added earlier keep the size
  they were stored with; the player corrects its shape in the browser as before.

## [0.2.5] - 2026-11-22

### Changed
- A GIF on a library tile shows its still frame and **plays only while the pointer is on the tile** (or the tile has the
  keyboard focus). The GIF file is fetched only then, which also saves data in a long list. A GIF with a card image of
  its own keeps that picture, and people whose system asks for less motion never get the animation on the tiles.

## [0.2.4] - 2026-11-22

### Fixed
- The video player no longer changes its shape when the film loads: with a square card image as its preview it was
  square first and then jumped to the shape of the film. The player now has the film's ratio from the start (taken from
  the stored size, then confirmed by the browser), the picture sits centred in it and the rest is grey. The same on a
  shared link.

## [0.2.3] - 2026-11-22

### Changed
- A **GIF plays on its tile** in the library, on a loop, instead of showing a still frame. A GIF with a card image of its
  own keeps that picture, and people whose system asks for less motion (`prefers-reduced-motion`) still see the frame.

## [0.2.2] - 2026-11-22

### Changed
- A clip's **card image** is now also its preview where the video is shown: the poster of the player on its page and the
  picture of a shared link. Without a card image of its own it is still the frame of the video, as before.

## [0.2.1] - 2026-11-22

### Added
- People have an **alias** (the main name, shown everywhere, and used for the lookup) and optional **first name** and
  **surname**. Without an alias the real name stands in for it. The search bar, the people field and the item search find
  a person and their items under any of the three. People you already have keep their name as the alias.

## [0.2.0] - 2026-11-22

### Changed
- Databases made before Drollery 0.1.0 are no longer upgraded in place (the code for it is gone, about 70 lines). Such a
  database stops at start with a message that names the version that still does it, 0.1.7. Everything from 0.1.0 on
  starts as before.
- The unused "ocr" column of the items table and of the search index (a removed feature) is dropped when Drollery starts;
  the index is rebuilt once from the items, search keeps working.
- The number of background workers follows the setting through one supervisor instead of eight permanent loops.
- The light and dark palette is written once (`light-dark()`) instead of twice in the stylesheet; every page looks the
  same (checked pixel by pixel in both themes and with two highlight colours).

## [0.1.7] - 2026-11-22

### Fixed
- Adding a link (the "Paste a link" field in the upload zone) did nothing in 0.1.6: a comment in the Enter-key handler
  swallowed its closing brackets, so the whole upload script failed to load. A test now checks the syntax of every script.

## [0.1.6] - 2026-11-22

### Changed
- Internal tidy-up with the same behaviour: one helper each for "item or 404", the album ZIP download and stored pictures;
  retrying all failed jobs shares its code with retrying one. Thumbnails now also carry `X-Content-Type-Options: nosniff`
  like every other stored picture.
- `max_movie_mb` is in the default `config.toml` (it was only in the code and the docs), a test keeps the code, the file
  and the docs in step, and `pydantic` and `anyio`, which the code imports, are declared dependencies.
- The pop-up windows (confirmation, transcript, the framed pages) close on a click outside them through the browser's own
  `closedby="any"`; the old script stays only for browsers that lack it.
- Pressing Enter to confirm a word with an input method (Japanese, Chinese, Korean) in the link field no longer adds the
  half-typed link.
- Polish of the look, the character stays (stone wall, gold, folio numbers): the muted grey text now reaches 4.5:1 contrast
  in both themes (it was 3.6:1 in the light one); headings and the back link that sat straight on the wall get a label
  plate; radii follow size (controls 12, cards 16, panels 20) instead of nearly everything being a pill; weights are 400
  to 500 (600 only for headings); the small type sizes are 12 and 14; colour swatches and tag crosses no longer grow on
  hover. On an item page the title and tags are one panel and the picture stays in view while you scroll the forms.

## [0.1.5] - 2026-11-22

### Fixed
- A video added after another one was deleted could show the deleted video's preview picture on its page: the new item
  takes over the old id and the browser kept the old picture for a day. The preview address now changes with the item.

## [0.1.4] - 2026-11-22

### Added
- **Settings › AI models › Background jobs**: choose how many background jobs run at the same time (1 to 8). It applies
  at once, without a restart, and overrides `worker_concurrency` from `config.toml`.
- **Transcribe only** and **Describe only**: start one AI step on its own, for a single item (next to *Run again*) or for
  the whole library (Settings › AI models › Existing items). A transcription started this way does not go on to describe.
  Handy when the describing service is overloaded or you want the words first.

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
