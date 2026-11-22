"""Settings pages: profile, security (password, 2FA, sessions), API keys and AI models."""
from __future__ import annotations

import re

import anyio.to_thread
import segno
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from . import __version__, accounts, aisettings, backup, db, i18n, imdb, pipeline, security
from .config import get_settings
from .deps import web_auth
from .i18n import t, tn
from .web import flash_redirect, render

router = APIRouter(prefix="/settings", dependencies=[Depends(web_auth)])


def _user(request: Request) -> dict:
    return request.state.user


def _fresh(request: Request) -> dict:
    return accounts.get_user(_user(request)["id"]) | {"_session_hash": _user(request).get("_session_hash", "")}


@router.get("")
def index():
    return RedirectResponse("/settings/profile", status_code=303)


# ---------------------------------------------------------------- profile

@router.get("/profile")
def profile(request: Request):
    return render(request, "settings_profile.html", tab="profile", me=_fresh(request), languages=i18n.languages())


@router.post("/profile")
def profile_save(request: Request, email: str = Form(""), language: str = Form("")):
    language = i18n.normalize(language)                       # "" = follow the browser
    request.state.user["language"] = language                 # the page that answers (even an error) already speaks it
    i18n.set_language(language or i18n.from_accept_language(request.headers.get("accept-language", "")))
    if email.strip() and ("@" not in email or " " in email.strip()):
        return render(request, "settings_profile.html", status_code=422, tab="profile", languages=i18n.languages(),
                      me=_fresh(request) | {"email": email, "language": language}, error=t("That email address does not look right"))
    accounts.update_profile(_user(request)["id"], email)
    accounts.set_language(_user(request)["id"], language)
    resp = flash_redirect("/settings/profile", "Profile saved")
    resp.set_cookie(i18n.COOKIE, language, max_age=365 * 86400, samesite="lax") if language else resp.delete_cookie(i18n.COOKIE)
    return resp


# ------------------------------------------------------------------ about

KOFI_URL = "https://ko-fi.com/scriptknight"
GITHUB_URL = "https://github.com/ScriptKnight-de"


@router.get("/about")
def about_page(request: Request):
    return render(request, "settings_about.html", tab="about", kofi_url=KOFI_URL, github_url=GITHUB_URL, version=__version__)


# ----------------------------------------------------------------- backup

@router.get("/backup")
def backup_page(request: Request):
    return render(request, "settings_backup.html", tab="backup", sizes=backup.sizes())


async def _backup_body(kind: str):
    """An async body, so that a browser which goes away cancels it and the `finally` stops the writer at once (a plain
    generator is not closed reliably, which would leave the writer and its snapshot waiting)."""
    dl = backup.Download(kind)
    try:
        while (chunk := await anyio.to_thread.run_sync(dl.read, abandon_on_cancel=True)) is not None:
            yield chunk
    finally:
        dl.cancel()


@router.post("/backup/download")
def backup_download(kind: str = Form("full")):
    """Stream a .tgz of the metadata (database) or of everything (database and files). POST, so a link on another site
    cannot start a heavy download for a signed-in user."""
    if kind not in backup.KINDS:
        return flash_redirect("/settings/backup", t("Choose what to back up"), "error")
    return StreamingResponse(_backup_body(kind), media_type="application/gzip",
                             headers={"Content-Disposition": f'attachment; filename="{backup.filename(kind)}"', "Cache-Control": "no-store"})


# ----------------------------------------------------------- online lookup

OMDB_KEY = re.compile(r"^[A-Za-z0-9]{4,40}$")


@router.get("/lookup")
def lookup_page(request: Request):
    return render(request, "settings_lookup.html", tab="lookup", has_key=imdb.has_key(), has_tmdb=imdb.has_tmdb(), enabled=get_settings().metadata_lookup,
                  language_name=i18n.languages().get(i18n.current(), ""))


TMDB_KEY = re.compile(r"^[0-9a-f]{32}$")


