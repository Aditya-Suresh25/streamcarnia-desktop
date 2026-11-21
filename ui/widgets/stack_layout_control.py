"""Preview and adjust the facecam/gameplay split in stacked Shorts."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from ui.theme import palette


class StackLayoutControl(QWidget):
    valueChanged = Signal(int)

    def __init__(self, value: int = 35, accent: str = "violet", parent=None):
        super().__init__(parent)
        self._colors = palette(accent)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(20, 50)
        self.slider.setValue(int(value))
        self.slider.valueChanged.connect(self._changed)
        self.value_label = QLabel()
        self.value_label.setObjectName("FieldLabel")
        row = QHBoxLayout()
        row.addWidget(QLabel("Facecam height in the short"))
        row.addStretch(1)
        row.addWidget(self.value_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(row)
        layout.addWidget(self.slider)
        self.setMinimumHeight(160)
        self._changed(self.slider.value())

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(int(value))

    def _changed(self, value: int) -> None:
        self.value_label.setText(f"{value}% facecam · {100 - value}% gameplay")
        self.update()
        self.valueChanged.emit(value)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = int((self.height() - 42) * self.slider.value() / 100)
        frame = self.rect().adjusted(2, 42, -2, -2)
        top = int(frame.height() * self.slider.value() / 100)
        painter.setPen(QPen(QColor(self._colors["border"]), 1))
        painter.setBrush(QColor(self._colors["panel"]))
        painter.drawRoundedRect(frame, 8, 8)
        face = frame.adjusted(1, 1, -1, -frame.height() + top)
        game = frame.adjusted(1, top, -1, -1)
        accent = QColor(self._colors["accent"])
        accent.setAlpha(115)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(face, 7, 7)
        painter.setBrush(QColor(self._colors["border_soft"]))
        painter.drawRect(game)
        painter.setPen(QColor(self._colors["text"]))
        painter.drawText(face, Qt.AlignmentFlag.AlignCenter, "FACECAM")
        painter.drawText(game, Qt.AlignmentFlag.AlignCenter, "GAMEPLAY")
