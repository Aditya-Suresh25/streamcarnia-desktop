"""
Resource-path handling that works identically in development and in a
PyInstaller-frozen build.

Dev layout:      desktop/main.py, desktop/assets/, ../backend/ (sibling package)
Frozen layout:    StreamCarnia.exe, _internal/assets/, _internal/backend/, bin/ffmpeg.exe
                   (PyInstaller unpacks bundled data next to the exe / into _MEIPASS)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory containing the running app: the exe's folder when frozen,
    otherwise the `desktop/` package folder."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """Where bundled data files (assets, backend/, ffmpeg) were unpacked.
    PyInstaller one-folder builds put these next to the exe (in _internal on
    newer PyInstaller); sys._MEIPASS points at the right place either way."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_root()))
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """The streamcarnia/ repo root (parent of desktop/ and backend/) in dev
    mode. Used only to locate the sibling `backend` package for import and
    the dev-mode ffmpeg binary."""
    return Path(__file__).resolve().parent.parent.parent


def resource_path(*parts: str) -> Path:
    """Resolve a path to a bundled resource (assets, ffmpeg, etc.)."""
    return bundle_root().joinpath(*parts)


def asset_path(*parts: str) -> Path:
    return resource_path("assets", *parts)


def ffmpeg_binary_name() -> str:
    return "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


def bundled_ffmpeg_path() -> Path | None:
    """The ffmpeg bundled with this app, if present."""
    candidates = [
        resource_path("bin", ffmpeg_binary_name()),
        resource_path("backend", "bin", ffmpeg_binary_name()),
    ]
    if not is_frozen():
        candidates.append(project_root() / "backend" / "bin" / ffmpeg_binary_name())
    for c in candidates:
        if c.is_file():
            return c
    return None


def app_data_dir() -> Path:
    """Per-user writable location for settings/history/logs (never inside
    the installed/frozen app folder, which may not be writable)."""
    if sys.platform == "win32":
        import os
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    d = base / "StreamCarnia"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_backend_importable() -> None:
    """Make the existing `backend` package importable from the desktop app,
    in both dev and frozen modes, without copying/duplicating its code.

    In a frozen (PyInstaller) build, `backend` is compiled into the
    bundled PYZ archive alongside every other imported module -- it is
    NOT extracted as a loose `backend/__init__.py` file anywhere on disk,
    so it must never be located by checking for one. PyInstaller's own
    import hook (already registered in sys.meta_path for a frozen app)
    makes `import backend` work immediately with no sys.path changes at
    all. Only in dev mode does `backend` need sys.path help, since it's
    a real sibling folder that isn't on the interpreter's path by default.
    """
    if importlib.util.find_spec("backend") is not None:
        return  # already importable: frozen build, or already on sys.path

    for base in (project_root(), bundle_root()):
        candidate = str(base)
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
        if importlib.util.find_spec("backend") is not None:
            return
        sys.path.remove(candidate)

    raise RuntimeError(
        "Could not locate the 'backend' package. In development, run this "
        "app from the desktop/ folder with backend/ sitting next to it as "
        "a sibling folder. In a built app, this means backend/ wasn't "
        "picked up during the PyInstaller build -- rebuild with "
        "build_windows.bat from within the full project (backend/ and "
        "desktop/ both present)."
    )