@router.post("/lookup/tmdb")
def lookup_tmdb_save(tmdb_key: str = Form(""), remove: str = Form("")):
    """The TMDB key is write-only too: stored, never shown again, never put into a page, a log or an error."""
    if remove:
        accounts.set_setting(imdb.TMDB_KEY_SETTING, None)
        return flash_redirect("/settings/lookup", t("TMDB key removed"))
    key = tmdb_key.strip().lower()
    if not TMDB_KEY.match(key):
        return flash_redirect("/settings/lookup", t("That does not look like a TMDB key (32 letters and digits)"), "error")
    accounts.set_setting(imdb.TMDB_KEY_SETTING, key)
    return flash_redirect("/settings/lookup", t("TMDB key saved"))


@router.post("/lookup")
def lookup_save(omdb_key: str = Form(""), remove: str = Form("")):
    """The OMDb key is write-only: it is stored, never shown again and never put into a page, a log or an error."""
    if remove:
        accounts.set_setting(imdb.KEY_SETTING, None)
        return flash_redirect("/settings/lookup", t("OMDb key removed"))
    key = omdb_key.strip()
    if not OMDB_KEY.match(key):
        return flash_redirect("/settings/lookup", t("That does not look like an OMDb key (letters and digits only)"), "error")
    accounts.set_setting(imdb.KEY_SETTING, key)
    return flash_redirect("/settings/lookup", t("OMDb key saved"))


# --------------------------------------------------------------- impressum

IMPRESSUM_MAX = 20000


@router.get("/impressum")
def impressum_page(request: Request):
    text, live = accounts.impressum()
    return render(request, "settings_impressum.html", tab="impressum", text=text, on=accounts.get_setting("impressum_on") == "1", live=live)


@router.post("/impressum")
def impressum_save(request: Request, text: str = Form(""), enabled: str = Form("")):
    text = text.replace("\r\n", "\n").strip()
    if len(text) > IMPRESSUM_MAX:
        return render(request, "settings_impressum.html", status_code=422, tab="impressum", text=text[:IMPRESSUM_MAX], on=bool(enabled), live=False,
                      error=t("That is too long. The limit is {max} characters", max=IMPRESSUM_MAX))
    accounts.set_setting("impressum", text or None)
    accounts.set_setting("impressum_on", "1" if enabled else None)
    if enabled and not text:
        msg = t("Saved, but the page stays hidden until you write some text")
    elif enabled:
        msg = t("Impressum saved and published. It is linked in the footer of every page")
    else:
        msg = t("Impressum saved. It is switched off, so the page and the footer link are hidden")
    return flash_redirect("/settings/impressum", msg)


# --------------------------------------------------------------- security

def qr_matrix(uri: str) -> list[list[int]]:
    return [list(row) for row in segno.make(uri, error="m").matrix]


def render_qr_svg(matrix: list[list[int]], quiet: int = 4, target: int = 260) -> str:
    """Draw the QR as an inline SVG with whole-pixel modules and a symmetric quiet zone (4 modules, per the spec),
    so it renders sharp at its natural size and scans reliably. Dark modules are merged into one path per run."""
    n = len(matrix)
    total = n + 2 * quiet
    px = max(5, target // total)
    parts = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start + quiet} {y + quiet}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{px * total}" height="{px * total}" viewBox="0 0 {total} {total}" '
            f'shape-rendering="crispEdges" role="img" aria-label="QR code to scan with your authenticator app">'
            f'<rect width="{total}" height="{total}" fill="#fff"/><path d="{"".join(parts)}" fill="#000"/></svg>')


def _qr_svg(uri: str) -> str:
    return render_qr_svg(qr_matrix(uri))


def _security_page(request: Request, status_code: int = 200, **extra):
    me = _fresh(request)
    ctx = dict(tab="security", me=me, sessions=accounts.list_sessions(me["id"]), backup_left=accounts.backup_codes_left(me),
               qr_svg=None, pending_secret=None, new_backup_codes=None)
    if me["totp_pending"] and not me["totp_enabled"]:
        ctx["pending_secret"] = me["totp_pending"]
        ctx["qr_svg"] = _qr_svg(security.totp_uri(me["totp_pending"], me["username"]))
    ctx.update(extra)
    return render(request, "settings_security.html", status_code=status_code, **ctx)


@router.get("/security")
def security_page(request: Request):
    return _security_page(request)


