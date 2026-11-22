# Configuration

Most things are set in the web interface (**Settings**). Two files cover the rest: `.env` next to `docker-compose.yml`
(for Docker) and `config.toml` inside the data volume (for Drollery itself).

## `.env` (Docker)

Copy `.env.example` to `.env` and fill in what you use. Every line is optional.

| Variable | What it does |
|---|---|
| `DROLLERY_PORT` | the port the web interface is published on (default `8080`) |
| `DROLLERY_IMAGE` | the image `docker compose up -d` pulls (default `ghcr.io/scriptknight-de/drollery:latest`); pin a release such as `ghcr.io/scriptknight-de/drollery:0.2.0`. `docker compose up -d --build` builds from the folder instead |
| `DROLLERY_SETUP_CODE` | choose your own first-run setup code instead of the generated one |
| `DROLLERY_COOKIE_SECURE` | set to `1` when the site is served over HTTPS, so cookies are marked Secure |
| `DROLLERY_PUBLIC_URL` | the address used in share links when you share beyond your home network, e.g. `https://memes.example.org` (can also be set under **Settings › Shares**) |
| `COMPOSE_PROFILES` | set to `whisper` to start the optional speech-to-text container |
| `WHISPER_MODEL`, `WHISPER_CPUS`, `WHISPER_MEM_LIMIT` | which Whisper model to use and how much of the machine it may take |

## `config.toml`

On the first start Drollery copies its defaults to `config.toml` in the data volume. Edit that copy and restart:

```bash
docker compose exec drollery vi /data/config.toml      # or copy it out with docker cp, edit, copy back
docker compose restart drollery
```

| Setting | Default | Meaning |
|---|---|---|
| `max_upload_mb` | 500 | largest single file you can upload (pictures, clips, sounds) |
| `max_movie_mb` | 16384 | largest single movie file |
| `max_album_mb` | 2048 | all tracks of one album together, and the unpacked size of a ZIP |
| `max_album_tracks` | 500 | most tracks in one album |
| `metadata_lookup` | `true` | offer the online lookups (MusicBrainz, IMDb); nothing is sent unless you press the button |
| `metadata_user_agent` | empty | sent to the lookup services; empty means just `Drollery/<version>`. MusicBrainz likes a contact URL here if you query a lot |
| `worker_concurrency` | 1 | background jobs at once (1 to 8); keep it at 1 on a Raspberry Pi. Settings › AI models › Background jobs overrides it |
| `job_max_attempts` | 3 | retries before a job is marked failed |
| `fetch_timeout` | 900 | seconds allowed for one link download |
| `fetch_max_files` | 4 | files kept from one page or gallery link |
| `allow_private_fetch` | `false` | see below |
| `fetch_allow_hosts` | `[]` | see below |

### Fetching links

When you add a link, the **server** downloads it. So that nobody can use that to reach things only the server can reach,
links that point to **private or local addresses** (`localhost`, `192.168.x.x`, `10.x.x.x`, `172.16–31.x.x`, link-local
addresses such as the cloud metadata address `169.254.169.254`, and their IPv6 equivalents) are refused by default. The
check runs when the link is added, again when the download runs, and on every redirect of a direct download.

To fetch from your own network on purpose:

```toml
allow_private_fetch = true                          # switch the check off, or
fetch_allow_hosts = ["nas.lan", "10.0.0.0/24"]      # allow just these hosts, addresses or networks
```

It is a strong defence against the usual attacks, not a sandbox: a hostile DNS server or a redirect that `yt-dlp` or
`gallery-dl` follow by themselves can still get around it. For strong isolation run the container on a network that
cannot reach your internal services.

## Optional AI (speech-to-text, naming, tagging)

Nothing is required and nothing is bundled. In the web interface, **Settings › AI models** is where you define a model,
give it a job and test the connection. Two jobs exist:

