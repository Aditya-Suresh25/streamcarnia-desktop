"""Left navigation sidebar: logo/brand + page switcher, ported from the
web app's Header.jsx nav (Downloader / Queue / History / Settings)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, Qt, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.paths import asset_path

NAV_GROUPS = [
    ("WORKSPACE", [("dashboard", "Dashboard")]),
    ("CREATE", [
        ("home", "Download Stream"),
        ("clipper", "Auto Clippr"),
        ("studio", "Clip Studio"),
        ("live", "Auto Clipper (Live)"),
    ]),
    ("YOUR LIBRARY", [
        ("queue", "Queue"),
        ("history", "History"),
    ]),
    ("PREFERENCES", [("settings", "Settings")]),
]

COPYRIGHT_LINE = "\u00a9 Aditya Suresh"


class Sidebar(QWidget):
    page_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(235)
        self._compact = False
        self._animation = None

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

        self._headings = []
        for section, items in NAV_GROUPS:
            heading = QLabel(section)
            heading.setObjectName("NavSection")
            self._headings.append(heading)
            layout.addWidget(heading)
            for key, label in items:
                btn = QPushButton(label)
                btn.setObjectName("NavButton")
                btn.setMinimumHeight(42)
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setAccessibleName(label)
                btn.setToolTip(label)
                btn.clicked.connect(lambda checked, k=key: self.page_selected.emit(k))
                self._group.addButton(btn)
                self._buttons[key] = btn
                layout.addWidget(btn)

        self._buttons["live"].hide()

        layout.addStretch(1)

        footer = QLabel(COPYRIGHT_LINE)
        footer.setObjectName("SidebarFooter")
        footer.setAlignment(Qt.AlignLeft)
        layout.addWidget(footer)

        self._icons = {"dashboard": "DB", "home": "DL", "clipper": "AC", "studio": "CS",
                       "live": "LV", "queue": "QU", "history": "HI", "settings": "ST"}
        self._brand_title = title
        self._footer = footer
        self._indicator = QWidget(self)
        self._indicator.setObjectName("NavIndicator")
        self._indicator.hide()
        self._buttons["dashboard"].setChecked(True)

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedWidth(76 if compact else 235)
        self._brand_title.setVisible(not compact)
        self._footer.setVisible(not compact)
        for heading in self._headings:
            heading.setVisible(not compact)
        for key, button in self._buttons.items():
            button.setProperty("compact", compact)
            if compact:
                button.setText(self._icons[key])
                button.setToolTip(button.accessibleName())
            else:
                button.setText(button.accessibleName())
                button.setToolTip(button.accessibleName())
            button.style().unpolish(button)
            button.style().polish(button)
        self._move_indicator()
        QTimer.singleShot(0, self._animate_indicator)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._move_indicator()

    def select(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn:
            btn.setChecked(True)
            QTimer.singleShot(0, self._animate_indicator)

    def _move_indicator(self):
        button = next((item for item in self._buttons.values() if item.isChecked()), None)
        if button and self._indicator.isVisible():
            self._indicator.setGeometry(10, button.y(), 3, button.height())

    def _animate_indicator(self):
        button = next((item for item in self._buttons.values() if item.isChecked()), None)
        if not button:
            return
        target = self._indicator.geometry().__class__(10, button.y(), 3, button.height())
        if not self._indicator.isVisible():
            self._indicator.setGeometry(target)
            self._indicator.show()
            return
        if self._animation:
            self._animation.stop()
        self._animation = QPropertyAnimation(self._indicator, b"geometry", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.setEndValue(target)
        self._animation.start()

    def set_live_enabled(self, enabled: bool) -> None:
        self._buttons["live"].setVisible(bool(enabled))
