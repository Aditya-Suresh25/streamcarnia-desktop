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
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
    log_dir = app_data_dir() / "logs"
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
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id == -1:
            logger.warning("Failed to load bundled font: %s", ttf.name)


def main() -> int:
    _setup_logging()
    logger = logging.getLogger("main")

    history_db_path = app_data_dir() / "history.db"
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

