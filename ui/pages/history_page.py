"""Download history -- ported from the web app's HistoryPage.jsx, backed
directly by the existing backend.services.history_store.HistoryStore
(same SQLite schema)."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from backend.services.history_store import HistoryStore

from ui.widgets.buttons import GhostButton
from ui.widgets.history_item_widget import HistoryItemWidget


class HistoryPage(QWidget):
    def __init__(self, history_store: HistoryStore, parent=None):
        super().__init__(parent)
        self._history_store = history_store

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        header_widget = QWidget()
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(32, 28, 32, 8)
        title_col = QVBoxLayout()
        eyebrow = QLabel("PAST DOWNLOADS")
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("History")
        title.setObjectName("PageTitle")
        title_col.addWidget(eyebrow)
        title_col.addWidget(title)
        header.addLayout(title_col)
        header.addStretch(1)
        self.refresh_btn = GhostButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        outer_layout.addWidget(header_widget)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        self._content = QWidget()
        scroll.setWidget(self._content)
        self._list_layout = QVBoxLayout(self._content)
        self._list_layout.setContentsMargins(32, 8, 32, 24)
        self._list_layout.setSpacing(10)

        self.refresh()

    def refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        entries = self._history_store.list_recent(limit=100)
        if not entries:
            empty = QLabel("No downloads yet.")
            empty.setObjectName("Muted")
            self._list_layout.addWidget(empty)
        else:
            for entry in entries:
                widget = HistoryItemWidget(entry)
                widget.delete_requested.connect(self._on_delete)
                self._list_layout.addWidget(widget)
        self._list_layout.addStretch(1)

    def _on_delete(self, entry_id: str) -> None:
        self._history_store.remove(entry_id)
        self.refresh()
