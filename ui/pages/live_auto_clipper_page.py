"""Feature-flagged live monitoring UI; VOD controls and screens remain unchanged."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QTableWidget,
    QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

from core.settings_store import SettingsStore
from services.live_clipper.config import LiveClipperSettings
from ui.effects import apply_card_shadow
from ui.widgets.buttons import DangerGhostButton, GhostButton, PrimaryButton


class LiveAutoClipperPage(QWidget):
    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self._settings_store = settings_store
        self._live_settings = LiveClipperSettings()
        from services.live_clipper.process import LiveProcessController
        from services.live_clipper.store import LiveJobStore
        self._controller = LiveProcessController()
        self._store = LiveJobStore()
        self._rows: dict[str, int] = {}
        self._current_progress = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
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
        self.output_input.setText(str(Path.home() / "Videos" / "StreamCarnia Live Clips"))
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_input, 1)
        browse_output = GhostButton("Choose folder…")
        browse_output.clicked.connect(self._pick_output_dir)
        output_row.addWidget(browse_output)
        source.addWidget(self._label("Save live clips to"))
        source.addLayout(output_row)
        layout.addWidget(source_card)

        config_card, config = self._section("CLIP AND DETECTION SETTINGS")
        row = QHBoxLayout()
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
            row.addLayout(col, 1)
        config.addLayout(row)
        self.transcription_combo = QComboBox()
        for label, data in (("Small — faster", "small"), ("Medium — recommended", "medium"),
                            ("Large-v3 — best accuracy", "large-v3")):
            self.transcription_combo.addItem(label, data)
        self.transcription_combo.setToolTip(
            "Larger multilingual Whisper models usually improve Hindi recognition, but take more time and disk space the first time they are downloaded.")
        config.addWidget(self._label("Speech recognition quality"))
        config.addWidget(self.transcription_combo)
        schedule_row = QHBoxLayout()
        self.schedule_start = QTimeEdit()
        self.schedule_start.setDisplayFormat("HH:mm")
        self.schedule_end = QTimeEdit()
        self.schedule_end.setDisplayFormat("HH:mm")
        self.approve_check = QCheckBox("Approve before upload")
        self.approve_check.setChecked(True)
        schedule_row.addWidget(self._label("Publish window starts"))
        schedule_row.addWidget(self.schedule_start)
        schedule_row.addWidget(self._label("ends"))
        schedule_row.addWidget(self.schedule_end)
        schedule_row.addStretch(1)
        schedule_row.addWidget(self.approve_check)
        config.addLayout(schedule_row)
        layout.addWidget(config_card)

        job_card, job = self._section("LIVE JOB QUEUE")
        self.status_label = QLabel("Ready when you are.")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        job.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        job.addWidget(self.progress)
        self.queue = QTableWidget(0, 4)
        self.queue.setHorizontalHeaderLabels(["Clip", "State", "Scheduled", "Action"])
        self.queue.horizontalHeader().setStretchLastSection(True)
        self.queue.setEditTriggers(QTableWidget.NoEditTriggers)
        self.queue.setSelectionBehavior(QTableWidget.SelectRows)
        job.addWidget(self.queue)
        actions = QHBoxLayout()
        self.start_btn = PrimaryButton("Start monitoring")
        self.start_btn.clicked.connect(self._start)
        actions.addWidget(self.start_btn)
        self.stop_btn = DangerGhostButton("Stop monitoring")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        actions.addWidget(self.stop_btn)
        actions.addStretch(1)
        job.addLayout(actions)
        layout.addWidget(job_card)
        layout.addStretch(1)

        self._load_config()
        self._load_jobs()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll_worker)

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
        for combo, data in ((self.layout_combo, config.layout), (self.caption_combo, config.caption_style)):
            index = combo.findData(data)
            if index >= 0:
                combo.setCurrentIndex(index)
        model_index = self.transcription_combo.findData(config.transcription_model)
        if model_index >= 0:
            self.transcription_combo.setCurrentIndex(model_index)
        self.schedule_start.setTime(self.schedule_start.time().fromString(config.schedule_start, "HH:mm"))
        self.schedule_end.setTime(self.schedule_end.time().fromString(config.schedule_end, "HH:mm"))
        self.approve_check.setChecked(config.approve_before_upload)
        if config.output_dir:
            self.output_input.setText(config.output_dir)

    def _save_config(self, enabled=True):
        config = self._live_settings.update(
            enabled=enabled, max_clips_per_stream=self.max_clips.value(),
            clip_length_seconds=self.length.value(), threshold=self.threshold.value(),
            layout=self.layout_combo.currentData(), caption_style=self.caption_combo.currentData(),
            transcription_model=self.transcription_combo.currentData(),
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
            payload = {**config.__dict__, "stream_url": url,
                       "ffmpeg_path": self._settings_store.ffmpeg_path,
                       "output_dir": str(session), "buffer_dir": str(session / "buffer"),
                       "stream_name": self._stream_name(url)}
            payload.update({"enabled": True})
            app_settings = self._settings_store.get()
            payload.update({"language": app_settings.caption_language or "",
                            "channel_name": app_settings.clip_channel_name,
                            "subscriber_text": app_settings.clip_subscriber_text,
                            "logo_path": app_settings.clip_logo_path,
                            "facecam": app_settings.clip_facecam,
                            "pan_zoom": app_settings.clip_pan_zoom})
            self._controller.start(payload)
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
            elif kind in {"detected", "rendered", "titled", "scheduled", "uploaded", "clip_failed"}:
                self._upsert_row(event)
                if kind == "rendered":
                    self.status_label.setText("Highlight rendered through the existing VOD clip pipeline.")
                elif kind == "scheduled":
                    self.status_label.setText(f"Approved; scheduled for {event.get('scheduled_at')}.")
                elif kind == "clip_failed":
                    self.status_label.setText(f"Clip failed at {event.get('stage')}: {event.get('message')}")
            elif kind == "stream_ended":
                self.status_label.setText("Stream ended. Final buffered highlights are being completed.")
            elif kind == "stream_title":
                self.status_label.setText(f"Monitoring: {event.get('title', 'Live stream')}")
            elif kind in {"error", "crashed", "capture_error", "control_error", "upload_error", "chat_unavailable", "storage_error"}:
                self.status_label.setText(event.get("message", f"Live worker {kind}: {event.get('exit_code', '')}"))
            if kind == "stopped":
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
        if not self._controller.running and self.stop_btn.isEnabled():
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            if self._timer.isActive():
                self._timer.stop()

    def _load_jobs(self):
        try:
            for item in self._store.list_jobs()[-100:]:
                data = item["data"]
                self._upsert_row({"id": item["id"], "state": item["state"],
                                  "metadata": data.get("metadata", {}),
                                  "scheduled_at": data.get("scheduled_at"),
                                  "path": data.get("file_path")})
        except Exception as exc:
            self.status_label.setText(f"Could not read live job queue: {exc}")

    def _upsert_row(self, event: dict):
        job_id = event.get("id")
        if not job_id:
            return
        row = self._rows.get(job_id)
        if row is None:
            row = self.queue.rowCount()
            self.queue.insertRow(row)
            self._rows[job_id] = row
        metadata = event.get("metadata", {})
        title = metadata.get("title") or event.get("path") or "Live highlight"
        scheduled = event.get("scheduled_at") or ""
        state = event.get("state") or event.get("type", "detected")
        for column, value in enumerate((title, state, scheduled)):
            self.queue.setItem(row, column, QTableWidgetItem(str(value)))
        if state == "titled" and self.approve_check.isChecked():
            button = QPushButton("Approve & schedule")
            button.setObjectName("GhostButton")
            button.clicked.connect(lambda _checked=False, clip_id=job_id, control=button: self._approve(clip_id, control))
            self.queue.setCellWidget(row, 3, button)
        else:
            self.queue.removeCellWidget(row, 3)

    def _approve(self, job_id: str, button: QPushButton):
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
