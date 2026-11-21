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
        accounts.create_user("admin", PASSWORD, "Admin Person")
        r = c.post("/login", data={"username": "admin", "password": PASSWORD})
        assert r.status_code == 303 and "drollery_session" in c.cookies
        c.follow_redirects = True
        yield c
    from drollery import config
    config.get_settings.cache_clear()
