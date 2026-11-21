"""Speech-to-text for every track of an album, so that what is said in a track can be searched."""
import json
import sqlite3

import pytest

from drollery import albums, db, pipeline, providers
from test_accounts import MODEL
from test_album import album_id, make_audio, make_mp3, mp3s, upload  # noqa: F401  (mp3s is a fixture)
from test_share import anon_client  # noqa: F401


def enable_transcription(client):
    client.post("/settings/ai/models", data={**MODEL, "name": "Whisper test", "model": "whisper-1"})
    from drollery import accounts
    mid = str(next(m["id"] for m in accounts.list_models() if m["name"] == "Whisper test"))
    client.post("/settings/ai/assign", data={"transcribe": mid, "describe": "default"})


def run_all_jobs():
    ran = 0
    while (job := db.claim_job()):
        pipeline.run_job(job)
        ran += 1
    return ran


def say(monkeypatch, words: dict | None = None):
    """A fake speech-to-text: the answer depends on which track the audio comes from (looked up by call order)."""
    calls = []
    script = iter(words or [])
    monkeypatch.setattr(providers, "transcribe", lambda cfg, audio: calls.append(audio.name) or next(script, f"words {len(calls)}"))
    return calls


@pytest.fixture()
def album(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]], title="Talk Show")
    aid = album_id(client)
    with db.tx() as c:
        return aid, albums.tracks_of(c, aid)


def jobs(aid=None):
    with db.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs WHERE type='transcribe_track' ORDER BY id")]


def test_nothing_is_queued_without_a_transcription_model(client, mp3s):
    upload(client, [mp3s["one"], mp3s["two"]])
    assert jobs() == []


def test_a_new_album_queues_one_job_per_track(client, mp3s):
    enable_transcription(client)
    upload(client, [mp3s["one"], mp3s["two"], mp3s["three"]], title="Talk Show")
    aid = album_id(client)
    with db.tx() as c:
        tracks = albums.tracks_of(c, aid)
    queued = jobs()
    assert [json.loads(j["payload"])["track_id"] for j in queued] == [t["id"] for t in tracks] and {j["item_id"] for j in queued} == {aid}
    assert all(j["status"] == "queued" for j in queued)


def test_every_track_gets_its_own_transcript(client, album, monkeypatch):
    aid, tracks = album
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    say(monkeypatch, ["the first speech about dragons", "second track mentions the treasurer", "and a third about cheese"])
    assert run_all_jobs() == 3
    with db.tx() as c:
        rows = albums.tracks_of(c, aid)
    assert [r["transcript"] for r in rows] == ["the first speech about dragons", "second track mentions the treasurer", "and a third about cheese"]
    assert all(r["transcribed_at"] for r in rows)
    with db.tx() as c:
        assert albums.transcription_state(c, aid) == {"total": 3, "done": 3, "waiting": 0, "failed": 0}


def test_a_long_track_is_cut_into_pieces_and_put_back_together(client, tmp_path, monkeypatch):
    long_track = make_audio(tmp_path / "long.mp3", "libmp3lame", seconds=25)
    upload(client, [long_track], title="Long")
    aid = album_id(client)
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    monkeypatch.setattr(pipeline, "_chunk_seconds", lambda cfg: 10)
    calls = say(monkeypatch)
    run_all_jobs()
    assert len(calls) == 3                                                  # 25 s in pieces of 10 s
    with db.tx() as c:
        assert albums.tracks_of(c, aid)[0]["transcript"] == "words 1 words 2 words 3"
    assert pipeline._chunk_seconds.__name__ == "<lambda>"
    monkeypatch.undo()
    class Cfg: timeout = 300                                                # the real rule: well inside the model's timeout
    assert pipeline._chunk_seconds(Cfg) == 150
    Cfg.timeout = 20
    assert pipeline._chunk_seconds(Cfg) == 60
    Cfg.timeout = 9999
    assert pipeline._chunk_seconds(Cfg) == 300


def test_what_is_said_makes_the_album_searchable_and_shows_where(client, album, monkeypatch):
    aid, tracks = album
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    say(monkeypatch, ["welcome everybody", "then the treasurer <script>alert(1)</script> explains the Bermuda-Dreieck problem", "goodbye"])
    run_all_jobs()
    home = client.get("/", params={"q": "treasurer"}).text
    assert f'href="/items/{aid}?q=treasurer"' in home                                    # the album is found by words nobody typed anywhere
    assert f"<b>{tracks[1]['title'].replace(chr(39), '&#39;')}</b>" in home and "<mark>treasurer</mark>" in home               # with the track and the words around it
    assert "<script>alert(1)</script>" not in home and "&lt;script&gt;" in home and "\x02" not in home and "\x03" not in home
    assert f'href="/items/{aid}' in client.get("/", params={"q": "welcom"}).text                                       # prefix search works inside transcripts
    assert 'class="hit"' not in client.get("/", params={"q": "talk show"}).text                                         # a title match needs no snippet of speech
    page = client.get(f"/items/{aid}", params={"q": "treasurer"}).text
    assert page.count('class="match"') == 1 and f'id="t{tracks[1]["id"]}"' in page and "<details class=\"tr-text\" open>" in page   # the matching track is marked and opened
    plain = client.get(f"/items/{aid}").text
    assert 'class="match"' not in plain and "<summary>Transcript</summary>" in plain and "&lt;script&gt;alert(1)&lt;/script&gt;" in plain


