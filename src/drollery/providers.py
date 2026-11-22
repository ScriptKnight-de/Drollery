"""AI providers. Each capability (transcribe / describe) is selected by `type` in config.toml.

To add a provider: write a function and register it in the matching dict at the bottom.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import httpx

from .config import Provider

DEFAULT_PROMPT = """You are cataloguing a meme / funny clip library so it can be found later by full-text search.
Respond with JSON only, no markdown:
{"name": "...", "description": "...", "tags": ["...", "..."]}

- name: short descriptive title, lowercase words separated by spaces, no file extension
- description: one or two sentences with the key visuals, any text shown or spoken, the meme template name if you recognise it, and the joke. Prioritise searchability.
- tags: up to 6 short lowercase tags. Prefer existing tags when they fit: {tags}. Invent new ones only if none apply."""


class ProviderError(Exception):
    """A provider call failed. `transient` marks overload and rate limits, which are worth trying again later."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def _check(r: httpx.Response) -> None:
    """Like raise_for_status, but the error says what the server answered (Google, OpenAI and Ollama all explain
    themselves in the body) and whether waiting is likely to help."""
    if r.status_code < 400:
        return
    detail = ""
    try:
        body = r.json()
        err = body.get("error", body) if isinstance(body, dict) else body
        detail = str(err.get("message", err) if isinstance(err, dict) else err)
    except ValueError:
        detail = r.text
    detail = " ".join(detail.split())[:300]
    transient = r.status_code in (408, 429, 500, 502, 503, 504)
    msg = f"HTTP {r.status_code} {r.reason_phrase} from {r.request.url.host}" + (f": {detail}" if detail else "")
    if transient:
        msg += ". The service is busy or limiting requests: try again later (Retry on the Jobs page)"
    elif r.status_code == 404:
        msg += ". Check the model name in Settings > AI models"
    elif r.status_code in (401, 403):
        msg += ". Check the API key in Settings > AI models"
    raise ProviderError(msg, transient=transient)


def _headers(cfg: Provider) -> dict:
    key = cfg.api_key or (os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _url(cfg: Provider, path: str) -> str:
    if not cfg.base_url:
        raise ProviderError("base_url is not set")
    return cfg.base_url.rstrip("/") + path


def _command(template: str, input_path: Path, langs: str = "") -> str:
    if not template:
        raise ProviderError("command is not set")
    args = [a.replace("{input}", str(input_path)).replace("{langs}", langs) for a in shlex.split(template)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise ProviderError(f"program not found: {args[0]}") from None
    if r.returncode != 0:
        raise ProviderError(f"{args[0]} failed: {r.stderr.strip()[:2000]}")
    return r.stdout.strip()


# ------------------------------------------------------------ transcribe

def _transcribe_openai(cfg: Provider, audio: Path) -> str:
    data = {"model": cfg.model, "response_format": "json"}
    if cfg.language:
        data["language"] = cfg.language
    with audio.open("rb") as f:
        r = httpx.post(_url(cfg, "/audio/transcriptions"), headers=_headers(cfg), data=data,
                       files={"file": (audio.name, f, "audio/mpeg")}, timeout=cfg.timeout)
    _check(r)
    return (r.json().get("text") or "").strip()


def _transcribe_command(cfg: Provider, audio: Path) -> str:
    return _command(cfg.command, audio)


TRANSCRIBE = {"openai": _transcribe_openai, "command": _transcribe_command}


def transcribe(cfg: Provider, audio: Path) -> str:
    fn = TRANSCRIBE.get(cfg.type)
    if fn is None:
        raise ProviderError(f"unknown transcribe provider type {cfg.type!r}")
    return fn(cfg, audio)


# -------------------------------------------------------------- describe

def parse_json(text: str) -> dict:
    """LLMs wrap JSON in prose or code fences; pull out the first object."""
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ProviderError(f"model did not return JSON: {text[:1000]!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ProviderError(f"invalid JSON from model: {e}") from None


def _normalize(data: dict) -> dict:
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,#\s]+", tags) if t]
    return {
        "name": str(data.get("name") or "").strip()[:120],
        "description": str(data.get("description") or "").strip()[:1500],
        "tags": [str(t).strip().lower() for t in tags][:8],
    }


def _describe_openai(cfg: Provider, image: Path | None, transcript: str, existing_tags: list[str]) -> dict:
    prompt = (cfg.prompt or DEFAULT_PROMPT).replace("{tags}", ", ".join(existing_tags) or "none")
    if transcript:
        prompt += f"\n\nTranscript of the audio:\n{transcript[:4000]}"
    if image is not None and cfg.send_image:
        b64 = base64.b64encode(image.read_bytes()).decode()
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
    elif transcript:
        content = prompt
    else:
        raise ProviderError("nothing to describe (no image and no transcript)")
    r = httpx.post(_url(cfg, "/chat/completions"), headers=_headers(cfg), timeout=cfg.timeout,
                   json={"model": cfg.model, "temperature": 0.2,
                         "messages": [{"role": "user", "content": content}]})
    _check(r)
    return _normalize(parse_json(r.json()["choices"][0]["message"]["content"]))


DESCRIBE = {"openai": _describe_openai}


def describe(cfg: Provider, image: Path | None, transcript: str, existing_tags: list[str]) -> dict:
    fn = DESCRIBE.get(cfg.type)
    if fn is None:
        raise ProviderError(f"unknown describe provider type {cfg.type!r}")
    return fn(cfg, image, transcript, existing_tags)
