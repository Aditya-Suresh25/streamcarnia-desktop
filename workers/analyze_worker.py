"""Background 'analyze URL' task. Thin QRunnable shell around the existing,
unmodified backend.services.ytdlp_service.analyze_url."""
from __future__ import annotations

from PySide6.QtCore import QRunnable, Slot

from backend.services import ytdlp_service

from workers.signals import AnalyzeSignals


class AnalyzeWorker(QRunnable):
    def __init__(self, url: str, ffmpeg_path: str | None, cookies_path: str | None):
        super().__init__()
        self.url = url
        self.ffmpeg_path = ffmpeg_path
        self.cookies_path = cookies_path
        self.signals = AnalyzeSignals()

    @Slot()
    def run(self) -> None:
        self._safe_emit(self.signals.started)
        try:
            result = ytdlp_service.analyze_url(
                self.url,
                ffmpeg_path=self.ffmpeg_path,
                cookies_path=self.cookies_path,
            )
        except ytdlp_service.UnsupportedURLError as exc:
            self._safe_emit(self.signals.failed, str(exc))
            return
        except RuntimeError as exc:
            self._safe_emit(self.signals.failed, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._safe_emit(self.signals.failed, f"Unexpected error: {exc}")
            return
        self._safe_emit(self.signals.succeeded, result)

    @staticmethod
    def _safe_emit(signal, *args) -> None:
        # Guards against the window (and its signal objects) already being
        # torn down if the app quit while this background task was running.
        try:
            signal.emit(*args)
        except RuntimeError:
            pass