@router.post("/security/password")
def change_password(request: Request, current: str = Form(""), new: str = Form(""), new2: str = Form("")):
    me = _fresh(request)
    if security.login_throttle.blocked(f"pw|{me['id']}"):
        return _security_page(request, 429, error=t("Too many attempts. Wait a few minutes"))
    if not security.verify_password(current, me["password_hash"]):
        security.login_throttle.fail(f"pw|{me['id']}")
        return _security_page(request, 401, error=t("The current password is not correct"))
    problem = security.password_problem(new, me["username"])
    if problem:
        return _security_page(request, 422, error=problem)
    if new != new2:
        return _security_page(request, 422, error=t("The two new passwords do not match"))
    accounts.set_password(me["id"], new)
    accounts.delete_user_sessions(me["id"], keep_hash=me["_session_hash"])   # everyone else is signed out
    return flash_redirect("/settings/security", t("Password changed. Other devices were signed out"))


@router.post("/security/2fa/start")
def twofa_start(request: Request):
    if not _user(request)["totp_enabled"]:
        accounts.start_2fa(_user(request)["id"])
    return RedirectResponse("/settings/security#two-factor", status_code=303)


@router.post("/security/2fa/cancel")
def twofa_cancel(request: Request):
    with db.tx() as c:
        c.execute("UPDATE users SET totp_pending='' WHERE id=?", (_user(request)["id"],))
    return RedirectResponse("/settings/security#two-factor", status_code=303)


@router.post("/security/2fa/enable")
def twofa_enable(request: Request, code: str = Form("")):
    me = _fresh(request)
    if me["totp_enabled"] or not me["totp_pending"]:
        return RedirectResponse("/settings/security#two-factor", status_code=303)
    step = security.totp_verify(me["totp_pending"], code)
    if step is None:
        return _security_page(request, 422, error=t("That code is not valid. Check the clock on your phone and try the next code"))
    codes = accounts.enable_2fa(me["id"], me["totp_pending"], step)
    return _security_page(request, new_backup_codes=codes, ok=t("Two-factor authentication is on"))


@router.post("/security/2fa/disable")
def twofa_disable(request: Request, password: str = Form("")):
    me = _fresh(request)
    if not security.verify_password(password, me["password_hash"]):
        return _security_page(request, 401, error=t("The password is not correct"))
    accounts.disable_2fa(me["id"])
    return flash_redirect("/settings/security#two-factor", t("Two-factor authentication is off"))


@router.post("/security/2fa/backup")
def twofa_backup(request: Request, password: str = Form("")):
    me = _fresh(request)
    if not me["totp_enabled"]:
        return RedirectResponse("/settings/security#two-factor", status_code=303)
    if not security.verify_password(password, me["password_hash"]):
        return _security_page(request, 401, error=t("The password is not correct"))
    return _security_page(request, new_backup_codes=accounts.regenerate_backup_codes(me["id"]), ok=t("New backup codes created; the old ones no longer work"))


@router.post("/security/sessions/revoke-others")
def revoke_others(request: Request):
    me = _user(request)
    accounts.delete_user_sessions(me["id"], keep_hash=me["_session_hash"])
    return flash_redirect("/settings/security", t("Signed out of all other devices"))


# --------------------------------------------------------------- API keys

def _keys_page(request: Request, status_code: int = 200, **extra):
    extra.setdefault("new_key", None)
    return render(request, "settings_keys.html", status_code=status_code, tab="keys",
                  keys=accounts.list_api_keys(_user(request)["id"]), base_url=str(request.base_url).rstrip("/"), **extra)


@router.get("/keys")
def keys_page(request: Request):
    return _keys_page(request)


@router.post("/keys")
def key_create(request: Request, name: str = Form(""), kind: str = Form("browser")):
    key_id, token = accounts.create_api_key(_user(request)["id"], name, kind)
    key = next(k for k in accounts.list_api_keys(_user(request)["id"]) if k["id"] == key_id)
    return _keys_page(request, new_key={"token": token, "name": key["name"], "kind": key["kind"]})