| Job | What it does | What it receives |
|---|---|---|
| Transcription | writes down what is said in clips, sounds and album tracks, so it becomes searchable | an extracted mono 16 kHz MP3 |
| Naming and tagging | suggests a title, a description and tags | a 640 px preview picture and/or the transcript |

**Adding a provider.** On the *Add a model* page, pick a preset or **Custom provider** (an empty form for any
OpenAI-compatible service, such as Google Gemini at `https://generativelanguage.googleapis.com/v1beta/openai/`). Once a
base URL is entered, Drollery asks the server for its model list by itself (and again when you change the address or
key) and you **choose the model from that list**, so a misspelled name cannot happen. Pick *Other…* to type a name the
server does not list. Names that come with a `models/` prefix (Gemini does that) are shown without it, which is what
chat calls expect.

A model can be:

| Type | Use it for |
|---|---|
| OpenAI-compatible API | Ollama (`http://host.docker.internal:11434/v1`), llama.cpp server, LocalAI, faster-whisper-server, OpenAI, OpenRouter… on this machine, on another one in your network, or in the cloud |
| Command | a local program that prints the result, e.g. `whisper-cli -m /models/ggml-tiny.bin -f {input} -nt` (`{input}` is replaced by the file) |

API keys you enter there are stored in the database inside the data volume and never shown again. Movies are never
transcribed or named automatically (they run for hours); nothing runs on a file unless a model is assigned.

`config.toml` also accepts `[transcribe]` and `[describe]` sections as a fallback for anything you leave on "From
config.toml"; see the comments in the file.

### Whisper, as a second container

The compose file includes an optional speech-to-text server ([Speaches](https://github.com/speaches-ai/speaches),
faster-whisper, int8 on CPU) with the **small** model. It is not published to the host; Drollery reaches it inside the
Docker network.

```bash
echo 'COMPOSE_PROFILES=whisper' >> .env     # opt in
docker compose up -d                        # starts it and downloads the model (about 460 MB) once
```

Then add a model under **Settings › AI models** with the **Whisper server** preset and assign it to **Transcription**.
The model name must match `WHISPER_MODEL` (default `Systran/faster-whisper-small`; `-tiny`, `-base`, `-medium` and
`-large-v3` also work).

### If the model does not download

The helper container `whisper-model` asks the Whisper server to download the model once and then exits. When that fails
it prints the HTTP code, the server's answer and the usual cause (`docker compose logs whisper-model`), and retries a
few times if the problem might pass. What the codes mean:

| Code | Meaning | What to do |
|---|---|---|
| `404` | the model name does not exist | fix `WHISPER_MODEL` in `.env` (for example `Systran/faster-whisper-small`) |
| `500` | the Whisper server could not fetch or store the model: it cannot reach `huggingface.co`, or it cannot write to the model volume (`Permission denied` in the server log; the `whisper-permissions` step of the compose file fixes that on every start) | read the reason in `docker compose logs whisper`; check the machine's DNS, firewall or proxy, or whether Hugging Face is up; test with `docker compose exec whisper curl -sI https://huggingface.co` |
| `000` | the helper cannot reach the Whisper server at all | `docker compose ps`: is the `whisper` container running and healthy? |

**A machine without internet:** copy the downloaded model from a machine where it worked (the volume is called
`<folder>_whisper-models`, see `docker volume ls`):

```bash
# on the machine that has the model
docker run --rm -v drollery_whisper-models:/m -v "$PWD":/b alpine tar czf /b/whisper-models.tgz -C /m .
# on the offline machine, after copying the file over
docker run --rm -v drollery_whisper-models:/m -v "$PWD":/b alpine sh -c "cd /m && tar xzf /b/whisper-models.tgz"
docker compose up -d
```

**Speed depends on your processor.** Whisper's fast int8 code needs a CPU feature called AVX2. On a virtual machine whose
CPU type hides it (for example a generic "QEMU Virtual CPU"), transcription of the small model runs about as fast as real
time. Setting the virtual CPU type to `host` in your hypervisor fixes that.