def test_the_status_and_the_buttons_on_the_album_page(client, album, monkeypatch):
    aid, tracks = album
    assert "transcribed" not in client.get(f"/items/{aid}").text                            # nothing is set up: no noise
    enable_transcription(client)
    page = client.get(f"/items/{aid}").text
    assert "0 of 3 tracks transcribed" in page and "Transcribe tracks" in page and "Transcribe all again" not in page
    r = client.post(f"/albums/{aid}/transcribe")
    assert "Transcription queued for 3 tracks" in r.text and "3 waiting" in r.text
    assert "Nothing to transcribe" in client.post(f"/albums/{aid}/transcribe").text          # already waiting: no duplicates
    assert len(jobs()) == 3
    say(monkeypatch)
    job = db.claim_job()
    pipeline.run_job(job)                                                                     # one track done
    page = client.get(f"/items/{aid}").text
    assert "1 of 3 tracks transcribed" in page and "2 waiting" in page and "Transcribe all again" in page
    run_all_jobs()
    page = client.get(f"/items/{aid}").text
    assert "3 of 3 tracks transcribed" in page and "Transcribe tracks" not in page and "waiting" not in page
    assert "Nothing to transcribe" in client.post(f"/albums/{aid}/transcribe").text          # everything is done
    again = client.post(f"/albums/{aid}/transcribe", data={"redo": "1"})
    assert "Transcription queued for 3 tracks" in again.text and len([j for j in jobs() if j["status"] == "queued"]) == 3
    one = client.get(f"/items/{aid}").text
    assert "3 of 3 tracks transcribed" in one                                                 # the old transcripts stay until the new ones replace them


def test_transcribing_needs_a_model_an_album_and_a_login(client, anon, album):
    aid, _ = album
    r = client.post(f"/albums/{aid}/transcribe")
    assert "No transcription model is set up" in r.text and jobs() == []
    enable_transcription(client)
    from test_share import make_item
    assert client.post(f"/albums/{make_item(client)}/transcribe").status_code == 404 and client.post("/albums/99999/transcribe").status_code == 404
    assert anon.post(f"/albums/{aid}/transcribe").status_code in (303, 401)


def test_the_bulk_button_in_settings_includes_album_tracks(client, album):
    aid, _ = album
    enable_transcription(client)
    r = client.post("/settings/ai/reprocess")
    assert "Queued AI processing for 1 item" in r.text and len(jobs()) == 3
    assert "Nothing to queue" in client.post("/settings/ai/reprocess").text


def test_the_jobs_page_names_the_track(client, album):
    aid, tracks = album
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    page = client.get("/jobs").text
    assert "Talk Show · " + tracks[0]["title"].replace("'", "&#39;") in page and "transcribe_track" not in page


def test_renaming_a_track_updates_the_track_search(client, album):
    aid, tracks = album
    client.post(f"/albums/{aid}/tracks", data={f"title_{tracks[0]['id']}": "Unmistakable Zeppelin"})
    home = client.get("/", params={"q": "zeppelin"}).text
    assert 'class="hit"' in home and "<mark>Zeppelin</mark>" in home


def test_deleting_the_album_removes_its_transcripts_and_jobs(client, album, monkeypatch):
    aid, _ = album
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    say(monkeypatch)
    pipeline.run_job(db.claim_job())
    client.post(f"/items/{aid}/delete")
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0] == 0 and c.execute("SELECT COUNT(*) FROM jobs WHERE type='transcribe_track'").fetchone()[0] == 0
    assert 'class="hit"' not in client.get("/", params={"q": "words"}).text


def test_a_track_that_vanished_is_not_an_error(client, album, monkeypatch):
    aid, tracks = album
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    calls = say(monkeypatch)
    with db.tx() as c:
        c.execute("DELETE FROM tracks WHERE id=?", (tracks[0]["id"],))
    run_all_jobs()
    assert len(calls) == 2
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()[0] == 0


def test_a_failing_model_fails_the_job_and_retry_works(client, album, monkeypatch):
    aid, _ = album
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    monkeypatch.setattr(providers, "transcribe", lambda cfg, audio: (_ for _ in ()).throw(providers.ProviderError("server on fire")))
    job = db.claim_job()
    pipeline.run_job(job)
    with db.tx() as c:
        row = c.execute("SELECT status, error FROM jobs WHERE id=?", (job["id"],)).fetchone()
    assert row["status"] == "queued" and "server on fire" in row["error"]                  # it will be tried again by itself
    with db.tx() as c:
        assert albums.transcription_state(c, aid)["done"] == 0


def test_an_empty_answer_still_counts_as_done(client, tmp_path, monkeypatch):
    upload(client, [make_audio(tmp_path / "jingle.mp3", "libmp3lame", seconds=2)], title="Instrumental")
    aid = album_id(client)
    enable_transcription(client)
    client.post(f"/albums/{aid}/transcribe")
    monkeypatch.setattr(providers, "transcribe", lambda cfg, audio: "")
    run_all_jobs()
    with db.tx() as c:
        assert albums.tracks_of(c, aid)[0]["transcribed_at"] and albums.transcription_state(c, aid)["done"] == 1
    assert "1 of 1 track transcribed" in client.get(f"/items/{aid}").text


def test_an_older_database_gets_the_columns_and_the_track_index(tmp_path):
    con = sqlite3.connect(tmp_path / "old.db")
    con.row_factory = sqlite3.Row
    con.executescript("CREATE TABLE tracks (id INTEGER PRIMARY KEY, item_id INTEGER, position INTEGER, title TEXT NOT NULL DEFAULT '');"
                      "INSERT INTO tracks(item_id,position,title) VALUES (1,1,'Old Song');")
    db._migrate_tracks(con)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(tracks)")}
    assert {"transcript", "transcribed_at"} <= cols
    assert con.execute("SELECT transcribed_at FROM tracks").fetchone()[0] is None                    # existing tracks count as not transcribed
