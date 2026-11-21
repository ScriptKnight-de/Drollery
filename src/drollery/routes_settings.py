"""Settings pages: profile, security (password, 2FA, sessions), API keys and AI models."""
from __future__ import annotations

import segno
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from . import accounts, aisettings, db, pipeline, security
from .deps import SESSION_COOKIE, web_auth
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
    return render(request, "settings_profile.html", tab="profile", me=_fresh(request))


@router.post("/profile")
def profile_save(request: Request, display_name: str = Form(""), email: str = Form("")):
    if email.strip() and ("@" not in email or " " in email.strip()):
        return render(request, "settings_profile.html", status_code=422, tab="profile", me=_fresh(request) | {"display_name": display_name, "email": email},
                      error="That email address does not look right")
    accounts.update_profile(_user(request)["id"], display_name, email)
    return flash_redirect("/settings/profile", "Profile saved")


# --------------------------------------------------------------- security

def _qr_svg(uri: str) -> str:
    return segno.make(uri, error="m").svg_inline(scale=5, border=2, dark="#000000", light="#ffffff")


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


def _check_password(request: Request, password: str) -> bool:
    return security.verify_password(password, _fresh(request)["password_hash"])


@router.post("/security/password")
def change_password(request: Request, current: str = Form(""), new: str = Form(""), new2: str = Form("")):
    me = _fresh(request)
    if security.login_throttle.blocked(f"pw|{me['id']}"):
        return _security_page(request, 429, error="Too many attempts. Wait a few minutes")
    if not security.verify_password(current, me["password_hash"]):
        security.login_throttle.fail(f"pw|{me['id']}")
        return _security_page(request, 401, error="The current password is not correct")
    problem = security.password_problem(new, me["username"])
    if problem:
        return _security_page(request, 422, error=problem)
    if new != new2:
        return _security_page(request, 422, error="The two new passwords do not match")
    accounts.set_password(me["id"], new)
    accounts.delete_user_sessions(me["id"], keep_hash=me["_session_hash"])   # everyone else is signed out
    return flash_redirect("/settings/security", "Password changed. Other devices were signed out")


@router.post("/security/2fa/start")
def twofa_start(request: Request):
    if not _user(request)["totp_enabled"]:
        accounts.start_2fa(_user(request)["id"])
    return RedirectResponse("/settings/security", status_code=303)


@router.post("/security/2fa/cancel")
def twofa_cancel(request: Request):
    with db.tx() as c:
        c.execute("UPDATE users SET totp_pending='' WHERE id=?", (_user(request)["id"],))
    return RedirectResponse("/settings/security", status_code=303)


@router.post("/security/2fa/enable")
def twofa_enable(request: Request, code: str = Form("")):
    me = _fresh(request)
    if me["totp_enabled"] or not me["totp_pending"]:
        return RedirectResponse("/settings/security", status_code=303)
    step = security.totp_verify(me["totp_pending"], code)
    if step is None:
        return _security_page(request, 422, error="That code is not valid. Check the clock on your phone and try the next code")
    codes = accounts.enable_2fa(me["id"], me["totp_pending"], step)
    return _security_page(request, new_backup_codes=codes, ok="Two-factor authentication is on")


@router.post("/security/2fa/disable")
def twofa_disable(request: Request, password: str = Form("")):
    me = _fresh(request)
    if not security.verify_password(password, me["password_hash"]):
        return _security_page(request, 401, error="The password is not correct")
    accounts.disable_2fa(me["id"])
    return flash_redirect("/settings/security", "Two-factor authentication is off")


@router.post("/security/2fa/backup")
def twofa_backup(request: Request, password: str = Form("")):
    me = _fresh(request)
    if not me["totp_enabled"]:
        return RedirectResponse("/settings/security", status_code=303)
    if not security.verify_password(password, me["password_hash"]):
        return _security_page(request, 401, error="The password is not correct")
    return _security_page(request, new_backup_codes=accounts.regenerate_backup_codes(me["id"]), ok="New backup codes created; the old ones no longer work")


@router.post("/security/sessions/revoke-others")
def revoke_others(request: Request):
    me = _user(request)
    accounts.delete_user_sessions(me["id"], keep_hash=me["_session_hash"])
    return flash_redirect("/settings/security", "Signed out of all other devices")


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
        return flash_redirect("/settings/keys", "That key no longer exists", "error")
    key = next(k for k in accounts.list_api_keys(_user(request)["id"]) if k["id"] == key_id)
    return _keys_page(request, new_key={"token": token, "name": key["name"], "kind": key["kind"], "regenerated": True})


@router.post("/keys/{key_id}/delete")
def key_delete(request: Request, key_id: int):
    accounts.delete_api_key(key_id, _user(request)["id"])
    return flash_redirect("/settings/keys", "API key revoked")


# -------------------------------------------------------------- AI models

