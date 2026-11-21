import json
import subprocess
from pathlib import Path

import pytest

from drollery import db, media, pipeline, providers


@pytest.mark.parametrize("name,kind", [
    ("a.mkv", "video"), ("a.mp4", "video"), ("a.webm", "video"), ("a.flv", "video"), ("a.ts", "video"), ("a.3gp", "video"),
    ("a.wmv", "video"), ("a.mpg", "video"), ("a.m4v", "video"), ("a.mov", "video"),
    ("a.m4a", "audio"), ("a.ogg", "audio"), ("a.mp3", "audio"), ("a.flac", "audio"), ("a.opus", "audio"), ("a.wav", "audio"),
    ("a.png", "image"), ("a.jpg", "image"), ("a.gif", "gif"), ("a.webp", "image"), ("a.avif", "image"),
])
def test_common_containers_are_recognised(name, kind):
    """Python's mimetypes in a slim container knows few of these; a YouTube merge to .mkv was being rejected."""
    assert media.guess(name)[0] == kind


@pytest.mark.parametrize("name", ["notes.txt", "evil.svg", "archive.zip", "thing.xyz", "noextension"])
def test_other_files_are_still_refused(name):
    with pytest.raises(media.MediaError):
        media.guess(name)


def fake_downloader(monkeypatch, writes: dict[str, bytes | str], seen: list):
    """Replace the yt-dlp call with one that writes the given files into its output directory."""
    monkeypatch.setattr(pipeline, "_direct_download", lambda url, td: [])           # the URL is a web page, not a media file

    def run(cmd, timeout):
        seen.append(cmd)
        outdir = Path(cmd[cmd.index("-o") + 1]).parent
        for name, data in writes.items():
            (outdir / name).write_bytes(data if isinstance(data, bytes) else data.encode())
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pipeline, "_run_tool", run)


def make_video(tmp_path, name):
    path = tmp_path / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x120:r=10:d=1", "-f", "lavfi", "-i", "sine=f=300:d=1",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "libopus", str(path)], check=True)
    return path.read_bytes()


def fetch_job(url="https://www.youtube.com/watch?v=BiM39zlpyxs"):
    return {"id": 1, "type": "fetch", "item_id": None, "payload": json.dumps({"url": url}), "attempts": 1}


def test_a_download_that_ends_up_as_mkv_is_imported(client, monkeypatch, tmp_path):
    """The exact failure from the bug report: yt-dlp merged H.264 + Opus into a .mkv and the job failed."""
    seen = []
    fake_downloader(monkeypatch, {"Some Clip [abc].mkv": make_video(tmp_path, "x.mkv"),
                                  "Some Clip [abc].info.json": json.dumps({"title": "Some Clip", "uploader": "Lukas"})}, seen)
    pipeline.job_fetch(fetch_job())
    with db.tx() as c:
        item = db.search(c, "")[0]
    assert item["kind"] == "video" and item["mime"] == "video/x-matroska" and item["title"] == "Some Clip"
    assert item["source_url"].endswith("BiM39zlpyxs") and item["has_thumb"]        # a thumbnail could be made from it too


def test_ytdlp_is_asked_for_browser_friendly_mp4(client, monkeypatch, tmp_path):
    seen = []
    fake_downloader(monkeypatch, {"Clip [abc].mp4": make_video(tmp_path, "x.mp4")}, seen)
    pipeline.job_fetch(fetch_job())
    cmd = seen[0]
    assert cmd[0] == "yt-dlp"
    assert cmd[cmd.index("--merge-output-format") + 1] == "mp4"                      # never leave a merge to pick .mkv
    assert "h264" in cmd[cmd.index("-S") + 1] and "aac" in cmd[cmd.index("-S") + 1]


def test_unusable_download_error_names_the_files(client, monkeypatch):
    fake_downloader(monkeypatch, {"weird thing.xyz": "not media", "another.dat": "nope"}, [])
    with pytest.raises(providers.ProviderError) as e:
        pipeline.job_fetch(fetch_job())
    msg = str(e.value)
    assert "weird thing.xyz" in msg and "another.dat" in msg and "not recognised" in msg


def test_nothing_downloaded_at_all_says_so(client, monkeypatch):
    fake_downloader(monkeypatch, {}, [])
    monkeypatch.setattr(pipeline, "_run_tool", lambda cmd, timeout: subprocess.CompletedProcess(cmd, 1, "", "ERROR: Video unavailable"))
    with pytest.raises(providers.ProviderError) as e:
        pipeline.job_fetch(fetch_job())
    assert "nothing downloadable" in str(e.value) and "Video unavailable" in str(e.value)
