"""
Background download task.

This ports backend.services.download_manager's per-download orchestration
(stage tracking, staging directory, cleanup-on-cancel, history write) to a
Qt QRunnable, while reusing the actual download implementation --
backend.services.ytdlp_service.download_video -- completely unchanged.

Unlike the web app (which stages into a temp dir and requires an explicit
browser "save" step), the desktop app has direct filesystem access, so it
downloads straight into the user's configured download folder.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from threading import Event

from PySide6.QtCore import QRunnable, Slot
from yt_dlp.utils import DownloadCancelled

from backend.models.schemas import DownloadItem, DownloadStage, HistoryEntry
from backend.services import ytdlp_service
from backend.services.history_store import HistoryStore

from workers.signals import DownloadSignals
from core.media_storage import configure_media_storage

logger = logging.getLogger("download_worker")


class DownloadWorker(QRunnable):
    def __init__(
        self,
        item: DownloadItem,
        format_selector: str,
        quality_key: str,
        container: str,
        download_dir: str,
        ffmpeg_path: str | None,
        cookies_path: str | None,
        history_store: HistoryStore,
    ):
        super().__init__()
        self.item = item
        self.format_selector = format_selector
        self.quality_key = quality_key
        self.container = container
        self.download_dir = download_dir
        self.ffmpeg_path = ffmpeg_path
        self.cookies_path = cookies_path
        self.history_store = history_store
        self.cancel_event = Event()
        self.signals = DownloadSignals()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _job_dir(self) -> Path:
        return Path(self.download_dir).expanduser() / ".streamcarnia" / "incomplete" / self.item.id

    def _emit(self) -> None:
        # The main window (and its Qt signal objects) may already be torn
        # down if the app is quitting while this background worker is
        # still running; emitting to a deleted QObject raises RuntimeError.
        try:
            self.signals.updated.emit(self.item)
        except RuntimeError:
            pass

    def _finish(self) -> None:
        try:
            self.signals.finished.emit(self.item)
        except RuntimeError:
            pass

    @Slot()
    def run(self) -> None:
        item = self.item

        if self.cancel_event.is_set():
            item.stage = DownloadStage.CANCELLED
            self._emit()
            self._finish()
            return

        job_dir = self._job_dir()
        job_dir.mkdir(parents=True, exist_ok=True)
        configure_media_storage(self.download_dir)
        import tempfile
        tempfile.tempdir = None

        item.stage = DownloadStage.DOWNLOADING_VIDEO
        self._emit()

        def on_progress(update: dict) -> None:
            if self.cancel_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            for key, value in update.items():
                setattr(item, key, value)
            self._emit()

        try:
            result = ytdlp_service.download_video(
                url=item.url,
                format_selector=self.format_selector,
                quality_key=self.quality_key,
                channel=item.channel,
                title_hint=item.title,
                output_dir=str(job_dir),
                container=self.container,
                ffmpeg_path=self.ffmpeg_path,
                cookies_path=self.cookies_path,
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(job_dir, ignore_errors=True)
            if self.cancel_event.is_set():
                item.stage = DownloadStage.CANCELLED
                self._emit()
            else:
                logger.exception("Download %s failed", item.id)
                item.stage = DownloadStage.FAILED
                item.error = str(exc)
                self._emit()
                self._record_history("failed", None)
            self._finish()
            return

        if self.cancel_event.is_set():
            shutil.rmtree(job_dir, ignore_errors=True)
            item.stage = DownloadStage.CANCELLED
            self._emit()
            self._finish()
            return

        staged_path = result.get("file_path")
        final_path = self._move_to_download_dir(staged_path, job_dir)

        item.file_path = final_path
        item.stage = DownloadStage.COMPLETED
        item.percent = 100.0
        self._emit()
        self._record_history("completed", final_path)
        self._finish()

    def _move_to_download_dir(self, staged_path: str | None, job_dir: Path) -> str | None:
        if not staged_path or not Path(staged_path).is_file():
            shutil.rmtree(job_dir, ignore_errors=True)
            return None
        src = Path(staged_path)
        dest_root = Path(self.download_dir)
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / src.name
        counter = 1
        while dest.exists():
            dest = dest_root / f"{src.stem} ({counter}){src.suffix}"
            counter += 1
        shutil.move(str(src), str(dest))
        shutil.rmtree(job_dir, ignore_errors=True)
        return str(dest)

    def _record_history(self, status: str, file_path: str | None) -> None:
        try:
            self.history_store.upsert(HistoryEntry(
                id=self.item.id,
                title=self.item.title,
                url=self.item.url,
                quality=self.item.format_label,
                date=self.item.created_at,
                status=status,
                file_path=file_path,
            ))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write history entry for %s", self.item.id)
