"""ffmpeg/ffprobe helpers. Everything is a subprocess call so memory stays small on a Pi."""
from __future__ import annotations

import json
import mimetypes
import subprocess
from pathlib import Path

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("audio/ogg", ".opus")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/quicktime", ".mov")

KINDS = ("image", "video", "audio")
# Formats that can carry scripts. Served from this origin they would run with the owner's session, so they are refused.
UNSAFE_MIMES = {"image/svg+xml", "image/svg+xml-compressed"}


class MediaError(Exception):
    pass


def guess(path_or_name: str) -> tuple[str, str]:
    """-> (kind, mime) from the file name, or raise MediaError."""
    mime = mimetypes.guess_type(path_or_name)[0] or ""
    kind = mime.split("/")[0]
    if kind not in KINDS or mime in UNSAFE_MIMES:
        raise MediaError(f"unsupported file type: {path_or_name!r}")
    return kind, mime


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe(path: Path) -> dict:
    r = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        raise MediaError(f"ffprobe failed: {r.stderr.strip()[:300]}")
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    duration = data.get("format", {}).get("duration")
    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": float(duration) if duration not in (None, "N/A") else None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def make_thumb(src: Path, dst: Path, kind: str, duration: float | None) -> bool:
    """640px-wide JPEG preview. Returns False for audio or on failure."""
    if kind == "audio":
        return False
    seek = ["-ss", f"{min(1.0, (duration or 0) / 2):.2f}"] if kind == "video" else []
    r = _run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(src), "-frames:v", "1",
              "-vf", "scale='min(640,iw)':-2", "-q:v", "5", str(dst)])
    return r.returncode == 0 and dst.exists()


def extract_audio(src: Path, dst: Path) -> None:
    """Mono 16 kHz low-bitrate MP3: small upload for transcription servers, plenty for speech."""
    r = _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
              "-b:a", "32k", str(dst)], timeout=600)
    if r.returncode != 0 or not dst.exists():
        raise MediaError(f"audio extraction failed: {r.stderr.strip()[:300]}")


def ocr_image(src: Path, dst: Path, kind: str) -> None:
    """1600px PNG still (video: a frame from the middle) for OCR."""
    seek = ["-ss", "1"] if kind == "video" else []
    r = _run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(src), "-frames:v", "1",
              "-vf", "scale='min(1600,iw)':-2", str(dst)])
    if r.returncode != 0 or not dst.exists():
        raise MediaError(f"frame extraction failed: {r.stderr.strip()[:300]}")
