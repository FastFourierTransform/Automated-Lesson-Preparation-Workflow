"""Application icon drawing."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap


def make_app_icon() -> QPixmap:
    """Return the shared workflow icon.

    The icon is intentionally generic (a document with lines) so it can be
    reused by every stage instead of implying video-to-slides only.
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#1d4ed8"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(12, 14, 40, 32, 4, 4)
    painter.setBrush(QColor("#1d4ed8"))
    painter.drawRect(17, 22, 30, 3)
    painter.drawRect(17, 29, 22, 2)
    painter.drawRect(17, 34, 26, 2)
    painter.end()
    return pixmap
