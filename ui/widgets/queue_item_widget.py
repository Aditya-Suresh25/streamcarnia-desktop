"""One row in the download queue: title, stage, progress bar, speed/eta,
cancel / open-file / open-folder actions -- ported from the web app's
DownloadCard.jsx + ProgressBar.jsx."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from backend.models.schemas import DownloadItem, DownloadStage

from ui.effects import apply_card_shadow
from ui.widgets.buttons import DangerGhostButton, IconButton

STAGE_LABELS = {
    DownloadStage.QUEUED: "Queued",
    DownloadStage.ANALYZING: "Analyzing",
    DownloadStage.DOWNLOADING_VIDEO: "Downloading video",
    DownloadStage.DOWNLOADING_AUDIO: "Downloading audio",
    DownloadStage.MERGING: "Merging with FFmpeg",
    DownloadStage.FINALIZING: "Finalizing",
    DownloadStage.COMPLETED: "Completed",
    DownloadStage.FAILED: "Failed",
    DownloadStage.CANCELLED: "Cancelled",
}

BADGE_STATE = {
    DownloadStage.COMPLETED: "completed",
    DownloadStage.FAILED: "failed",
    DownloadStage.CANCELLED: "",
}

ACTIVE_STAGES = {
    DownloadStage.QUEUED,
    DownloadStage.ANALYZING,
    DownloadStage.DOWNLOADING_VIDEO,
    DownloadStage.DOWNLOADING_AUDIO,
    DownloadStage.MERGING,
    DownloadStage.FINALIZING,
}


def _human_speed(bytes_per_sec: float | None) -> str:
    if not bytes_per_sec:
        return ""
    mb = bytes_per_sec / (1024 * 1024)
    return f"{mb:.1f} MB/s" if mb >= 1 else f"{bytes_per_sec / 1024:.0f} KB/s"


def _human_eta(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s left" if m else f"{s}s left"


class QueueItemWidget(QFrame):
    cancel_requested = Signal(str)

    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.download_id = item.id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        top_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_label = QLabel(item.title)
        self.title_label.setStyleSheet(
            "font-family: 'Space Grotesk'; font-weight:700; font-size:14px; "
            "color:#f4f6fb; letter-spacing:-0.01em;"
        )
        self.title_label.setWordWrap(True)
        self.sub_label = QLabel(item.format_label)
        self.sub_label.setObjectName("Faint")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.sub_label)
        top_row.addLayout(title_col, 1)

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("StatusBadge")
        top_row.addWidget(self.status_badge)
        outer.addLayout(top_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)

        bottom_row = QHBoxLayout()
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("Faint")
        bottom_row.addWidget(self.detail_label)
        bottom_row.addStretch(1)

        self.cancel_btn = DangerGhostButton("Cancel")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.download_id))
        bottom_row.addWidget(self.cancel_btn)

        self.open_file_btn = IconButton("Open File")
        self.open_file_btn.clicked.connect(self._open_file)
        self.open_file_btn.hide()
        bottom_row.addWidget(self.open_file_btn)

        self.open_folder_btn = IconButton("Open Folder")
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.open_folder_btn.hide()
        bottom_row.addWidget(self.open_folder_btn)

        outer.addLayout(bottom_row)

        self._item = item
        self.update_item(item)
        apply_card_shadow(self, blur=24, y_offset=9, alpha=120)

    def update_item(self, item: DownloadItem) -> None:
        self._item = item
        self.title_label.setText(item.title)
        self.progress.setValue(int(item.percent or 0))

        state = BADGE_STATE.get(item.stage, "active")
        self.status_badge.setText(STAGE_LABELS.get(item.stage, item.stage.value))
        self.status_badge.setProperty("state", state)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        detail_bits = []
        if item.stage in (DownloadStage.DOWNLOADING_VIDEO, DownloadStage.DOWNLOADING_AUDIO):
            speed = _human_speed(item.speed_bytes_s)
            eta = _human_eta(item.eta_seconds)
            if speed:
                detail_bits.append(speed)
            if eta:
                detail_bits.append(eta)
        elif item.stage == DownloadStage.FAILED and item.error:
            detail_bits.append(item.error)
        self.detail_label.setText("  •  ".join(detail_bits))

        is_active = item.stage in ACTIVE_STAGES
        self.cancel_btn.setVisible(is_active)
        self.open_file_btn.setVisible(item.stage == DownloadStage.COMPLETED and bool(item.file_path))
        self.open_folder_btn.setVisible(item.stage == DownloadStage.COMPLETED and bool(item.file_path))

    def _open_file(self) -> None:
        if self._item.file_path:
            _open_path(self._item.file_path)

    def _open_folder(self) -> None:
        if self._item.file_path:
            _open_path(str(Path(self._item.file_path).parent))


def _open_path(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:  # noqa: BLE001
        pass
