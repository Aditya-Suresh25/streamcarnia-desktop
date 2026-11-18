"""Signal objects for QRunnable workers (QRunnable itself can't emit Qt
signals, so each worker owns one of these QObjects)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AnalyzeSignals(QObject):
    started = Signal()
    succeeded = Signal(object)   # backend.models.schemas.AnalyzeResponse
    failed = Signal(str)


class DownloadSignals(QObject):
    updated = Signal(object)     # backend.models.schemas.DownloadItem
    finished = Signal(object)    # DownloadItem (completed or cancelled or failed)


class ClipSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)  # clips and the job summary, including partial results
    failed = Signal(str)
    cancelled = Signal()
