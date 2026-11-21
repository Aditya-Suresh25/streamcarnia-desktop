"""Shared scroll-area sizing for pages that need to work on laptop widths."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLayout, QScrollArea, QSizePolicy, QWidget


def configure_page_scroll(scroll: QScrollArea, content: QWidget, max_width: int = 1440) -> None:
    """Center page content on wide screens and let it shrink to the viewport."""
    scroll.setWidgetResizable(True)
    scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    content.setMinimumSize(0, 0)
    content.setMaximumWidth(max_width)
    # Ignore the aggregate width hint from wide form rows; child layouts then
    # receive the viewport width and can wrap/reflow instead of widening the
    # scroll area and hiding the trailing controls off-screen.
    content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    if content.layout():
        content.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
