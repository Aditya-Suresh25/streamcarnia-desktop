"""Background local-media probing and catalog import for Studio.

Signals are ``progress(dict)``, ``finished(dict)``, ``cancelled(dict)``, and
``failed(str)``. The result dictionary contains ``imported`` and ``errors``
lists; each imported record includes the original path, source id, dimensions,
duration, and whether it was already present. One bad file does not prevent
other files from importing. Cancellation stops between files and preserves
completed imports. No source media is copied, moved, or edited.
"""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class StudioImportSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)
    cancelled = Signal(object)
    failed = Signal(str)


class StudioImportWorker(QRunnable):
    """Probe and register local videos using the existing Studio services."""

    def __init__(self, paths, catalog_path: Path, ffmpeg_path: str | None = None,
                 streamer_id: str | None = None):
        super().__init__()
        self.paths = [Path(path).expanduser() for path in paths]
        self.catalog_path = Path(catalog_path)
        self.ffmpeg_path = ffmpeg_path
        self.streamer_id = streamer_id
        self.cancel_event = Event()
        self.signals = StudioImportSignals()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            from services.studio.catalog import StudioCatalog
            from services.studio.media import probe_media

            catalog = StudioCatalog(self.catalog_path)
            known = {str(Path(item["path"]).resolve()): item["id"]
                     for item in catalog.list_sources()}
            imported, errors = [], []
            total = len(self.paths)
            for index, path in enumerate(self.paths, start=1):
                if self.cancel_event.is_set():
                    self._emit(self.signals.cancelled, {"imported": imported, "errors": errors,
                                                        "completed": index - 1, "total": total})
                    return
                try:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_file():
                        raise ValueError("Choose a video file")
                    details = probe_media(resolved, self.ffmpeg_path)
                    key = str(resolved)
                    is_existing = key in known
                    # Avoid StudioCatalog.add_source's duplicate update path so an
                    # import cannot clear existing streamer assignment or metadata.
                    source_id = known[key] if is_existing else catalog.add_source(
                        resolved, title=resolved.stem, streamer_id=self.streamer_id,
                        duration=float(details["duration"]), width=int(details["width"]),
                        height=int(details["height"]))
                    known[key] = source_id
                    imported.append({"id": source_id, "path": str(resolved), "title": resolved.stem,
                                     "duration": float(details["duration"]),
                                     "width": int(details["width"]), "height": int(details["height"]),
                                     "existing": is_existing})
                except Exception as exc:  # A single corrupt/missing source must not stop a batch.
                    errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
                self._emit(self.signals.progress, {"completed": index, "total": total,
                    "path": str(path), "succeeded": len(imported), "failed": len(errors)})
            self._emit(self.signals.finished, {"imported": imported, "errors": errors,
                                               "completed": total, "total": total})
        except Exception as exc:
            self._emit(self.signals.failed, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _emit(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            # The owning page may have closed while the background task unwound.
            pass
