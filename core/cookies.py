"""
Cookie handling for the desktop app.

The existing backend.services.ytdlp_service only ever takes a *cookies
file path* (cookiefile). To add local browser-cookie support without
touching that reused code, we materialize the browser's cookie jar to a
Netscape-format cookies.txt once per session and hand that file's path to
the existing functions unchanged -- no downloader logic is duplicated.

Cookie contents are never logged.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("cookies")

_CACHE: dict[tuple[str, str], str] = {}


class CookieExtractionError(RuntimeError):
    pass


def _cache_dir(media_root: str | Path) -> Path:
    d = Path(media_root).expanduser() / ".streamcarnia" / "cache" / "cookies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_browser_cookies_to_file(browser: str, media_root: str | Path) -> str:
    """Export cookies from a locally installed browser to a temp
    cookies.txt file and return its path. Cached per browser per run."""
    browser = browser.lower().strip()
    cache_key = (browser, str(Path(media_root).expanduser().resolve()))
    if cache_key in _CACHE and Path(_CACHE[cache_key]).is_file():
        return _CACHE[cache_key]

    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except ImportError as exc:  # pragma: no cover - yt-dlp always present
        raise CookieExtractionError("yt-dlp is not available.") from exc

    try:
        jar = extract_cookies_from_browser(browser)
    except Exception as exc:  # noqa: BLE001
        logger.error("Cookie extraction failed for browser=%s: %s", browser, type(exc).__name__)
        raise CookieExtractionError(
            f"Couldn't read cookies from {browser.title()}. Make sure it's "
            "installed and fully closed, then try again."
        ) from exc

    cookie_file = _cache_dir(media_root) / f"cookies_{browser}.txt"
    try:
        jar.save(str(cookie_file), ignore_discard=True, ignore_expires=True)
    except Exception as exc:  # noqa: BLE001
        raise CookieExtractionError("Couldn't save extracted cookies.") from exc

    _CACHE[cache_key] = str(cookie_file)
    logger.info("Extracted browser cookies for %s (contents not logged).", browser)
    return str(cookie_file)


def resolve_cookies_path(settings, media_root: str | Path | None = None) -> str | None:
    """Turn the user's cookie-source setting into a cookiefile path
    understood by backend.services.ytdlp_service, or None."""
    from core.settings_store import COOKIE_MODE_BROWSER, COOKIE_MODE_FILE, COOKIE_MODE_NONE

    if settings.cookie_mode == COOKIE_MODE_NONE:
        return None
    if settings.cookie_mode == COOKIE_MODE_FILE:
        path = settings.cookie_file
        return path if path and Path(path).is_file() else None
    if settings.cookie_mode == COOKIE_MODE_BROWSER:
        return extract_browser_cookies_to_file(settings.cookie_browser, media_root or settings.download_dir)
    return None
