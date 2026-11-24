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


def test_the_compose_file_makes_the_container_read_only_with_every_write_going_to_the_data_volume():
    compose = (ROOT / "docker-compose.yml").read_text()
    drollery = compose.split("  # ---- Optional local speech-to-text")[0]
    assert "read_only: true" in drollery and "- /tmp:size=" in drollery and "TMPDIR: /data/tmp" in drollery
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "HOME=/data/.home" in dockerfile and "XDG_CACHE_HOME=/data/.cache" in dockerfile      # what read_only relies on


def test_the_logo_wiggles_in_every_theme_and_the_title_squiggle_is_gone():
    base = (STATIC / "style.css").read_text()
    assert re.search(r"\.brand:is\(:hover, :focus-visible\) \.mark \{ animation: logo-wiggle", base)       # no theme selector: all of them
    playful = (STATIC / "style-playful.css").read_text()
    assert "squiggle" not in playful and "h1::after" not in playful
    assert not (STATIC / "squiggle.svg").exists()


def test_the_default_size_limit_is_ten_gigabytes():
    from drollery.config import Settings
    assert Settings().max_upload_mb == 10240
    assert "max_upload_mb = 10240" in (ROOT / "src" / "drollery" / "config.default.toml").read_text()


def test_a_closed_dialog_can_never_cover_the_page():
    """0.15.0 gave the zoom window the class "zoom", which the card editor's slider already used with display: grid; that made
    the closed window a full-screen invisible layer over the whole page. Every dialog in the page frame has a class of its
    own and a rule that hides it while closed."""
    css = (STATIC / "style.css").read_text()
    base = (ROOT / "src" / "drollery" / "templates" / "base.html").read_text()
    assert 'id="zoom-dialog" class="bigview"' in base and ".bigview:not([open]) { display: none; }" in css
    for cls in re.findall(r'<dialog[^>]*class="([^" ]+)', base):
        rules = re.findall(r"(?m)^([^{}\n]*(?<![\w-])" + re.escape(cls) + r"(?![\w-])[^{}\n]*)\{([^}]*)\}", css)
        shown = [sel for sel, body in rules if "display" in body and "[open]" not in sel and ":not([open])" not in sel
                 and re.search(r"(?<![\w-])" + re.escape(cls) + r"(?![\w-])", sel.split()[-1])]       # a rule for the dialog itself, not for something inside it
        assert not shown, f"the closed dialog .{cls} would be shown by: {shown}"
    template_classes = set(re.findall(r'class="([^"]*)"', (ROOT / "src" / "drollery" / "templates" / "item_card.html").read_text()))
    assert "bigview" not in " ".join(template_classes)


def test_a_long_link_or_error_text_cannot_push_the_drop_zone_wider():
    css = (STATIC / "style.css").read_text()
    assert re.search(r"\.uploader \{[^}]*grid-template-columns: minmax\(0, 1fr\)", css)                # a grid column may shrink below its content
    assert re.search(r"\.upload-panel \.up-detail[^{]*\{ overflow-wrap: anywhere", css)
