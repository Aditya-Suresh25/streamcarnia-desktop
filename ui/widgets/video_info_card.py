"""Displays analyzed video metadata (thumbnail, title, channel, duration,
live/VOD badges) -- ported from the web app's VideoInfo.jsx."""
from __future__ import annotations

import urllib.request

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from backend.models.schemas import AnalyzeResponse

from ui.effects import apply_card_shadow


class _ThumbnailFetchSignals(QObject):
    loaded = Signal(bytes)


class _ThumbnailFetcher(QRunnable):
    def __init__(self, url: str, signals: _ThumbnailFetchSignals):
        super().__init__()
        self.url = url
        self.signals = signals

    def run(self) -> None:
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            self.signals.loaded.emit(data)
        except Exception:  # noqa: BLE001
            pass


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class VideoInfoCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._thumb_signals = _ThumbnailFetchSignals()
        self._thumb_signals.loaded.connect(self._on_thumb_loaded)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        self.thumb = QLabel()
        self.thumb.setFixedSize(160, 90)
        self.thumb.setStyleSheet("background-color:#0a0b0f; border-radius:8px;")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setScaledContents(True)
        layout.addWidget(self.thumb)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-family: 'Space Grotesk'; font-size:16px; font-weight:700; color:#f4f6fb; letter-spacing:-0.01em;")
        text_col.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("Muted")
        text_col.addWidget(self.meta_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        self.badge = QLabel("")
        self.badge.setObjectName("StatusBadge")
        self.badge.hide()
        badge_row.addWidget(self.badge)
        badge_row.addStretch(1)
        text_col.addLayout(badge_row)
        text_col.addStretch(1)

        layout.addLayout(text_col, 1)
        self.hide()
        apply_card_shadow(self)

    def set_info(self, info: AnalyzeResponse) -> None:
        self.title_label.setText(info.title)
        meta_bits = []
        if info.channel:
            meta_bits.append(info.channel)
        dur = _format_duration(info.duration)
        if dur:
            meta_bits.append(dur)
        self.meta_label.setText("  •  ".join(meta_bits))

        if info.is_live:
            self.badge.setText("LIVE")
            self.badge.setProperty("state", "active")
            self.badge.show()
        elif info.was_live:
            self.badge.setText("VOD")
            self.badge.setProperty("state", "completed")
            self.badge.show()
        else:
            self.badge.hide()
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

        self.thumb.setStyleSheet("background-color:#0a0b0f; border-radius:8px;")
        self.thumb.clear()
        if info.thumbnail:
            fetcher = _ThumbnailFetcher(info.thumbnail, self._thumb_signals)
            QThreadPool.globalInstance().start(fetcher)

        self.show()

    def _on_thumb_loaded(self, data: bytes) -> None:
        pix = QPixmap()
        if pix.loadFromData(data):
            self.thumb.setPixmap(pix)

    def clear(self) -> None:
        self.hide()
        self.thumb.clear()
