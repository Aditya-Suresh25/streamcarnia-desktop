"""Feature-flagged live monitoring UI; VOD controls and screens remain unchanged."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from PySide6.QtCore import QTimer, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QMessageBox, QDoubleSpinBox, QHeaderView, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QTimeEdit,
    QVBoxLayout, QWidget,
)

from core.settings_store import SettingsStore
from services.live_clipper.config import LiveClipperSettings
from ui.effects import apply_card_shadow
from ui.widgets.buttons import DangerGhostButton, GhostButton, PrimaryButton
from ui.widgets.facecam_selector import FacecamSelector
from ui.widgets.stack_layout_control import StackLayoutControl
from ui.widgets.page_layout import configure_page_scroll


class LiveAutoClipperPage(QWidget):
    task_progress = Signal(object)
    task_finished = Signal()

    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self._settings_store = settings_store
        self._live_settings = LiveClipperSettings()
        from services.live_clipper.process import LiveProcessController
        from services.live_clipper.store import LiveJobStore
        self._controller = LiveProcessController()
        self._store = None
        self._rows: dict[str, int] = {}
        self._queue_data: dict[str, dict] = {}
        self._current_progress = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        configure_page_scroll(scroll, content)
        layout.setContentsMargins(32, 28, 32, 30)
        layout.setSpacing(16)

        eyebrow = QLabel("STREAMCARNIA STUDIO")
        eyebrow.setObjectName("Eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Auto Clipper (Live)")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Monitor a stream in the background and send detected moments through the existing VOD clipper.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        source_card, source = self._section("LIVE SOURCE")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        source.addWidget(self._label("Stream URL"))
        source.addWidget(self.url_input)
        self.output_input = QLineEdit()
        settings = self._settings_store.get()
        media_home = Path(settings.clip_output_dir or settings.download_dir).expanduser()
        self.output_input.setText(str(media_home / "StreamCarnia Live Clips"))
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_input, 1)
        browse_output = GhostButton("Choose folder…")
        browse_output.clicked.connect(self._pick_output_dir)
        output_row.addWidget(browse_output)
        source.addWidget(self._label("Save live clips to"))
        source.addLayout(output_row)
        monitor_actions = QHBoxLayout()
        self.start_btn = PrimaryButton("Start monitoring")
        self.start_btn.clicked.connect(self._start)
        monitor_actions.addWidget(self.start_btn)
        self.stop_btn = DangerGhostButton("Stop monitoring")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        monitor_actions.addWidget(self.stop_btn)
        monitor_actions.addStretch(1)
        source.addLayout(monitor_actions)
        layout.addWidget(source_card)

        config_card, config = self._section("CLIP AND DETECTION SETTINGS")
        row = QGridLayout()
        row.setHorizontalSpacing(12)
        row.setVerticalSpacing(10)
        self._clip_setting_columns = []
        self.max_clips = QSpinBox()
        self.max_clips.setRange(1, 100)
        self.length = QSpinBox()
        self.length.setRange(20, 60)
        self.length.setSuffix(" sec")
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.1, 20.0)
        self.threshold.setSingleStep(0.1)
        self.threshold.setDecimals(1)
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Blurred vertical background", "blur")
        self.layout_combo.addItem("Top facecam / bottom gameplay", "stack")
        self.layout_combo.addItem("Centered vertical crop", "center")
        self.layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        self.caption_combo = QComboBox()
        for label, data in (("Pop", "pop"), ("Bounce", "bounce"),
                            ("Word", "word"), ("Karaoke", "karaoke")):
            self.caption_combo.addItem(label, data)
        for label, control in (("Maximum clips / stream", self.max_clips),
                               ("Clip duration", self.length), ("Highlight threshold", self.threshold),
                               ("Portrait layout", self.layout_combo), ("Animated captions", self.caption_combo)):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(self._label(label))
            col.addWidget(control)
            self._clip_setting_columns.append(col)
        self._clip_settings_grid = row
        self._reflow_clip_settings(2 if self.width() < 1080 else 5)
        config.addLayout(row)

        self.facecam_row = QWidget()
        facecam_layout = QVBoxLayout(self.facecam_row)
        facecam_layout.setContentsMargins(0, 4, 0, 0)
        facecam_layout.setSpacing(6)
        facecam_layout.addWidget(self._label("Select the facecam area in the source frame"))
        self.facecam_selector = FacecamSelector(accent=self._settings_store.get().accent)
        facecam_layout.addWidget(self.facecam_selector)
        facecam_hint = QLabel("Drag the box to move it. Drag the lower-right handle to resize, or draw a new box on the frame.")
        facecam_hint.setObjectName("Faint")
        facecam_hint.setWordWrap(True)
        facecam_layout.addWidget(facecam_hint)
        self.facecam_input = QLineEdit("0.75,0.68,0.25,0.32")
        self.facecam_selector.coordinatesChanged.connect(self.facecam_input.setText)
        self.facecam_input.textChanged.connect(self.facecam_selector.setCoordinates)
        facecam_layout.addWidget(self.facecam_input)
        self.stack_layout = StackLayoutControl(accent=self._settings_store.get().accent)
        facecam_layout.addWidget(self.stack_layout)
        config.addWidget(self.facecam_row)
        self.facecam_row.hide()

        self.transcription_combo = QComboBox()
        for label, data in (("Small — faster", "small"), ("Medium — recommended", "medium"),
                            ("Large-v3 — best accuracy", "large-v3")):
            self.transcription_combo.addItem(label, data)
        self.transcription_combo.setToolTip(
            "Larger multilingual Whisper models usually improve Hindi recognition, but take more time and disk space the first time they are downloaded.")
        config.addWidget(self._label("Speech recognition quality"))
        config.addWidget(self.transcription_combo)
        layout.addWidget(config_card)

        publish_card, publish = self._section("PUBLISH & APPROVAL")
        publish_intro = QLabel("Choose when approved Shorts become public. Clips are uploaded privately ahead of their scheduled publish time.")
        publish_intro.setObjectName("Faint")
        publish_intro.setWordWrap(True)
        publish.addWidget(publish_intro)
        schedule_row = QGridLayout()
        self.schedule_start = QTimeEdit()
        self.schedule_start.setDisplayFormat("HH:mm")
        self.schedule_end = QTimeEdit()
        self.schedule_end.setDisplayFormat("HH:mm")
        self.approve_check = QCheckBox("Require approval before YouTube upload")
        self.approve_check.setChecked(True)
        schedule_row.addWidget(self._label("Publish window starts"), 0, 0)
        schedule_row.addWidget(self.schedule_start, 1, 0)
        schedule_row.addWidget(self._label("Publish window ends"), 0, 1)
        schedule_row.addWidget(self.schedule_end, 1, 1)
        schedule_row.addWidget(self.approve_check, 1, 2)
        schedule_row.setColumnStretch(2, 1)
        publish.addLayout(schedule_row)
        schedule_hint = QLabel("Approved clips are scheduled at up to 6 per hour (10-minute slots) within this window. YouTube's default project quota allows 100 uploads per day.")
        schedule_hint.setObjectName("Faint")
        schedule_hint.setWordWrap(True)
        publish.addWidget(schedule_hint)
        layout.addWidget(publish_card)

        job_card, job = self._section("LIVE JOB QUEUE")
        queue_header = QHBoxLayout()
        queue_header.addStretch(1)
        self.clear_queue_btn = DangerGhostButton("Clear queue & local files")
        self.clear_queue_btn.clicked.connect(self._clear_live_queue)
        queue_header.addWidget(self.clear_queue_btn)
        job.addLayout(queue_header)
        self.status_label = QLabel("Ready when you are.")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        job.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        job.addWidget(self.progress)
        self.queue = QTableWidget(0, 5)
        self.queue.setHorizontalHeaderLabels(["Preview", "Clip", "State", "Scheduled", "Action"])
        self.queue.horizontalHeader().setStretchLastSection(True)
        self.queue.setEditTriggers(QTableWidget.NoEditTriggers)
        self.queue.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue.setAlternatingRowColors(True)
        self.queue.setIconSize(QSize(128, 72))
        self.queue.verticalHeader().setVisible(False)
        self.queue.verticalHeader().setDefaultSectionSize(42)
        self.queue.setAccessibleName("Live Auto Clipper publishing queue")
        self.queue.setAccessibleDescription("Detected, rendered, titled, scheduled, and uploaded live clips")
        header = self.queue.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.queue.setColumnWidth(0, 140)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_empty = QLabel("No live clips in this queue yet. Start monitoring a stream to detect highlight moments.")
        self.queue_empty.setObjectName("Muted")
        self.queue_empty.setWordWrap(True)
        job.addWidget(self.queue_empty)
        job.addWidget(self.queue)
        layout.addWidget(job_card)
        layout.addStretch(1)

        self._load_config()
        self._set_store_for_media_root(Path(self.output_input.text()))
        self._load_jobs()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll_worker)

    def _reflow_clip_settings(self, columns: int) -> None:
        """Keep the five setting groups readable on compact laptop widths."""
        if not hasattr(self, "_clip_settings_grid"):
            return
        grid = self._clip_settings_grid
        while grid.count():
            grid.takeAt(0)
        columns = max(1, min(columns, len(self._clip_setting_columns)))
        for index, column in enumerate(self._clip_setting_columns):
            grid.addLayout(column, index // columns, index % columns)
        for column_index in range(max(grid.columnCount(), columns)):
            grid.setColumnStretch(column_index, 1 if column_index < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_clip_settings_grid"):
            self._reflow_clip_settings(2 if self.width() < 1080 else 5)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    @staticmethod
    def _section(title: str):
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(11)
        heading = QLabel(title)
        heading.setObjectName("Eyebrow")
        layout.addWidget(heading)
        apply_card_shadow(frame)
        return frame, layout

    def _load_config(self):
        config = self._live_settings.get()
        self.max_clips.setValue(config.max_clips_per_stream)
        self.length.setValue(config.clip_length_seconds)
        self.threshold.setValue(config.threshold)
        self.facecam_input.setText(config.facecam)
        self.stack_layout.setValue(config.stack_facecam_percent)
        for combo, data in ((self.layout_combo, config.layout), (self.caption_combo, config.caption_style)):
            index = combo.findData(data)
            if index >= 0:
                combo.setCurrentIndex(index)
        model_index = self.transcription_combo.findData(self._settings_store.get().transcription_model)
        if model_index >= 0:
            self.transcription_combo.setCurrentIndex(model_index)
        self.transcription_combo.currentIndexChanged.connect(self._on_transcription_model_changed)
        self.schedule_start.setTime(self.schedule_start.time().fromString(config.schedule_start, "HH:mm"))
        self.schedule_end.setTime(self.schedule_end.time().fromString(config.schedule_end, "HH:mm"))
        self.approve_check.setChecked(config.approve_before_upload)
        if config.output_dir:
            self.output_input.setText(config.output_dir)

    def _save_config(self, enabled=True):
        shared_model = self.transcription_combo.currentData()
        if shared_model in {"small", "medium", "large-v3"}:
            self._settings_store.update(transcription_model=shared_model)
        config = self._live_settings.update(
            enabled=enabled, max_clips_per_stream=self.max_clips.value(),
            clip_length_seconds=self.length.value(), threshold=self.threshold.value(),
            layout=self.layout_combo.currentData(), facecam=self.facecam_input.text().strip(),
            stack_facecam_percent=self.stack_layout.value(),
            caption_style=self.caption_combo.currentData(),
            transcription_model=shared_model,
            approve_before_upload=self.approve_check.isChecked(),
            schedule_start=self.schedule_start.time().toString("HH:mm"),
            schedule_end=self.schedule_end.time().toString("HH:mm"),
            output_dir=self.output_input.text().strip(),
        )
        return config

    def _pick_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Live Auto Clipper folder", self.output_input.text())
        if path:
            self.output_input.setText(path)
            self._set_store_for_media_root(Path(path))
            self._reload_jobs()

    def _set_store_for_media_root(self, media_root: Path):
        from services.live_clipper.store import LiveJobStore
        root = media_root.expanduser().resolve()
        state_dir = root / ".streamcarnia"
        self._store = LiveJobStore(state_dir / "live_jobs.sqlite3", migrate_legacy=True)
        self._media_root = root

    def _on_transcription_model_changed(self, index: int):
        model = self.transcription_combo.itemData(index)
        if model in {"small", "medium", "large-v3"}:
            self._settings_store.update(transcription_model=model)
            self._live_settings.update(transcription_model=model)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        index = self.transcription_combo.findData(self._settings_store.get().transcription_model)
        if index >= 0 and not self.transcription_combo.hasFocus():
            self.transcription_combo.setCurrentIndex(index)

    def _on_layout_changed(self, _index: int) -> None:
        self.facecam_row.setVisible(self.layout_combo.currentData() == "stack")

    def _start(self):
        url = self.url_input.text().strip()
        if not url.startswith(("https://", "http://")):
            self.status_label.setText("Enter a valid stream URL to start monitoring.")
            return
        try:
            config = self._save_config(True)
            if not self._settings_store.ffmpeg_path:
                raise RuntimeError("FFmpeg is unavailable. Restore the bundled FFmpeg before monitoring.")
            output_text = self.output_input.text().strip()
            if not output_text:
                raise RuntimeError("Choose an output folder before starting live monitoring.")
            base = Path(output_text).expanduser()
            session = base / datetime.now().strftime("%Y%m%d_%H%M%S")
            self._set_store_for_media_root(base)
            payload = {**config.__dict__, "stream_url": url,
                       "ffmpeg_path": self._settings_store.ffmpeg_path,
                       "output_dir": str(session), "buffer_dir": str(session / "buffer"),
                       "media_root": str(base.resolve()),
                       "runtime_root": str(base / ".streamcarnia" / "runtime"),
                       "queue_db_path": str(base / ".streamcarnia" / "live_jobs.sqlite3"),
                       "stream_name": self._stream_name(url)}
            payload.update({"enabled": True})
            app_settings = self._settings_store.get()
            payload.update({"language": app_settings.caption_language or "",
                            "channel_name": app_settings.clip_channel_name,
                            "subscriber_text": app_settings.clip_subscriber_text,
                            "logo_path": app_settings.clip_logo_path,
                            "pan_zoom": app_settings.clip_pan_zoom})
            self._controller.start(payload)
            self.task_progress.emit({"id": "live-monitor", "title": "Live stream monitor",
                                     "percent": 0, "message": "Connecting to live stream"})
            self.clear_queue_btn.setEnabled(False)
        except Exception as exc:
            self.status_label.setText(f"Could not start live monitor: {exc}")
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Starting isolated live monitor…")
        self._timer.start()

    def stop(self):
        if self._controller.running:
            self._controller.request_stop()
            self.status_label.setText("Stopping live monitor safely…")
            self.start_btn.setEnabled(False)
            return
        self._timer.stop()
        self.clear_queue_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Live monitoring stopped.")

    def shutdown(self):
        self._timer.stop()
        self._controller.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _poll_worker(self):
        for event in self._controller.poll():
            kind = event.get("type")
            if kind == "started":
                self.status_label.setText("Monitoring live stream. Captured segments rotate every five minutes.")
                self.task_progress.emit({"id": "live-monitor", "title": "Live stream monitor",
                                         "percent": 0, "message": "Monitoring active stream"})
            elif kind == "clip_progress":
                percent = int(event.get("percent", 0))
                self.progress.show()
                self.progress.setValue(percent)
                eta = event.get("eta_seconds")
                eta_text = self._format_eta(eta) if eta is not None else "calculating time remaining"
                self.status_label.setText(
                    f"Clip {event.get('clip', 1)} of {event.get('total', self.max_clips.value())} "
                    f"({percent}%) — {event.get('stage', 'working')}; time remaining: {eta_text}"
                )
                self.task_progress.emit({"id": "live-monitor", "title": "Live highlight render",
                                         "percent": percent, "message": event.get("stage", "Rendering clip")})
            elif kind in {"detected", "rendered", "titled", "scheduled", "uploaded", "clip_failed"}:
                self._upsert_row(event)
                if kind == "rendered":
                    self.status_label.setText("Highlight rendered through the existing VOD clip pipeline.")
                elif kind == "detected":
                    reason = event.get("reason", "audio/chat spike")
                    self.status_label.setText(f"Highlight detected from {reason} spike (score {event.get('score', '—')}).")
                elif kind == "titled" and event.get("fallback"):
                    self.status_label.setText("Clip titled with a fallback. " + event.get("fallback_reason", "Check Gemini key, transcript, and API access."))
                elif kind == "scheduled":
                    self.status_label.setText(f"Approved; scheduled for {event.get('scheduled_at')}.")
                elif kind == "clip_failed":
                    self.status_label.setText(f"Clip failed at {event.get('stage')}: {event.get('message')}")
            elif kind == "metadata_fallback":
                self.status_label.setText("Automatic title fallback: " + event.get("reason", "Gemini metadata unavailable"))
            elif kind == "stream_ended":
                self.status_label.setText("Stream ended. Final buffered highlights are being completed.")
            elif kind == "stream_title":
                self.status_label.setText(f"Monitoring: {event.get('title', 'Live stream')}")
            elif kind in {"error", "crashed", "capture_error", "control_error", "upload_error", "chat_unavailable", "storage_error"}:
                self.status_label.setText(event.get("message", f"Live worker {kind}: {event.get('exit_code', '')}"))
            if kind == "stopped":
                self.task_finished.emit()
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                self.clear_queue_btn.setEnabled(True)
        if not self._controller.running and self.stop_btn.isEnabled():
            self.task_finished.emit()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.clear_queue_btn.setEnabled(True)
            if self._timer.isActive():
                self._timer.stop()

    def _load_jobs(self):
        if self._store is None:
            return
        try:
            for item in self._store.list_jobs()[-100:]:
                data = item["data"]
                self._upsert_row({"id": item["id"], "state": item["state"],
                                  "metadata": data.get("metadata", {}),
                                  "scheduled_at": data.get("scheduled_at"),
                                  "path": data.get("file_path"),
                                  "thumbnail": data.get("thumbnail_path")})
        except Exception as exc:
            self.status_label.setText(f"Could not read live job queue: {exc}")

    def _reload_jobs(self):
        self.queue.setRowCount(0)
        self._rows.clear()
        self._queue_data.clear()
        self.queue_empty.show()
        self._load_jobs()

    def _clear_live_queue(self):
        if self._controller.running:
            self.status_label.setText("Stop live monitoring before clearing its queue and files.")
            return
        root = Path(self.output_input.text()).expanduser().resolve()
        expected_db = root / ".streamcarnia" / "live_jobs.sqlite3"
        if self._store is None or self._store.path.resolve() != expected_db.resolve():
            self._set_store_for_media_root(root)
            self._reload_jobs()
        answer = QMessageBox.question(
            self, "Clear Live Auto Clipper queue?",
            "This removes the live queue, rendered clip folders, captions, metadata, and buffered stream segments from the selected media folder.\n\nAlready uploaded YouTube videos are not affected. Shared Whisper model cache is kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        jobs = self._store.list_jobs() if self._store is not None else []
        session_dirs: set[Path] = set()
        for job in jobs:
            data = job.get("data", {})
            candidate = data.get("session_dir")
            if candidate:
                session_dirs.add(Path(candidate).expanduser())
            elif data.get("file_path"):
                file_path = Path(data["file_path"]).expanduser()
                candidate_path = file_path.parent.parent.parent
                session_dirs.add(candidate_path)
        removed = 0
        for candidate in session_dirs:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root)
                if resolved == root or not resolved.is_dir():
                    continue
                shutil.rmtree(resolved)
                removed += 1
            except (OSError, ValueError):
                continue

        runtime_dir = root / ".streamcarnia" / "runtime"
        if runtime_dir.is_dir():
            for child in runtime_dir.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink(missing_ok=True)
                except OSError:
                    continue
        count = self._store.clear_jobs() if self._store is not None else 0
        self._reload_jobs()
        self.status_label.setText(f"Cleared {count} live queue item(s) and {removed} local session folder(s).")

    def _upsert_row(self, event: dict):
        job_id = event.get("id")
        if not job_id:
            return
        row = self._rows.get(job_id)
        if row is None:
            row = self.queue.rowCount()
            self.queue.insertRow(row)
            self._rows[job_id] = row
        self.queue_empty.setVisible(self.queue.rowCount() == 0)
        previous = self._queue_data.get(job_id, {})
        previous.update({key: value for key, value in event.items() if value is not None})
        self._queue_data[job_id] = previous
        event = previous
        metadata = event.get("metadata", {})
        title = metadata.get("title") or event.get("path") or "Live highlight"
        scheduled = event.get("scheduled_at") or ""
        state = event.get("state") or event.get("type", "detected")
        if state == "titled" and event.get("fallback"):
            state = "titled (fallback)"
        preview = QTableWidgetItem()
        thumbnail_path = event.get("thumbnail") or event.get("thumbnail_path")
        if thumbnail_path and Path(thumbnail_path).is_file():
            pixmap = QPixmap(thumbnail_path)
            if not pixmap.isNull():
                preview.setIcon(QIcon(pixmap.scaled(128, 72, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)))
        self.queue.setItem(row, 0, preview)
        self.queue.setItem(row, 1, QTableWidgetItem(str(title)))
        self.queue.setItem(row, 2, QTableWidgetItem(str(state)))
        self.queue.setItem(row, 3, QTableWidgetItem(str(scheduled)))
        self.queue.setRowHeight(row, 82)
        if state.startswith("titled") and self.approve_check.isChecked():
            button = PrimaryButton("Review & schedule")
            button.clicked.connect(lambda _checked=False, clip_id=job_id, control=button: self._approve(clip_id, control))
            self.queue.setCellWidget(row, 4, button)
        else:
            self.queue.removeCellWidget(row, 4)

    def _approve(self, job_id: str, button: QPushButton):
        item = self._queue_data.get(job_id, {})
        metadata = item.get("metadata", {})
        dialog = QDialog(self)
        dialog.setWindowTitle("Review YouTube schedule")
        dialog.setObjectName("CardDialog")
        dialog.setMinimumWidth(460)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(24, 22, 24, 22)
        dialog_layout.setSpacing(14)
        heading = QLabel("Approve this Short")
        heading.setObjectName("CardTitle")
        dialog_layout.addWidget(heading)
        thumb = QLabel()
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setMinimumHeight(160)
        thumb.setObjectName("PreviewFrame")
        thumbnail_path = item.get("thumbnail") or item.get("thumbnail_path")
        if thumbnail_path and Path(thumbnail_path).is_file():
            pixmap = QPixmap(thumbnail_path)
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(360, 160, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        dialog_layout.addWidget(thumb)
        title = QLabel(metadata.get("title") or "Live highlight")
        title.setObjectName("FieldLabel")
        title.setWordWrap(True)
        dialog_layout.addWidget(title)
        schedule = QLabel(
            f"Publish window: {self.schedule_start.time().toString('HH:mm')}–{self.schedule_end.time().toString('HH:mm')}\n"
            "The next available 10-minute slot will be selected. The video is uploaded privately before it goes public."
        )
        schedule.setObjectName("Faint")
        schedule.setWordWrap(True)
        dialog_layout.addWidget(schedule)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        approve_btn = buttons.addButton("Approve & schedule", QDialogButtonBox.ButtonRole.AcceptRole)
        approve_btn.setObjectName("PrimaryButton")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        button.setEnabled(False)
        button.setText("Scheduling…")
        self._controller.send({"type": "approve", "job_id": job_id})

    @staticmethod
    def _stream_name(url: str) -> str:
        return url.rstrip("/").split("/")[-1][:80] or "Live stream"

    @staticmethod
    def _format_eta(seconds: int | None) -> str:
        if seconds is None:
            return "calculating"
        seconds = max(0, int(seconds))
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes} min {seconds} sec" if minutes else f"{seconds} sec"

    def close(self):
        self.shutdown()
        return super().close()
