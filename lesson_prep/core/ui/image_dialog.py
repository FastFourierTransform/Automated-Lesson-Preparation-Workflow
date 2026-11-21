"""Large image preview with zoom and pan."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class _ZoomView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self._zoom = 1.0
        self._fit = True

    def set_scene_item(self, item: QGraphicsPixmapItem) -> None:
        scene = QGraphicsScene(self)
        scene.addItem(item)
        self.setScene(scene)
        self.fit()

    def fit(self) -> None:
        if self.scene() is None:
            return
        self._fit = True
        self.resetTransform()
        self.fitInView(self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0

    def actual_size(self) -> None:
        self._fit = False
        self.resetTransform()
        self._zoom = 1.0

    def zoom_in(self) -> None:
        self._fit = False
        self.scale(1.25, 1.25)
        self._zoom *= 1.25

    def zoom_out(self) -> None:
        self._fit = False
        self.scale(0.8, 0.8)
        self._zoom *= 0.8

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit:
            self.fit()


class ImagePreviewDialog(QDialog):
    def __init__(self, image: QImage, title: str = "大图预览", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1180, 780)
        self.setMinimumSize(700, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        header = QHBoxLayout()
        self.info_label = QLabel(f"{image.width()} × {image.height()} px")
        self.info_label.setStyleSheet("color:#4b5563;")
        header.addWidget(self.info_label)
        header.addStretch(1)
        for text, slot in (
            ("适应窗口", self._fit),
            ("100%", self._actual),
            ("－", self._zoom_out),
            ("＋", self._zoom_in),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            header.addWidget(button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        header.addWidget(close_button)
        layout.addLayout(header)
        self.view = _ZoomView(self)
        self.item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        self.view.set_scene_item(self.item)
        layout.addWidget(self.view, 1)

    def _fit(self) -> None:
        self.view.fit()

    def _actual(self) -> None:
        self.view.actual_size()

    def _zoom_in(self) -> None:
        self.view.zoom_in()

    def _zoom_out(self) -> None:
        self.view.zoom_out()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "view", None) and self.view._fit:
            self.view.fit()
