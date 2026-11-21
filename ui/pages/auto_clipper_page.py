"""Native UI for configuring and running short-form stream clip jobs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThreadPool, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from core.settings_store import SettingsStore
from ui.effects import apply_card_shadow
from ui.widgets.buttons import DangerGhostButton, GhostButton, PrimaryButton
from ui.widgets.facecam_selector import FacecamSelector
from ui.widgets.stack_layout_control import StackLayoutControl
from ui.widgets.page_layout import configure_page_scroll
from workers.clip_worker import ClipWorker


class AutoClipperPage(QWidget):
    task_progress = Signal(object)
    task_finished = Signal()

    def __init__(self, settings_store: SettingsStore, cookies_provider, parent=None):
        super().__init__(parent)
        self._settings_store = settings_store
        self._cookies_provider = cookies_provider
        self._worker: ClipWorker | None = None
        self._output_dir: Path | None = None

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
        title = QLabel("Auto Clippr")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Turn a finished stream into vertical clips with captions and your branding.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        source_card, source = self._section("1  ·  VIDEO SOURCE")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        source.addWidget(self._field_label("Stream or VOD URL"))
        source.addWidget(self.url_input)
        source.addWidget(self._hint("Paste a video or finished livestream. For an active stream, use Auto Clipper (Live)."))
        layout.addWidget(source_card)

        edit_card, edit = self._section("2  ·  CLIP SETTINGS")
        row = QHBoxLayout()
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 20)
        self.count_spin.setValue(5)
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Blurred vertical background", "blur")
        self.layout_combo.addItem("Top facecam / bottom gameplay", "stack")
        self.layout_combo.addItem("Centered vertical crop", "center")
        self.layout_combo.addItem("Full horizontal gameplay", "landscape")
        self.layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        self.style_combo = QComboBox()
        self.style_combo.addItem("Pop", "pop")
        self.style_combo.addItem("Bounce", "bounce")
        self.style_combo.addItem("Word", "word")
        self.style_combo.addItem("Karaoke", "karaoke")
        for label, widget in (("Number of clips", self.count_spin), ("Video layout", self.layout_combo),
                              ("Animated captions", self.style_combo)):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(self._field_label(label))
            col.addWidget(widget)
            row.addLayout(col, 1)
        edit.addLayout(row)

        model_row = QHBoxLayout()
        model_col = QVBoxLayout()
        model_col.setSpacing(6)
        model_col.addWidget(self._field_label("Speech recognition quality"))
        self.model_combo = QComboBox()
        for label, value in (("Small — faster", "small"), ("Medium — recommended", "medium"),
                             ("Large-v3 — best accuracy", "large-v3")):
            self.model_combo.addItem(label, value)
        self.model_combo.setToolTip("This setting is shared with Auto Clipper (Live).")
        self.model_combo.currentIndexChanged.connect(self._persist_transcription_model)
        model_col.addWidget(self.model_combo)
        model_row.addLayout(model_col, 1)
        model_row.addStretch(2)
        edit.addLayout(model_row)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("AdvancedToggle")
        self.advanced_toggle.setText("More options  ·  language, facecam, motion & branding")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._set_advanced_options)
        edit.addWidget(self.advanced_toggle)

        self.advanced_panel = QFrame()
        self.advanced_panel.setObjectName("CardAlt")
        self._advanced_layout = QVBoxLayout(self.advanced_panel)
        self._advanced_layout.setContentsMargins(14, 14, 14, 14)
        self._advanced_layout.setSpacing(12)
        edit.addWidget(self.advanced_panel)
        self.advanced_panel.hide()

        lang_row = QHBoxLayout()
        lang_col = QVBoxLayout()
        lang_col.setSpacing(6)
        lang_col.addWidget(self._field_label("Caption language"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Auto detect", "")
        for label, code in [("English", "en"), ("Hindi", "hi"), ("Spanish", "es"),
                            ("Portuguese", "pt"), ("French", "fr"), ("German", "de"),
                            ("Japanese", "ja"), ("Korean", "ko"), ("Arabic", "ar"),
                            ("Other…", "other")]:
            self.language_combo.addItem(label, code)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_col.addWidget(self.language_combo)
        lang_row.addLayout(lang_col, 1)
        self.other_language = QLineEdit()
        self.other_language.setPlaceholderText("Whisper language code, e.g. te")
        self.other_language.hide()
        lang_row.addWidget(self.other_language, 1)
        self._advanced_layout.addLayout(lang_row)

        self.facecam_row = QWidget()
        face_layout = QVBoxLayout(self.facecam_row)
        face_layout.setContentsMargins(0, 4, 0, 0)
        face_layout.setSpacing(6)
        face_layout.addWidget(self._field_label("Select the facecam area in the source frame"))
        accent = self._settings_store.get().accent
        self.facecam_selector = FacecamSelector(accent=accent)
        face_layout.addWidget(self.facecam_selector)
        face_layout.addWidget(self._hint("Drag the box to move it. Drag the lower-right handle to resize, or drag on the frame to draw a new box."))
        face_layout.addWidget(self._field_label("Position and size (x, y, width, height)"))
        self.facecam_input = QLineEdit("0.75,0.68,0.25,0.32")
        self.facecam_selector.coordinatesChanged.connect(self.facecam_input.setText)
        self.facecam_input.textChanged.connect(self.facecam_selector.setCoordinates)
        face_layout.addWidget(self.facecam_input)
        self.stack_layout = StackLayoutControl(accent=accent)
        face_layout.addWidget(self.stack_layout)
        self._advanced_layout.addWidget(self.facecam_row)
        self.facecam_row.hide()

        self.pan_zoom_check = QCheckBox("Add gentle pan and zoom across selected highlight moments")
        self._advanced_layout.addWidget(self.pan_zoom_check)
        layout.addWidget(edit_card)

        brand_card, brand = self._section("SHORTS BRANDING")
        brand.addWidget(self._hint("Optional lower third. Subscriber text is entered by you and is not fetched from the channel."))
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("Channel name")
        brand.addWidget(self.channel_input)
        self.subscriber_input = QLineEdit()
        self.subscriber_input.setPlaceholderText("Subscriber text, e.g. 25K subscribers")
        brand.addWidget(self.subscriber_input)
        logo_row = QHBoxLayout()
        self.logo_input = QLineEdit()
        self.logo_input.setPlaceholderText("Optional PNG/JPG logo path")
        logo_row.addWidget(self.logo_input, 1)
        pick_logo = GhostButton("Choose logo…")
        pick_logo.clicked.connect(self._pick_logo)
        logo_row.addWidget(pick_logo)
        brand.addLayout(logo_row)
        self._advanced_layout.addWidget(brand_card)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#f87171; font-size:12px; font-weight:500;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        job_card, job = self._section("CLIP JOB")
        self.status_label = QLabel("Ready when you are.")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        job.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        job.addWidget(self.progress)
        self.output_list = QVBoxLayout()
        job.addLayout(self.output_list)
        actions = QHBoxLayout()
        self.start_btn = PrimaryButton("Generate clips")
        self.start_btn.clicked.connect(self._start)
        actions.addWidget(self.start_btn)
        self.cancel_btn = DangerGhostButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.hide()
        actions.addWidget(self.cancel_btn)
        self.open_folder_btn = GhostButton("Open clips folder")
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.open_folder_btn.hide()
        actions.addWidget(self.open_folder_btn)
        actions.addStretch(1)
        job.addLayout(actions)
        layout.addWidget(job_card)
        layout.addStretch(1)
        self._load_preferences()
        self._restore_latest_job()

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Faint")
        label.setWordWrap(True)
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

    def _on_layout_changed(self, _index: int) -> None:
        self.facecam_row.setVisible(self.layout_combo.currentData() == "stack")
        if self.layout_combo.currentData() == "stack":
            self.advanced_toggle.setChecked(True)

    def _set_advanced_options(self, expanded: bool) -> None:
        self.advanced_panel.setVisible(expanded)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _on_language_changed(self, _index: int) -> None:
        self.other_language.setVisible(self.language_combo.currentData() == "other")

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose channel logo", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.logo_input.setText(path)

    def _load_preferences(self) -> None:
        settings = self._settings_store.get()
        self.count_spin.setValue(max(1, min(20, int(settings.clip_count))))
        for combo, value in ((self.layout_combo, settings.clip_layout),
                             (self.style_combo, settings.caption_style)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        model_index = self.model_combo.findData(settings.transcription_model)
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)
        language_index = self.language_combo.findData(settings.caption_language)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)
        elif settings.caption_language:
            self.language_combo.setCurrentIndex(self.language_combo.findData("other"))
            self.other_language.setText(settings.caption_language)
        self.pan_zoom_check.setChecked(settings.clip_pan_zoom)
        self.facecam_input.setText(settings.clip_facecam)
        self.stack_layout.setValue(settings.clip_stack_facecam_percent)
        self.channel_input.setText(settings.clip_channel_name)
        self.subscriber_input.setText(settings.clip_subscriber_text)
        self.logo_input.setText(settings.clip_logo_path)

    def _restore_latest_job(self) -> None:
        settings = self._settings_store.get()
        base = Path(settings.clip_output_dir or settings.download_dir) / "StreamCarnia Clips"
        if not base.is_dir():
            return
        jobs = sorted((item for item in base.iterdir() if item.is_dir()), reverse=True)
        for job in jobs:
            clips_file = job / "clips.json"
            if not clips_file.is_file():
                continue
            try:
                entries = json.loads(clips_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            try:
                summary = json.loads((job / "job_summary.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summary = {}
            self._output_dir = job
            self._display_job_result(entries, summary, f"Most recent job · {job.name}")
            self.open_folder_btn.show()
            return

    def _validate(self) -> tuple[dict | None, str | None]:
        url = self.url_input.text().strip()
        if not url.startswith(("https://", "http://")):
            return None, "Enter a valid stream or VOD URL."
        layout = self.layout_combo.currentData()
        facecam = None
        if layout == "stack":
            try:
                coords = [float(value.strip()) for value in self.facecam_input.text().split(",")]
                if len(coords) != 4 or any(value < 0 or value > 1 for value in coords):
                    raise ValueError
                x, y, width, height = coords
                if width == 0 or height == 0 or x + width > 1 or y + height > 1:
                    raise ValueError
                facecam = ",".join(str(value) for value in coords)
            except ValueError:
                return None, "Facecam position needs four valid frame fractions (x,y,width,height) within 0–1."
        logo = self.logo_input.text().strip()
        if logo and (not Path(logo).is_file() or Path(logo).suffix.lower() not in {".png", ".jpg", ".jpeg"}):
            return None, "Choose an existing PNG or JPG logo file."
        language = self.language_combo.currentData()
        if language == "other":
            language = self.other_language.text().strip()
            if not language:
                return None, "Enter a language code or select Auto detect."
        return {
            "url": url, "count": self.count_spin.value(), "layout": layout,
            "style": self.style_combo.currentData(), "language": language or None,
            "model": self.model_combo.currentData(),
            "facecam": facecam, "stack_facecam_percent": self.stack_layout.value(),
            "pan_zoom": self.pan_zoom_check.isChecked(),
            "channel_name": self.channel_input.text().strip(),
            "subscriber_text": self.subscriber_input.text().strip(), "logo_path": logo or None,
        }, None

    def _start(self) -> None:
        options, error = self._validate()
        if error:
            self.error_label.setText(error)
            self.error_label.show()
            return
        if not self._settings_store.ffmpeg_path:
            self.error_label.setText("FFmpeg is unavailable. Restore the bundled FFmpeg or install it, then retry.")
            self.error_label.show()
            return
        settings = self._settings_store.get()
        initial = settings.clip_output_dir or settings.download_dir
        chosen = QFileDialog.getExistingDirectory(self, "Choose where to save these clips", initial)
        if not chosen:
            return
        self.error_label.hide()
        self._clear_outputs()
        base = Path(chosen) / "StreamCarnia Clips"
        self._output_dir = base / datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            try:
                cookies_path = self._cookies_provider(chosen)
            except TypeError:
                cookies_path = self._cookies_provider()
        except Exception as exc:  # noqa: BLE001
            self.error_label.setText(f"Could not use the configured YouTube cookies: {exc}")
            self.error_label.show()
            return
        if cookies_path:
            options["cookies"] = cookies_path
        language = options["language"] or ""
        self._settings_store.update(
            clip_count=options["count"], clip_layout=options["layout"],
            caption_style=options["style"], caption_language=language,
            clip_pan_zoom=options["pan_zoom"], clip_facecam=self.facecam_input.text().strip(),
            clip_stack_facecam_percent=options["stack_facecam_percent"],
            clip_channel_name=options["channel_name"],
            clip_subscriber_text=options["subscriber_text"],
            clip_logo_path=options["logo_path"] or "",
            clip_output_dir=chosen,
            transcription_model=options["model"],
        )
        options["media_root"] = chosen
        self._worker = ClipWorker(options, self._output_dir, self._settings_store.ffmpeg_path)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)
        self.start_btn.setEnabled(False)
        self.cancel_btn.show()
        self.progress.show()
        self.progress.setValue(0)
        self.status_label.setText("Starting clip pipeline…")
        QThreadPool.globalInstance().start(self._worker)

    def _on_progress(self, event) -> None:
        if isinstance(event, dict):
            percent = int(event.get("percent", 0))
            self.progress.setValue(percent)
            clip, total = event.get("clip", 0), event.get("total", 0)
            prefix = f"{clip} of {total} · " if clip and total else ""
            eta = event.get("eta_seconds")
            eta_text = "Estimating time remaining" if eta is None else (f"Time remaining: ~{max(1, (eta + 59) // 60)} min" if eta >= 60 else f"Time remaining: ~{eta} sec")
            self.status_label.setText(f"{prefix}{percent}% · {event.get('message', 'Working')} · {eta_text}")
            self.task_progress.emit({"id": "auto-clippr", "title": "Auto Clippr render",
                                     "percent": percent, "message": event.get("message", "Rendering clips")})
        else:
            self.status_label.setText(str(event))

    def _on_finished(self, payload) -> None:
        if isinstance(payload, dict):
            entries = payload.get("clips", [])
            summary = payload.get("summary", {})
            fatal_error = payload.get("fatal_error")
        else:  # support results from an older worker during a live app upgrade
            try:
                entries = json.loads(payload) if isinstance(payload, str) else payload
            except (json.JSONDecodeError, TypeError):
                entries = []
            summary = {}
            fatal_error = None
        self._set_idle()
        self._display_job_result(entries, summary)
        if fatal_error:
            self.error_label.setText(fatal_error)
            self.error_label.show()
        if self._output_dir and self._output_dir.exists():
            self.open_folder_btn.show()

    def _display_job_result(self, entries: list, summary: dict, prefix: str = "") -> None:
        failures = summary.get("failed", []) or []
        requested = summary.get("requested", len(entries) + len(failures))
        status = summary.get("status", "complete")
        if status == "partial":
            message = f"Partial result: {len(entries)} of {requested} clips generated; {len(failures)} failed."
        elif status == "failed":
            message = f"Clip job failed: {len(failures)} clip(s) failed; {len(entries)} successful output(s) retained."
        else:
            message = f"Finished. Generated {len(entries)} clip(s)."
        self.status_label.setText(f"{prefix}: {message}" if prefix else message)
        for entry in entries:
            path = Path(entry.get("file", ""))
            row = QLabel(f"Clip {entry.get('rank', '')}: {path.name}  ·  {entry.get('duration', 0)} sec")
            row.setObjectName("Muted")
            row.setWordWrap(True)
            self.output_list.addWidget(row)
        if failures:
            details = "\n".join(
                f"Clip {item.get('rank', '?')} · {item.get('stage', 'processing')}: "
                f"{item.get('error_type', 'Error')}: {item.get('message', 'Unknown error')}"
                for item in failures
            )
            self.error_label.setText(details)
            self.error_label.show()
        else:
            self.error_label.hide()

    def _on_failed(self, message: str) -> None:
        self._set_idle()
        self.status_label.setText("Clip job failed.")
        self.error_label.setText(message)
        self.error_label.show()

    def _on_cancelled(self) -> None:
        self._set_idle()
        self.status_label.setText("Clip job cancelled.")

    def _set_idle(self) -> None:
        self._worker = None
        self.task_finished.emit()
        self.start_btn.setEnabled(True)
        self.cancel_btn.hide()
        self.progress.hide()

    def _clear_outputs(self) -> None:
        while self.output_list.count():
            item = self.output_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.open_folder_btn.hide()

    def _open_folder(self) -> None:
        if self._output_dir and self._output_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def cancel(self) -> None:
        if self._worker:
            self.status_label.setText("Cancelling clip job…")
            self._worker.cancel()

    def _persist_transcription_model(self, index: int) -> None:
        model = self.model_combo.itemData(index)
        if model in {"small", "medium", "large-v3"}:
            self._settings_store.update(transcription_model=model)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        index = self.model_combo.findData(self._settings_store.get().transcription_model)
        if index >= 0 and not self.model_combo.hasFocus():
            self.model_combo.setCurrentIndex(index)
