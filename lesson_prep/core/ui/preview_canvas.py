"""Video display with normalized-coordinate region selection and resizing.

The widget is intentionally business-agnostic: it draws one primary region
plus any number of overlays, and reports selected/resized rectangles by an
opaque "kind" string supplied by the caller.  A stage decides what "ppt" or
"camera:<id>" means.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..geometry import Rect


class PreviewCanvas(QWidget):
    region_committed = Signal(str, object)  # opaque region kind, Rect
    region_edit_started = Signal()
    selection_cancelled = Signal()

    HANDLE_SIZE = 8.0
    HIT_TOLERANCE = 8.0
    MIN_SIZE_PX = 14.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self._content_rect = QRectF()
        self._primary_region: Rect | None = None
        self._primary_kind = "primary"
        self._primary_label = "区域"
        # (opaque kind, display label, normalized region)
        self._overlays: list[tuple[str, str, Rect]] = []
        self._primary_color = QColor("#3b82f6")
        self._overlay_color = QColor("#f59e0b")
        self._selection_mode: str | None = None
        self._selection_label = ""
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._regions_editable = False
        self._edit_kind: str | None = None
        self._edit_edges: set[str] = set()
        self._edit_start_point: QPointF | None = None
        self._edit_start_region: Rect | None = None
        self._edit_current_region: Rect | None = None
        self.setMinimumSize(560, 315)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def has_image(self) -> bool:
        return not self._image.isNull()

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def clear_image(self) -> None:
        self._image = QImage()
        self.set_regions_editable(False)
        self.update()

    def set_regions(
        self,
        primary: Rect | None,
        overlays: list[tuple[str, str, Rect]] | None = None,
        primary_kind: str = "primary",
        primary_label: str = "区域",
    ) -> None:
        self._primary_region = primary
        self._primary_kind = primary_kind
        self._primary_label = primary_label
        self._overlays = list(overlays or [])
        self._clear_edit()
        self.update()

    def set_regions_editable(self, editable: bool) -> None:
        if not editable:
            self._clear_edit()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._regions_editable = editable and not self._image.isNull()
        self.update()

    @property
    def selection_mode(self) -> str | None:
        return self._selection_mode

    def start_selection(self, mode: str, label: str = "") -> None:
        self._clear_edit()
        self._selection_mode = mode
        self._selection_label = label
        self._drag_start = None
        self._drag_current = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocus()
        self.update()

    def cancel_selection(self) -> None:
        if self._selection_mode is None:
            return
        self._selection_mode = None
        self._selection_label = ""
        self._drag_start = None
        self._drag_current = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.selection_cancelled.emit()
        self.update()

    def _clear_edit(self) -> None:
        self._edit_kind = None
        self._edit_edges.clear()
        self._edit_start_point = None
        self._edit_start_region = None
        self._edit_current_region = None

    def _effective_region(self, kind: str) -> Rect | None:
        if self._edit_kind == kind and self._edit_current_region is not None:
            return self._edit_current_region
        if kind == self._primary_kind:
            return self._primary_region
        for current_kind, _label, region in self._overlays:
            if current_kind == kind:
                return region
        return None

    def _recompute_content_rect(self) -> QRectF:
        available = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        if self._image.isNull() or available.width() <= 0 or available.height() <= 0:
            self._content_rect = QRectF()
            return self._content_rect
        image_ratio = self._image.width() / max(1, self._image.height())
        area_ratio = available.width() / max(1.0, available.height())
        if image_ratio >= area_ratio:
            width = available.width()
            height = width / image_ratio
        else:
            height = available.height()
            width = height * image_ratio
        left = available.left() + (available.width() - width) / 2
        top = available.top() + (available.height() - height) / 2
        self._content_rect = QRectF(left, top, width, height)
        return self._content_rect

    @staticmethod
    def _rect_to_qrect(region: Rect, content: QRectF) -> QRectF:
        return QRectF(
            content.left() + region.x * content.width(),
            content.top() + region.y * content.height(),
            region.w * content.width(),
            region.h * content.height(),
        )

    def _point_to_normalized(self, point: QPointF) -> tuple[float, float]:
        if self._content_rect.isEmpty():
            return 0.0, 0.0
        x = (point.x() - self._content_rect.left()) / self._content_rect.width()
        y = (point.y() - self._content_rect.top()) / self._content_rect.height()
        return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#111827"))
        content = self._recompute_content_rect()
        if self._image.isNull() or content.isEmpty():
            painter.setPen(QColor("#9ca3af"))
            font = painter.font()
            font.setPointSize(12)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "导入视频后将在此预览")
            return
        painter.drawImage(content, self._image)

        if self._primary_region is not None:
            self._draw_region(
                painter,
                self._effective_region(self._primary_kind),
                content,
                self._primary_label,
                self._primary_color,
            )
        for kind, label, _region in self._overlays:
            self._draw_region(
                painter,
                self._effective_region(kind),
                content,
                label,
                self._overlay_color,
            )

        if self._selection_mode and self._drag_start and self._drag_current:
            start_x, start_y = self._point_to_normalized(self._drag_start)
            end_x, end_y = self._point_to_normalized(self._drag_current)
            selection = QRectF(
                content.left() + min(start_x, end_x) * content.width(),
                content.top() + min(start_y, end_y) * content.height(),
                abs(end_x - start_x) * content.width(),
                abs(end_y - start_y) * content.height(),
            )
            color = (
                self._primary_color
                if self._selection_mode == self._primary_kind
                else self._overlay_color
            )
            fill = QColor(color)
            fill.setAlpha(45)
            self._fill_rect(painter, selection, fill)
            pen = QPen(color, 2.2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(selection)

        if self._selection_mode:
            label = self._selection_label or "区域"
            prompt = f"拖拽框选{label}"
            painter.setFont(QFont(self.font().family(), 10, QFont.Weight.DemiBold))
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(prompt + "    Esc 取消") + 24
            box = QRectF(content.left() + 12, content.top() + 12, width, 34)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(17, 24, 39, 205))
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(QColor("#f9fafb"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, prompt + "    Esc 取消")

    @staticmethod
    def _fill_rect(painter: QPainter, rect: QRectF, color: QColor) -> None:
        # Do not use fillRect(rect, color) here: when a brush is already set,
        # some PySide6 builds reuse that brush color.  Explicit save/restore
        # makes region fills deterministic.
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(rect)
        painter.restore()

    def _draw_region(
        self,
        painter: QPainter,
        region: Rect | None,
        content: QRectF,
        label: str,
        color: QColor,
    ) -> None:
        if region is None:
            return
        rect = self._rect_to_qrect(region, content).normalized()
        fill = QColor(color)
        fill.setAlpha(35)
        self._fill_rect(painter, rect, fill)
        pen = QPen(color, 2.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        # Label tab in the top-left corner.  Keep all brush changes scoped.
        painter.save()
        painter.setFont(QFont(self.font().family(), 8, QFont.Weight.DemiBold))
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(label) + 12
        tab = QRectF(rect.left(), max(content.top(), rect.top() - 20), text_width, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(tab, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(tab, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()
        if self._regions_editable and self._selection_mode is None:
            self._draw_handles(painter, rect, color)

    def _draw_handles(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        size = self.HANDLE_SIZE
        points = [
            (rect.left(), rect.top()),
            (rect.center().x(), rect.top()),
            (rect.right(), rect.top()),
            (rect.right(), rect.center().y()),
            (rect.right(), rect.bottom()),
            (rect.center().x(), rect.bottom()),
            (rect.left(), rect.bottom()),
            (rect.left(), rect.center().y()),
        ]
        painter.save()
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(QColor("#ffffff"))
        for x, y in points:
            painter.drawRect(QRectF(x - size / 2, y - size / 2, size, size))
        painter.restore()

    def _hit_test(self, point: QPointF) -> tuple[str, set[str]] | None:
        if (
            not self._regions_editable
            or self._selection_mode is not None
            or self._image.isNull()
            or self._content_rect.isEmpty()
        ):
            return None
        tolerance = self.HIT_TOLERANCE
        # Overlays are drawn on top of the primary region; the last-drawn
        # overlay has priority.
        candidates: list[tuple[str, Rect]] = [
            (kind, region) for kind, _label, region in reversed(self._overlays)
        ]
        if self._primary_region is not None:
            candidates.append((self._primary_kind, self._primary_region))
        for kind, region in candidates:
            if region is None:
                continue
            rect = self._rect_to_qrect(region, self._content_rect).normalized()
            expanded = rect.adjusted(-tolerance, -tolerance, tolerance, tolerance)
            if not expanded.contains(point):
                continue
            edges: set[str] = set()
            y_within = rect.top() - tolerance <= point.y() <= rect.bottom() + tolerance
            x_within = rect.left() - tolerance <= point.x() <= rect.right() + tolerance
            if y_within and abs(point.x() - rect.left()) <= tolerance:
                edges.add("left")
            if y_within and abs(point.x() - rect.right()) <= tolerance:
                edges.add("right")
            if x_within and abs(point.y() - rect.top()) <= tolerance:
                edges.add("top")
            if x_within and abs(point.y() - rect.bottom()) <= tolerance:
                edges.add("bottom")
            if edges:
                return kind, edges
        return None

    @staticmethod
    def _cursor_for_edges(edges: set[str]) -> Qt.CursorShape:
        if ("left" in edges and "top" in edges) or (
            "right" in edges and "bottom" in edges
        ):
            return Qt.CursorShape.SizeFDiagCursor
        if ("right" in edges and "top" in edges) or (
            "left" in edges and "bottom" in edges
        ):
            return Qt.CursorShape.SizeBDiagCursor
        if "left" in edges or "right" in edges:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _update_hover_cursor(self, point: QPointF) -> None:
        if self._selection_mode is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self._edit_kind is not None:
            self.setCursor(self._cursor_for_edges(self._edit_edges))
            return
        hit = self._hit_test(point)
        if hit is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(self._cursor_for_edges(hit[1]))

    def _begin_edit(self, kind: str, edges: set[str], point: QPointF) -> None:
        region = self._effective_region(kind)
        if region is None:
            return
        self._edit_kind = kind
        self._edit_edges = set(edges)
        self._edit_start_point = point
        self._edit_start_region = region
        self._edit_current_region = region
        self.setCursor(self._cursor_for_edges(edges))
        self.setFocus()
        self.region_edit_started.emit()
        self.update()

    def _update_edit(self, point: QPointF) -> None:
        if (
            self._edit_kind is None
            or self._edit_start_point is None
            or self._edit_start_region is None
        ):
            return
        current_x, current_y = self._point_to_normalized(point)
        region = self._edit_start_region
        min_w = max(0.004, self.MIN_SIZE_PX / max(1.0, self._content_rect.width()))
        min_h = max(0.004, self.MIN_SIZE_PX / max(1.0, self._content_rect.height()))
        left = region.left
        right = region.right
        top = region.top
        bottom = region.bottom
        # Dragging a border changes that border only; the opposite side stays
        # fixed.  Corner handles modify two sides.
        if "left" in self._edit_edges:
            left = min(current_x, right - min_w)
        if "right" in self._edit_edges:
            right = max(current_x, left + min_w)
        if "top" in self._edit_edges:
            top = min(current_y, bottom - min_h)
        if "bottom" in self._edit_edges:
            bottom = max(current_y, top + min_h)
        updated = Rect.from_ltrb(left, top, right, bottom).clamped()
        if updated.is_valid(0.0001):
            self._edit_current_region = updated
            self.update()

    def _finish_edit(self) -> None:
        kind = self._edit_kind
        original = self._edit_start_region
        current = self._edit_current_region
        self._clear_edit()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        if kind is None or original is None or current is None:
            return
        changed = (
            abs(original.x - current.x) > 1e-6
            or abs(original.y - current.y) > 1e-6
            or abs(original.w - current.w) > 1e-6
            or abs(original.h - current.h) > 1e-6
        )
        if changed and current.is_valid(0.0001):
            self.region_committed.emit(kind, current)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._image.isNull():
            self._recompute_content_rect()
            if self._content_rect.isEmpty():
                super().mousePressEvent(event)
                return
            if self._selection_mode is not None:
                if self._content_rect.contains(event.position()):
                    self._clear_edit()
                    self._drag_start = event.position()
                    self._drag_current = event.position()
                    self.update()
                    return
            elif self._regions_editable:
                hit = self._hit_test(event.position())
                if hit is not None:
                    self._begin_edit(hit[0], hit[1], event.position())
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selection_mode is not None and self._drag_start is not None:
            self._drag_current = event.position()
            self.update()
            return
        if self._edit_kind is not None:
            self._update_edit(event.position())
            return
        self._recompute_content_rect()
        self._update_hover_cursor(event.position())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._edit_kind is not None:
            self._update_edit(event.position())
            self._finish_edit()
            self._update_hover_cursor(event.position())
            return
        if (
            self._selection_mode is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self._drag_start is not None
        ):
            self._drag_current = event.position()
            start_x, start_y = self._point_to_normalized(self._drag_start)
            end_x, end_y = self._point_to_normalized(self._drag_current)
            region = Rect.from_ltrb(
                min(start_x, end_x),
                min(start_y, end_y),
                max(start_x, end_x),
                max(start_y, end_y),
            )
            mode = self._selection_mode
            self._selection_mode = None
            self._selection_label = ""
            self._drag_start = None
            self._drag_current = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if region.w >= 0.01 and region.h >= 0.01:
                self.region_committed.emit(mode, region)
            else:
                self.selection_cancelled.emit()
            self.update()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._edit_kind is None and self._selection_mode is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._selection_mode is not None:
                self.cancel_selection()
                return
            if self._edit_kind is not None:
                self._clear_edit()
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.update()
                return
        super().keyPressEvent(event)