@router.post("/keys/{key_id}/regenerate")
def key_regenerate(request: Request, key_id: int):
    token = accounts.regenerate_api_key(key_id, _user(request)["id"])
    if token is None:
        return flash_redirect("/settings/keys", t("That key no longer exists"), "error")
    key = next(k for k in accounts.list_api_keys(_user(request)["id"]) if k["id"] == key_id)
    return _keys_page(request, new_key={"token": token, "name": key["name"], "kind": key["kind"], "regenerated": True})


@router.post("/keys/{key_id}/delete")
def key_delete(request: Request, key_id: int):
    accounts.delete_api_key(key_id, _user(request)["id"])
    return flash_redirect("/settings/keys", t("API key revoked"))


# -------------------------------------------------------------- AI models

def _ai_page(request: Request, status_code: int = 200, **extra):
    models = accounts.list_models()
    rows = []
    for cap in aisettings.CAPS:
        state = aisettings.describe_state(cap, models)
        options = [m for m in models if m["type"] in aisettings.COMPAT[cap]]
        rows.append({"cap": cap, "label": aisettings.CAP_LABEL[cap], "help": aisettings.CAP_HELP[cap], "state": state, "options": options})
    with db.tx() as c:
        ai_tag_count = c.execute("SELECT COUNT(*) FROM tags WHERE source='ai'").fetchone()[0]
    return render(request, "settings_ai.html", status_code=status_code, tab="ai", models=models, rows=rows, ai_tag_count=ai_tag_count, worker_limit=accounts.worker_limit(), max_workers=accounts.MAX_WORKERS,
                  types=aisettings.MODEL_TYPES, compat=aisettings.COMPAT, **extra)


@router.get("/ai")
def ai_page(request: Request):
    return _ai_page(request)


@router.post("/ai/assign")
def ai_assign(request: Request, transcribe: str = Form("default"), describe: str = Form("default")):
    chosen = {"transcribe": transcribe, "describe": describe}
    models = {str(m["id"]): m for m in accounts.list_models()}
    for cap, value in chosen.items():
        if value == "default":
            accounts.set_setting(f"ai.{cap}", None)
        elif value == "off":
            accounts.set_setting(f"ai.{cap}", "off")
        elif value in models and models[value]["type"] in aisettings.COMPAT[cap]:
            accounts.set_setting(f"ai.{cap}", value)
    return flash_redirect("/settings/ai", t("AI assignments saved. They apply to new items right away"))


@router.post("/ai/concurrency")
def ai_concurrency(request: Request, concurrency: int = Form(1)):
    n = max(1, min(accounts.MAX_WORKERS, concurrency))
    accounts.set_setting("jobs.concurrency", str(n))
    return flash_redirect("/settings/ai", tn("Up to {n} background job at a time", "Up to {n} background jobs at a time", n))


@router.post("/ai/reprocess")
def ai_reprocess(request: Request):
    count = 0
    with db.tx() as c:
        busy = {r[0] for r in c.execute("SELECT DISTINCT item_id FROM jobs WHERE status IN ('queued','running') AND item_id IS NOT NULL")}
        for (item_id,) in c.execute("SELECT id FROM items ORDER BY id").fetchall():
            if item_id not in busy and pipeline.plan_jobs(c, item_id):
                count += 1
    return flash_redirect("/settings/ai", tn("Queued AI processing for {n} item", "Queued AI processing for {n} items", count) if count else t("Nothing to queue: no AI model is assigned, or every item is already queued"))


@router.post("/ai/clear-tags")
def ai_clear_tags(request: Request):
    with db.tx() as c:
        n = db.clear_all_ai_tags(c)
    return flash_redirect("/settings/ai", tn("Removed {n} AI tag. Your own tags were not touched", "Removed {n} AI tags. Your own tags were not touched", n))


def _model_form(request: Request, model: dict | None, status_code: int = 200, **extra):
    presets = aisettings.PRESETS
    return render(request, "settings_ai_model.html", status_code=status_code, tab="ai", model=model, presets=presets,
                  types=aisettings.MODEL_TYPES, **extra)


@router.get("/ai/models/new")
def model_new(request: Request):
    blank = {"id": None, "name": "", "type": "openai", "base_url": "", "model": "", "api_key": "", "command": "", "langs": "eng",
             "language": "", "prompt": "", "timeout": 300, "send_image": 1}
    return _model_form(request, blank)


