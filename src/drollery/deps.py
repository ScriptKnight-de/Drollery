"""Authentication dependencies: session cookies for the web UI, API keys or sessions for the API."""
from __future__ import annotations

from fastapi import HTTPException, Request

from . import accounts

SESSION_COOKIE = "drollery_session"
PENDING_COOKIE = "drollery_pending"


class LoginRequired(Exception):
    pass


class SetupRequired(Exception):
    pass


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def api_auth(request: Request) -> None:
    """API and file routes: an API key (Bearer) or a logged-in browser session."""
    if accounts.user_count() == 0:
        raise HTTPException(503, "Setup required: open the web interface to create the admin account")
    token = _bearer(request)
    user = accounts.lookup_api_key(token) if token else None
    if user is None:
        user = accounts.lookup_session(request.cookies.get(SESSION_COOKIE, ""))
    if user is None:
        raise HTTPException(401, "Missing or invalid API key", headers={"WWW-Authenticate": "Bearer"})
    request.state.user = user


def web_auth(request: Request) -> None:
    """Web pages: a logged-in browser session only (API keys cannot open the settings pages)."""
    if accounts.user_count() == 0:
        raise SetupRequired
    user = accounts.lookup_session(request.cookies.get(SESSION_COOKIE, ""))
    if user is None:
        raise LoginRequired
    request.state.user = user
