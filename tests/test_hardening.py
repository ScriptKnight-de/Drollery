"""Small protections added after the checklist review: robots, common passwords, finished-job retention, one submit per form."""
import re
import time
from pathlib import Path

from drollery import db, security

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "drollery" / "static"


def test_robots_txt_asks_every_crawler_to_stay_away(anon):
    r = anon.get("/robots.txt")
    assert r.status_code == 200 and "Disallow: /" in r.text and r.headers["content-type"].startswith("text/plain")


def test_every_answer_says_noindex(client, anon):
    for resp in (client.get("/"), anon.get("/login"), anon.get("/healthz")):
        assert resp.headers["x-robots-tag"] == "noindex, nofollow"


def test_a_common_password_is_refused_even_when_it_is_long_enough():
    assert security.password_problem("Password123", "someone")
    assert security.password_problem("QWERTYUIOP", "someone")
    assert not security.password_problem("correct horse battery", "someone")


def test_finished_jobs_older_than_the_keep_time_are_deleted_at_start(client):
    old = time.time() - (db.JOB_KEEP_DAYS + 1) * 86400
    with db.tx() as c:
        for status, when in (("done", old), ("done", time.time()), ("failed", old)):
            c.execute("INSERT INTO jobs(type,status,created_at,updated_at) VALUES ('x',?,?,?)", (status, when, when))
    db.init()
    with db.tx() as c:
        left = sorted((r["status"], r["updated_at"] > old + 86400) for r in c.execute("SELECT status, updated_at FROM jobs WHERE type='x'"))
    assert left == [("done", True), ("failed", False)]          # the old finished one went, the failed one stays for the owner to see


def test_the_double_submit_guard_is_loaded_and_leaves_htmx_forms_alone(client):
    assert re.search(r'/static/once\.js\?v=', client.get("/").text)
    js = (STATIC / "once.js").read_text()
    assert "hx-post" in js and "preventDefault" in js


def test_small_controls_grow_on_touch_screens_and_headlines_balance():
    css = (STATIC / "style.css").read_text()
    assert re.search(r"@media \(pointer: coarse\) \{[^@]*min-height: 44px", css)
    assert "text-wrap: balance" in css and "text-wrap: pretty" in css


def test_the_playful_theme_no_longer_wiggles_the_menu_on_every_hover():
    css = (STATIC / "style-playful.css").read_text()
    assert not re.search(r"\.nav-link:hover[^{]*\{[^}]*animation", css)


def test_the_compose_file_drops_capabilities_and_can_bind_to_one_address():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "cap_drop: [ALL]" in compose and "no-new-privileges:true" in compose and "${DROLLERY_BIND:-0.0.0.0}" in compose
