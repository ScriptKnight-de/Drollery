# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com), and the project
uses [Semantic Versioning](https://semver.org) (while it is 0.x, minor versions may still change behaviour).

## [Unreleased]

## [0.19.1] - 2026-11-25

### Fixed
- YouTube links failed with "Requested format is not available" (also with cookies saved): YouTube only lists the real video formats after a script challenge is solved, and the image had neither the helper scripts (`yt-dlp-ejs`) nor a JavaScript runtime. Both are installed now (`yt-dlp[default]` and `deno`, for amd64 and arm64).

## [0.19.0] - 2026-11-25

### Added
- Settings > Cookies: paste the cookies.txt of a browser that is signed in, and downloads of links use it (yt-dlp, gallery-dl and direct file downloads). That is the answer to "Sign in to confirm your age" and to members-only galleries. The cookies are write-only (only the site names are shown), a cookie is only sent to the site it belongs to, and each job works on its own private copy of the file. A failed download that asks for cookies now says where to add them.

### Fixed
- A picture from a link without a file name (an image proxy link) failed with "downloaded files were not recognised": the long name was cut and took the `.png` with it. The long part is cut first and the ending is added afterwards.

## [0.18.1] - 2026-11-25

### Fixed
- A file that a browser extension handed over as a link, such as a picture from an image proxy, failed with "nothing downloadable found". The direct download now looks like a browser (user agent) and sends the page the file was on as the Referer when the clipper names it (`referer` in `POST /api/v1/ingest`). A host that answers `application/octet-stream` is accepted when the file's first bytes show it is a picture, video or sound.
- yt-dlp failed with "Cannot write video metadata to JSON file" when a link's id was very long (an image proxy link carries the whole address). The id in the temporary file name is cut at 40 characters.

## [0.18.0] - 2026-11-24

### Added
- A person's picture can come from a link: the person forms (new person and edit) have an "Or a picture link" field next to the file upload. Drollery fetches the image with the same safety checks as other link downloads (public addresses only, redirects checked, 25 MB at most), and a Google Images result link works too. A chosen file is used first.

## [0.17.3] - 2026-11-24

### Changed
- When a link download is finished you stay on the library page: the grid refreshes, the new card is marked for a moment and scrolled into view, and the progress bar says "Added to the library" with an Open button. Before, you were sent to the page of the new item. Uploading a single file from your computer still opens its page.

## [0.17.2] - 2026-11-24

### Changed
- `max_upload_mb` is 10240 (10 GB) by default, up from 2048. It is the largest file an upload or a link download may be. A `config.toml` that has its own `max_upload_mb` line keeps that value: edit or delete the line there to get the new default.

### Fixed
- A long link, or a long error message with a link in it, no longer pushes the progress bar and the link line out of the drop zone on the library page. The text wraps inside it.

## [0.17.1] - 2026-11-24

### Fixed
- A Google Images result link (`google.com/imgres?…`) is now fetched as the picture it points to, and so are Google's and Bing's redirect and image-result links. They failed with "Unsupported URL" before.
- A YouTube search results link used to be taken as a playlist and downloaded video after video until the time limit. It is now refused at once with "this link is a search results page, not a video", and a playlist link takes at most `fetch_max_files` videos (4 by default).
- A download that hits `fetch_timeout`, and a link nothing can be downloaded from, now fail once with a plain message instead of a raw error and two more pointless tries.

## [0.17.0] - 2026-11-24

### Added
- **Make browser-friendly copy** on the page of a video or movie, for a film your browser will not play (a codec it lacks, 10-bit, an odd container): a background job makes an H.264 + stereo AAC MP4 with the index at the front, with a percentage in the button while it runs. The player and shared links then play the copy; **Download** still gives the original, which is never touched. **Remove browser-friendly copy** deletes the copy again. It needs about as much free disk space as the film, and takes about as long as the film on a CPU. A copy goes with its item when you delete it, and comes back with Undo.

## [0.16.0] - 2026-11-24

### Added
- A link added on the library page now gets a progress bar there, like an upload, instead of sending you to the Jobs page. It shows the percentage while the site reports one (a moving stripe when it does not), says when the download waits for its turn or is trying again, and opens the new item when it is done. You can hide it and leave the page: the download carries on in the background.
- Settings > AI models: a new box "Start by itself when something is added" for transcription and for naming and tagging. Unticked, a step runs only when you ask for it, from an item or from the selection. It is ticked by default, as before. A step whose model is not set up never starts, whatever the box says.

## [0.15.1] - 2026-11-24

### Fixed
- 0.15.0 made every button and field unclickable: the new, closed zoom window took the class name `zoom`, which the card editor's slider already used with `display: grid`, so the empty window covered the whole page. It has its own class now and a rule that hides it while closed, and a test checks that no dialog in the page frame can be shown by a rule meant for something else. The card editor's slider is back to its normal size.
- The note under a film player that the browser cannot play now also shows when the browser refuses the file outright ("Media resource could not be decoded"), not only when it plays the sound without a picture.

## [0.15.0] - 2026-11-24

### Added
- A picture opens bigger in a window of its own when you click it (click again for real size, with scrolling). A video has an **Enlarge** button that moves the player into such a window, still playing; it goes back when you close it. Both also work on shared links.
- A film whose picture the browser cannot decode (it plays the sound and keeps showing the preview picture) now says so, with a hint to download it and use a player such as VLC.
- The logo wiggles when pointed at or focused in every theme, not only the playful one.

### Changed
- `max_upload_mb` is 2048 (2 GB) by default, up from 500. It is also the largest file a link download may fetch. A `config.toml` that sets its own value keeps it.
- The playful theme no longer draws the squiggly line under page titles.

## [0.14.2] - 2026-11-24

### Fixed
- A link to a video bigger than `max_upload_mb` no longer ends up as a sound in the library. The downloader skips the too-big video but still fetches its small audio stream, and that used to be saved without a word. The job now fails with "the video is larger than the limit of N MB" and nothing is saved.

## [0.14.1] - 2026-11-24

### Changed
- The Drollery container now runs with a read-only file system (`read_only: true`). Everything it writes goes to the `/data` volume, and `/tmp` is a small memory disk. Big uploads are spooled into `/data/tmp` (`TMPDIR`) instead of RAM.

## [0.14.0] - 2026-11-24

### Added
- Deleting an item (one, or several from the selection) can be undone for a minute: the message afterwards has an Undo button, and the question "are you sure?" is gone. The item, its tags, people, shares and files are kept in a short-lived trash folder and deleted for good after the minute (and at every start). The API's DELETE is still immediate.

### Changed
- The optional Whisper server image is pinned to `0.8.3-cpu` (what `latest-cpu` was) instead of following `latest-cpu`.

## [0.13.0] - 2026-11-23

### Added
- **An optional privacy notice.** Write it under Settings › Privacy notice and switch it on: it is shown at `/privacy`, readable without
  signing in, and linked in the footer next to the Impressum. Visitors of your share links can now see who is responsible and what
  happens to their data. It is off until you fill it in.
- **`/robots.txt`** asks every crawler to stay away, and every answer carries `X-Robots-Tag: noindex, nofollow`.
- **Common passwords are refused** when you choose one (a short built-in list; the password is never sent anywhere).
- **`DROLLERY_BIND`** chooses the host address the port is published on, for example `127.0.0.1` behind a reverse proxy on the same machine.

### Changed
- **Finished background jobs are deleted after 30 days** (at the next start). Failed jobs stay until you remove them.
- **A form that is already on its way is not sent twice.** A second click or Enter within five seconds is ignored.
- **Small controls are 44 px high on touch screens**, and the round badge on a card has a larger touch area.
- **Headings break evenly and paragraphs avoid a lone last word.**
- **The playful style is calmer.** Menu links and icon buttons no longer wiggle on every hover, and cards pop in a little faster.
- **The Compose file drops all Linux capabilities** and sets `no-new-privileges` for the app container.
- **The weekly image scan fails on HIGH as well as CRITICAL** vulnerabilities that have a fix.

### Documentation
- The README lists what Drollery stores and for how long, says the container's web server log holds visitor IP addresses, explains what to
  check when using an outside AI service (processor agreement, transfers to other countries), and states that you are responsible for what you share.

## [0.12.6] - 2026-11-23

### Fixed
- **A flaky test.** The two-factor replay test read the real clock and failed now and then when the 30-second code window changed between
  two logins; it now runs on a frozen clock. Nothing in the app itself changed.

## [0.12.5] - 2026-11-23

### Changed
- **The Pixel ornaments have more room between them** (8 to 20 px instead of 2 to 6 px).

## [0.12.4] - 2026-11-23

### Changed
- **The Pixel style's header and footer ornaments are mixed anew on every page.** Before, each strip was a fixed row of scenery that
  simply repeated, and there were only five of them. Now 40 single pieces (towers, a dragon, tents, a windmill, sheep, a duck,
  a knight ...) are picked and ordered at random for each page load: none twice before all have been used, never the same one next to
  itself, with random gaps. Pieces still take the highlight colour.
- **The footer ornaments are as big as the header's.** Header and footer now draw from the same pool, with the same dot size and the
  same height (46 px). The footer used to have its own set of small things (flowers, barrels, ducks).

## [0.12.3] - 2026-11-23

### Fixed
- **The Pixel ornaments were missing from the Docker image.** The ten header and footer strips live in `static/pixel-orn/`, which was not
  listed in the package data, so a pip-installed copy (the image) had none of them while a source checkout showed them. A test now
  checks that every data file is shipped.
- **Downloaded TikTok videos could not be played in Firefox** ("no video with supported format and MIME type found"). The download
  ranked resolution before codec, so a 1080p HEVC stream won over a lower-resolution H.264 one. The codec now comes first. Videos
  imported before this stay as they are: delete them and fetch the link again.

## [0.12.2] - 2026-11-23

### Changed
- **The Playful style's headings use Almendra instead of a blackletter face.** Blackletter carries associations that were not wanted
  here; Almendra (SIL OFL, 37 KB) is a calligraphic, medieval-looking hand. The name, headings, banners and folio numbers use it.

### Fixed
- **The Playful style still scrolled much more slowly than the others.** The colour wash over the wall was a layer of the scrolling
  background, so the browser repainted it as new parts came into view (up to 217 ms for one frame). It now lies on the fixed layer in
  front of the wall; scrolling is as smooth as in Plain and Pixel in the same measurement (no frame over 34 ms).
- **The Pixel ornaments could be missing after an update**, most clearly in Firefox. Static files had no caching instruction, so a
  browser could keep an old stylesheet that points at a file the new version no longer has. Static files are now always checked
  for changes (`Cache-Control: no-cache`, which costs only a "not modified" answer), and every stylesheet and script link carries the
  version, so a new version can never meet an old file. After updating, one hard reload (Ctrl+Shift+R) clears what the browser kept.

## [0.12.1] - 2026-11-23

### Fixed
- **The Playful style was slow and cards vanished when the pointer left them.** The dark edges of the wall were a *fixed*
  background, which makes the browser repaint the whole wall on every scroll step; together with the new colour wash over the wall
  that made scrolling and hovering several times slower (5.1 s instead of 1.0 s for the same scripted scroll and six hovers on 40
  cards, measured in headless Chromium). They are now a fixed layer of their own. And the hover rule of a card switched its entrance
  animation off, so every time the pointer left, the fade-in started again from invisible.

## [0.12.0] - 2026-11-23

### Changed
- **Editing tags and people for a selection works like on an item page:** tags are typed as chips (every word becomes a chip with a
  cross to delete it), and people are found with a search box that suggests the people who exist while you type; every pick becomes
  a chip too. Several people can be added or removed in one go (the message names them). The bar no longer lists every person in a
  drop-down, which was slow with many people. The chip fields were also fixed in the Playful and Pixel styles, where the typing
  field inside a chip box had its own outline.
- **The Playful style is now a medieval fair** (it was close to Plain with a stone wall):
  - Bunting hangs from the header and the footer, in the highlight colour and two relatives of it.
  - Cards are snapshots taped to the wall: a little crooked, with a piece of tape in a different colour each, a hard shadow in the
    highlight colour, and they straighten, lift and pop in when you point at them or when they arrive.
  - Buttons, fields, tabs and panels have a thick outline, corners that are not quite square and a hard coloured shadow; buttons
    wiggle on hover and squish when pressed.
  - Headings and the name are in a calligraphic hand (Almendra, SIL OFL; it was blackletter at first, see 0.12.2), titles have a wavy underline, empty states show a banner, and
    the wall is washed with the highlight colour.
  - The wobbling stops with "reduce motion".

## [0.11.1] - 2026-11-23

### Changed
- **Pixel style, more ornaments:** the header and the footer each have five different strips (header: a town, ramparts with
  banners, mountains with flying dragons, a camp with tents and fires, windmills; footer: a meadow, a treasury, a marching
  patrol, a village road, a pond). One is picked when the page is made, and the two footer strips always differ. Each strip is
  drawn in stone and the highlight colour, so banners, flames, tents and ducks follow the highlight switch.
- **A new dragon** in the pixel scenes: a horned head with fangs and fire, a wing in the highlight colour, claws and a spade tail.

## [0.11.0] - 2026-11-23

### Added
- **A style switch in the palette menu**, next to mode and highlight colour (kept in the browser):
  - **Playful** is the look as before: the castle wall, the doodles and the skyline.
  - **Plain** has no doodles, no wall and no tilting stickers: just the pages.
  - **Pixel** is block-built medieval scenery in the spirit of a sandbox game: a brick wall, a pixel typeface (Pixelify Sans,
    SIL OFL), bevelled square frames with hard shadows, buttons that sink when pressed, a pixel skyline in the header and eight
    pixel scenes (castle, knight and snail, dragon, wizard, tower, king and queen, burglar, forest) in place of the line doodles.
  - All three follow the highlight colour and light or dark mode: the pixel wall, buttons, scenes and skyline take its colour.
  - `scripts/gen_pixel.py` draws the pixel assets.

### Changed
- The jester icon has a transparent background (favicon, `favicon.ico`, the 192 and 512 pixel PNGs and the browser extension's
  icons). Only the iPhone/iPad home-screen icon keeps a dark square, because iOS paints transparent icons black.

## [0.10.2] - 2026-11-23

### Changed
- **A new app icon, a pixelated jester:** drawn on a 16 by 16 grid in fixed colours (it ignores the highlight colour and the theme),
  on an ink square so it reads on any page. It replaces the castle as favicon, `favicon.ico`, home-screen icon, and as the mark in the
  page header, where it no longer changes with the highlight colour. `scripts/make_icons.py` draws every size.

## [0.10.1] - 2026-11-23

### Changed
- **One fixed app icon:** a gold tile with a dark castle, drawn bold so it reads at 16 pixels. It no longer follows the highlight
  colour (the castle in the page header still does). It is now the favicon (SVG, `favicon.ico`, a 192 px PNG) and the iPhone/iPad
  home-screen icon, and the browser extension uses the same picture.

## [0.10.0] - 2026-11-23

### Added
- **API for clippers:** `GET /api/v1/tags` and `GET /api/v1/people` (to pick from while typing), `PATCH /api/v1/items/{id}` accepts
  `people`, and `POST /api/v1/ingest` takes an optional title, description, tags and people for the item that arrives.

## [0.9.0] - 2026-11-23

### Added
- **Protective headers on every answer:** a content security policy (own scripts only, each inline script carries a nonce that is
  new for every request, nothing is loaded from another site, forms and frames only to and from this site), `X-Frame-Options`,
  `Referrer-Policy: same-origin`, `X-Content-Type-Options` and a permissions policy that switches off camera, microphone and
  location. The two fields that sent their form through an inline `onchange` now use a small shared script.
- **Check the latest backup** (Settings > Backup): unpacks an automatic backup into a scratch folder and checks it the way a
  restore does (files, database, accounts), tells what is in it, and leaves the library untouched. Every backup in the list has its
  own *Check* button too, and a full backup that lacks files is reported.

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
