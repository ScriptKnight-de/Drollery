import shutil

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe required")
    monkeypatch.setenv("DROLLERY_DATA", str(tmp_path))
    monkeypatch.delenv("DROLLERY_TOKEN", raising=False)
    from drollery import config
    config.get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from drollery.main import app
    with TestClient(app) as c:
        yield c
    config.get_settings.cache_clear()
