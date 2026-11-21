"""Settings for Live Auto Clipper. Secrets are deliberately not stored here."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock

from core.paths import app_data_dir
from .env_config import live_env_value

CONFIG_PATH = app_data_dir() / "live_clipper.json"


@dataclass(frozen=True)
class LiveClipperConfig:
    enabled: bool = False
    max_clips_per_stream: int = 10
    clip_length_seconds: int = 60
    threshold: float = 2.0
    layout: str = "blur"
    facecam: str = "0.75,0.68,0.25,0.32"
    stack_facecam_percent: int = 35
    caption_style: str = "pop"
    transcription_model: str = "medium"
    approve_before_upload: bool = True
    schedule_start: str = "09:00"
    schedule_end: str = "21:00"
    oauth_client_file: str = ""
    output_dir: str = ""

    def validated(self) -> "LiveClipperConfig":
        if not 20 <= int(self.clip_length_seconds) <= 60:
            raise ValueError("Live clip length must be between 20 and 60 seconds")
        if not 1 <= int(self.max_clips_per_stream) <= 100:
            raise ValueError("Maximum clips per stream must be between 1 and 100")
        if not 0.1 <= float(self.threshold) <= 20.0:
            raise ValueError("Detection threshold must be between 0.1 and 20")
        if self.layout not in {"blur", "center", "stack"}:
            raise ValueError("Live clips must use a portrait layout: blur, center, or stack")
        try:
            facecam = tuple(float(part.strip()) for part in self.facecam.split(","))
        except (AttributeError, ValueError):
            raise ValueError("Facecam position must use x,y,width,height fractions") from None
        if (len(facecam) != 4 or any(not 0 <= value <= 1 for value in facecam)
                or facecam[2] == 0 or facecam[3] == 0
                or facecam[0] + facecam[2] > 1 or facecam[1] + facecam[3] > 1):
            raise ValueError("Facecam position must fit inside the source frame")
        if not 20 <= int(self.stack_facecam_percent) <= 50:
            raise ValueError("Stack facecam portion must be between 20% and 50%")
        if self.caption_style not in {"pop", "bounce", "word", "karaoke"}:
            raise ValueError("Unsupported animated caption style")
        if self.transcription_model not in {"small", "medium", "large-v3"}:
            raise ValueError("Transcription model must be small, medium, or large-v3")
        for value in (self.schedule_start, self.schedule_end):
            _parse_clock(value)
        if _parse_clock(self.schedule_end) <= _parse_clock(self.schedule_start):
            raise ValueError("The publishing window must end after it starts on the same day")
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
                return LiveClipperConfig(oauth_client_file=live_env_value("oauth_client_file") or "")
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                # Accept the advertised dotted feature-flag key as well as nested config.
                enabled = raw.pop("live_clipper.enabled", raw.get("enabled", False))
                raw.pop("enabled", None)
                allowed = set(LiveClipperConfig.__dataclass_fields__) - {"enabled"}
                options = {key: value for key, value in raw.items() if key in allowed}
                if not options.get("oauth_client_file"):
                    options["oauth_client_file"] = live_env_value("oauth_client_file") or ""
                return LiveClipperConfig(enabled=bool(enabled), **options).validated()
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return LiveClipperConfig(oauth_client_file=live_env_value("oauth_client_file") or "")

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
