"""Main 'paste URL -> analyze -> pick quality -> download' page. Ported
from the web app's Home.jsx + UrlInput.jsx."""
from __future__ import annotations

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from backend.models.schemas import AnalyzeResponse, ContainerPreference

from core.cookies import CookieExtractionError, resolve_cookies_path
from core.queue_manager import QueueManager
from core.settings_store import SettingsStore
from ui.effects import apply_card_shadow
from ui.widgets.buttons import PrimaryButton
from ui.widgets.quality_list import QualityList
from ui.widgets.video_info_card import VideoInfoCard
from workers.analyze_worker import AnalyzeWorker


class HomePage(QWidget):
    toast = Signal(str, str)  # message, kind
    download_started = Signal()

    def __init__(self, settings_store: SettingsStore, queue_manager: QueueManager, parent=None):
        super().__init__(parent)
        self._settings_store = settings_store
        self._queue_manager = queue_manager
        self._current_info: AnalyzeResponse | None = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)
        layout.setAlignment(layout.alignment())

        eyebrow = QLabel("STREAMCARNIA")
        eyebrow.setObjectName("Eyebrow")
        layout.addWidget(eyebrow)

        title = QLabel("Don't let good streams fade with time..")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("Paste a link below to get started 👇")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        input_card = QFrame()
        input_card.setObjectName("Card")
        input_layout = QHBoxLayout(input_card)
        input_layout.setContentsMargins(14, 14, 14, 14)
        input_layout.setSpacing(10)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.returnPressed.connect(self._on_analyze_clicked)
        input_layout.addWidget(self.url_input, 1)

        self.analyze_btn = PrimaryButton("Analyze")
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        input_layout.addWidget(self.analyze_btn)

        layout.addWidget(input_card)
        apply_card_shadow(input_card)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#f87171; font-size:12px; font-weight:500;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.video_info = VideoInfoCard()
        layout.addWidget(self.video_info)

        quality_section = QFrame()
        quality_section.setObjectName("Card")
        quality_layout = QVBoxLayout(quality_section)
        quality_layout.setContentsMargins(14, 14, 14, 14)
        quality_layout.setSpacing(10)

        q_header = QLabel("QUALITY")
        q_header.setObjectName("Eyebrow")
        quality_layout.addWidget(q_header)

        self.quality_list = QualityList()
        quality_layout.addWidget(self.quality_list)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Container:"))
        self.container_combo = QComboBox()
        self.container_combo.addItems(["Auto", "MP4", "MKV", "WEBM"])
        options_row.addWidget(self.container_combo)
        options_row.addStretch(1)

        self.download_btn = PrimaryButton("Download")
        self.download_btn.clicked.connect(self._on_download_clicked)
        options_row.addWidget(self.download_btn)
        quality_layout.addLayout(options_row)

        quality_section.hide()
        self.quality_section = quality_section
        layout.addWidget(quality_section)
        apply_card_shadow(quality_section)

        layout.addStretch(1)

        self._pool = QThreadPool.globalInstance()

    # --- actions ---------------------------------------------------------

    def _on_analyze_clicked(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            return
        self.error_label.hide()
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("Analyzing...")
        self.video_info.clear()
        self.quality_section.hide()

        try:
            cookies_path = resolve_cookies_path(self._settings_store.get())
        except CookieExtractionError as exc:
            self._on_analyze_failed(str(exc))
            return

        worker = AnalyzeWorker(
            url=url,
            ffmpeg_path=self._settings_store.ffmpeg_path,
            cookies_path=cookies_path,
        )
        worker.signals.succeeded.connect(self._on_analyze_succeeded)
        worker.signals.failed.connect(self._on_analyze_failed)
        self._pool.start(worker)

    def _on_analyze_succeeded(self, info: AnalyzeResponse) -> None:
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("Analyze")
        self._current_info = info
        self.video_info.set_info(info)
        self.quality_list.set_options(info.formats)
        self.quality_section.show()

    def _on_analyze_failed(self, message: str) -> None:
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("Analyze")
        self.error_label.setText(message)
        self.error_label.show()

    def _on_download_clicked(self) -> None:
        if not self._current_info:
            return
        option = self.quality_list.selected_option()
        if not option:
            return

        container_map = {
            "Auto": ContainerPreference.AUTO,
            "MP4": ContainerPreference.MP4,
            "MKV": ContainerPreference.MKV,
            "WEBM": ContainerPreference.WEBM,
        }
        container = container_map[self.container_combo.currentText()]

        current_default = self._settings_store.get().download_dir
        chosen_dir = QFileDialog.getExistingDirectory(
            self, "Choose where to save this download", current_default
        )
        if not chosen_dir:
            return  # user cancelled the picker; don't start the download

        self._settings_store.update(container=container.value, download_dir=chosen_dir)

        self._queue_manager.enqueue(
            url=self._current_info.webpage_url,
            format_selector=option.format_selector,
            quality_key=option.key,
            title=self._current_info.title,
            channel=self._current_info.channel,
            format_label=option.label,
            download_dir=chosen_dir,
        )
        self.toast.emit(f'Added "{self._current_info.title}" to the queue', "success")
        self.download_started.emit()
