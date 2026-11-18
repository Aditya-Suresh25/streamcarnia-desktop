"""Settings: download directory, container, concurrency, cookies, theme,
and FFmpeg/yt-dlp status -- ported from the web app's Settings.jsx /
SettingsPage.jsx."""
from __future__ import annotations

import yt_dlp
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from backend.services.ffmpeg_service import get_ffmpeg_status

from core.settings_store import (
    COOKIE_MODE_BROWSER, COOKIE_MODE_FILE, COOKIE_MODE_NONE,
    SUPPORTED_COOKIE_BROWSERS, SettingsStore,
)
from services.live_clipper.config import LiveClipperSettings
from ui.effects import apply_card_shadow
from ui.theme import ACCENT_PRESETS, palette
from ui.widgets.buttons import GhostButton, PrimaryButton

APP_VERSION = "1.0.0"
COPYRIGHT_LINE = "\u00a9 Aditya Suresh. All rights reserved."


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.HLine)
    return line


def _section(title: str) -> tuple[QFrame, QVBoxLayout, QFrame]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 20)
    layout.setSpacing(14)

    header_row = QHBoxLayout()
    header_row.setSpacing(8)
    mark = QFrame()
    mark.setFixedSize(18, 2)
    mark.setObjectName("EyebrowMark")
    header_row.addWidget(mark)
    header = QLabel(title)
    header.setObjectName("Eyebrow")
    header_row.addWidget(header)
    header_row.addStretch(1)
    layout.addLayout(header_row)

    apply_card_shadow(frame, blur=26, y_offset=10, alpha=110)
    return frame, layout, mark


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    queue_settings_changed = Signal()

    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self._settings_store = settings_store
        self._live_settings = LiveClipperSettings()
        self._eyebrow_marks: list[QFrame] = []

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(20)

        eyebrow = QLabel("PREFERENCES")
        eyebrow.setObjectName("Eyebrow")
        layout.addWidget(eyebrow)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        layout.addWidget(self._build_downloads_section())
        layout.addWidget(self._build_cookies_section())
        layout.addWidget(self._build_appearance_section())
        layout.addWidget(self._build_live_clipper_section())
        layout.addWidget(self._build_status_section())
        layout.addWidget(self._build_about_section())
        layout.addStretch(1)

        self._load_from_settings()
        self._apply_mark_color()

    # --- sections ----------------------------------------------------

    def _build_downloads_section(self) -> QFrame:
        frame, layout, mark = _section("DOWNLOADS")
        self._eyebrow_marks.append(mark)

        layout.addWidget(_field_label("Download folder"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_input = QLineEdit()
        dir_row.addWidget(self.dir_input, 1)
        browse_btn = GhostButton("Browse...")
        browse_btn.clicked.connect(self._pick_download_dir)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        note = QLabel(
            "You'll also be asked to confirm (or change) this location "
            "each time you start a new download."
        )
        note.setObjectName("Faint")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(_divider())

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        col_a = QVBoxLayout()
        col_a.setSpacing(6)
        col_a.addWidget(_field_label("Container"))
        self.container_combo = QComboBox()
        self.container_combo.addItems(["Auto", "MP4", "MKV", "WEBM"])
        col_a.addWidget(self.container_combo)
        row2.addLayout(col_a)

        col_b = QVBoxLayout()
        col_b.setSpacing(6)
        col_b.addWidget(_field_label("Concurrent downloads"))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 5)
        col_b.addWidget(self.concurrency_spin)
        row2.addLayout(col_b)
        row2.addStretch(1)
        layout.addLayout(row2)

        save_btn = PrimaryButton("Save")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        return frame

    def _build_cookies_section(self) -> QFrame:
        frame, layout, mark = _section("COOKIES / SIGN-IN")
        self._eyebrow_marks.append(mark)
        note = QLabel(
            "Some videos require sign-in. Use cookies from a browser you're "
            "already signed into YouTube with, or point to a cookies.txt "
            "file. Cookie contents are never logged or transmitted."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(_field_label("Source"))
        mode_row = QHBoxLayout()
        self.cookie_mode_combo = QComboBox()
        self.cookie_mode_combo.addItems(["None", "Browser", "cookies.txt file"])
        self.cookie_mode_combo.currentIndexChanged.connect(self._on_cookie_mode_changed)
        mode_row.addWidget(self.cookie_mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.browser_row = QWidget()
        browser_row_layout = QVBoxLayout(self.browser_row)
        browser_row_layout.setContentsMargins(0, 4, 0, 0)
        browser_row_layout.setSpacing(6)
        browser_row_layout.addWidget(_field_label("Browser"))
        browser_combo_row = QHBoxLayout()
        self.browser_combo = QComboBox()
        self.browser_combo.addItems([b.title() for b in SUPPORTED_COOKIE_BROWSERS])
        browser_combo_row.addWidget(self.browser_combo)
        browser_combo_row.addStretch(1)
        browser_row_layout.addLayout(browser_combo_row)
        layout.addWidget(self.browser_row)

        self.cookie_file_row = QWidget()
        file_row_layout = QVBoxLayout(self.cookie_file_row)
        file_row_layout.setContentsMargins(0, 4, 0, 0)
        file_row_layout.setSpacing(6)
        file_row_layout.addWidget(_field_label("cookies.txt file"))
        file_pick_row = QHBoxLayout()
        file_pick_row.setSpacing(8)
        self.cookie_file_input = QLineEdit()
        file_pick_row.addWidget(self.cookie_file_input, 1)
        pick_btn = GhostButton("Browse...")
        pick_btn.clicked.connect(self._pick_cookie_file)
        file_pick_row.addWidget(pick_btn)
        file_row_layout.addLayout(file_pick_row)
        layout.addWidget(self.cookie_file_row)

        save_btn = PrimaryButton("Save")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        return frame

    def _build_appearance_section(self) -> QFrame:
        frame, layout, mark = _section("APPEARANCE")
        self._eyebrow_marks.append(mark)
        layout.addWidget(_field_label("Accent color"))
        row = QHBoxLayout()
        self.accent_combo = QComboBox()
        self.accent_combo.addItems([name.title() for name in ACCENT_PRESETS.keys()])
        self.accent_combo.currentTextChanged.connect(self._on_accent_changed)
        row.addWidget(self.accent_combo)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    def _build_live_clipper_section(self) -> QFrame:
        frame, layout, mark = _section("LIVE AUTO CLIPPER")
        self._eyebrow_marks.append(mark)
        self.live_enabled = QCheckBox("Enable Live Auto Clipper")
        self.live_enabled.setObjectName("FieldLabel")
        layout.addWidget(self.live_enabled)
        note = QLabel("Optional live monitoring is off by default. Enabling it adds the live monitor to StreamCarnia.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        layout.addWidget(note)
        save_btn = PrimaryButton("Save Live Settings")
        save_btn.clicked.connect(self._save_live_settings)
        layout.addWidget(save_btn)
        return frame

    def _build_status_section(self) -> QFrame:
        frame, layout, mark = _section("SYSTEM STATUS")
        self._eyebrow_marks.append(mark)
        ffmpeg_status = get_ffmpeg_status(self._settings_store.ffmpeg_path)
        if ffmpeg_status.installed and ffmpeg_status.version:
            ffmpeg_text = f"FFmpeg  \u2014  bundled, v{ffmpeg_status.version}"
        elif ffmpeg_status.installed:
            ffmpeg_text = "FFmpeg  \u2014  available"
        else:
            ffmpeg_text = "FFmpeg  \u2014  not found"
        ffmpeg_label = QLabel(ffmpeg_text)
        ffmpeg_label.setObjectName("Muted")
        layout.addWidget(ffmpeg_label)

        ytdlp_label = QLabel(f"yt-dlp  \u2014  v{yt_dlp.version.__version__}")
        ytdlp_label.setObjectName("Muted")
        layout.addWidget(ytdlp_label)
        return frame

    def _build_about_section(self) -> QFrame:
        frame, layout, mark = _section("ABOUT")
        self._eyebrow_marks.append(mark)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel("StreamCarnia Desktop")
        name.setStyleSheet(
            "font-family: 'Space Grotesk'; font-weight:700; font-size:14px; color:#f4f6fb;"
        )
        name_row.addWidget(name)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("Faint")
        name_row.addWidget(version)
        name_row.addStretch(1)
        layout.addLayout(name_row)

        copyright_label = QLabel(COPYRIGHT_LINE)
        copyright_label.setObjectName("Muted")
        layout.addWidget(copyright_label)

        blurb = QLabel(
            "This application and its source are the original work of "
            "Aditya Suresh. Unauthorized copying, redistribution, or "
            "resale is prohibited."
        )
        blurb.setObjectName("Faint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)
        return frame

    # --- behavior ------------------------------------------------------

    def _pick_download_dir(self) -> None:
        current = self.dir_input.text() or str(self._settings_store.get().download_dir)
        path = QFileDialog.getExistingDirectory(self, "Choose download folder", current)
        if path:
            self.dir_input.setText(path)

    def _pick_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose cookies.txt", "", "Text files (*.txt);;All files (*)")
        if path:
            self.cookie_file_input.setText(path)

    def _on_cookie_mode_changed(self, index: int) -> None:
        self.browser_row.setVisible(index == 1)
        self.cookie_file_row.setVisible(index == 2)

    def _on_accent_changed(self, text: str) -> None:
        self.theme_changed.emit(text.lower())
        self._apply_mark_color()

    def _apply_mark_color(self) -> None:
        accent = palette(self._settings_store.get().accent)["accent_hover"]
        for mark in self._eyebrow_marks:
            mark.setStyleSheet(f"background-color:{accent}; border-radius:1px;")

    def _load_from_settings(self) -> None:
        s = self._settings_store.get()
        self.dir_input.setText(s.download_dir)
        self.container_combo.setCurrentText(s.container.upper() if s.container != "auto" else "Auto")
        self.concurrency_spin.setValue(s.concurrent_downloads)

        mode_index = {COOKIE_MODE_NONE: 0, COOKIE_MODE_BROWSER: 1, COOKIE_MODE_FILE: 2}.get(s.cookie_mode, 0)
        self.cookie_mode_combo.setCurrentIndex(mode_index)
        self._on_cookie_mode_changed(mode_index)
        if s.cookie_browser.lower() in SUPPORTED_COOKIE_BROWSERS:
            self.browser_combo.setCurrentText(s.cookie_browser.title())
        self.cookie_file_input.setText(s.cookie_file)
        self.live_enabled.setChecked(self._live_settings.get().enabled)

        self.accent_combo.blockSignals(True)
        self.accent_combo.setCurrentText(s.accent.title())
        self.accent_combo.blockSignals(False)

    def _save(self) -> None:
        container_value = self.container_combo.currentText().lower()
        mode_map = {0: COOKIE_MODE_NONE, 1: COOKIE_MODE_BROWSER, 2: COOKIE_MODE_FILE}
        self._settings_store.update(
            download_dir=self.dir_input.text().strip(),
            container=container_value,
            concurrent_downloads=self.concurrency_spin.value(),
            cookie_mode=mode_map[self.cookie_mode_combo.currentIndex()],
            cookie_browser=self.browser_combo.currentText().lower(),
            cookie_file=self.cookie_file_input.text().strip(),
        )
        self.queue_settings_changed.emit()

    def _save_live_settings(self) -> None:
        self._live_settings.update(enabled=self.live_enabled.isChecked())
