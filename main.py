"""
StreamCarnia Desktop -- entry point.

Boots a PySide6 app that reuses the existing backend/ business logic
(yt-dlp integration, filename sanitization, ffmpeg detection, SQLite
history) directly, with no local web server, no React/Vite, and no
localhost involved.

© Aditya Suresh. All rights reserved.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _dispatch_child_process() -> bool:
    """Run packaged helper tools without starting a second GUI instance."""
    if len(sys.argv) < 2:
        return False
    mode = sys.argv[1]
    if mode == "--run-clipper" and len(sys.argv) >= 3:
        _restore_child_stdio()
        script, *args = sys.argv[2:]
        script_path = Path(script).resolve()
        sys.path.insert(0, str(script_path.parent))
        sys.argv = [str(script_path), *args]
        namespace = {
            "__name__": "__main__", "__file__": str(script_path),
            "__package__": None, "__cached__": None,
        }
        source = script_path.read_text(encoding="utf-8-sig")
        exec(compile(source, str(script_path), "exec"), namespace)
        return True
    if mode == "--run-ytdlp":
        _restore_child_stdio()
        from yt_dlp import main as ytdlp_main
        ytdlp_main(sys.argv[2:])
        return True
    if mode == "--run-live-worker" and len(sys.argv) >= 3:
        _restore_child_stdio()
        from services.live_clipper.worker import run_worker
        raise SystemExit(run_worker(sys.argv[2]))
    return False


def _restore_child_stdio() -> None:
    """PyInstaller windowed builds set Python's stdout/stderr to None."""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name, None) is not None:
            continue
        try:
            setattr(sys, name, os.fdopen(fd, "w", encoding="utf-8", errors="replace", buffering=1))
        except OSError:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


if _dispatch_child_process():
    raise SystemExit(0)

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

# Make the sibling `backend/` package importable (dev) or the bundled copy
# (frozen build) before importing anything from it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.paths import app_data_dir, asset_path, ensure_backend_importable  # noqa: E402

ensure_backend_importable()

from backend.services.history_store import HistoryStore  # noqa: E402

from core.settings_store import settings_store  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

APP_NAME = "StreamCarnia"
APP_COPYRIGHT = "\u00a9 Aditya Suresh"


def _setup_logging() -> None:
    from core.settings_store import settings_store
    media_root = Path(settings_store.get().clip_output_dir or settings_store.get().download_dir).expanduser()
    log_dir = media_root / ".streamcarnia" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load_bundled_fonts() -> None:
    """Load the app's actual brand fonts (Inter for body copy, Space
    Grotesk for display/heading text -- the same pairing the web app
    uses) so the UI renders identically rich typography regardless of
    what's installed on the end user's machine, instead of silently
    falling back to plain system UI fonts."""
    fonts_dir = asset_path("fonts")
    if not fonts_dir.is_dir():
        return
    logger = logging.getLogger("fonts")
    for ttf in sorted(fonts_dir.glob("*.ttf")):
        # Loading from bytes is reliable in PyInstaller's one-folder build,
        # where Qt may reject a font by its extracted filesystem path.
        font_id = QFontDatabase.addApplicationFontFromData(ttf.read_bytes())
        if font_id == -1:
            logger.warning("Failed to load bundled font: %s", ttf.name)


def main() -> int:
    _setup_logging()
    logger = logging.getLogger("main")

    media_root = Path(settings_store.get().clip_output_dir or settings_store.get().download_dir).expanduser()
    media_state = media_root / ".streamcarnia"
    media_state.mkdir(parents=True, exist_ok=True)
    history_db_path = media_state / "history.db"
    legacy_history = app_data_dir() / "history.db"
    if not history_db_path.exists() and legacy_history.exists():
        try:
            with sqlite3.connect(legacy_history) as source, sqlite3.connect(history_db_path) as target:
                source.backup(target)
        except sqlite3.Error:
            history_db_path.unlink(missing_ok=True)
            shutil.copy2(legacy_history, history_db_path)
    history_store = HistoryStore(str(history_db_path))

    logger.info(
        "Starting %s desktop (%s); download_dir=%s, ffmpeg=%s",
        APP_NAME, APP_COPYRIGHT, settings_store.get().download_dir, settings_store.ffmpeg_path or "not found",
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    _load_bundled_fonts()

    window = MainWindow(settings_store, history_store)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

