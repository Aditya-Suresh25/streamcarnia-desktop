"""Settings for Live Auto Clipper. Secrets are deliberately not stored here."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock

from core.paths import app_data_dir

CONFIG_PATH = app_data_dir() / "live_clipper.json"


@dataclass(frozen=True)
class LiveClipperConfig:
    enabled: bool = False
    max_clips_per_stream: int = 10
    clip_length_seconds: int = 60
    threshold: float = 2.0
    layout: str = "blur"
    caption_style: str = "pop"
    approve_before_upload: bool = True
    schedule_start: str = "09:00"
    schedule_end: str = "21:00"
    oauth_client_file: str = ""

    def validated(self) -> "LiveClipperConfig":
        if not 20 <= int(self.clip_length_seconds) <= 60:
            raise ValueError("Live clip length must be between 20 and 60 seconds")
        if not 1 <= int(self.max_clips_per_stream) <= 100:
            raise ValueError("Maximum clips per stream must be between 1 and 100")
        if not 0.1 <= float(self.threshold) <= 20.0:
            raise ValueError("Detection threshold must be between 0.1 and 20")
        if self.layout not in {"blur", "center", "stack"}:
            raise ValueError("Live clips must use a portrait layout: blur, center, or stack")
        if not self.caption_style.strip():
            raise ValueError("Caption style cannot be empty")
        for value in (self.schedule_start, self.schedule_end):
            _parse_clock(value)
        return self


def _parse_clock(value: str) -> int:
    try:
        h, m = (int(p) for p in value.split(":"))
    except (ValueError, AttributeError):
        raise ValueError("Schedule times must use HH:MM") from None
    if not 0 <= h <= 23 or not 0 <= m <= 59:
        raise ValueError("Schedule times must use HH:MM")
    return h * 60 + m


class LiveClipperSettings:
    """Independent UTF-8 settings store; does not touch the existing app JSON."""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)
        self._lock = RLock()

    def get(self) -> LiveClipperConfig:
        with self._lock:
            if not self.path.exists():
                return LiveClipperConfig()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                # Accept the advertised dotted feature-flag key as well as nested config.
                enabled = raw.pop("live_clipper.enabled", raw.get("enabled", False))
                raw.pop("enabled", None)
                allowed = set(LiveClipperConfig.__dataclass_fields__) - {"enabled"}
                options = {key: value for key, value in raw.items() if key in allowed}
                return LiveClipperConfig(enabled=bool(enabled), **options).validated()
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return LiveClipperConfig()

    def update(self, **changes) -> LiveClipperConfig:
        with self._lock:
            current = asdict(self.get())
            current.update(changes)
            updated = LiveClipperConfig(**current).validated()
            payload = asdict(updated)
            payload["live_clipper.enabled"] = payload.pop("enabled")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp.replace(self.path)
            return updated
