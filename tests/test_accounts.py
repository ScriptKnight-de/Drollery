import re
import sqlite3

from conftest import PASSWORD
from drollery import accounts, aisettings, db, pipeline, providers, security
from test_app import png


# ------------------------------------------------------------- first run

def test_everything_redirects_to_setup_until_an_admin_exists(anon):
    assert anon.get("/").headers["location"] == "/setup"
    assert anon.get("/jobs").headers["location"] == "/setup"
    assert anon.get("/login").headers["location"] == "/setup"
    r = anon.get("/api/v1/items")
    assert r.status_code == 503 and "Setup required" in r.json()["detail"]
    assert anon.get("/healthz").status_code == 200
    page = anon.get("/setup")
    assert page.status_code == 200 and "Setup code" in page.text


def test_setup_needs_the_code_and_a_decent_password(anon):
    good = {"username": "boss", "password": "a-long-enough-pass", "password2": "a-long-enough-pass"}
    code = accounts.get_setup_code()

    r = anon.post("/setup", data={**good, "code": "wrong"})
    assert r.status_code == 422 and "setup code" in r.text and accounts.user_count() == 0
    r = anon.post("/setup", data={**good, "code": code, "password": "short", "password2": "short"})
    assert r.status_code == 422 and "at least 10" in r.text
    r = anon.post("/setup", data={**good, "code": code, "password2": "different-pass-word"})
    assert r.status_code == 422 and "do not match" in r.text
    r = anon.post("/setup", data={**good, "code": code, "username": "x y"})
    assert r.status_code == 422 and "Username" in r.text
    assert accounts.user_count() == 0

    r = anon.post("/setup", data={**good, "code": code})
    assert r.status_code == 303 and r.headers["location"] == "/settings/ai"
    assert "drollery_session" in anon.cookies and accounts.user_count() == 1
    assert not accounts.setup_code_path().exists()                       # the code is single-use
    assert anon.get("/setup").headers["location"] == "/"                  # setup closes itself
    again = anon.post("/setup", data={**good, "code": code, "username": "second"})
    assert again.headers["location"] == "/" and accounts.user_count() == 1


def test_setup_code_can_come_from_the_environment(anon, monkeypatch):
    monkeypatch.setenv("DROLLERY_SETUP_CODE", "my-own-code")
    r = anon.post("/setup", data={"code": "my-own-code", "username": "boss", "password": "a-long-enough-pass", "password2": "a-long-enough-pass"})
    assert r.status_code == 303


def test_setup_code_attempts_are_throttled(anon):
    for _ in range(30):
        anon.post("/setup", data={"code": "nope", "username": "boss", "password": "a-long-enough-pass", "password2": "a-long-enough-pass"})
    r = anon.post("/setup", data={"code": accounts.get_setup_code(), "username": "boss", "password": "a-long-enough-pass", "password2": "a-long-enough-pass"})
    assert r.status_code == 429 and accounts.user_count() == 0


# ----------------------------------------------------------------- login

def test_login_logout_and_protection(client):
    client.follow_redirects = False
    assert client.get("/").status_code == 200
    client.post("/logout")
    assert client.get("/").headers["location"] == "/login"
    r = client.post("/login", data={"username": "admin", "password": "wrong wrong wrong"})
    assert r.status_code == 401 and "Wrong username or password" in r.text
    r = client.post("/login", data={"username": "nobody", "password": PASSWORD})
    assert r.status_code == 401 and "Wrong username or password" in r.text      # same message: no username enumeration
    assert client.post("/login", data={"username": "ADMIN", "password": PASSWORD}).status_code == 303   # usernames are case-insensitive
    assert client.get("/").status_code == 200


def test_login_is_throttled(client):
    client.follow_redirects = False
    client.post("/logout")
    for _ in range(5):
        assert client.post("/login", data={"username": "admin", "password": "nope nope nope"}).status_code == 401
    r = client.post("/login", data={"username": "admin", "password": PASSWORD})          # even the right password is refused now
    assert r.status_code == 429


def test_passwords_are_hashed_not_stored(client):
    with db.tx() as c:
        stored = c.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert security.verify_password(PASSWORD, stored) and not security.verify_password("other", stored)


