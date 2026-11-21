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


FRAME_MAX = 1600     # width cap of the still the cropper works on
CARD_SIZE = 480      # edge of the square card image


def _run_bytes(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _times(t: float) -> list[float]:
    """Seek targets to try. Seeking to the very end can land after the last frame and yield nothing, so back off a little."""
    t = max(t, 0.0)
    return list(dict.fromkeys([t, max(t - 0.25, 0.0), max(t - 1.0, 0.0), 0.0]))


def frame_jpeg(src: Path, kind: str, t: float = 0.0) -> bytes:
    """One full-size still (JPEG, at most FRAME_MAX wide) of an image or of a video at t seconds.
    The cropper UI and make_card() both start from exactly this still, so the crop you frame is the crop you get
    (ffmpeg also applies any rotation flag, so phone photos line up)."""
    last = ""
    for at in (_times(t) if kind == "video" else [0.0]):
        seek = ["-ss", f"{at:.3f}"] if kind == "video" else []
        r = _run_bytes(["ffmpeg", "-v", "error", *seek, "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale='min({FRAME_MAX},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"])
        if r.returncode == 0 and r.stdout:
            return r.stdout
        last = r.stderr.decode(errors="replace").strip()[:200]
    raise MediaError(f"could not read a frame: {last}")


def make_card(src: Path, dst: Path, kind: str, t: float, x: float, y: float, s: float) -> None:
    """Crop a square from the still at time t and save it as the card image.
    x, y: top-left corner as fractions of the still's width/height. s: side as a fraction of its shorter edge."""
    s = min(max(s, 0.02), 1.0)
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    vf = (f"scale='min({FRAME_MAX},iw)':-2,"
          f"crop=w='trunc(min(iw,ih)*{s:.5f})':h='trunc(min(iw,ih)*{s:.5f})':"
          f"x='max(0,min(trunc(iw*{x:.5f}),iw-ow))':y='max(0,min(trunc(ih*{y:.5f}),ih-oh))',"
          f"scale={CARD_SIZE}:{CARD_SIZE}:flags=lanczos")
    tmp = dst.with_suffix(".tmp.jpg")
    err = ""
    for at in (_times(t) if kind == "video" else [0.0]):
        seek = ["-ss", f"{at:.3f}"] if kind == "video" else []
        tmp.unlink(missing_ok=True)
        r = _run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(src), "-frames:v", "1", "-vf", vf, "-q:v", "3", str(tmp)])
        if r.returncode == 0 and tmp.exists():
            tmp.replace(dst)
            return
        err = r.stderr.strip()[:200]
    tmp.unlink(missing_ok=True)
    raise MediaError(f"could not render the card image: {err}")