@router.get("/ai/models/{model_id}")
def model_edit(request: Request, model_id: int):
    model = accounts.get_model(model_id)
    if model is None:
        return flash_redirect("/settings/ai", t("That model no longer exists"), "error")
    return _model_form(request, model | {"has_key": bool(model["api_key"]), "api_key": ""})


def _validate_model(data: dict, model_id: int | None) -> str:
    if not data["name"].strip():
        return t("Give the model a name")
    other = next((m for m in accounts.list_models() if m["name"].lower() == data["name"].strip().lower() and m["id"] != model_id), None)
    if other:
        return t("Another model already has that name")
    if data["type"] not in aisettings.MODEL_TYPES:
        return t("Choose a model type")
    if data["type"] == "openai":
        if not data["base_url"].startswith(("http://", "https://")):
            return t("The base URL must start with http:// or https://")
        if not data["model"].strip():
            return t("Enter the model name the server should use")
    if data["type"] == "command" and "{input}" not in data["command"]:
        return t("The command must contain {input}, which is replaced by the file path")
    return ""


def _form_data(name, type, base_url, model, api_key, command, langs, language, prompt, timeout, send_image) -> dict:
    return {"name": name.strip(), "type": type, "base_url": base_url.strip(), "model": model.strip(), "api_key": api_key.strip(),
            "command": command.strip(), "langs": langs.strip() or "eng", "language": language.strip(), "prompt": prompt.strip(),
            "timeout": timeout or 300, "send_image": 1 if send_image else 0}


@router.post("/ai/models")
def model_create(request: Request, name: str = Form(""), type: str = Form("openai"), base_url: str = Form(""), model: str = Form(""),
                 api_key: str = Form(""), command: str = Form(""), langs: str = Form("eng"), language: str = Form(""),
                 prompt: str = Form(""), timeout: int = Form(300), send_image: str = Form("")):
    data = _form_data(name, type, base_url, model, api_key, command, langs, language, prompt, timeout, send_image)
    err = _validate_model(data, None)
    if err:
        return _model_form(request, data | {"id": None}, 422, error=err)
    accounts.save_model(None, data)
    return flash_redirect("/settings/ai", t("Model “{name}” added. Assign it below to start using it", name=data["name"]))


@router.post("/ai/models/{model_id}")
def model_update(request: Request, model_id: int, name: str = Form(""), type: str = Form("openai"), base_url: str = Form(""),
                 model: str = Form(""), api_key: str = Form(""), command: str = Form(""), langs: str = Form("eng"), language: str = Form(""),
                 prompt: str = Form(""), timeout: int = Form(300), send_image: str = Form(""), clear_key: str = Form("")):
    existing = accounts.get_model(model_id)
    if existing is None:
        return flash_redirect("/settings/ai", t("That model no longer exists"), "error")
    data = _form_data(name, type, base_url, model, api_key, command, langs, language, prompt, timeout, send_image)
    err = _validate_model(data, model_id)
    if err:
        return _model_form(request, data | {"id": model_id, "has_key": bool(existing["api_key"])}, 422, error=err)
    accounts.save_model(model_id, data, clear_key=bool(clear_key))
    return flash_redirect("/settings/ai", t("Model “{name}” saved", name=data["name"]))


@router.post("/ai/models/{model_id}/delete")
def model_delete(request: Request, model_id: int):
    accounts.delete_model(model_id)
    return flash_redirect("/settings/ai", t("Model deleted"))


@router.post("/ai/test")
def model_test(request: Request, id: str = Form(""), type: str = Form(""), base_url: str = Form(""), model: str = Form(""),
               api_key: str = Form(""), command: str = Form("")):
    key = api_key.strip()
    if not key and id.isdigit():                    # editing: the form never contains the stored key, so use it for the test
        stored = accounts.get_model(int(id))
        key = stored["api_key"] if stored else ""
    ok, message, ids = aisettings.test_model({"type": type, "base_url": base_url, "model": model, "api_key": key, "command": command})
    return render(request, "ai_test_result.html", ok=ok, message=message, model_ids=ids, value=model.strip())
