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
        c.execute("INSERT INTO jobs(type,item_id,payload,status,created_at,updated_at) VALUES ('ocr',NULL,'{}','queued',?,?)", (time.time(), time.time()))
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
