import re
import json
import time

from drollery import db, pipeline


def make_failed_job(client, n=1, kind="describe"):
    """A failed job for a real item (or a failed download job when kind == 'fetch')."""
    from test_app import png
    item_id = client.post("/api/v1/items", files={"file": (f"j{n}.png", png(200 + n), "image/png")}).json()["id"]
    with db.tx() as c:
        if kind == "fetch":
            jid = db.enqueue(c, "fetch", None, json.dumps({"url": "http://example.invalid/x.png"}))
        else:
            jid = db.enqueue(c, kind, item_id)
        c.execute("UPDATE jobs SET status='failed', attempts=3, error='ProviderError: server down' WHERE id=?", (jid,))
    return item_id, jid


def row(jid):
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())


def test_retry_one_failed_job_leaves_the_others_alone(client):
    _, a = make_failed_job(client, 1)
    _, b = make_failed_job(client, 2)
    r = client.post(f"/jobs/{a}/retry", data={"next": "/jobs"})
    assert r.status_code == 200 and "Job queued again" in r.text
    first, second = row(a), row(b)
    assert first["status"] == "queued" and first["attempts"] == 0 and first["error"] == "" and first["run_after"] == 0
    assert second["status"] == "failed" and second["attempts"] == 3 and "server down" in second["error"]     # untouched


def test_each_failed_row_has_its_own_retry_button_and_others_do_not(client):
    _, failed = make_failed_job(client, 1)
    _, other = make_failed_job(client, 2)
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='done', error='' WHERE id=?", (other,))
        c.execute("INSERT INTO jobs(type,item_id,payload,status,created_at,updated_at,run_after) VALUES ('describe',NULL,'{}','queued',?,?,4e9)", (time.time(), time.time()))   # far ahead: the worker must not claim it mid-test
    html = client.get("/jobs").text
    assert f'action="/jobs/{failed}/retry"' in html
    assert f'action="/jobs/{other}/retry"' not in html and html.count("/retry\"") == 1
    assert 'action="/jobs/retry-failed"' in html                                         # the bulk button is still there


def test_retry_button_on_the_item_page(client):
    item_id, jid = make_failed_job(client, 1)
    html = client.get(f"/items/{item_id}").text
    assert f'action="/jobs/{jid}/retry"' in html and f'value="/items/{item_id}"' in html
    r = client.post(f"/jobs/{jid}/retry", data={"next": f"/items/{item_id}"})
    assert "Job queued again" in r.text and row(jid)["status"] == "queued"                # lands back on the item page
    assert f'action="/jobs/{jid}/retry"' not in client.get(f"/items/{item_id}").text


def test_only_failed_jobs_can_be_retried(client):
    _, jid = make_failed_job(client, 1)
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    r = client.post(f"/jobs/{jid}/retry")
    assert "failed state any more" in r.text and row(jid)["status"] == "running"
    assert "failed state any more" in client.post("/jobs/99999/retry").text               # unknown id: same polite answer


