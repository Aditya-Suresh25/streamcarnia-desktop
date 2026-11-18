"""
Desktop settings: persisted JSON in the per-user app-data directory.

Reuses backend.models.schemas.ContainerPreference and
backend.utils.system.{default_download_dir, find_ffmpeg} rather than
re-implementing them, and adds the desktop-only concerns (cookie source,
window/theme prefs) the web app doesn't need.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock

from backend.utils.system import default_download_dir, find_ffmpeg

from core.paths import app_data_dir, bundled_ffmpeg_path

SETTINGS_FILE = app_data_dir() / "settings.json"

COOKIE_MODE_NONE = "none"
COOKIE_MODE_FILE = "file"
COOKIE_MODE_BROWSER = "browser"

SUPPORTED_COOKIE_BROWSERS = ["brave", "chrome", "edge", "firefox"]


@dataclass
class DesktopSettings:
    download_dir: str = field(default_factory=lambda: str(default_download_dir()))
    container: str = "auto"  # auto | mp4 | mkv | webm
    concurrent_downloads: int = 2
    cookie_mode: str = COOKIE_MODE_NONE
    cookie_browser: str = "chrome"
    cookie_file: str = ""
    accent: str = "violet"  # theme accent preset, see ui/theme.py
    clip_count: int = 5
    clip_layout: str = "blur"
    caption_style: str = "pop"
    caption_language: str = ""
    clip_pan_zoom: bool = False
    clip_facecam: str = "0.75,0.68,0.25,0.32"
    clip_channel_name: str = ""
    clip_subscriber_text: str = ""
    clip_logo_path: str = ""
    clip_output_dir: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_FILE):
        self._path = path
        self._lock = Lock()
        self._settings = self._load()

    def _load(self) -> DesktopSettings:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                defaults = DesktopSettings()
                merged = {**defaults.to_dict(), **data}
                return DesktopSettings(**merged)
            except Exception:
                pass
        return DesktopSettings()

    def get(self) -> DesktopSettings:
        return self._settings

    def update(self, **changes) -> DesktopSettings:
        with self._lock:
            current = asdict(self._settings)
            current.update(changes)
            self._settings = DesktopSettings(**current)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._settings.to_dict(), indent=2), encoding="utf-8"
            )
        return self._settings

    @property
    def ffmpeg_path(self) -> str | None:
        bundled = bundled_ffmpeg_path()
        if bundled:
            return str(bundled)
        return find_ffmpeg(None)


settings_store = SettingsStore()
