"""A tiny self-dismissing toast/notification banner, ported in spirit from
the web app's Toasts.jsx."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.effects import apply_card_shadow


class ToastHost(QWidget):
    """Overlay container; call show_toast() to pop up a message that
    auto-dismisses. Place this as a floating child of the main window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.setFixedWidth(320)

    def show_toast(self, message: str, kind: str = "info", timeout_ms: int = 3500) -> None:
        colors = {
            "info": "#171a24",
            "success": "#123326",
            "error": "#3a1f22",
        }
        borders = {
            "info": "#272b3a",
            "success": "#2f6b4c",
            "error": "#7a3038",
        }
        bg = colors.get(kind, colors["info"])
        border = borders.get(kind, borders["info"])

        label = QLabel(message)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"background-color:{bg}; color:#f4f6fb; border:1px solid {border};"
            "border-radius:10px; padding:11px 15px; font-size:12px; font-weight:500;"
        )
        self._layout.insertWidget(self._layout.count() - 1, label)
        apply_card_shadow(label, blur=20, y_offset=6, alpha=140)
        self.show()
        self.raise_()

        def remove():
            label.setParent(None)
            label.deleteLater()
            if self._layout.count() <= 1:
                self.hide()

        QTimer.singleShot(timeout_ms, remove)
