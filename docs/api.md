# HTTP API

Drollery has a small JSON API for tools such as a browser extension or a phone app. Everything the web interface does
can be done in the browser; the API is only for programs.

## Keys

Create a key per device under **Settings › API keys** (a key is shown once and stored only as a hash). Send it with every
request:

```
Authorization: Bearer <your key>
```

`GET /api/v1/me` checks a key and returns the user name and the server version. Revoke a key in the same place the moment
you no longer use it.

## Item kinds

Every item has a `kind`: `image`, `gif`, `video` (shown as "Clip"), `audio` (shown as "Sound"), `album` (music album or
audiobook) or `movie`.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/v1/me` | check a key |
| `GET` | `/api/v1/items?q=&kind=&tag=&tag_source=&limit=&offset=` | search / list. Items carry `tags` (yours) and `ai_tags`; `tag_source` is `user` or `ai` |
| `GET` | `/api/v1/items/{id}` | one item |
| `POST` | `/api/v1/items` | upload one file (`multipart`, field `file`) |
| `POST` | `/api/v1/albums` | create an album (`multipart`: `files` = audio files and/or ZIPs, optional `cover`, `title`, `artist`, `subtype` = `album`\|`audiobook`, `description`, `tags`) |
| `POST` | `/api/v1/ingest` | `{"url": "https://…"}` queues a download; optionally with `title`, `description`, `tags` and `people` (ids), which are applied to the item that arrives (an item that was already in the library keeps its title and description and gains the tags and people). Links to private or local addresses are refused with `422` (see [configuration](configuration.md#fetching-links)) |
| `PATCH` | `/api/v1/items/{id}` | `{"title","description","tags","people"}`; `people` is a list of person ids and sets exactly those people (ids that do not exist are ignored); a field you leave out is not changed |
| `GET` | `/api/v1/tags?q=&limit=` | tags to offer while typing: those containing `q`, or your most used ones without `q`. Each is `{"tag","n"}` with the number of items. At most 50 |
| `GET` | `/api/v1/people?q=&limit=` | people whose alias or real name contains `q`, or the ones on the most items without `q`: `{"id","name","first_name","surname","picture_url"}`. At most 50 |
| `DELETE` | `/api/v1/items/{id}` | delete an item |
| `GET` `POST` | `/api/v1/items/{id}/shares` | list / create share links. Body: `{"expires_in": seconds or null, "label": "", "track_id": album track or omit for the whole album}` |
| `DELETE` | `/api/v1/shares/{id}` | remove a share link |
| `GET` | `/api/v1/jobs` | the state of the background queue |
| `POST` | `/api/v1/jobs/{id}/retry` | run one failed job again (`409` if it isn't failed) |
| `GET` | `/media/{id}`, `/thumb/{id}` | the file and its thumbnail. An album has `url: null`; use `/albums/{id}/track/{track}`, `/albums/{id}/cover` and `/albums/{id}/download` |

Titles, tags and descriptions are your own text and are returned exactly as stored; error messages and the API itself
always answer in English.

There is no generated API documentation page: it is switched off so that a stranger who can reach the port cannot read
a list of every endpoint.