def test_cross_site_posts_are_blocked(client):
    r = client.post("/logout", headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403
    assert client.get("/").status_code == 200                               # still signed in
    ok = client.post("/settings/profile", data={"email": ""}, headers={"origin": "http://testserver"}, follow_redirects=False)
    assert ok.status_code == 303


# --------------------------------------------------------------- profile

def test_profile_update_and_validation(client):
    r = client.post("/settings/profile", data={"email": "me@example.org"})
    assert r.status_code == 200 and "Profile saved" in r.text and "me@example.org" in r.text
    bad = client.post("/settings/profile", data={"email": "not-an-email"})
    assert bad.status_code == 422 and "email address" in bad.text
    assert accounts.get_user_by_name("admin")["email"] == "me@example.org"


def test_password_change_signs_out_other_devices(client):
    from fastapi.testclient import TestClient
    from drollery.main import app
    with TestClient(app, follow_redirects=False) as other:
        assert other.post("/login", data={"username": "admin", "password": PASSWORD}).status_code == 303
        assert other.get("/").status_code == 200
        bad = client.post("/settings/security/password", data={"current": "wrong", "new": "brand-new-password", "new2": "brand-new-password"})
        assert bad.status_code == 401
        weak = client.post("/settings/security/password", data={"current": PASSWORD, "new": "short", "new2": "short"})
        assert weak.status_code == 422
        ok = client.post("/settings/security/password", data={"current": PASSWORD, "new": "brand-new-password", "new2": "brand-new-password"})
        assert ok.status_code == 200 and "Password changed" in ok.text
        assert client.get("/").status_code == 200                           # this device stays signed in
        assert other.get("/").headers["location"] == "/login"               # the other one is gone
        assert other.post("/login", data={"username": "admin", "password": "brand-new-password"}).status_code == 303


# ------------------------------------------------------------------- 2FA

def _enable_2fa(client) -> tuple[str, list[str]]:
    client.post("/settings/security/2fa/start")
    secret = accounts.get_user_by_name("admin")["totp_pending"]
    page = client.get("/settings/security")
    assert "<svg" in page.text and secret in page.text                       # QR code and the manual key are shown
    r = client.post("/settings/security/2fa/enable", data={"code": security.totp_now(secret)})
    assert r.status_code == 200 and "backup codes" in r.text
    codes = re.findall(r"<li>([0-9a-f]{6}-[0-9a-f]{6})</li>", r.text)
    assert len(codes) == 8
    return secret, codes


def test_enable_2fa_rejects_a_wrong_code(client):
    client.post("/settings/security/2fa/start")
    r = client.post("/settings/security/2fa/enable", data={"code": "000000"})
    assert r.status_code == 422 and not accounts.get_user_by_name("admin")["totp_enabled"]


def test_two_factor_login_flow_and_code_reuse(client):
    secret, codes = _enable_2fa(client)
    client.follow_redirects = False
    client.post("/logout")

    r = client.post("/login", data={"username": "admin", "password": PASSWORD})
    assert r.headers["location"] == "/login/2fa" and "drollery_session" not in client.cookies
    assert client.get("/").headers["location"] == "/login"                   # password alone gets you nowhere
    assert client.post("/login/2fa", data={"code": "123456"}).status_code == 401

    # the code used to switch 2FA on is "spent", so the next one is needed (move the clock a step by faking last_step)
    import time
    step = int(time.time() // 30)
    with db.tx() as c:
        c.execute("UPDATE users SET totp_last_step=?", (step - 2,))
    good = client.post("/login/2fa", data={"code": security.totp_now(secret)})
    assert good.status_code == 303 and good.headers["location"] == "/"
    assert client.get("/").status_code == 200

    client.post("/logout")
    client.post("/login", data={"username": "admin", "password": PASSWORD})
    replay = client.post("/login/2fa", data={"code": security.totp_now(secret)})  # same 30s window: refused
    assert replay.status_code == 401


def test_backup_codes_work_once(client):
    secret, codes = _enable_2fa(client)
    client.follow_redirects = False
    client.post("/logout")
    client.post("/login", data={"username": "admin", "password": PASSWORD})
    assert client.post("/login/2fa", data={"code": codes[0]}).status_code == 303
    client.post("/logout")
    client.post("/login", data={"username": "admin", "password": PASSWORD})
    assert client.post("/login/2fa", data={"code": codes[0]}).status_code == 401      # already used
    assert client.post("/login/2fa", data={"code": codes[1].upper()}).status_code == 303   # case-insensitive
    assert accounts.backup_codes_left(accounts.get_user_by_name("admin")) == 6


def test_wrong_2fa_codes_destroy_the_pending_login(client):
    _enable_2fa(client)
    client.follow_redirects = False
    client.post("/logout")
    client.post("/login", data={"username": "admin", "password": PASSWORD})
    for _ in range(4):
        assert client.post("/login/2fa", data={"code": "111111"}).status_code == 401
    last = client.post("/login/2fa", data={"code": "111111"})
    assert last.status_code == 303 and last.headers["location"] == "/login"
    assert client.get("/login/2fa").headers["location"] == "/login"


def test_disable_2fa_needs_the_password(client):
    _enable_2fa(client)
    assert client.post("/settings/security/2fa/disable", data={"password": "wrong"}).status_code == 401
    assert accounts.get_user_by_name("admin")["totp_enabled"]
    r = client.post("/settings/security/2fa/disable", data={"password": PASSWORD})
    assert "off" in r.text and not accounts.get_user_by_name("admin")["totp_enabled"]


def test_totp_matches_rfc_6238_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"      # ASCII "12345678901234567890", base32
    assert security._hotp(secret, 59 // 30, 8) == "94287082"      # RFC 6238 appendix B, T=59s, SHA-1


# -------------------------------------------------------------- API keys

def test_api_key_lifecycle(client):
    r = client.post("/settings/keys", data={"name": "Firefox laptop", "kind": "browser"})
    token = re.search(r'id="new-key">(drl_[\w-]+)<', r.text).group(1)
    assert "Firefox laptop" in r.text

    with db.tx() as c:                                                        # only a hash is stored
        dump = " ".join(str(tuple(row)) for row in c.execute("SELECT * FROM api_keys"))
    assert token not in dump and security.token_hash(token) in dump

    from fastapi.testclient import TestClient
    from drollery.main import app
    with TestClient(app, follow_redirects=False) as app_client:               # a client with no session cookie
        auth = {"Authorization": f"Bearer {token}"}
        me = app_client.get("/api/v1/me", headers=auth)
        assert me.status_code == 200 and me.json()["via"] == "api_key" and me.json()["username"] == "admin"
        up = app_client.post("/api/v1/items", headers=auth, files={"file": ("from_phone.png", png(3), "image/png")})
        assert up.status_code == 201
        assert app_client.get("/api/v1/items", headers={"Authorization": "Bearer drl_nope"}).status_code == 401
        assert app_client.get("/api/v1/items").status_code == 401
        assert app_client.get("/settings/profile", headers=auth).headers["location"] == "/login"   # keys can't open settings

        key_id = accounts.list_api_keys(1)[0]["id"]
        regen = client.post(f"/settings/keys/{key_id}/regenerate")
        new_token = re.search(r'id="new-key">(drl_[\w-]+)<', regen.text).group(1)
        assert new_token != token
        assert app_client.get("/api/v1/me", headers=auth).status_code == 401                        # old key is dead
        assert app_client.get("/api/v1/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200

        client.post(f"/settings/keys/{key_id}/delete")
        assert app_client.get("/api/v1/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 401
    assert accounts.list_api_keys(1) == []


def test_keys_page_lists_prefix_not_secret(client):
    r = client.post("/settings/keys", data={"name": "Pixel", "kind": "app"})
    token = re.search(r'id="new-key">(drl_[\w-]+)<', r.text).group(1)
    page = client.get("/settings/keys").text
    assert token not in page and token[:8] in page and "Pixel" in page


# ------------------------------------------------------------ AI models

MODEL = {"name": "Home vision", "type": "openai", "base_url": "http://llm.test/v1", "model": "moondream", "api_key": "sk-secret-123",
         "command": "", "langs": "eng", "language": "", "prompt": "", "timeout": 120, "send_image": "1"}


def test_model_crud_never_leaks_the_api_key(client):
    r = client.post("/settings/ai/models", data=MODEL)
    assert r.status_code == 200 and "Home vision" in r.text
    model = accounts.list_models()[0]
    assert model["api_key"] == "sk-secret-123"
    assert "sk-secret-123" not in client.get("/settings/ai").text
    edit = client.get(f"/settings/ai/models/{model['id']}").text
    assert "sk-secret-123" not in edit and "Stored. Leave empty to keep it" in edit

    client.post(f"/settings/ai/models/{model['id']}", data={**MODEL, "model": "llava", "api_key": ""})
    assert accounts.get_model(model["id"])["model"] == "llava" and accounts.get_model(model["id"])["api_key"] == "sk-secret-123"
    client.post(f"/settings/ai/models/{model['id']}", data={**MODEL, "api_key": "", "clear_key": "1"})
    assert accounts.get_model(model["id"])["api_key"] == ""


def test_model_validation(client):
    assert client.post("/settings/ai/models", data={**MODEL, "name": ""}).status_code == 422
    assert client.post("/settings/ai/models", data={**MODEL, "base_url": "ftp://nope"}).status_code == 422
    assert client.post("/settings/ai/models", data={**MODEL, "type": "command", "command": "whisper -f"}).status_code == 422
    client.post("/settings/ai/models", data=MODEL)
    dup = client.post("/settings/ai/models", data={**MODEL, "name": "HOME VISION"})
    assert dup.status_code == 422 and "already has that name" in dup.text


def test_assignment_drives_the_pipeline_without_a_restart(client):
    assert aisettings.provider("describe").enabled is False                    # nothing in config.toml, nothing assigned
    client.post("/settings/ai/models", data=MODEL)
    mid = str(accounts.list_models()[0]["id"])
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": mid})

    p = aisettings.provider("describe")
    assert p.enabled and p.type == "openai" and p.model == "moondream" and p.api_key == "sk-secret-123"

    r = client.post("/api/v1/items", files={"file": ("meme.png", png(21), "image/png")})
    assert r.status_code == 201
    with db.tx() as c:
        jobs = [row["type"] for row in c.execute("SELECT type FROM jobs")]
    assert jobs == ["describe"]

    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": "off"})
    assert aisettings.provider("describe").enabled is False


def test_a_model_cannot_be_assigned_to_a_job_it_cannot_do(client):
    client.post("/settings/ai/models", data=MODEL)                              # an OpenAI chat model
    mid = str(accounts.list_models()[0]["id"])
    client.post("/settings/ai/models", data={**MODEL, "name": "Local cmd", "type": "command", "command": "echo {input}"})
    cmd = str(next(m["id"] for m in accounts.list_models() if m["type"] == "command"))
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": cmd})          # chat naming needs an API model
    assert accounts.get_setting("ai.describe") is None


def test_deleting_a_model_unassigns_it(client):
    client.post("/settings/ai/models", data=MODEL)
    mid = accounts.list_models()[0]["id"]
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": str(mid)})
    client.post(f"/settings/ai/models/{mid}/delete")
    assert accounts.list_models() == [] and accounts.get_setting("ai.describe") is None


def test_ui_defined_model_is_used_for_describe_jobs(client, monkeypatch):
    client.post("/settings/ai/models", data=MODEL)
    mid = str(accounts.list_models()[0]["id"])
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": mid})
    seen = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '{"name":"Wise owl","description":"An owl.","tags":["owl"]}'}}]}

    def fake_post(url, **kw):
        seen["url"], seen["auth"] = url, kw["headers"].get("Authorization")
        return Resp()

    monkeypatch.setattr(providers.httpx, "post", fake_post)
    item_id = client.post("/api/v1/items", files={"file": ("x.png", png(40), "image/png")}).json()["id"]
    pipeline.run_job(db.claim_job())
    assert seen == {"url": "http://llm.test/v1/chat/completions", "auth": "Bearer sk-secret-123"}
    assert client.get(f"/api/v1/items/{item_id}").json()["title"] == "Wise owl"


def test_connection_test(client, monkeypatch):
    class Resp:
        status_code = 200
        def json(self): return {"data": [{"id": "moondream"}, {"id": "llava"}]}

    calls = {}
    def fake_get(url, **kw):
        calls["url"], calls["auth"] = url, kw["headers"].get("Authorization")
        return Resp()

    monkeypatch.setattr(aisettings.httpx, "get", fake_get)
    r = client.post("/settings/ai/test", data={"type": "openai", "base_url": "http://llm.test/v1", "model": "moondream", "api_key": "k"})
    assert "Connected. 2 model(s)" in r.text and "llava" in r.text and calls == {"url": "http://llm.test/v1/models", "auth": "Bearer k"}

    client.post("/settings/ai/models", data=MODEL)                              # editing: the stored key is used
    mid = accounts.list_models()[0]["id"]
    client.post("/settings/ai/test", data={"id": str(mid), "type": "openai", "base_url": "http://llm.test/v1", "model": "moondream", "api_key": ""})
    assert calls["auth"] == "Bearer sk-secret-123"

    bad = client.post("/settings/ai/test", data={"type": "openai", "base_url": "nope", "model": "m"})
    assert "http://" in bad.text and "bad" in bad.text
    missing = client.post("/settings/ai/test", data={"type": "command", "command": "definitely-not-installed {input}"})
    assert "not found" in missing.text


def test_reprocess_existing_items(client):
    client.post("/api/v1/items", files={"file": ("a.png", png(60), "image/png")})
    client.post("/api/v1/items", files={"file": ("b.png", png(61), "image/png")})
    r = client.post("/settings/ai/reprocess")
    assert "Nothing to queue" in r.text                                        # no model assigned yet
    client.post("/settings/ai/models", data=MODEL)
    mid = str(accounts.list_models()[0]["id"])
    client.post("/settings/ai/assign", data={"transcribe": "default", "describe": mid})
    r = client.post("/settings/ai/reprocess")
    assert "Queued AI processing for 2 items" in r.text
    assert "Nothing to queue" in client.post("/settings/ai/reprocess").text    # already queued: no duplicates


def test_qr_svg_reproduces_the_matrix_exactly_and_is_centered():
    """The 2FA QR is drawn module-by-module with a symmetric 4-module quiet zone and whole-pixel size."""
    from drollery import routes_settings as rs
    uri = security.totp_uri("JBSWY3DPEHPK3PXP", "admin")
    matrix = rs.qr_matrix(uri)
    svg = rs.render_qr_svg(matrix)
    n = len(matrix)
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    total = n + 8
    assert vb.groups() == (str(total), str(total))                                # square, quiet zone 4 on every side
    size = int(re.search(r'width="(\d+)"', svg).group(1))
    assert size % total == 0 and size >= 200                                      # integer pixels per module
    rebuilt = [[0] * n for _ in range(n)]
    for x, y, w in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", svg):
        for dx in range(int(w)):
            rebuilt[int(y) - 4][int(x) - 4 + dx] = 1
    assert rebuilt == matrix                                                       # drawn exactly as encoded, nothing shifted
    assert all(not any(r[:0]) for r in matrix)


def test_whisper_preset_matches_the_compose_stack():
    """The UI preset and docker-compose.yml must point at the same service and model, or the one-click setup breaks."""
    from pathlib import Path
    compose = (Path(__file__).parent.parent / "docker-compose.yml").read_text()
    default_model = re.search(r"WHISPER_MODEL:-([\w./-]+)\}", compose).group(1)
    preset = next(p for p in aisettings.PRESETS if p["label"] == "Whisper server")
    assert preset["model"] == default_model and preset["base_url"] == "http://whisper:8000/v1"
    assert re.search(r"^  whisper:\n", compose, re.M) and 'profiles: ["whisper"]' in compose
    assert "ports:" not in compose.split("  whisper:")[1].split("volumes:")[0]           # the server is never published to the host


# ------------------------------------------------------------ impressum

def _foot(html: str) -> bool:
    return 'href="/impressum"' in html


def test_impressum_is_hidden_until_it_is_set_and_switched_on(client, anon):
    assert not _foot(client.get("/").text) and not _foot(anon.get("/login").text) and anon.get("/impressum").status_code == 404
    client.post("/settings/impressum", data={"text": "Max Mustermann", "enabled": "1"})        # on, with text
    assert _foot(client.get("/").text) and _foot(anon.get("/login").text)                        # linked signed in or not
    off = client.post("/settings/impressum", data={"text": "Max Mustermann"})                    # switched off, text kept
    assert "switched off" in off.text and not _foot(client.get("/").text) and not _foot(anon.get("/login").text)
    assert anon.get("/impressum").status_code == 404 and "Max Mustermann" in client.get("/settings/impressum").text
    empty = client.post("/settings/impressum", data={"text": "  ", "enabled": "1"})              # on, but nothing to show
    assert "stays hidden" in empty.text and not _foot(client.get("/").text) and anon.get("/impressum").status_code == 404


def test_impressum_page_is_public_escaped_and_needs_login_to_edit(client, anon):
    client.post("/settings/impressum", data={"text": "Max\n\n<script>alert(1)</script>", "enabled": "1"})
    page = anon.get("/impressum")
    assert page.status_code == 200 and "Max" in page.text and "<script>alert(1)" not in page.text and "&lt;script&gt;" in page.text
    assert anon.post("/settings/impressum", data={"text": "x"}, follow_redirects=False).status_code in (303, 401, 403)
    big = client.post("/settings/impressum", data={"text": "a" * 20001, "enabled": "1"})
    assert big.status_code == 422 and "too long" in big.text


def test_impressum_page_has_a_way_back_to_the_library(client):
    client.post("/settings/impressum", data={"text": "Max", "enabled": "1"})
    html = client.get("/impressum").text
    assert 'class="back" href="/"' in html
