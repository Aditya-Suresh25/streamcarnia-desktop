"""Real drop-shadow effects (Qt style sheets have no box-shadow property,
so cards/buttons would otherwise render completely flat). Ported in
spirit from the web app's `shadow-glow` utility class and the accent
glow on `.btn-primary:hover`."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


def apply_card_shadow(widget: QWidget, blur: int = 34, y_offset: int = 12, alpha: int = 150) -> None:
    """Soft black shadow beneath a card/panel for depth, matching the
    web app's `shadow-glow` card treatment."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def apply_accent_glow(widget: QWidget, rgb: tuple[int, int, int], blur: int = 26, y_offset: int = 6, alpha: int = 130) -> None:
    """Colored glow beneath an accent element (primary button, selected
    quality row) for a touch of richness, matching the site's
    accent-tinted button shadow on hover."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    r, g, b = rgb
    effect.setColor(QColor(r, g, b, alpha))
    widget.setGraphicsEffect(effect)
