"""Small styled QPushButton subclasses (object names map to ui/theme.py QSS)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


class PrimaryButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("PrimaryButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)


class GhostButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("GhostButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34)


class DangerGhostButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("DangerGhostButton")
        self.setCursor(Qt.PointingHandCursor)


class IconButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("IconButton")
        self.setCursor(Qt.PointingHandCursor)
