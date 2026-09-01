"""Selectable list of quality/format options -- ported from the web app's
QualitySelector.jsx. Wraps backend.models.schemas.FormatOption entries."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from backend.models.schemas import FormatOption


def _human_size(num_bytes: int | None) -> str:
    if not num_bytes:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"~{size:.0f} {unit}" if unit == "B" else f"~{size:.1f} {unit}"
        size /= 1024
    return ""


class _QualityRow(QFrame):
    clicked = Signal(str)

    def __init__(self, option: FormatOption, parent=None):
        super().__init__(parent)
        self.setObjectName("QualityRow")
        self.option = option
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        label = QLabel(option.label)
        label.setObjectName("QualityLabel")
        top_row.addWidget(label)
        if option.recommended:
            tag = QLabel("RECOMMENDED")
            tag.setObjectName("RecommendedTag")
            top_row.addWidget(tag)
        top_row.addStretch(1)
        text_col.addLayout(top_row)

        sub_bits = [option.sublabel] if option.sublabel else []
        size_text = _human_size(option.approx_filesize)
        if size_text:
            sub_bits.append(size_text)
        sub_label = QLabel("  •  ".join(b for b in sub_bits if b))
        sub_label.setObjectName("QualitySub")
        text_col.addWidget(sub_label)

        layout.addLayout(text_col, 1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.option.key)
        super().mousePressEvent(event)


class QualityList(QWidget):
    selection_changed = Signal(object)  # FormatOption

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._rows: dict[str, _QualityRow] = {}
        self._options: dict[str, FormatOption] = {}
        self._selected_key: str | None = None

    def set_options(self, options: list[FormatOption]) -> None:
        self.clear()
        for opt in options:
            row = _QualityRow(opt)
            row.clicked.connect(self._on_row_clicked)
            self._layout.addWidget(row)
            self._rows[opt.key] = row
            self._options[opt.key] = opt

        default = next((o for o in options if o.recommended), options[0] if options else None)
        if default:
            self._on_row_clicked(default.key)

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows.clear()
        self._options.clear()
        self._selected_key = None

    def _on_row_clicked(self, key: str) -> None:
        if self._selected_key and self._selected_key in self._rows:
            self._rows[self._selected_key].set_selected(False)
        self._selected_key = key
        self._rows[key].set_selected(True)
        self.selection_changed.emit(self._options[key])

    def selected_option(self) -> FormatOption | None:
        return self._options.get(self._selected_key) if self._selected_key else None
