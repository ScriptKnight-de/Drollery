"""Resolve which AI provider is active for each capability, and test model definitions.

Precedence per capability (transcribe / describe):
  1. an assignment made in Settings > AI models (a model id, or "off")
  2. otherwise the [transcribe] / [describe] section of config.toml
Reads the database on every call, so changes apply immediately without a restart.
"""
from __future__ import annotations

import shlex
import shutil

import httpx

from . import accounts
from .i18n import N_, t
from .config import Provider, get_settings

CAPS = ("transcribe", "describe")
CAP_LABEL = {"transcribe": N_("Transcription"), "describe": N_("Naming and tagging")}
CAP_HELP = {
    "transcribe": N_("Speech-to-text for audio and video clips"),
    "describe": N_("Writes title, description and tags from the preview image and transcript"),
}
MODEL_TYPES = {"openai": N_("OpenAI-compatible API"), "command": N_("Local command")}
COMPAT = {"transcribe": ("openai", "command"), "describe": ("openai",)}

PRESETS = [
    {"label": N_("Ollama (local vision)"), "type": "openai", "base_url": "http://host.docker.internal:11434/v1", "model": "moondream", "name": "Ollama vision"},
    {"label": N_("Custom provider"), "type": "openai", "base_url": "", "model": "", "name": ""},
    {"label": "OpenAI", "type": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "name": "OpenAI"},
    {"label": "Whisper server", "type": "openai", "base_url": "http://whisper:8000/v1", "model": "Systran/faster-whisper-small", "name": "Whisper small"},
    {"label": "Whisper (OpenAI)", "type": "openai", "base_url": "https://api.openai.com/v1", "model": "whisper-1", "name": "OpenAI Whisper"},
]


def to_provider(row: dict) -> Provider:
    return Provider(type=row["type"], base_url=row["base_url"], model=row["model"], api_key=row["api_key"],
                    command=row["command"], langs=row["langs"] or "eng", language=row["language"], prompt=row["prompt"],
                    timeout=row["timeout"], send_image=bool(row["send_image"]))


def assignment(cap: str) -> str | None:
    """None = follow config.toml, 'off' = disabled, otherwise a model id as text."""
    return accounts.get_setting(f"ai.{cap}")


def provider(cap: str) -> Provider:
    value = assignment(cap)
    if value is None:
        return getattr(get_settings(), cap)
    if value == "off":
        return Provider()
    row = accounts.get_model(int(value)) if value.isdigit() else None
    return to_provider(row) if row else Provider()


def enabled(cap: str) -> bool:
    return provider(cap).enabled


def describe_state(cap: str, models: list[dict]) -> dict:
    """What the Settings page shows for one capability."""
    value = assignment(cap)
    cfg = getattr(get_settings(), cap)
    if value is None:
        text = f"config.toml: {cfg.type}" + (f" · {cfg.model}" if cfg.model else "") if cfg.enabled else t("Off (config.toml)")
    elif value == "off":
        text = t("Off")
    else:
        row = next((m for m in models if str(m["id"]) == value), None)
        text = row["name"] if row else t("Off (model was deleted)")
    return {"value": value if value is not None else "default", "text": text}


# ----------------------------------------------------------------- tests

def test_model(data: dict) -> tuple[bool, str, list[str]]:
    """Check a model definition without running a job. Returns (ok, message, model ids found)."""
    kind = data.get("type", "")
    if kind == "openai":
        base = (data.get("base_url") or "").rstrip("/")
        if not base.startswith(("http://", "https://")):
            return False, t("Enter a base URL starting with http:// or https://"), []
        headers = {"Authorization": f"Bearer {data['api_key']}"} if data.get("api_key") else {}
        try:
            r = httpx.get(base + "/models", headers=headers, timeout=10, follow_redirects=True)
        except httpx.HTTPError as e:
            return False, t("Could not reach {base}: {error}", base=base, error=f"{type(e).__name__}: {e}"), []
        if r.status_code in (401, 403):
            return False, t("The server answered {status}: check the API key", status=r.status_code), []
        if r.status_code != 200:
            return True, t("Reached the server (GET /models answered {status}); model listing isn't supported but chat and audio calls may still work", status=r.status_code), []
        try:
            ids = sorted({str(m["id"]).removeprefix("models/") for m in r.json().get("data", []) if "id" in m})
        except (ValueError, TypeError, AttributeError):
            ids = []
        wanted = data.get("model") or ""
        note = ""
        if wanted and ids and wanted not in ids:
            note = " " + t("The model “{model}” is not in that list.", model=wanted)
        return True, t("Connected. {n} model(s) available.", n=len(ids)) + note, ids[:200]
    if kind == "command":
        try:
            program = shlex.split(data.get("command") or "")[0]
        except (ValueError, IndexError):
            return False, t("Enter a command, with {input} where the file path goes"), []
        if "{input}" not in (data.get("command") or ""):
            return False, t("The command must contain {input}, which is replaced by the file path"), []
        return (True, t("Found {program}.", program=program), []) if shutil.which(program) else (False, t("The program “{program}” was not found in the container.", program=program), [])
    return False, t("Choose a model type"), []
