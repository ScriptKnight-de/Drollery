# Drollery

A self-hosted library for memes and funny video / audio clips. Gather them from anywhere, let
small local models (or any API you choose) name, tag and transcribe them, and find them again
instantly with full-text search.

> *drollery* (n.): the comic doodles medieval scribes drew in manuscript margins — arguably the first memes.

**Status:** early (v0.1). Web app + HTTP API work. Browser extension and Android app are planned and will use the same API.

## Features

- **Fast full-text search** (SQLite FTS5, prefix matching, ranked): titles, descriptions, tags, transcripts, text found in images, source URL.
- **Images, video and audio.** Thumbnails and metadata via ffmpeg. Duplicates (same content) are detected and not stored twice.
- **Add by upload or by link.** Direct media URLs, anything `yt-dlp` supports, and gallery pages via `gallery-dl` — downloaded by a background job.
- **Optional, pluggable AI** — nothing is required, nothing is bundled, everything is configurable (see below). Jobs are queued, retried, and run one at a time so a Raspberry Pi stays responsive.
- **Your edits win.** A title you set by hand is never overwritten by AI.
- **Playful, themeable UI.** Light, dark or follow-the-system, a parchment/stone texture, glow or plain backdrop and 10 highlight colors from the palette button in the header; the choice is remembered per browser.
- **Medieval doodles.** Line-art knights, snails, dragons, wizards, castles, chests and burglars decorate the empty states, login and 404 pages; a tiny skyline runs along the bottom.
- **One container**, one data volume, no external services. Token auth for the UI and API.

## Quick start

```bash
git clone https://forgejo.scriptknight.de/scriptknight/drollery.git && cd drollery
cp .env.example .env        # set DROLLERY_TOKEN (openssl rand -hex 24)
docker compose up -d --build
```

Open <http://localhost:8080>. All data (database, media, thumbnails, `config.toml`) lives in the
`drollery-data` volume; back it up like any Docker volume.

## Configuration

On first start `config.default.toml` is copied to `/data/config.toml` inside the volume. Edit it and restart:

```bash
docker compose exec drollery vi /data/config.toml   # or: docker cp
docker compose restart
```

### AI providers

Three independent capabilities, each off by default (`type = "none"`):

| Section | Does | Input |
|---|---|---|
| `[transcribe]` | speech-to-text for audio and video | extracted mono 16 kHz MP3 |
| `[describe]` | title, description and tags | 640 px preview image and/or the transcript |
| `[ocr]` | text inside images | 1600 px still |

Provider types:

| `type` | Use for |
|---|---|
| `openai` | **Any OpenAI-compatible HTTP API.** Ollama (`http://host.docker.internal:11434/v1`), llama.cpp server, LocalAI, faster-whisper-server, OpenAI, OpenRouter… Run the model on the Pi, on another box in your network, or in the cloud — it is just a URL. |
| `command` | A local program that prints the result to stdout, e.g. `whisper-cli -m /models/ggml-tiny.bin -f {input} -nt`. `{input}` is replaced by the file path. |
| `tesseract` | OCR shortcut. Build with `WITH_TESSERACT: "1"` in `docker-compose.yml`. |

API keys are never stored in the config: set `api_key_env = "DESCRIBE_API_KEY"` and put the key in `.env`.

Example — name and tag with a small vision model on a LAN machine, transcribe with a whisper server:

```toml
[describe]
type = "openai"
base_url = "http://192.168.1.50:11434/v1"
model = "moondream"

[transcribe]
type = "openai"
base_url = "http://192.168.1.50:8000/v1"
model = "Systran/faster-whisper-tiny"
```

Adding a new provider type is a function plus one line in the registry dict at the bottom of the matching section of `src/drollery/providers.py`.

## HTTP API

All endpoints take `Authorization: Bearer <DROLLERY_TOKEN>` (when a token is set).

| Method | Path | |
|---|---|---|
| `GET` | `/api/v1/items?q=&kind=&tag=&limit=&offset=` | search / list |
| `GET` | `/api/v1/items/{id}` | one item |
| `POST` | `/api/v1/items` | upload (`multipart`, field `file`) |
| `POST` | `/api/v1/ingest` | `{"url": "https://…"}` — queue a download |
| `PATCH` | `/api/v1/items/{id}` | `{"title","description","tags"}` |
| `DELETE` | `/api/v1/items/{id}` | |
| `GET` | `/api/v1/jobs` | queue state |
| `GET` | `/media/{id}`, `/thumb/{id}` | files |

## Security notes

- **Set `DROLLERY_TOKEN`** if the port is reachable by anyone but you. Use HTTPS (reverse proxy) if it leaves your LAN: the token travels in a header/cookie.
- `/api/v1/ingest` makes the server fetch arbitrary URLs. That is the feature, but it means anyone holding the token can make the container request addresses on your network.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest
DROLLERY_DATA=./data .venv/bin/uvicorn drollery.main:app --reload
```
Requires `ffmpeg` on the PATH.

## Roadmap

- Browser extension (Firefox/Chrome): save image/video/link or the current page into the library.
- Android app: share-sheet target that posts to `/api/v1/ingest` and `/api/v1/items`.
- Collections, bulk edit, import of an existing folder, semantic (embedding) search, multi-user.

## License

MIT