def _ai_page(request: Request, status_code: int = 200, **extra):
    models = accounts.list_models()
    rows = []
    for cap in aisettings.CAPS:
        state = aisettings.describe_state(cap, models)
        options = [m for m in models if m["type"] in aisettings.COMPAT[cap]]
        rows.append({"cap": cap, "label": aisettings.CAP_LABEL[cap], "help": aisettings.CAP_HELP[cap], "state": state, "options": options})
    return render(request, "settings_ai.html", status_code=status_code, tab="ai", models=models, rows=rows,
                  types=aisettings.MODEL_TYPES, compat=aisettings.COMPAT, **extra)


@router.get("/ai")
def ai_page(request: Request):
    return _ai_page(request)


@router.post("/ai/assign")
def ai_assign(request: Request, transcribe: str = Form("default"), describe: str = Form("default"), ocr: str = Form("default")):
    chosen = {"transcribe": transcribe, "describe": describe, "ocr": ocr}
    models = {str(m["id"]): m for m in accounts.list_models()}
    for cap, value in chosen.items():
        if value == "default":
            accounts.set_setting(f"ai.{cap}", None)
        elif value == "off":
            accounts.set_setting(f"ai.{cap}", "off")
        elif value in models and models[value]["type"] in aisettings.COMPAT[cap]:
            accounts.set_setting(f"ai.{cap}", value)
    return flash_redirect("/settings/ai", "AI assignments saved. They apply to new items right away")


@router.post("/ai/reprocess")
def ai_reprocess(request: Request):
    count = 0
    with db.tx() as c:
        busy = {r[0] for r in c.execute("SELECT DISTINCT item_id FROM jobs WHERE status IN ('queued','running') AND item_id IS NOT NULL")}
        for (item_id,) in c.execute("SELECT id FROM items ORDER BY id").fetchall():
            if item_id not in busy and pipeline.plan_jobs(c, item_id):
                count += 1
    return flash_redirect("/settings/ai", f"Queued AI processing for {count} item(s)" if count else "Nothing to queue: no AI model is assigned, or every item is already queued")


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
        return flash_redirect("/settings/ai", "That model no longer exists", "error")
    return _model_form(request, model | {"has_key": bool(model["api_key"]), "api_key": ""})


def _validate_model(data: dict, model_id: int | None) -> str:
    if not data["name"].strip():
        return "Give the model a name"
    other = next((m for m in accounts.list_models() if m["name"].lower() == data["name"].strip().lower() and m["id"] != model_id), None)
    if other:
        return "Another model already has that name"
    if data["type"] not in aisettings.MODEL_TYPES:
        return "Choose a model type"
    if data["type"] == "openai":
        if not data["base_url"].startswith(("http://", "https://")):
            return "The base URL must start with http:// or https://"
        if not data["model"].strip():
            return "Enter the model name the server should use"
    if data["type"] == "command" and "{input}" not in data["command"]:
        return "The command must contain {input}, which is replaced by the file path"
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
    return flash_redirect("/settings/ai", f"Model “{data['name']}” added. Assign it below to start using it")


@router.post("/ai/models/{model_id}")
def model_update(request: Request, model_id: int, name: str = Form(""), type: str = Form("openai"), base_url: str = Form(""),
                 model: str = Form(""), api_key: str = Form(""), command: str = Form(""), langs: str = Form("eng"), language: str = Form(""),
                 prompt: str = Form(""), timeout: int = Form(300), send_image: str = Form(""), clear_key: str = Form("")):
    existing = accounts.get_model(model_id)
    if existing is None:
        return flash_redirect("/settings/ai", "That model no longer exists", "error")
    data = _form_data(name, type, base_url, model, api_key, command, langs, language, prompt, timeout, send_image)
    err = _validate_model(data, model_id)
    if err:
        return _model_form(request, data | {"id": model_id, "has_key": bool(existing["api_key"])}, 422, error=err)
    accounts.save_model(model_id, data, clear_key=bool(clear_key))
    return flash_redirect("/settings/ai", f"Model “{data['name']}” saved")


@router.post("/ai/models/{model_id}/delete")
def model_delete(request: Request, model_id: int):
    accounts.delete_model(model_id)
    return flash_redirect("/settings/ai", "Model deleted")


@router.post("/ai/test")
def model_test(request: Request, id: str = Form(""), type: str = Form(""), base_url: str = Form(""), model: str = Form(""),
               api_key: str = Form(""), command: str = Form("")):
    key = api_key.strip()
    if not key and id.isdigit():                    # editing: the form never contains the stored key, so use it for the test
        stored = accounts.get_model(int(id))
        key = stored["api_key"] if stored else ""
    ok, message, ids = aisettings.test_model({"type": type, "base_url": base_url, "model": model, "api_key": key, "command": command})
    return render(request, "ai_test_result.html", ok=ok, message=message, model_ids=ids)
