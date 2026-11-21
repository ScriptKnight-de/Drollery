from __future__ import annotations

import os
import shutil
import tomllib
from functools import lru_cache
from importlib import resources
from pathlib import Path

from pydantic import BaseModel


class Provider(BaseModel):
    type: str = "none"
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    timeout: int = 300
    language: str = ""
    prompt: str = ""
    command: str = ""
    langs: str = "eng"
    send_image: bool = True
    api_key: str = ""      # filled from the database for UI-defined models; never read from config.toml

    @property
    def enabled(self) -> bool:
        return self.type not in ("", "none")


class Settings(BaseModel):
    max_upload_mb: int = 500
    max_album_mb: int = 2048          # all the tracks of one album together (also the unpacked size of a ZIP)
    max_album_tracks: int = 500
    metadata_lookup: bool = True       # offer the online album lookup (MusicBrainz + Cover Art Archive); it only runs when someone asks for it
    metadata_user_agent: str = ""      # sent to those services; empty = just "Drollery/<version>". They ask for a contact URL here if you want to give one
    worker_concurrency: int = 1
    job_max_attempts: int = 3
    fetch_timeout: int = 900
    fetch_max_files: int = 4
    transcribe: Provider = Provider()
    describe: Provider = Provider()
    # runtime values (not read from the TOML file)
    data_dir: Path = Path("data")
    cookie_secure: bool = False

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def cards_dir(self) -> Path:
        return self.data_dir / "cards"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "drollery.db"


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("DROLLERY_DATA", "data")).resolve()
    for sub in ("media", "thumbs", "cards", "tmp"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    cfg_path = data_dir / "config.toml"
    if not cfg_path.exists():
        default = resources.files("drollery").joinpath("config.default.toml")
        with resources.as_file(default) as src:
            shutil.copyfile(src, cfg_path)
    with cfg_path.open("rb") as f:
        raw = tomllib.load(f)
    return Settings(**raw, data_dir=data_dir, cookie_secure=os.environ.get("DROLLERY_COOKIE_SECURE", "") in ("1", "true", "yes"))
