"""What a stranger who can reach the port, but has no account, can and cannot see."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def guest(client):
    from drollery.main import app
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_the_api_docs_and_schema_are_not_published(guest, path):
    assert guest.get(path).status_code in (303, 404)


def test_the_library_the_api_and_the_files_need_a_login(guest, client):
    from test_card import two_color_png
    item = client.post("/api/v1/items", files={"file": ("a.png", two_color_png(), "image/png")}).json()["id"]
    for path in ("/", f"/items/{item}", "/people", "/jobs", "/settings/profile", "/settings/lookup", "/movies/new", "/suggest?q=a"):
        r = guest.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login", path
    for path in ("/api/v1/items", f"/api/v1/items/{item}", "/api/v1/me", "/api/v1/jobs", f"/media/{item}", f"/thumb/{item}", f"/card/{item}", "/people/1/picture"):
        assert guest.get(path).status_code in (401, 404), path


def test_only_the_health_check_the_assets_and_a_switched_on_impressum_are_open(guest):
    assert guest.get("/healthz").status_code == 200
    assert guest.get("/static/style.css").status_code == 200
    assert guest.get("/impressum").status_code == 404                                  # off until the owner switches it on
    assert guest.get("/privacy").status_code == 404                                    # likewise
    assert guest.get("/login").status_code == 200


def test_the_health_check_reveals_nothing_about_the_installation(guest):
    body = guest.get("/healthz").text
    assert len(body) < 80 and "version" not in body.lower() and "/" not in body


def test_a_wrong_share_token_looks_the_same_as_no_share(guest):
    assert guest.get("/s/not-a-real-token").status_code == 404
    assert guest.get("/s/not-a-real-token/raw/x.png").status_code == 404
    assert guest.get("/s/not-a-real-token/thumb").status_code == 404
