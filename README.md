# Drollery

**Your own library for memes, funny clips, sounds, albums and movies.** Drop things in, find them again in a second, and
share the good ones with a link. It runs on your own computer or home server, keeps everything in one folder, and works
without any account at a big company.

> *drollery* (n.): the comic doodles medieval scribes drew in the margins of manuscripts, arguably the first memes.

[Get started](#get-started) · [A quick tour](#a-quick-tour) · [How do I…?](#how-do-i) · [Looking after your library](#looking-after-your-library) · [Troubleshooting](#troubleshooting) · [Privacy](#privacy) · [For developers](#for-developers)

## What you can do with it

- **Collect anything funny:** pictures, GIFs, video clips, sound effects, whole music albums and audiobooks, and movies
  (films, parodies and synchros, the dubs with new voices).
- **Find it fast:** one search box looks through titles, descriptions, tags, the names of people, and even what is said
  in a clip when you turn on transcription. It suggests tags and people while you type.
- **Play sounds like a soundboard:** every sound is a big round button in a colour of its own; press it and it plays.
- **Fill in the details for you:** look an album up on MusicBrainz or a movie on IMDb and take over the title, cast,
  genres, poster and more, in German or English.
- **Share with a link:** one item, a whole album or a single track, for an hour or forever, and take it back any time.
- **Stay in control:** no tracking, no ads, no cloud. AI help (naming, tagging, transcription) is optional and runs only
  where you point it.

## Get started

You need a computer or server with **Docker** (a Raspberry Pi is fine). There are two ways.

**The quick way: the ready-made image.** It is built for ordinary PCs (`amd64`) and for Raspberry Pis (`arm64`), so
nothing has to be built on your machine:

```bash
docker run -d --name drollery --restart unless-stopped -p 8080:8080 -v drollery-data:/data \
  ghcr.io/scriptknight-de/drollery:latest
docker logs drollery               # shows your one-time setup code
```

Prefer Compose? Save this as `compose.yml`, then run `docker compose up -d` and `docker compose logs drollery`:

```yaml
services:
  drollery:
    image: ghcr.io/scriptknight-de/drollery:latest
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - drollery-data:/data
volumes:
  drollery-data:
```

The image is published with these tags: `latest` (the newest version on the main branch), a release number such as
`0.12.2` (that exact release), and `0.12` (the newest `0.12.x`). To stay on one release, use its number, for example
`ghcr.io/scriptknight-de/drollery:0.12.2`. The same image is also in the Forgejo registry as
`forgejo.scriptknight.de/scriptknight/drollery`.

**Or use the project's Compose file**, which also gives you the optional Whisper container and the `.env` file. It pulls
the same ready-made image:

```bash
git clone https://forgejo.scriptknight.de/scriptknight/drollery.git
cd drollery
docker compose up -d               # add --build to build the image from this folder instead
docker compose logs drollery       # shows your one-time setup code
```

Either way, then:

1. Open <http://localhost:8080> (or `http://<the-server's-address>:8080` from another device).
2. Enter the **setup code** from the log and choose a user name and a password. You are the owner of this library.
3. Drop a few files on the page. That is all.

> The setup code keeps strangers from claiming your library if they find the address first. It disappears once you have
> created your account.

Everything you add lives in one Docker volume: `drollery-data` with the ready-made image, or `drollery_drollery-data`
when you started it from the cloned project's Compose file (the first part is the name of the folder you cloned into). See
[Looking after your library](#looking-after-your-library).

> The commands further down use `docker compose …`. If you started Drollery with the plain `docker run` command, use
> `docker logs drollery`, `docker exec drollery …`, `docker stop drollery` and `docker start drollery` instead.

## A quick tour

**The library page** is your home. At the top is the **upload zone**: drop files anywhere on the page, choose them, or
paste a link. Below it is the **search box** (press `/` to jump to it) and the **filters**: *All, Images, GIFs, Clips,
Sounds, Albums* and *Movies*. Each thing in your library is a card. In the header you find **Jobs** (what is running in
the background), **Settings**, the **palette** button (light, dark or automatic, three styles, plus ten highlight colours) and the
**globe** (English or Deutsch).

**An item's page** shows the picture, player or soundboard button on the left, with a row of buttons under it:
*Download, Look up, Card image, Share, Background jobs* and *Delete*. On the right are its title, your tags, its
**Details** (type, size, length, and for albums and movies everything the lookup found) and one box where you edit the
title, description, **people** and tags.

**Settings** has tabs for your *Profile*, *Security*, *API keys*, *AI models*, *People*, *Shares*, *Online lookup*, the
*Impressum* and *About*.

## How do I…?

### Add things

Drop files on the library page, choose them with a click, or paste a link. A small panel then shows what you picked and
suggests what it should become, which you can change:

| You add | It becomes | Good to know |
|---|---|---|
| a picture, GIF, clip or sound | **separate items**, one per file | GIFs have their own filter, apart from pictures |
| several audio files, or one ZIP | an **album or audiobook**: one card with a cover | tracks are put in order by their track numbers; a picture among the files becomes the cover |
| one video file | **separate item**, or a **movie, parody or synchro** | you choose; a video of 300 MB or more is suggested as a movie |
| a link | a download in the background | works for direct file links, most video sites (via `yt-dlp`) and picture galleries (via `gallery-dl`); follow it under **Jobs** |

A progress bar shows the speed and the time left, and you can cancel. Limits: 500 MB per file, 16 GB for a movie, 2 GB
per album (changeable, see [Configuration](docs/configuration.md)). A file that is already in your library is not added
twice.

> **Links to your own network are refused by default.** So that nobody can use "add a link" to reach things only your
> server can reach, links to `localhost`, `192.168.x.x` and similar addresses are blocked. You can allow chosen hosts, see
> [Fetching links](docs/configuration.md#fetching-links).

### Find things

Type in the search box and the grid narrows as you type. While you type, suggestions of matching **tags** and
**people** appear; pick one to filter by it. The buttons above the grid filter by type. Searching finds words in
titles, descriptions, tags (yours and the AI's), people's names, an album's artist and track titles, a movie's film,
cast and genres, and transcripts.

### Play sounds

Sounds are round, colourful buttons right on the cards. Press one to play it without leaving the page; press another and
the first stops. A sound's own page has the same button, bigger.

### Work with albums and audiobooks

An album is one card; open it to play the tracks one after another, **download everything as a ZIP**, and open
**Rename and reorder** to change track names and positions. Press **Look up details online** to search
[MusicBrainz](https://musicbrainz.org): pick the matching release, see every change it proposes (title, artist, release
details, cover, track names) and **take over only what you tick**. If transcription is on, each track gets a small
transcript button that opens what is said.

### Work with movies, parodies and synchros

Add a movie from the upload zone and choose *Movie*, *Parody* or *Synchro (dub)*. For a parody or synchro, fill in the
**original film** it makes fun of or dubs. **Look up on IMDb** searches for the film; you see every proposed change and
take over only what you want: title, description, cast, directors, genres, rating, runtime and the poster as the card
picture. Without a key IMDb's search gives title, year, main cast and poster (in English). For more, and in the language
of the page, add a free key under **Settings › Online lookup**:

- **TMDB** key: title, plot, genres, cast and poster **in your language** (German or English, following the language you
  chose for the page);
- **OMDb** key: plot, genres, cast and the IMDb rating (English).

You need your own free keys; they are stored only on your server.

### Tag, describe and credit people

Under an item's edit box you can add **tags** (type a word and press space or Enter; each becomes a small chip with a
cross to remove it), a **description**, and the **people involved**. People (creators, voice actors, anyone) are
stored once, under **Settings › People**, with an **alias** (how they are known and shown everywhere), their real
**first name** and **surname**, a picture, a **birthday** (their age is worked out for you), a gender and a link to their
social media. Items are found under any of the names. Start typing in the item's people field to pick someone who
already exists, or press **New person** to add them.

**Looking after your tags and people:** **Settings › Tags** lists every tag with how many items carry it as yours and as one
the AI suggested. You can **rename** a tag for the whole library (renaming to a name that exists **merges** the two, an item
that had both keeps one copy), **merge** several ticked tags into one, **delete** a tag everywhere (the AI is told not to bring it
back on those items) and **keep as mine** the AI's copies of a tag. Joining tags asks first and says how many items it touches.
Merged tag names are **remembered**: typed again by you or suggested by the AI, an old name becomes the new tag, and the
tags page lists these renames so you can forget one. The people list can be searched and sorted, and it can delete everyone who is
on no item. Two entries for the same person can be merged on that person's page (*Merge with another person*): its items go to the other
person, details the other lacks (name, birthday, gender, link, picture) are filled in, and the entry is deleted. **Settings ›
People** points out likely duplicates. None of this can be undone; a backup is the way back.

If an AI model is set up, it also suggests tags. **Your tags and the AI's stay apart:** you can keep or remove the AI's
with one click, and what you wrote is never overwritten.

### Choose a card picture

**Card image** lets you decide what the card shows. For a clip or movie, scrub to the exact moment and crop a square
from it. For a picture, drag and zoom the crop. Or **use your own picture** from your computer. Your original file is
never changed, and **Reset to automatic** goes back.

### Share something

Press **Share** on an item. Choose how long the link should work (1 hour, 1 day, 7 days, 30 days, forever, or your own
time up to a year), give it a label if you like ("for Alex"), and copy the link. The people who open it see only that one
item, with a player and a download button, no login needed. For an album you can share **everything** (player and ZIP) or
just **one track**. **Settings › Shares** lists every link with its view count and lets you revoke one instantly.

Share links use the address you are browsing with. If your library sits on your home network and you want to share with
people outside it, put it behind HTTPS and set the public address under **Settings › Shares** (see
[Privacy and security](#privacy)).

### Change the look and the language

The **palette** button in the header switches between light, dark and automatic, picks one of ten highlight colours and
chooses a **style**: *Playful* (a medieval fair: bunting, taped-up cards, calligraphic headings, a castle wall with doodles), *Plain* (no doodles and no wall, just the pages) or *Pixel*
(block-built medieval scenery with a brick wall and a pixel typeface). All three follow the highlight colour. The choice is
kept in your browser. The **globe** switches between English and German. Under **Settings › Profile** you can save your language. If you
publish your library to the public, **Settings › Impressum** lets you write the legal notice that German law asks for,
with a link in the footer.

### Let AI help (optional)

You can connect a model that **transcribes** speech (so what is said in a clip becomes searchable) and one that
**suggests a title, description and tags**. Nothing is built in and nothing runs unless you set it up under
**Settings › AI models**. Any OpenAI-compatible service works (Ollama on your own machine, for example), and the project
includes an optional **Whisper** container for transcription. Setup is in [docs/configuration.md](docs/configuration.md).
Movies are never transcribed or named automatically, because they run for hours.

## Looking after your library

**Where is everything?** In the Docker volume `drollery-data`, or `drollery_drollery-data` if you built it yourself (check
the exact name with `docker volume ls`): the database, your media, thumbnails, card pictures and `config.toml`. The volume keeps your data
when you update or rebuild the container. In the commands below, use your volume's name if it differs.

**Back it up** (do this before big changes, and now and then):

```bash
docker run --rm -v drollery_drollery-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/drollery-backup.tgz -C /data .
```

**From the web interface:** **Settings › Backup** downloads your library as one `.tgz` file, either *everything*
(database and files) or *metadata only* (titles, tags, transcripts, people, accounts and settings: small and quick).
Drollery keeps running while it is made, and the download starts at once. The file is laid out like the data folder, so
the restore below works for it. Keep it private: it contains your accounts and saved API keys.

**Automatic backups:** under **Settings › Backup** Drollery can make backups by itself and keep the latest ones. Choose how
often (every day or every week on Sunday) and at what hour of the server's clock, whether to back up only the metadata (small,
the default) or everything, and how many to keep (7 by default; only backups Drollery made itself are ever deleted). It is
off until you switch it on. The files go to the `backups` folder in the data volume; set `backup_dir` in `config.toml` to a
folder on another disk or a mounted share to be safe from losing the volume, because a folder on the same disk only protects
against deleting something by mistake. A backup missed while the server was off is made when it starts again, a failed one is
shown on the page with its reason and tried again after an hour, and the page lists the backups with *Download*, *Delete* and
*Back up now*. The files can be owner-read only (they hold password hashes and saved API keys) and restore like any other
backup.

**Restore** a backup: on a new Drollery that has no account yet, the first page offers **Or restore a backup**. Choose the
file, enter the setup code from the container log, and your library, accounts and settings come back; then you sign in
with an account from the backup. Drollery checks the file first (only the parts a backup has, nothing that could leave
its folder, enough free disk space, an intact database with at least one account) and changes nothing if it does not pass.
It only works while the library has no account, so a library in use is never overwritten. A metadata-only backup brings
back the entries and tells you how many of them have no file yet. A big library takes a while, and a web server in front of
Drollery may limit the size of an upload.

Or **on the server**, with the same checks, from the command line (Drollery stopped, or running without an account yet):

```bash
docker compose run --rm -v "$PWD":/backup drollery python -m drollery restore /backup/drollery-backup.tgz
docker compose up -d
```

Add `--check` to only look at a file: it says what is in it (items, people, accounts, how many items have no file) and changes
nothing, so you can test a backup at any time, even on a library in use. Restoring is only done for a library without an
account. Or unpack it yourself into an empty volume:

```bash
docker compose down
docker run --rm -v drollery_drollery-data:/data -v "$PWD":/backup alpine \
  sh -c "cd /data && tar xzf /backup/drollery-backup.tgz"
docker compose up -d
```

**Update** to the newest version. With the ready-made image:

```bash
docker pull ghcr.io/scriptknight-de/drollery:latest
docker rm -f drollery                    # removes the container only; your data stays in the volume
docker run -d --name drollery --restart unless-stopped -p 8080:8080 -v drollery-data:/data \
  ghcr.io/scriptknight-de/drollery:latest
```

(with a Compose file: `docker compose pull && docker compose up -d`). If you cloned the project and build it yourself:

```bash
git pull
docker compose up -d --build
```

**Stop or start** it: `docker compose stop` and `docker compose start`. `docker compose down` removes the container but
keeps your data; only `docker compose down -v` deletes the volume, **and with it your library**, so avoid `-v`.

**Move to another computer:** make a backup, copy the `.tgz` file over, install Drollery there and restore it.

## Troubleshooting

**I lost the setup code.** Run `docker compose logs drollery`. It is printed every time Drollery starts while no account
exists yet; once you have created your account it is no longer needed.

**I can't sign in any more** (forgotten password, lost two-factor device and backup codes). Run this on the machine
where Drollery runs:

```bash
docker compose exec drollery python -m drollery reset-admin
```

It prints a new one-time password, turns two-factor authentication off and signs the account out everywhere. Sign in
with it, then change it under **Settings › Security** and switch two-factor authentication on again. Nothing else
changes: your library, tags and settings stay as they are. With more than one account, add `--user NAME`. If the sign-in
page says "too many attempts", wait 15 minutes or run `docker compose restart drollery`. Only someone who can run
commands on your server can do this, which is the point: they already control the data.

**An upload or a link failed.** Open **Jobs** (header) to see what happened; a failed job shows its error and a **Retry**
button. A link from your own network needs [allowing](docs/configuration.md#fetching-links) first.

**A big file never arrives.** If a reverse proxy sits in front of Drollery, it must allow big request bodies and long
requests, because a large file is checked after it has arrived.

**The Whisper model does not download.** Look at `docker compose logs whisper-model`: it prints the HTTP code, what the
server answered and the usual cause. `404` means the model name in `WHISPER_MODEL` does not exist; `500` almost always
means the Whisper container cannot reach `huggingface.co` (no internet, DNS, firewall or proxy) or cannot write to its
model volume (`Permission denied` in the server log; update to the current compose file, which repairs the volume). The exact reason is in
`docker compose logs whisper`. See [docs/configuration.md](docs/configuration.md#if-the-model-does-not-download).

**Transcription is very slow.** See the speed note in [docs/configuration.md](docs/configuration.md#whisper-as-a-second-container).

**The lookup says the service is busy.** MusicBrainz asks everyone to go slowly; wait a few seconds and try again.

**Can several people use it?** There is one owner account for now; several users are on the roadmap. You can share
single items with anyone by link.

**Which files work?** Common picture, video and audio formats. SVG pictures are refused on purpose, because they can
carry scripts.

## Privacy

Drollery has **no telemetry**, no analytics and no external resources in its pages (no CDN, fonts or trackers): the
whole interface is served by your own server. It only contacts another site when **you** ask it to, and sends as little
as possible:

| When you… | It contacts | What is sent |
|---|---|---|
| press **Look up details online** on an album | MusicBrainz, Cover Art Archive | the album title and artist you see in the form |
| press **Look up on IMDb** on a movie | IMDb's search, and OMDb or TMDB if you added a key | the title you see in the form, the id you picked, your key |
| add a link | the site you pasted (through `yt-dlp` or `gallery-dl`) | a normal download request |
| use an AI model | the address you configured | the preview picture and/or transcript, only for the jobs you turned on |

The name sent to the lookup services is just `Drollery/<version>`.

## Security

- **Use HTTPS** if the site leaves your home network (a reverse proxy is fine), and set `DROLLERY_COOKIE_SECURE=1`.
  Otherwise passwords and keys travel unencrypted.
- Passwords are hashed with scrypt, sign-in attempts are rate-limited (5 wrong passwords for one name, 30 from one address, then 15 minutes of waiting), and you can turn on **two-factor authentication**
  with backup codes under **Settings › Security**.
- Every page carries protective headers: a **content security policy** (only Drollery's own scripts run, nothing is loaded
  from another site), `X-Frame-Options`, `Referrer-Policy: same-origin`, `X-Content-Type-Options` and a permissions policy.
  If your reverse proxy adds its own, keep these or make them at least as strict. `Strict-Transport-Security` is left to the
  proxy, which knows whether the site is served over HTTPS.
- Links to private or local addresses are refused when you add a link (see above).
- A **share link** is a secret address: anyone who has it can open that one item until it expires or you revoke it. The
  public page shows only the title, description and, for movies, the type, year and original film, never your tags or
  the people you linked.
- Keep the data volume and your backups private; they hold your library and your keys.

Found a problem? Please report it privately, see [SECURITY.md](SECURITY.md).

## For developers

- [HTTP API](docs/api.md): upload, search and share from your own tools, with per-device keys.
- [Configuration](docs/configuration.md): every setting, the Docker `.env` file and the AI providers.
- [Development](docs/development.md): run it from source, how it is built, tests and translating.
- [Contributing](CONTRIBUTING.md), [Changelog](CHANGELOG.md) and the [third-party notices](THIRD_PARTY_NOTICES.md).

**Roadmap:** a browser extension (save a picture, video or page into the library), an Android app (a share-sheet target
that posts to the API), collections, bulk edit, importing an existing folder, semantic (embedding) search and several
users.

## License

[MIT](LICENSE). Third-party code, assets and online services are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<p align="center">
  <sub>Free and open source. If it saves you time, you can say thanks on Ko-fi.</sub><br>
  <a href="https://ko-fi.com/scriptknight"><img src="docs/kofi_logo.png" alt="Support me on Ko-fi" height="36"></a>
</p>
