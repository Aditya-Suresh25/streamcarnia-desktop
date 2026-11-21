"""Background QRunnable wrapper for Studio highlight discovery."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from services.studio.discovery import StudioDiscoveryCancelled, run_discovery


class StudioDiscoverySignals(QObject):
    progress = Signal(object)  # stage/message and backend progress, when available
    completed = Signal(object)  # list of unmodified backend candidate dictionaries
    failed = Signal(str)
    cancelled = Signal()


class StudioDiscoveryWorker(QRunnable):
    """Run the existing detect-only pipeline without blocking the UI thread."""

    def __init__(self, source_path: str | Path, output_dir: str | Path, *,
                 top: int = 8, ffmpeg_path: str | Path | None = None):
        super().__init__()
        self.source_path = Path(source_path)
        self.output_dir = Path(output_dir)
        self.top = top
        self.ffmpeg_path = Path(ffmpeg_path) if ffmpeg_path else None
        self.cancel_event = Event()
        self.signals = StudioDiscoverySignals()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            candidates = run_discovery(
                self.source_path, self.output_dir, top=self.top,
                ffmpeg_path=self.ffmpeg_path, cancelled=self.cancel_event,
                on_progress=self.signals.progress.emit,
            )
            self.signals.completed.emit(candidates)
        except StudioDiscoveryCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
