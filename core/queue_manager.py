"""Owns the download queue: submits DownloadWorkers to a QThreadPool,
tracks DownloadItem state, and re-emits updates for the UI."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QThreadPool, Signal

from backend.models.schemas import DownloadItem, DownloadStage
from backend.services.history_store import HistoryStore

from core.settings_store import SettingsStore
from workers.download_worker import DownloadWorker


class QueueManager(QObject):
    item_added = Signal(object)     # DownloadItem
    item_updated = Signal(object)   # DownloadItem
    item_finished = Signal(object)  # DownloadItem

    def __init__(self, settings_store: SettingsStore, history_store: HistoryStore, ffmpeg_path_provider, cookies_path_provider):
        super().__init__()
        self._settings_store = settings_store
        self._history_store = history_store
        self._ffmpeg_path_provider = ffmpeg_path_provider
        self._cookies_path_provider = cookies_path_provider
        self._pool = QThreadPool.globalInstance()
        self._apply_concurrency()
        self._workers: dict[str, DownloadWorker] = {}
        self._items: dict[str, DownloadItem] = {}

    def active_items(self) -> list[DownloadItem]:
        """Snapshot current in-memory downloads for dashboard progress views."""
        return list(self._items.values())

    def _apply_concurrency(self) -> None:
        n = max(1, int(self._settings_store.get().concurrent_downloads))
        self._pool.setMaxThreadCount(n)

    def refresh_concurrency(self) -> None:
        self._apply_concurrency()

    def enqueue(self, *, url: str, format_selector: str, quality_key: str,
                title: str, channel: str | None, format_label: str,
                download_dir: str | None = None) -> DownloadItem:
        settings = self._settings_store.get()
        target_dir = download_dir or settings.download_dir
        item = DownloadItem(
            id=str(uuid.uuid4()),
            url=url,
            title=title,
            channel=channel,
            format_label=format_label,
            stage=DownloadStage.QUEUED,
            percent=0.0,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        worker = DownloadWorker(
            item=item,
            format_selector=format_selector,
            quality_key=quality_key,
            container=settings.container,
            download_dir=target_dir,
            ffmpeg_path=self._ffmpeg_path_provider(),
            cookies_path=self._cookies_path_provider(),
            history_store=self._history_store,
        )
        worker.signals.updated.connect(self._on_updated)
        worker.signals.finished.connect(self._on_finished)
        self._workers[item.id] = worker
        self._items[item.id] = item
        self.item_added.emit(item)
        self._pool.start(worker)
        return item

    def cancel(self, download_id: str) -> None:
        worker = self._workers.get(download_id)
        if worker:
            worker.cancel()

    def cancel_all(self) -> None:
        """Request cancellation of every active download, e.g. on app exit."""
        for worker in list(self._workers.values()):
            worker.cancel()

    def _on_updated(self, item: DownloadItem) -> None:
        self._items[item.id] = item
        self.item_updated.emit(item)

    def _on_finished(self, item: DownloadItem) -> None:
        self._items[item.id] = item
        self.item_finished.emit(item)
        self._workers.pop(item.id, None)
        self._items.pop(item.id, None)
