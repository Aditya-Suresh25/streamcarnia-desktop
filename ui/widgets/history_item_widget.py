"""One row in download history -- ported from the web app's HistoryPage.jsx."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from backend.models.schemas import HistoryEntry

from ui.effects import apply_card_shadow
from ui.widgets.buttons import DangerGhostButton, IconButton
from ui.widgets.queue_item_widget import _open_path


class HistoryItemWidget(QFrame):
    delete_requested = Signal(str)

    def __init__(self, entry: HistoryEntry, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.entry = entry

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(entry.title)
        title.setStyleSheet(
            "font-family: 'Space Grotesk'; font-weight:700; font-size:14px; "
            "color:#f4f6fb; letter-spacing:-0.01em;"
        )
        title.setWordWrap(True)
        sub = QLabel(f"{entry.quality}  •  {entry.date[:19].replace('T', ' ')}")
        sub.setObjectName("Faint")
        text_col.addWidget(title)
        text_col.addWidget(sub)
        layout.addLayout(text_col, 1)

        badge = QLabel(entry.status.upper())
        badge.setObjectName("StatusBadge")
        badge.setProperty("state", "completed" if entry.status == "completed" else "failed")
        layout.addWidget(badge)

        if entry.status == "completed" and entry.file_path and Path(entry.file_path).is_file():
            open_btn = IconButton("Open File")
            open_btn.clicked.connect(lambda: _open_path(entry.file_path))
            layout.addWidget(open_btn)

            folder_btn = IconButton("Open Folder")
            folder_btn.clicked.connect(lambda: _open_path(str(Path(entry.file_path).parent)))
            layout.addWidget(folder_btn)

        remove_btn = DangerGhostButton("Remove")
        remove_btn.clicked.connect(lambda: self.delete_requested.emit(entry.id))
        layout.addWidget(remove_btn)

        apply_card_shadow(self, blur=22, y_offset=8, alpha=110)