def test_next_cannot_redirect_off_site(client):
    _, jid = make_failed_job(client, 1)
    r = client.post(f"/jobs/{jid}/retry", data={"next": "https://evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/jobs"


def test_a_retried_job_really_runs_again(client, monkeypatch):
    """Not just a status change: the worker claims it and executes the handler once more."""
    _, jid = make_failed_job(client, 1)
    ran = []
    monkeypatch.setitem(pipeline.HANDLERS, "describe", lambda job: ran.append(job["id"]))
    assert db.claim_job() is None                                                         # failed jobs are never picked up
    client.post(f"/jobs/{jid}/retry")
    job = db.claim_job()
    assert job["id"] == jid
    pipeline.run_job(job)
    assert ran == [jid] and row(jid)["status"] == "done"


def test_a_failed_download_job_can_be_retried_too(client):
    _, jid = make_failed_job(client, 1, kind="fetch")
    client.post(f"/jobs/{jid}/retry")
    assert row(jid)["status"] == "queued" and json.loads(row(jid)["payload"])["url"] == "http://example.invalid/x.png"


def test_bulk_retry_also_clears_old_errors(client):
    _, a = make_failed_job(client, 1)
    client.post("/jobs/retry-failed")
    assert row(a)["status"] == "queued" and row(a)["error"] == ""


def test_retry_needs_a_login_and_has_an_api_endpoint(client):
    import re
    from fastapi.testclient import TestClient
    from drollery.main import app
    _, jid = make_failed_job(client, 1)
    anon = TestClient(app, follow_redirects=False)
    assert anon.post(f"/jobs/{jid}/retry").headers["location"] == "/login"
    assert row(jid)["status"] == "failed"
    key = re.search(r'id="new-key">(drl_[\w-]+)<', client.post("/settings/keys", data={"name": "app", "kind": "app"}).text).group(1)
    auth = {"Authorization": f"Bearer {key}"}
    assert anon.post(f"/api/v1/jobs/{jid}/retry").status_code == 401
    r = anon.post(f"/api/v1/jobs/{jid}/retry", headers=auth)
    assert r.status_code == 202 and r.json() == {"job_id": jid, "status": "queued"}
    assert anon.post(f"/api/v1/jobs/{jid}/retry", headers=auth).status_code == 409          # no longer failed
    assert anon.post("/api/v1/jobs/99999/retry", headers=auth).status_code == 404


# ---------------------------------------------------- reading the whole error

def test_the_whole_error_is_available_in_the_list_and_on_the_item_page(client):
    long_error = "MediaError: audio extraction failed: " + " ".join(f"line{i}-detail" for i in range(120))      # ~1.4 kB
    item_id, jid = make_failed_job(client, 1)
    with db.tx() as c:
        c.execute("UPDATE jobs SET error=? WHERE id=?", (long_error, jid))
    for page in (client.get("/jobs").text, client.get(f"/items/{item_id}").text):
        assert '<details class="errbox">' in page and "Click to read the whole message" in page
        assert "<pre>" + long_error + "</pre>" in page                      # the whole message, untruncated, in a scrollable block
        assert f'data-copy="{long_error}"' in page and "Copy error" in page


def test_error_text_is_escaped_not_executed(client):
    item_id, jid = make_failed_job(client, 1)
    with db.tx() as c:
        c.execute("UPDATE jobs SET error=? WHERE id=?", ('<script>alert(1)</script> & "quoted"', jid))
    page = client.get("/jobs").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_long_errors_are_stored_and_returned_in_full(client):
    item_id, jid = make_failed_job(client, 1)
    big = "x" * 5000                                                         # used to be cut at 2000 characters
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='running', attempts=3 WHERE id=?", (jid,))
    db.finish_job(jid, big, max_attempts=3, attempts=3)
    got = next(j for j in client.get("/api/v1/jobs").json()["jobs"] if j["id"] == jid)
    assert got["error"] == big
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    db.finish_job(jid, "y" * 20000, max_attempts=3, attempts=3)
    assert len(row(jid)["error"]) == 8000                                    # a sane upper bound


def test_tool_errors_keep_their_detail(monkeypatch, tmp_path):
    """ffmpeg's message used to be cut at 300 characters, losing the useful part."""
    import subprocess
    from drollery import media
    detail = "[out#0/mp3] " + "reason " * 200                                # ~1.4 kB
    monkeypatch.setattr(media, "_run", lambda cmd, timeout=120: subprocess.CompletedProcess(cmd, 1, "", detail))
    try:
        media.extract_audio(tmp_path / "in.mp4", tmp_path / "out.mp3")
    except media.MediaError as e:
        assert detail.strip() in str(e) and len(str(e)) > 1200
    else:
        raise AssertionError("expected a MediaError")


# ------------------------------------------------------------------ deleting failed jobs

def test_a_failed_job_can_be_deleted_and_nothing_else_is_touched(client):
    item_a, a = make_failed_job(client, 1)
    item_b, b = make_failed_job(client, 2)
    r = client.post(f"/jobs/{a}/delete")
    assert r.status_code == 200 and "Job deleted" in r.text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE id=?", (a,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM items WHERE id=?", (item_a,)).fetchone()[0] == 1       # the item stays
    assert row(b)["status"] == "failed"


def test_only_failed_jobs_can_be_deleted(client):
    _, jid = make_failed_job(client, 1)
    for status in ("queued", "running", "done"):
        with db.tx() as c:
            c.execute("UPDATE jobs SET status=? WHERE id=?", (status, jid))
        r = client.post(f"/jobs/{jid}/delete")
        assert "only failed jobs can be removed" in r.text and row(jid)["status"] == status
    assert "only failed jobs" in client.post("/jobs/99999/delete").text                              # unknown id: same calm answer


def test_delete_failed_clears_every_failed_job_and_keeps_the_rest(client):
    _, a = make_failed_job(client, 1)
    _, b = make_failed_job(client, 2, kind="fetch")
    _, keep = make_failed_job(client, 3)
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='queued', error='' WHERE id=?", (keep,))
    r = client.post("/jobs/delete-failed")
    assert "Deleted 2 failed job(s)" in r.text
    with db.tx() as c:
        left = [x["id"] for x in c.execute("SELECT id FROM jobs ORDER BY id")]
    assert a not in left and b not in left and keep in left
    assert "There were no failed jobs" in client.post("/jobs/delete-failed").text


def test_the_jobs_page_offers_delete_only_where_it_applies(client):
    _, failed = make_failed_job(client, 1)
    _, other = make_failed_job(client, 2)
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='done', error='' WHERE id=?", (other,))
    html = client.get("/jobs").text
    assert f'action="/jobs/{failed}/delete"' in html and f'action="/jobs/{other}/delete"' not in html
    assert re.search(r'<form[^>]*action="/jobs/delete-failed"[^>]*data-confirm=', html)                  # asks before clearing the list


# ------------------------------------------------------------ how many jobs run at once

def test_the_number_of_parallel_jobs_is_set_in_the_ai_settings(client):
    from drollery import accounts
    assert accounts.worker_limit() == 1                                                  # the config.toml default
    page = client.get("/settings/ai").text
    assert "Jobs at the same time" in page and '<option value="1" selected>' in page
    r = client.post("/settings/ai/concurrency", data={"concurrency": "3"})
    assert "Up to 3 background jobs at a time" in r.text
    assert accounts.worker_limit() == 3 and '<option value="3" selected>' in client.get("/settings/ai").text
    client.post("/settings/ai/concurrency", data={"concurrency": "99"})                  # out of range is clamped, never trusted
    assert accounts.worker_limit() == accounts.MAX_WORKERS
    client.post("/settings/ai/concurrency", data={"concurrency": "0"})
    assert accounts.worker_limit() == 1


def test_the_setting_beats_the_config_and_junk_falls_back_to_one(client):
    from drollery import accounts
    accounts.set_setting("jobs.concurrency", "oops")
    assert accounts.worker_limit() == 1
    accounts.set_setting("jobs.concurrency", None)
    assert accounts.worker_limit() == 1


def test_only_as_many_workers_claim_jobs_as_the_limit_allows(tmp_path, monkeypatch):
    """Eight loops exist; slot n takes jobs only while the limit is above n, so raising or lowering it needs no restart.
    No app is started here (its own workers would take part): just the database and the loops."""
    import asyncio, time
    from conftest import _boot
    from drollery import accounts, db, main, pipeline
    _boot(tmp_path, monkeypatch)
    db.init()

    async def run(limit):
        accounts.set_setting("jobs.concurrency", str(limit))
        claimed, ran = [], []
        monkeypatch.setattr(db, "claim_job", lambda: claimed.append(1) or ({"id": len(claimed)} if len(claimed) <= 8 else None))
        monkeypatch.setattr(pipeline, "run_job", lambda job: (ran.append(job["id"]), time.sleep(0.4)))
        stop = asyncio.Event()
        tasks = [asyncio.create_task(main._worker_loop(stop, n)) for n in range(accounts.MAX_WORKERS)]
        await asyncio.sleep(0.2)
        running = len(ran)                                                               # these are all busy inside run_job now
        stop.set()
        await asyncio.gather(*tasks)
        return running

    assert asyncio.run(run(1)) == 1
    assert asyncio.run(run(3)) == 3
    assert asyncio.run(run(8)) == 8


# ------------------------------------------------ transcribe and describe on their own

def _talking_clip(client, tmp_path):
    from test_fetch import make_video
    r = client.post("/api/v1/items", files={"file": ("clip.mp4", make_video(tmp_path, "clip.mp4"), "video/mp4")})
    return r.json()["id"]


def _both_models(client):
    from test_accounts import MODEL
    from drollery import accounts
    client.post("/settings/ai/models", data={**MODEL, "name": "stt", "model": "whisper-1"})
    client.post("/settings/ai/models", data={**MODEL, "name": "llm", "model": "chat-1"})
    ids = {m["name"]: str(m["id"]) for m in accounts.list_models()}
    client.post("/settings/ai/assign", data={"transcribe": ids["stt"], "describe": ids["llm"]})


def _queued():
    with db.tx() as c:
        rows = c.execute("SELECT type, payload FROM jobs WHERE status='queued' ORDER BY id").fetchall()
        c.execute("DELETE FROM jobs")
    return [(r["type"], r["payload"]) for r in rows]


def _pause_workers(monkeypatch):
    """The app's own workers would claim the queued rows under the test: tell them the limit is zero."""
    from drollery import accounts
    monkeypatch.setattr(accounts, "worker_limit", lambda: 0)


def test_transcribing_and_describing_can_be_started_separately(client, tmp_path, monkeypatch):
    _pause_workers(monkeypatch)
    item = _talking_clip(client, tmp_path)
    _both_models(client)
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
    page = client.get(f"/items/{item}").text
    assert "Transcribe only" in page and "Describe only" in page

    client.post(f"/items/{item}/reprocess", data={"step": "describe"})
    assert [t for t, _ in _queued()] == ["describe"]
    client.post(f"/items/{item}/reprocess", data={"step": "transcribe"})
    queued = _queued()
    assert [t for t, _ in queued] == ["transcribe"]                                      # and nothing else
    client.post(f"/items/{item}/reprocess")                                              # the old button: transcribe, which goes on to describe
    assert [t for t, _ in _queued()] == ["transcribe"]
    client.post(f"/items/{item}/reprocess", data={"step": "nonsense"})                   # unknown value = the old behaviour
    assert [t for t, _ in _queued()] == ["transcribe"]


def test_a_transcription_started_on_its_own_does_not_describe_afterwards(client, tmp_path, monkeypatch):
    from drollery import pipeline, providers
    _pause_workers(monkeypatch)
    item = _talking_clip(client, tmp_path)
    _both_models(client)
    monkeypatch.setattr(providers, "transcribe", lambda cfg, audio: "some spoken words")
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
    client.post(f"/items/{item}/reprocess", data={"step": "transcribe"})
    pipeline.run_job(db.claim_job())
    assert _queued() == []                                                               # no describe job followed
    client.post(f"/items/{item}/reprocess")
    pipeline.run_job(db.claim_job())
    assert [t for t, _ in _queued()] == ["describe"]                                     # the normal run still chains


def test_the_bulk_buttons_do_one_step_for_every_item(client, tmp_path, monkeypatch):
    _pause_workers(monkeypatch)
    _talking_clip(client, tmp_path)
    _both_models(client)
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
    client.post("/settings/ai/reprocess", data={"step": "describe"})
    assert "Only describe" in client.get("/settings/ai").text and "Only transcribe" in client.get("/settings/ai").text
    assert {t for t, _ in _queued()} == {"describe"}
    client.post("/settings/ai/reprocess", data={"step": "transcribe"})
    assert {t for t, _ in _queued()} == {"transcribe"}


def test_a_new_video_that_takes_over_a_deleted_ones_id_gets_a_fresh_preview_address(client, tmp_path):
    """SQLite hands the id of the last deleted item to the next one, and the browser keeps a preview for a day:
    the address of the preview must therefore change with the item, or the old picture shows up."""
    import re, subprocess, time
    from test_fetch import make_video

    def poster(i):
        return re.search(r'poster="(/thumb/\d+\?v=\d+)"', client.get(f"/items/{i}").text).group(1)

    first = _talking_clip(client, tmp_path)
    before = poster(first)
    client.post(f"/items/{first}/delete")
    time.sleep(0.01)
    other = tmp_path / "other.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=160x120:r=10:d=1", "-f", "lavfi", "-i", "sine=f=500:d=1",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "libopus", str(other)], check=True)
    second = client.post("/api/v1/items", files={"file": ("other.mp4", other.read_bytes(), "video/mp4")}).json()["id"]
    assert second == first                                                               # the id really is reused
    assert poster(second) != before


# ------------------------------------------------------------ small web-platform details

def test_the_windows_close_on_the_backdrop_by_themselves_and_the_script_only_covers_old_browsers(client):
    """closedby="any" does the backdrop click natively; the scripts keep it only where the browser lacks it (progressive enhancement)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "drollery"
    assert 'id="confirm-dialog" class="modal confirm" closedby="any"' in client.get("/").text
    assert 'closedby="any"' in (root / "templates" / "popup_dialog.html").read_text()
    assert 'id="transcript-dialog" class="modal" closedby="any"' in (root / "templates" / "album.html").read_text()
    for js in ("popup.js", "transcript.js"):
        text = (root / "static" / js).read_text()
        assert '"closedBy" in HTMLDialogElement.prototype' in text and "!nativeLightDismiss && e.target === dlg" in text
    assert "e.isComposing" in (root / "static" / "uploader.js").read_text()                 # Enter that confirms an IME word does not add the link
