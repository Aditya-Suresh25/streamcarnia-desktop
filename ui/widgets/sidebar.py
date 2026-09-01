"""Left navigation sidebar: logo/brand + page switcher, ported from the
web app's Header.jsx nav (Downloader / Queue / History / Settings)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.paths import asset_path

NAV_ITEMS = [
    ("home", "Downloader"),
    ("queue", "Queue"),
    ("history", "History"),
    ("settings", "Settings"),
]

COPYRIGHT_LINE = "\u00a9 Aditya Suresh"


class Sidebar(QWidget):
    page_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(235)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)

        brand = QWidget()
        brand.setObjectName("SidebarLogo")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(18, 24, 18, 16)
        brand_layout.setSpacing(6)

        logo_row = QWidget()
        logo_row_layout = QHBoxLayout(logo_row)
        logo_row_layout.setContentsMargins(0, 0, 0, 0)
        logo_row_layout.setSpacing(11)

        logo_label = QLabel()
        pix = QPixmap(str(asset_path("logo.png")))
        if not pix.isNull():
            logo_label.setPixmap(
                pix.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        logo_row_layout.addWidget(logo_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("StreamCarnia")
        title.setObjectName("SidebarTitle")
        # subtitle = QLabel("Quality Uncompromised")
        title_col.addWidget(title)
        # title_col.addWidget(subtitle)
        logo_row_layout.addLayout(title_col)
        logo_row_layout.addStretch(1)

        brand_layout.addWidget(logo_row)
        layout.addWidget(brand)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for key, label in NAV_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self.page_selected.emit(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch(1)

        footer = QLabel(COPYRIGHT_LINE)
        footer.setObjectName("SidebarFooter")
        footer.setAlignment(Qt.AlignLeft)
        layout.addWidget(footer)

        self._buttons["home"].setChecked(True)

    def select(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn:
            btn.setChecked(True)
