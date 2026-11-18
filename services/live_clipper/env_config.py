"""Small .env reader for local Live Auto Clipper configuration.

The API key is read-only from this file; the app's Settings UI continues to
store entered keys and OAuth tokens in the OS credential store.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.paths import app_root


ENV_KEYS = {
    "gemini.api_key": "GEMINI_API_KEY",
    "oauth_client_file": "GOOGLE_OAUTH_CLIENT_FILE",
}


def env_file_path() -> Path:
    explicit = os.environ.get("STREAMCARNIA_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = app_root()
    # The packaged build output is nested under the repository during local
    # development. Prefer a nearby .env but only search a few parents.
    candidates = [root, *list(root.parents)[:4]]
    for directory in candidates:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return root / ".env"


def parse_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse simple KEY=VALUE lines; no variable interpolation or code execution."""
    source = Path(path) if path else env_file_path()
    try:
        lines = source.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    values = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        name, separator, value = stripped.partition("=")
        if not separator:
            continue
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name in ENV_KEYS.values() and value:
            values[name] = value
    return values


def env_value(name: str, path: Path | None = None) -> str | None:
    """Process environment takes priority over the local .env file."""
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    value = parse_env_file(path).get(name)
    if not value:
        return None
    normalized = value.strip()
    if normalized.startswith("<") and normalized.endswith(">"):
        return None
    if normalized.lower() in {"your_api_key", "replace_me", "changeme", "todo"}:
        return None
    return normalized


def live_env_value(setting: str, path: Path | None = None) -> str | None:
    env_name = ENV_KEYS.get(setting)
    return env_value(env_name, path) if env_name else None
