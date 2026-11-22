"""First-run setup, login (with optional 2FA) and logout."""
from __future__ import annotations

import re

import anyio.to_thread
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from . import accounts, i18n, restore, security, shares
from .i18n import t, tn
from .config import get_settings
from .deps import PENDING_COOKIE, SESSION_COOKIE, client_ip
from .web import flash_redirect, render

router = APIRouter()
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
DUMMY_HASH = security.hash_password("not-a-real-password")   # so unknown usernames cost the same as wrong passwords


def _secure(request: Request) -> bool:
    return get_settings().cookie_secure or request.url.scheme == "https"


def _set_session(resp, request: Request, user_id: int) -> None:
    token = accounts.create_session(user_id, "session", request.headers.get("user-agent", ""), client_ip(request))
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=_secure(request), max_age=accounts.SESSION_TTL)
    lang = (accounts.get_user(user_id) or {}).get("language", "")
    if lang:                                                  # carry the account's language to this browser
        resp.set_cookie(i18n.COOKIE, lang, max_age=365 * 86400, samesite="lax")


# ------------------------------------------------------------------ setup

@router.get("/setup")
def setup_page(request: Request):
    if accounts.user_count():
        return RedirectResponse("/", status_code=303)
    return render(request, "setup.html", form={})


@router.post("/setup")
def setup(request: Request, code: str = Form(""), username: str = Form(""),
          password: str = Form(""), password2: str = Form("")):
    if accounts.user_count():
        return RedirectResponse("/", status_code=303)
    form = {"username": username}
    ip = client_ip(request)

    def fail(msg: str, status: int = 422):
        return render(request, "setup.html", status_code=status, form=form, error=msg)

    if security.ip_throttle.blocked(f"setup|{ip}"):
        return fail(t("Too many attempts. Wait a few minutes and try again"), 429)
    if not security.safe_equal(code.strip(), accounts.get_setup_code()):
        security.ip_throttle.fail(f"setup|{ip}")
        return fail(t("That setup code is not correct. It is printed in the container log"))
    if not USERNAME_RE.match(username.strip()):
        return fail(t("Username: 3 to 32 letters, digits, dots, dashes or underscores"))
    problem = security.password_problem(password, username)
    if problem:
        return fail(problem)
    if password != password2:
        return fail(t("The two passwords do not match"))
    user_id = accounts.create_first_user(username, password)
    if user_id is None:
        return RedirectResponse("/", status_code=303)
    accounts.clear_setup_code()
    resp = flash_redirect("/settings/ai", t("Admin account created. Next, tell Drollery which AI models to use, or skip this for now"))
    _set_session(resp, request, user_id)
    return resp


@router.post("/setup/restore")
async def setup_restore(request: Request, code: str = Form(""), backup: UploadFile | None = File(default=None)):
    """First run: bring back a library from a backup file (Settings > Backup) instead of creating a new one."""
    if accounts.user_count():
        return RedirectResponse("/", status_code=303)
    ip = client_ip(request)

    def fail(msg: str, status: int = 422):
        return render(request, "setup.html", status_code=status, form={}, restore_error=msg)

    if security.ip_throttle.blocked(f"setup|{ip}"):
        return fail(t("Too many attempts. Wait a few minutes and try again"), 429)
    if not security.safe_equal(code.strip(), accounts.get_setup_code()):
        security.ip_throttle.fail(f"setup|{ip}")
        return fail(t("That setup code is not correct. It is printed in the container log"))
    if backup is None or not backup.filename:
        return fail(t("Choose the backup file"))
    try:
        summary = await anyio.to_thread.run_sync(restore.restore, backup.file)
    except restore.RestoreError as e:
        return fail(t(str(e)))
    text = tn("Backup restored: {n} item", "Backup restored: {n} items", summary.items)
    if summary.no_file:
        text += ". " + tn("{n} item has no file yet", "{n} items have no file yet", summary.no_file)
    return flash_redirect("/login", text + ". " + t("Sign in with an account from the backup"))


# --------------------------------------------------------------- language

@router.post("/language")
def choose_language(request: Request, language: str = Form(""), next: str = Form("/login")):
    """The switcher on the sign-in pages. It sets the browser's language cookie (and the account's, if someone is signed in)."""
    code = i18n.normalize(language)
    resp = RedirectResponse(shares.safe_next(next, "/login"), status_code=303)
    if code:
        resp.set_cookie(i18n.COOKIE, code, max_age=365 * 86400, samesite="lax")
        user = accounts.lookup_session(request.cookies.get(SESSION_COOKIE, ""))
        if user:
            accounts.set_language(user["id"], code)
    return resp


# ------------------------------------------------------------------ login

@router.get("/login")
def login_page(request: Request):
    if accounts.user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return render(request, "login.html", form={})


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    if accounts.user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    ip, name = client_ip(request), username.strip().lower()
    key = f"{ip}|{name}"
    if security.login_throttle.blocked(key) or security.ip_throttle.blocked(ip):
        return render(request, "login.html", status_code=429, form={"username": username},
                      error=t("Too many failed attempts. Wait about 15 minutes and try again"))
    user = accounts.get_user_by_name(username)
    ok = security.verify_password(password, user["password_hash"] if user else DUMMY_HASH) and user is not None
    if not ok:
        security.login_throttle.fail(key)
        security.ip_throttle.fail(ip)
        return render(request, "login.html", status_code=401, form={"username": username}, error=t("Wrong username or password"))
    security.login_throttle.reset(key)
    if user["totp_enabled"]:
        token = accounts.create_session(user["id"], "pending", request.headers.get("user-agent", ""), ip)
        resp = RedirectResponse("/login/2fa", status_code=303)
        resp.set_cookie(PENDING_COOKIE, token, httponly=True, samesite="lax", secure=_secure(request), max_age=accounts.PENDING_TTL)
        return resp
    resp = RedirectResponse("/", status_code=303)
    _set_session(resp, request, user["id"])
    return resp


@router.get("/login/2fa")
def twofa_page(request: Request):
    if accounts.lookup_session(request.cookies.get(PENDING_COOKIE, ""), "pending") is None:
        return RedirectResponse("/login", status_code=303)
    return render(request, "login_2fa.html")


@router.post("/login/2fa")
def twofa(request: Request, code: str = Form("")):
    token = request.cookies.get(PENDING_COOKIE, "")
    user = accounts.lookup_session(token, "pending")
    if user is None:
        return flash_redirect("/login", t("That sign-in expired. Please start again"), "error")
    ip = client_ip(request)
    if security.ip_throttle.blocked(ip):
        return render(request, "login_2fa.html", status_code=429, error=t("Too many attempts. Wait a few minutes"))
    if not accounts.check_second_factor(user, code):
        security.ip_throttle.fail(ip)
        if accounts.note_pending_failure(token) >= accounts.MAX_PENDING_FAILURES:
            resp = flash_redirect("/login", t("Too many wrong codes. Please sign in again"), "error")
            resp.delete_cookie(PENDING_COOKIE)
            return resp
        return render(request, "login_2fa.html", status_code=401, error=t("That code is not valid"))
    accounts.delete_session(token)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(PENDING_COOKIE)
    _set_session(resp, request, user["id"])
    return resp


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        accounts.delete_session(token)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
