"""Live download queue -- ported from the web app's DownloadQueue.jsx."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from backend.models.schemas import DownloadItem

from core.queue_manager import QueueManager
from ui.widgets.queue_item_widget import QueueItemWidget


class QueuePage(QWidget):
    def __init__(self, queue_manager: QueueManager, parent=None):
        super().__init__(parent)
        self._queue_manager = queue_manager
        self._widgets: dict[str, QueueItemWidget] = {}

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        header = QVBoxLayout()
        header.setContentsMargins(32, 28, 32, 8)
        eyebrow = QLabel("ACTIVE & RECENT")
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("Download Queue")
        title.setObjectName("PageTitle")
        header.addWidget(eyebrow)
        header.addWidget(title)
        header_widget = QWidget()
        header_widget.setLayout(header)
        outer_layout.addWidget(header_widget)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        self._content = QWidget()
        scroll.setWidget(self._content)
        self._list_layout = QVBoxLayout(self._content)
        self._list_layout.setContentsMargins(32, 8, 32, 24)
        self._list_layout.setSpacing(10)

        self._empty_label = QLabel("Nothing queued yet. Analyze a video and hit Download.")
        self._empty_label.setObjectName("Muted")
        self._list_layout.addWidget(self._empty_label)
        self._list_layout.addStretch(1)

        queue_manager.item_added.connect(self._on_item_added)
        queue_manager.item_updated.connect(self._on_item_updated)
        queue_manager.item_finished.connect(self._on_item_updated)

    def _on_item_added(self, item: DownloadItem) -> None:
        self._empty_label.hide()
        widget = QueueItemWidget(item)
        widget.cancel_requested.connect(self._queue_manager.cancel)
        self._widgets[item.id] = widget
        self._list_layout.insertWidget(0, widget)

    def _on_item_updated(self, item: DownloadItem) -> None:
        widget = self._widgets.get(item.id)
        if widget:
            widget.update_item(item)
