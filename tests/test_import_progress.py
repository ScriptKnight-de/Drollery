"""A link download shows a progress bar on the library page, and the AI steps start on import only when they are set up
and switched on for imports."""
import json
import subprocess
from pathlib import Path

import pytest

from drollery import accounts, aisettings, db, pipeline, providers
from test_app import png
from test_card import red_then_blue_video
from test_fetch import fake_downloader, fetch_job, make_video


def jobs():
    with db.tx() as c:
        return [(r["type"], json.loads(r["payload"])) for r in c.execute("SELECT type, payload FROM jobs ORDER BY id")]


# ---------------------------------------------------------------- the link's progress bar

def test_a_link_from_the_progress_bar_answers_with_the_job_and_a_plain_form_is_still_redirected(client, monkeypatch):
    monkeypatch.setattr("drollery.netguard.check_url", lambda url: None)
    r = client.post("/add", data={"url": "https://media.example/a.mp4"}, headers={"X-Drollery-Upload": "1"}, follow_redirects=False)
    assert r.status_code == 200 and r.json()["job"] > 0
    plain = client.post("/add", data={"url": "https://media.example/b.mp4"}, follow_redirects=False)
    assert plain.status_code == 303 and plain.headers["location"] == "/jobs"


def test_the_job_status_tells_where_the_download_stands(client):
    with db.tx() as c:
        job = db.enqueue(c, "fetch", None, json.dumps({"url": "https://media.example/a.mp4"}))
    assert client.get(f"/jobs/{job}/status").json()["status"] == "queued"
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='running', progress=42.5 WHERE id=?", (job,))
    d = client.get(f"/jobs/{job}/status").json()
    assert d["status"] == "running" and d["progress"] == 42.5 and d["item_id"] is None
    assert client.get("/jobs/99999/status").status_code == 404


def test_a_finished_download_points_the_job_at_the_new_item(client, monkeypatch, tmp_path):
    seen = []
    fake_downloader(monkeypatch, {"Clip [abc].mp4": make_video(tmp_path, "x.mp4")}, seen)
    with db.tx() as c:
        job = db.enqueue(c, "fetch", None, json.dumps({"url": "https://www.youtube.com/watch?v=BiM39zlpyxs"}))
    pipeline.job_fetch({**fetch_job(), "id": job})
    d = client.get(f"/jobs/{job}/status").json()
    assert d["item_id"] and d["progress"] == 100
    assert "--newline" in seen[0]


def test_percentages_from_ytdlp_reach_the_job_while_it_runs(client, tmp_path, monkeypatch):
    fake = tmp_path / "yt-dlp"
    fake.write_text("#!/bin/sh\nfor p in 5.0 40.2 40.2 99.9 100; do echo \"[download]  $p% of 10MiB at 1MiB/s\"; done\necho 'warning text' >&2\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    with db.tx() as c:
        job = db.enqueue(c, "fetch", None, "{}")
    seen = []
    real = pipeline._set_progress
    monkeypatch.setattr(pipeline, "_set_progress", lambda j, p: (seen.append(p), real(j, p)))
    pipeline._running.job_id = job
    try:
        r = pipeline._run_tool(["yt-dlp", "x"], 30)
    finally:
        pipeline._running.job_id = None
    assert seen == [5, 40, 99] and r.returncode == 0 and "warning text" in r.stderr and "100%" in r.stdout


def test_the_progress_bar_script_follows_a_job_and_opens_the_item():
    js = (Path(__file__).resolve().parent.parent / "src/drollery/static/upload.js").read_text()
    assert "d.job" in js and "/jobs/" in js and '"/items/" + d.item_id' in js


# ---------------------------------------------------------------- AI steps on import

def test_nothing_is_queued_on_import_without_a_model(client):
    client.post("/api/v1/items", files={"file": ("a.png", png(1), "image/png")})
    assert jobs() == []


def test_a_step_that_is_switched_off_for_imports_does_not_start_but_can_still_be_asked_for(client, monkeypatch):
    monkeypatch.setattr(aisettings, "enabled", lambda cap: True)
    accounts.set_setting("ai.auto.describe", "0")
    i = client.post("/api/v1/items", files={"file": ("a.png", png(2), "image/png")}).json()["id"]
    assert jobs() == []                                                   # imported: nothing by itself
    with db.tx() as c:
        assert pipeline.plan_jobs(c, i) == ["describe"]                   # by hand: it runs
    assert [t for t, _ in jobs()] == ["describe"]


def test_a_step_that_is_on_for_imports_starts_with_the_marker(client, monkeypatch):
    monkeypatch.setattr(aisettings, "enabled", lambda cap: True)
    client.post("/api/v1/items", files={"file": ("a.png", png(3), "image/png")})
    assert jobs() == [("describe", {"auto": True})]


def test_transcription_of_an_import_goes_on_to_describe_only_when_describe_is_on_for_imports(client, monkeypatch, tmp_path):
    monkeypatch.setattr(aisettings, "enabled", lambda cap: True)
    monkeypatch.setattr(aisettings, "provider", lambda cap: None)
    monkeypatch.setattr(pipeline.media, "extract_audio", lambda src, dst: dst.write_bytes(b"x"))
    monkeypatch.setattr(providers, "transcribe", lambda prov, audio: "hello")
    accounts.set_setting("ai.auto.describe", "0")
    i = client.post("/api/v1/items", files={"file": ("a.mp4", red_then_blue_video(tmp_path / "a.mp4"), "video/mp4")}).json()["id"]
    with db.tx() as c:
        c.execute("DELETE FROM jobs")
        db.enqueue(c, "transcribe", i, json.dumps({"auto": True}))
    pipeline.job_transcribe({"id": 1, "item_id": i, "type": "transcribe", "payload": json.dumps({"auto": True}), "attempts": 1})
    assert "describe" not in [t for t, _ in jobs()[1:]]
    pipeline.job_transcribe({"id": 1, "item_id": i, "type": "transcribe", "payload": json.dumps({}), "attempts": 1})      # by hand: it chains
    assert "describe" in [t for t, _ in jobs()]


def test_the_settings_page_saves_the_run_on_import_boxes(client):
    page = client.get("/settings/ai").text
    assert 'name="auto_transcribe"' in page and 'name="auto_describe"' in page and page.count("checked") >= 2
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": "default", "auto_set": "1", "auto_transcribe": "1"})
    assert aisettings.auto("transcribe") and not aisettings.auto("describe")
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": "default"})            # an older form without the boxes changes nothing
    assert aisettings.auto("transcribe") and not aisettings.auto("describe")
