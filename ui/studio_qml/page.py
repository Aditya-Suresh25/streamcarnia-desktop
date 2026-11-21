"""Qt Quick Studio surface with a Python owned timeline/render boundary.

The page is intentionally independent of the existing Studio page so it can be
validated and integrated without changing current workflows.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from core.paths import resource_path
from ui.theme import palette


class StudioController(QObject):
    """Typed boundary between QML interactions and the host application."""

    source_url_changed = Signal()
    source_path_changed = Signal()
    duration_changed = Signal()
    position_changed = Signal()
    ranges_changed = Signal()
    active_range_changed = Signal()
    status_changed = Signal()
    render_available_changed = Signal()
    theme_changed = Signal()
    sources_changed = Signal()
    source_requested = Signal(str)
    source_in_library_changed = Signal()
    candidates_changed = Signal()
    thumbnails_changed = Signal()
    candidate_chosen = Signal(str)
    candidate_review_requested = Signal(str, str)
    history_changed = Signal()
    preview_changed = Signal()

    def __init__(self, theme: dict[str, str], parent: QObject | None = None):
        super().__init__(parent)
        self._theme = dict(theme)
        self._source_path = ""
        self._preview_path = ""
        self._source_url = QUrl()
        self._duration_ms = 0
        self._position_ms = 0
        self._ranges: list[dict[str, int]] = []
        self._active_range = -1
        self._status = "Choose a local video to begin."
        self._render_available = False
        self._sources: list[dict[str, str]] = []
        self._candidates: list[dict[str, Any]] = []
        self._thumbnails: list[dict[str, Any]] = []
        self._range_history: list[list[dict[str, int]]] = [[]]
        self._history_index = 0
        self._range_editing = False

    @Property(str, notify=source_url_changed)
    def sourceUrl(self) -> str:
        return self._source_url.toString()

    @Property(str, notify=source_path_changed)
    def sourcePath(self) -> str:
        return self._source_path

    @Property(str, notify=preview_changed)
    def previewUrl(self) -> str:
        return QUrl.fromLocalFile(self._preview_path).toString() if self._preview_path else ""

    @Property(int, notify=duration_changed)
    def durationMs(self) -> int:
        return self._duration_ms

    @Property(int, notify=position_changed)
    def positionMs(self) -> int:
        return self._position_ms

    @Property("QVariantList", notify=ranges_changed)
    def ranges(self) -> list[dict[str, int]]:
        return [dict(r) for r in self._ranges]

    @Property(int, notify=active_range_changed)
    def activeRange(self) -> int:
        return self._active_range

    @Property(str, notify=status_changed)
    def statusText(self) -> str:
        return self._status

    @Property(bool, notify=render_available_changed)
    def renderAvailable(self) -> bool:
        return self._render_available

    @Property("QVariantMap", notify=theme_changed)
    def theme(self) -> dict[str, str]:
        return dict(self._theme)

    @Property(str, constant=True)
    def bodyFont(self) -> str:
        return "Inter"

    @Property(str, constant=True)
    def displayFont(self) -> str:
        return "Space Grotesk"

    @Property("QVariantList", notify=sources_changed)
    def sources(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._sources]

    @Property(bool, notify=source_in_library_changed)
    def sourceInLibrary(self) -> bool:
        try:
            selected = Path(self._source_path).resolve() if self._source_path else None
            return bool(selected and any(Path(item["path"]).resolve() == selected for item in self._sources))
        except OSError:
            return False

    @Property("QVariantList", notify=candidates_changed)
    def candidates(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._candidates]

    @Property("QVariantList", notify=thumbnails_changed)
    def thumbnails(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._thumbnails]

    @Property(bool, notify=history_changed)
    def canUndo(self) -> bool:
        return self._history_index > 0

    @Property(bool, notify=history_changed)
    def canRedo(self) -> bool:
        return self._history_index < len(self._range_history) - 1

    def set_source(self, path: str) -> None:
        resolved = Path(path).expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"Not a file: {resolved}")
        self._source_path = str(resolved)
        self._preview_path = ""
        self._source_url = QUrl.fromLocalFile(str(resolved))
        self._duration_ms = 0
        self._position_ms = 0
        self._ranges = []
        self._active_range = -1
        self._reset_range_history()
        self._status = "Loading local media…"
        self.source_path_changed.emit()
        self.preview_changed.emit()
        self.source_url_changed.emit()
        self.source_in_library_changed.emit()
        self.duration_changed.emit()
        self.position_changed.emit()
        self.ranges_changed.emit()
        self.active_range_changed.emit()
        self.status_changed.emit()

    @Slot(int)
    def set_duration(self, duration_ms: int) -> None:
        duration_ms = max(0, int(duration_ms))
        if duration_ms == self._duration_ms:
            return
        self._duration_ms = duration_ms
        self.duration_changed.emit()
        if duration_ms and self._ranges:
            bounded = []
            for item in self._ranges:
                start = min(item["startMs"], max(0, duration_ms - 100))
                end = min(item["endMs"], duration_ms)
                if end > start:
                    bounded.append({"startMs": start, "endMs": end})
            if bounded != self._ranges:
                self._ranges = bounded
                self._active_range = min(self._active_range, len(bounded) - 1)
                self.ranges_changed.emit()
                self.active_range_changed.emit()

    @Slot("QVariantList")
    def set_ranges(self, ranges: list) -> None:
        """Sync saved/editor ranges into the QML timeline without rendering."""
        parsed: list[dict[str, int]] = []
        for item in ranges:
            try:
                start, end = float(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if start < 0 or end <= start:
                continue
            start_ms, end_ms = round(start * 1000), round(end * 1000)
            if self._duration_ms:
                start_ms = min(start_ms, self._duration_ms - 100)
                end_ms = min(end_ms, self._duration_ms)
            if end_ms > start_ms:
                parsed.append({"startMs": start_ms, "endMs": end_ms})
        self._ranges = parsed
        self._active_range = len(parsed) - 1 if parsed else -1
        self._reset_range_history()
        self.ranges_changed.emit()
        self.active_range_changed.emit()

    def set_candidates(self, records: list[dict[str, Any]]) -> None:
        self._candidates = [dict(item) for item in records if isinstance(item, dict)]
        self.candidates_changed.emit()

    def set_thumbnails(self, frames: list[dict[str, Any]]) -> None:
        self._thumbnails = [{"time": float(item["time"]),
                             "url": QUrl.fromLocalFile(str(item["path"])).toString()}
                            for item in frames if item.get("path")]
        self.thumbnails_changed.emit()

    @Slot(int)
    def choose_candidate(self, index: int) -> None:
        if not 0 <= index < len(self._candidates):
            return
        record = self._candidates[index]
        candidate = record.get("payload", record)
        try:
            start, end = float(candidate["start"]), float(candidate["end"])
        except (KeyError, TypeError, ValueError):
            self.set_status("This highlight has no valid time range.")
            return
        if start < 0 or end <= start:
            self.set_status("This highlight has no valid time range.")
            return
        self.set_position(int(start * 1000))
        self.add_range(start, end)
        identifier = str(record.get("id") or candidate.get("id") or candidate.get("rank") or "")
        if identifier:
            self.candidate_chosen.emit(identifier)

    @Slot(int, str)
    def set_candidate_review(self, index: int, state: str) -> None:
        if not 0 <= index < len(self._candidates) or state not in {"favorite", "rejected"}:
            return
        record = self._candidates[index]
        identifier = str(record.get("id") or record.get("rank") or "")
        if identifier:
            self.candidate_review_requested.emit(identifier, state)

    def set_theme(self, theme: dict[str, str]) -> None:
        self._theme = dict(theme)
        self.theme_changed.emit()

    @Slot(int)
    def set_position(self, position_ms: int) -> None:
        position = max(0, min(int(position_ms), self._duration_ms or int(position_ms)))
        if position != self._position_ms:
            self._position_ms = position
            self.position_changed.emit()

    @Slot(str)
    def set_status(self, status: str) -> None:
        self._status = str(status)
        self.status_changed.emit()

    @Slot(int, int)
    def seek(self, position_ms: int, _unused: int = 0) -> None:
        self.set_position(position_ms)

    @Slot(int)
    def seek_to(self, position_ms: int) -> None:
        self.set_position(position_ms)
        self.seek_requested.emit(self._position_ms)

    seek_requested = Signal(int)

    @Slot(float, float)
    def add_range(self, start_seconds: float, end_seconds: float) -> None:
        if not self._duration_ms:
            self.set_status("Wait for the video duration before adding a range.")
            return
        start = max(0, min(int(start_seconds * 1000), self._duration_ms))
        end = max(start + 100, min(int(end_seconds * 1000), self._duration_ms))
        if end > self._duration_ms:
            start = max(0, self._duration_ms - 100)
            end = self._duration_ms
        self._ranges.append({"startMs": start, "endMs": end})
        self._active_range = len(self._ranges) - 1
        self.ranges_changed.emit()
        self.active_range_changed.emit()
        self._record_range_snapshot()

    @Slot(int)
    def select_range(self, index: int) -> None:
        if 0 <= index < len(self._ranges) and index != self._active_range:
            self._active_range = index
            self.active_range_changed.emit()

    @Slot(int, float, int)
    def set_range_edge(self, index: int, start_seconds: float, edge: int = 0) -> None:
        """Update edge (0=in, 1=out) of a range in seconds."""
        if not (0 <= index < len(self._ranges)) or not self._duration_ms:
            return
        r = dict(self._ranges[index])
        value = max(0, min(int(start_seconds * 1000), self._duration_ms))
        if edge == 0:
            r["startMs"] = min(value, r["endMs"] - 100)
        else:
            r["endMs"] = max(value, r["startMs"] + 100)
        self._ranges[index] = r
        self._active_range = index
        self.ranges_changed.emit()
        self.active_range_changed.emit()
        self._record_range_snapshot()

    @Slot(int)
    def remove_range(self, index: int) -> None:
        if 0 <= index < len(self._ranges):
            del self._ranges[index]
            self._active_range = min(index, len(self._ranges) - 1)
            self.ranges_changed.emit()
            self.active_range_changed.emit()
            self._record_range_snapshot()

    def _reset_range_history(self) -> None:
        self._range_history = [[dict(item) for item in self._ranges]]
        self._history_index = 0
        self._range_editing = False
        self.history_changed.emit()

    def _record_range_snapshot(self) -> None:
        if self._range_editing:
            return
        current = [dict(item) for item in self._ranges]
        if self._range_history[self._history_index] == current:
            return
        self._range_history = self._range_history[:self._history_index + 1]
        self._range_history.append(current)
        if len(self._range_history) > 100:
            del self._range_history[0]
        self._history_index = len(self._range_history) - 1
        self.history_changed.emit()

    @Slot()
    def begin_range_edit(self) -> None:
        self._range_editing = True

    @Slot()
    def end_range_edit(self) -> None:
        if self._range_editing:
            self._range_editing = False
            self._record_range_snapshot()

    @Slot()
    def undo(self) -> None:
        if self.canUndo:
            self._history_index -= 1
            self._ranges = [dict(item) for item in self._range_history[self._history_index]]
            self._active_range = min(max(0, self._active_range), len(self._ranges) - 1)
            self.ranges_changed.emit()
            self.active_range_changed.emit()
            self.history_changed.emit()

    @Slot()
    def redo(self) -> None:
        if self.canRedo:
            self._history_index += 1
            self._ranges = [dict(item) for item in self._range_history[self._history_index]]
            self._active_range = min(max(0, self._active_range), len(self._ranges) - 1)
            self.ranges_changed.emit()
            self.active_range_changed.emit()
            self.history_changed.emit()

    @Slot()
    def clear_source(self) -> None:
        self._source_path = ""
        self._preview_path = ""
        self._source_url = QUrl()
        self._duration_ms = self._position_ms = 0
        self._ranges = []
        self._active_range = -1
        self._reset_range_history()
        self._status = "Choose a local video to begin."
        for signal in (self.source_path_changed, self.source_url_changed, self.duration_changed,
                       self.position_changed, self.ranges_changed, self.active_range_changed,
                       self.status_changed, self.source_in_library_changed, self.preview_changed):
            signal.emit()

    def set_rendered_preview(self, path: str) -> None:
        self._preview_path = str(Path(path).expanduser().resolve(strict=True))
        self.preview_changed.emit()

    @Slot(str)
    def open_source(self, path: str) -> None:
        self.source_requested.emit(path)


class StudioQmlPage(QWidget):
    """Embeddable, isolated QML media/timeline proof of concept."""

    task_progress = Signal(object)
    task_finished = Signal()
    render_requested = Signal(str, object)
    source_opened = Signal(str)
    cancel_requested = Signal()
    editor_settings_changed = Signal(str, str, str)
    discovery_requested = Signal(str, int)
    discovery_cancel_requested = Signal()
    candidate_review_requested = Signal(str, str)
    preview_requested = Signal(str, float, float)

    def __init__(self, accent_name: str = "violet", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StudioQmlPage")
        self._render_available = False
        self.view = QQuickWidget(self)
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.view.setClearColor(QColor(palette(accent_name)["bg"]))
        self.controller = StudioController(palette(accent_name), self)
        self.view.rootContext().setContextProperty("studioController", self.controller)
        self.view.rootContext().setContextProperty("studioPage", self)
        self.controller.seek_requested.connect(self._seek_player)
        self.controller.source_requested.connect(self.open_source)
        self.controller.candidate_review_requested.connect(self.candidate_review_requested)
        self.view.statusChanged.connect(self._on_qml_status)
        qml_path = resource_path("ui", "studio_qml", "qml", "Studio.qml")
        self.view.setSource(QUrl.fromLocalFile(str(qml_path)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def _on_qml_status(self, status: QQuickWidget.Status) -> None:
        if status == QQuickWidget.Status.Error:
            errors = "\n".join(error.toString() for error in self.view.errors())
            self.controller.set_status(f"Studio interface could not load: {errors}")

    def _seek_player(self, position_ms: int) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("requestedPosition", position_ms)

    def open_source(self, path: str) -> bool:
        """Open a real local file. Returns False and shows an error on failure."""
        try:
            self.controller.set_source(path)
            self.source_opened.emit(self.controller.sourcePath)
            return True
        except (OSError, ValueError) as exc:
            self.controller.set_status(f"Cannot open source: {exc}")
            return False

    @Slot()
    def choose_source(self) -> None:
        """Open a native file picker for local video sources."""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose a video source",
            "",
            "Video files (*.mp4 *.mkv *.mov *.webm *.avi *.m4v);;All files (*)",
        )
        if path:
            self.open_source(path)

    def set_sources(self, sources: list[dict[str, Any]]) -> None:
        """Supply catalog sources; accepted keys are path and optional title."""
        clean = []
        for item in sources:
            path = str(item.get("path", ""))
            if path:
                clean.append({"path": path, "title": str(item.get("title") or Path(path).name)})
        self.controller._sources = clean
        self.controller.sources_changed.emit()
        self.controller.source_in_library_changed.emit()

    def set_candidates(self, records: list[dict[str, Any]]) -> None:
        self.controller.set_candidates(records)

    def set_renderer_available(self, available: bool) -> None:
        """Enable the render action only when a host callback is connected."""
        self._render_available = bool(available)
        self.controller._render_available = self._render_available
        self.controller.render_available_changed.emit()

    def set_ranges(self, ranges) -> None:
        self.controller.set_ranges([[start, end] for start, end in ranges])

    def set_accent(self, accent_name: str) -> None:
        theme = palette(accent_name)
        self.view.setClearColor(QColor(theme["bg"]))
        self.controller.set_theme(theme)

    def set_editor_settings(self, layout: str, caption_style: str, model: str) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("outputLayout", layout)
            root.setProperty("captionStyle", caption_style)
            root.setProperty("speechModel", model)

    @Slot(str, str, str)
    def set_output_settings(self, layout: str, caption_style: str, model: str) -> None:
        self.editor_settings_changed.emit(layout, caption_style, model)

    def report_started(self) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("rendering", True)
        self.controller.set_status("Starting clip rendering…")

    @Slot(int)
    def find_highlights(self, count: int) -> None:
        if self.controller.sourceInLibrary and self.controller.sourcePath:
            self.discovery_requested.emit(self.controller.sourcePath, max(1, min(30, int(count))))

    @Slot()
    def cancel_highlight_search(self) -> None:
        self.discovery_cancel_requested.emit()

    def report_discovery_started(self) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("analyzing", True)
        self.controller.set_status("Analyzing video for highlight moments…")

    def report_discovery_finished(self, records: list[dict[str, Any]] | None = None, status: str = "") -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("analyzing", False)
        if records is not None:
            self.set_candidates(records)
        if status:
            self.controller.set_status(status)

    def request_render(self) -> None:
        """Emit an actual host request; this page never performs rendering."""
        source = self.controller.sourcePath
        if not self._render_available or not source:
            self.controller.set_status("Rendering is not connected in this host.")
            return
        ranges = [(r["startMs"] / 1000.0, r["endMs"] / 1000.0) for r in self.controller.ranges]
        self.render_requested.emit(source, ranges)

    @Slot()
    def request_preview(self) -> None:
        """Ask the host to render the active range using the production pipeline."""
        source = self.controller.sourcePath
        index = self.controller.activeRange
        ranges = self.controller.ranges
        if not self.controller.sourceInLibrary or not source:
            self.controller.set_status("Add this video to the Studio library before rendering a preview.")
            return
        if not 0 <= index < len(ranges):
            self.controller.set_status("Select a clip range before rendering a preview.")
            return
        item = ranges[index]
        self.preview_requested.emit(source, item["startMs"] / 1000.0, item["endMs"] / 1000.0)

    @Slot()
    def show_source_preview(self) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("renderedPreview", False)

    def show_rendered_preview(self, path: str) -> None:
        self.controller.set_rendered_preview(path)
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("renderedPreview", True)
            root.setProperty("playing", False)
            root.setProperty("requestedPosition", 0)
            root.setProperty("playing", True)

    def report_progress(self, event: object) -> None:
        """Forward progress from the real host worker without fabricating it."""
        self.task_progress.emit(event)
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("rendering", True)
        if isinstance(event, dict):
            self.controller.set_status(str(event.get("message") or "Rendering clips…"))

    def report_finished(self) -> None:
        self.task_finished.emit()
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("rendering", False)

    @Slot()
    def cancel_render(self) -> None:
        self.cancel_requested.emit()

    def shutdown(self) -> None:
        """Stop local playback and release the media source before host teardown."""
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("active", False)
            root.setProperty("playing", False)
            root.setProperty("requestedPosition", 0)
            root.setProperty("rendering", False)
        self.controller.clear_source()
        self.view.setSource(QUrl())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("active", True)

    def hideEvent(self, event) -> None:  # noqa: N802
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("active", False)
        self.controller.end_range_edit()
        super().hideEvent(event)
