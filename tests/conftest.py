import shutil

import pytest

PASSWORD = "correct horse battery"


def _boot(tmp_path, monkeypatch):
    monkeypatch.setenv("DROLLERY_DATA", str(tmp_path))
    monkeypatch.delenv("DROLLERY_SETUP_CODE", raising=False)
    from drollery import config, security, shares
    config.get_settings.cache_clear()
    security.login_throttle.reset()
    security.ip_throttle.reset()
    shares.share_throttle.reset()


def pause_workers(monkeypatch):
    """The app's own background workers must not take queued jobs away under a test: only the test's own thread may claim one.
    (Lowering the worker limit is not enough: the supervisor only looks at it every two seconds.)"""
    import threading
    from drollery import db
    real = db.claim_job
    monkeypatch.setattr(db, "claim_job", lambda: real() if threading.current_thread() is threading.main_thread() else None)


def create_user(username: str, password: str, email: str = "", role: str = "admin") -> int:
    """Make an account directly (the app itself only ever creates the first admin through the setup page)."""
    import time
    from drollery import db, security
    now = time.time()
    with db.tx() as c:
        return c.execute("INSERT INTO users(username,email,password_hash,role,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         (username.strip(), email.strip(), security.hash_password(password), role, now, now)).lastrowid


def totp_now(secret: str, at: float | None = None) -> str:
    """The code an authenticator app shows right now."""
    import time
    from drollery import security
    return security._hotp(secret, int((at if at is not None else time.time()) // 30))


@pytest.fixture()
def anon(tmp_path, monkeypatch):
    """A fresh instance where first-run setup has NOT been done."""
    _boot(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from drollery.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c
    from drollery import config
    config.get_settings.cache_clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A logged-in admin (username 'admin'). Skips if ffmpeg is missing, since most tests import media."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe required")
    _boot(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from drollery import accounts
    from drollery.main import app
    with TestClient(app, follow_redirects=False) as c:
        create_user("admin", PASSWORD)
        r = c.post("/login", data={"username": "admin", "password": PASSWORD})
        assert r.status_code == 303 and "drollery_session" in c.cookies
        c.follow_redirects = True
        yield c
    from drollery import config
    config.get_settings.cache_clear()
