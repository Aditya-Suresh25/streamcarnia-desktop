"""Small interactive source-frame selector for stacked clip layouts."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui.theme import palette


class FacecamSelector(QWidget):
    """Let users position and size the facecam crop on a 16:9 source frame.

    Drag inside the selected box to move it. Drag outside the box to draw a
    replacement. Drag the small lower-right handle to resize it.
    Coordinates are emitted as normalized ``x,y,width,height`` fractions.
    """

    coordinatesChanged = Signal(str)

    _MIN_SIZE = 0.04

    def __init__(self, coordinates: str = "0.75,0.68,0.25,0.32", accent: str = "violet", parent=None):
        super().__init__(parent)
        self._colors = palette(accent)
        self._rect = self._parse(coordinates)
        self._drag_mode: str | None = None
        self._drag_start = None
        self._start_rect: QRectF | None = None
        self._canvas = QRectF()
        self.setMinimumSize(300, 190)
        self.setMaximumHeight(300)
        self.setMouseTracking(True)
        self.setToolTip("Drag the box to move the facecam selection; drag its lower-right handle to resize.")

    @staticmethod
    def _parse(value: str) -> QRectF:
        try:
            x, y, width, height = (float(part.strip()) for part in value.split(","))
            if (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1
                    and x + width <= 1 and y + height <= 1):
                return QRectF(x, y, width, height)
        except (TypeError, ValueError):
            pass
        return QRectF(0.75, 0.68, 0.25, 0.32)

    def coordinates(self) -> str:
        return ",".join(f"{part:.3f}" for part in
                         (self._rect.x(), self._rect.y(), self._rect.width(), self._rect.height()))

    def setCoordinates(self, value: str) -> None:
        selected = self._parse(value)
        if selected != self._rect:
            self._rect = selected
            self.update()

    def _selection_pixels(self) -> QRectF:
        return QRectF(self._canvas.x() + self._rect.x() * self._canvas.width(),
                      self._canvas.y() + self._rect.y() * self._canvas.height(),
                      self._rect.width() * self._canvas.width(),
                      self._rect.height() * self._canvas.height())

    def _normalized(self, point) -> tuple[float, float]:
        x = min(1.0, max(0.0, (point.x() - self._canvas.x()) / self._canvas.width()))
        y = min(1.0, max(0.0, (point.y() - self._canvas.y()) / self._canvas.height()))
        return x, y

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._colors["panel"]))

        margin = 12.0
        available = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        frame_ratio = 16 / 9
        width = min(available.width(), available.height() * frame_ratio)
        height = width / frame_ratio
        self._canvas = QRectF(available.center().x() - width / 2, available.center().y() - height / 2,
                              width, height)

        painter.setPen(QPen(QColor(self._colors["border"]), 1))
        painter.setBrush(QColor("#0a0b0f"))
        painter.drawRoundedRect(self._canvas, 8, 8)
        painter.save()
        painter.setClipRect(self._canvas)
        for col in range(1, 4):
            x = self._canvas.x() + self._canvas.width() * col / 4
            painter.setPen(QPen(QColor(self._colors["border_soft"]), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(x), int(self._canvas.y()), int(x), int(self._canvas.bottom()))
        for row in range(1, 3):
            y = self._canvas.y() + self._canvas.height() * row / 3
            painter.drawLine(int(self._canvas.x()), int(y), int(self._canvas.right()), int(y))
        painter.setPen(QColor(self._colors["text_faint"]))
        painter.drawText(self._canvas.adjusted(8, 5, -8, -5), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         "SOURCE FRAME")
        painter.restore()

        selection = self._selection_pixels()
        accent = QColor(self._colors["accent"])
        fill = QColor(accent)
        fill.setAlpha(70)
        painter.setPen(QPen(QColor(self._colors["accent_hover"]), 2))
        painter.setBrush(fill)
        painter.drawRoundedRect(selection, 3, 3)
        painter.setPen(QColor(self._colors["text"]))
        painter.drawText(selection, Qt.AlignmentFlag.AlignCenter, "FACECAM")
        handle_size = 10
        handle = QRectF(selection.right() - handle_size / 2, selection.bottom() - handle_size / 2,
                        handle_size, handle_size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._colors["accent_hover"]))
        painter.drawEllipse(handle)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._canvas.contains(event.position()):
            return
        point = event.position()
        selection = self._selection_pixels()
        handle = QRectF(selection.right() - 10, selection.bottom() - 10, 20, 20)
        if handle.contains(point):
            self._drag_mode = "resize"
        elif selection.contains(point):
            self._drag_mode = "move"
        else:
            self._drag_mode = "draw"
            x, y = self._normalized(point)
            self._rect = QRectF(x, y, self._MIN_SIZE, self._MIN_SIZE)
        self._drag_start = point
        self._start_rect = QRectF(self._rect)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None:
            return
        x, y = self._normalized(event.position())
        sx, sy = self._normalized(self._drag_start)
        start = self._start_rect
        if self._drag_mode == "move":
            nx = min(1 - start.width(), max(0.0, start.x() + x - sx))
            ny = min(1 - start.height(), max(0.0, start.y() + y - sy))
            self._rect = QRectF(nx, ny, start.width(), start.height())
        elif self._drag_mode == "resize":
            width = max(self._MIN_SIZE, min(1 - start.x(), x - start.x()))
            height = max(self._MIN_SIZE, min(1 - start.y(), y - start.y()))
            self._rect = QRectF(start.x(), start.y(), width, height)
        else:
            left, right = sorted((sx, x))
            top, bottom = sorted((sy, y))
            right = max(right, left + self._MIN_SIZE)
            bottom = max(bottom, top + self._MIN_SIZE)
            left = min(left, 1 - self._MIN_SIZE)
            top = min(top, 1 - self._MIN_SIZE)
            self._rect = QRectF(left, top, min(right, 1) - left, min(bottom, 1) - top)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode is not None:
            self._drag_mode = None
            self._drag_start = None
            self._start_rect = None
            self.coordinatesChanged.emit(self.coordinates())
