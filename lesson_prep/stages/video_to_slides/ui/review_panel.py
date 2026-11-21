"""Manual review workspace for detected slide candidates."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ....core.geometry import bgr_to_qimage
from ....core.project import resolve_asset
from ....core.timecode import format_timecode
from ..export.processor import SlideImageError, process_selected_image
from ..models import FLAG_LABELS, PageCandidate, SlidesProject

THUMB_SIZE = QSize(240, 135)
ALT_THUMB_SIZE = QSize(96, 54)


class ScaledImageLabel(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击打开大图")

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def has_image(self) -> bool:
        return not self._image.isNull()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        if self._image.isNull():
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选择候选页面以查看截图")
            return
        available = self.rect().adjusted(6, 6, -6, -6)
        scaled = self._image.size().scaled(available.size(), Qt.AspectRatioMode.KeepAspectRatio)
        left = available.left() + (available.width() - scaled.width()) / 2
        top = available.top() + (available.height() - scaled.height()) / 2
        painter.drawImage(
            QRectF(left, top, scaled.width(), scaled.height()),
            self._image,
        )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.has_image():
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ReviewPanel(QWidget):
    changed = Signal()
    locate_requested = Signal(float)
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: SlidesProject | None = None
        self._current_page_id: str | None = None
        self._updating = False
        self._icon_cache: dict[tuple, QIcon] = {}
        self._alt_icon_cache: dict[str, QIcon] = {}
        self._current_image = QImage()
        self._edit_enabled = True
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("候选页面复核")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        self.count_label = QLabel("尚未分析")
        self.count_label.setObjectName("mutedLabel")
        header.addWidget(self.count_label)
        header.addStretch(1)

        self.locate_button = self._tool_button("定位视频", self._locate_current)
        self.up_button = self._tool_button("上移", lambda: self._move_current(-1))
        self.down_button = self._tool_button("下移", lambda: self._move_current(1))
        self.delete_button = self._tool_button("删除", self._delete_current)
        self.trash_button = self._tool_button("回收站", self._open_trash)
        self.skip_low_button = self._tool_button("跳过低置信度", self._skip_low_confidence)
        self.keep_all_button = self._tool_button("全部保留", self._keep_all)
        for button in (
            self.locate_button,
            self.up_button,
            self.down_button,
            self.delete_button,
            self.trash_button,
            self.skip_low_button,
            self.keep_all_button,
        ):
            header.addWidget(button)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.stack = QStackedWidget()
        self.stack.setMinimumWidth(500)
        empty = QLabel("尚未生成候选页面。\n\n导入视频、设置正片区间与 PPT 区域后，点击“开始分析”。\n分析完成后可在此删除、排序、切换备选帧和标记跳过。")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setObjectName("emptyState")
        empty.setWordWrap(True)
        self.stack.addWidget(empty)

        self.page_list = QListWidget()
        self.page_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.page_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.page_list.setMovement(QListWidget.Movement.Static)
        self.page_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.page_list.setIconSize(THUMB_SIZE)
        self.page_list.setGridSize(QSize(268, 206))
        self.page_list.setSpacing(6)
        self.page_list.setUniformItemSizes(True)
        self.page_list.setWordWrap(True)
        self.page_list.setObjectName("pageGrid")
        self.page_list.currentItemChanged.connect(self._on_page_changed)
        self.page_list.itemDoubleClicked.connect(lambda _item: self._open_large())
        self.page_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.page_list.customContextMenuRequested.connect(self._show_context_menu)
        self.stack.addWidget(self.page_list)
        splitter.addWidget(self.stack)

        details = QWidget()
        details.setObjectName("detailsPanel")
        details.setMinimumWidth(380)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(10, 8, 8, 8)
        details_layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.image_label = ScaledImageLabel()
        self.image_label.clicked.connect(self._open_large)
        top_row.addWidget(self.image_label, 3)

        info_column = QVBoxLayout()
        info_column.setSpacing(3)
        self.page_title = QLabel("未选择页面")
        self.page_title.setObjectName("pageTitle")
        self.page_title.setWordWrap(True)
        info_column.addWidget(self.page_title)

        meta_row = QHBoxLayout()
        self.confidence_label = QLabel("")
        self.review_state_label = QLabel("")
        meta_row.addWidget(self.confidence_label)
        meta_row.addWidget(self.review_state_label)
        meta_row.addStretch(1)
        info_column.addLayout(meta_row)

        self.interval_label = QLabel("")
        self.interval_label.setObjectName("mutedLabel")
        self.interval_label.setWordWrap(True)
        info_column.addWidget(self.interval_label)

        self.flags_label = QLabel("")
        self.flags_label.setWordWrap(True)
        info_column.addWidget(self.flags_label)

        self.keep_checkbox = QCheckBox("保留此页（参与导出）")
        self.keep_checkbox.toggled.connect(self._on_keep_toggled)
        info_column.addWidget(self.keep_checkbox)
        info_column.addStretch(1)
        top_row.addLayout(info_column, 2)
        details_layout.addLayout(top_row, 1)

        alt_header = QHBoxLayout()
        alt_title = QLabel("备选帧（点击切换）")
        alt_title.setObjectName("subTitle")
        alt_header.addWidget(alt_title)
        alt_header.addStretch(1)
        self.note_button = self._tool_button("备注…", self._edit_note)
        self.open_button = self._tool_button("打开大图", self._open_large)
        alt_header.addWidget(self.note_button)
        alt_header.addWidget(self.open_button)
        details_layout.addLayout(alt_header)

        self.alt_list = QListWidget()
        self.alt_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.alt_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.alt_list.setMovement(QListWidget.Movement.Static)
        self.alt_list.setIconSize(ALT_THUMB_SIZE)
        self.alt_list.setGridSize(QSize(128, 86))
        self.alt_list.setFixedHeight(90)
        self.alt_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.alt_list.setObjectName("altGrid")
        self.alt_list.currentItemChanged.connect(self._on_alt_changed)
        details_layout.addWidget(self.alt_list)

        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details_scroll.setWidget(details)
        details_scroll.setMinimumWidth(390)
        splitter.addWidget(details_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 500])
        root.addWidget(splitter, 1)
        self.details_widget = details
        self._set_buttons_enabled(False)

    def _tool_button(self, text: str, slot) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.clicked.connect(slot)
        button.setObjectName("reviewTool")
        return button

    def set_project(self, project: SlidesProject | None) -> None:
        self.project = project
        self._current_page_id = None
        self._icon_cache.clear()
        self._alt_icon_cache.clear()
        self._rebuild_list()

    def set_edit_enabled(self, enabled: bool) -> None:
        self._edit_enabled = enabled
        self.page_list.setEnabled(enabled)
        self.details_widget.setEnabled(enabled)
        selected = enabled and self._has_selection()
        for button in (
            self.locate_button,
            self.up_button,
            self.down_button,
            self.delete_button,
        ):
            button.setEnabled(selected)
        has_pages = enabled and bool(self.project and self.project.pages)
        self.skip_low_button.setEnabled(has_pages)
        self.keep_all_button.setEnabled(has_pages)
        self._update_trash_button()

    def _has_selection(self) -> bool:
        return bool(self._current_page_id and self.project and self._page_by_id(self._current_page_id))

    def _page_by_id(self, page_id: str) -> PageCandidate | None:
        if not self.project:
            return None
        return next((p for p in self.project.pages if p.id == page_id), None)

    def _page_index(self, page_id: str) -> int:
        if not self.project:
            return -1
        return next((i for i, p in enumerate(self.project.pages) if p.id == page_id), -1)

    def _rebuild_list(self, select_page_id: str | None = None) -> None:
        self._updating = True
        try:
            self.page_list.clear()
            self.alt_list.clear()
            self._current_image = QImage()
            self.image_label.set_image(QImage())
            pages = self.project.pages if self.project else []
            self._update_trash_button()
            if not pages:
                self.stack.setCurrentIndex(0)
                self.count_label.setText("尚未分析" if self.project is None else "没有候选页面")
                self._current_page_id = None
                self._show_empty_details()
                return
            self.stack.setCurrentIndex(1)
            target_id = select_page_id or self._current_page_id
            target_row = 0
            for index, page in enumerate(pages):
                item = QListWidgetItem(self._page_icon(page), self._page_item_text(page, index))
                item.setData(Qt.ItemDataRole.UserRole, page.id)
                item.setToolTip(
                    f"第 {index + 1} 页 · {format_timecode(page.selected_time, milliseconds=True)}"
                    f"\n置信度 {page.confidence * 100:.0f}%"
                    + (f"\n{page.label_flags}" if page.flags else "")
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.page_list.addItem(item)
                if page.id == target_id:
                    target_row = index
            self.count_label.setText(
                f"共 {len(pages)} 页 · 保留 {len(self.project.active_pages())} 页"
                if self.project
                else ""
            )
            self.page_list.setCurrentRow(target_row)
            self.page_list.scrollToItem(self.page_list.item(target_row), QAbstractItemView.ScrollHint.PositionAtCenter)
        finally:
            self._updating = False
        current = self.page_list.currentItem()
        if current is not None:
            self._current_page_id = current.data(Qt.ItemDataRole.UserRole)
            self._show_details(self._page_by_id(self._current_page_id))

    def _page_item_text(self, page: PageCandidate, index: int) -> str:
        state = "保留" if page.kept else "已跳过"
        review = " · 待复核" if page.needs_review else ""
        line = f"#{index + 1:02d}  {format_timecode(page.selected_time)}\n{state} · 置信度 {page.confidence * 100:.0f}%{review}"
        if page.flags:
            labels = [FLAG_LABELS.get(flag, flag) for flag in page.flags if flag != "low_confidence"]
            if labels:
                line += "\n⚠ " + " / ".join(labels[:2])
        return line

    def _page_icon(self, page: PageCandidate) -> QIcon:
        key = (page.id, page.selected_raw_path, page.kept, tuple(page.flags), page.needs_review)
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        canvas = QPixmap(THUMB_SIZE)
        canvas.fill(QColor("#e5e7eb"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        alt = page.selected_alternative()
        pixmap = QPixmap()
        if alt is not None:
            thumb = resolve_asset(self.project, alt.thumb_path) if self.project else None
            raw = resolve_asset(self.project, alt.raw_path) if self.project else None
            if thumb and thumb.is_file():
                pixmap = QPixmap(str(thumb))
            elif raw and raw.is_file():
                pixmap = QPixmap(str(raw))
        if pixmap.isNull():
            painter.setPen(QColor("#6b7280"))
            painter.setFont(QFont(self.font().family(), 9))
            painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "截图缺失")
        else:
            scaled = pixmap.scaled(
                THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            left = (THUMB_SIZE.width() - scaled.width()) // 2
            top = (THUMB_SIZE.height() - scaled.height()) // 2
            painter.drawPixmap(left, top, scaled)
        if not page.kept:
            painter.fillRect(canvas.rect(), QColor(17, 24, 39, 120))
            painter.setPen(QColor("#f9fafb"))
            painter.setFont(QFont(self.font().family(), 11, QFont.Weight.Bold))
            painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "已跳过")
        if page.needs_review:
            painter.setBrush(QColor("#f59e0b"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(THUMB_SIZE.width() - 78, 8, 68, 22, 5, 5)
            painter.setPen(QColor("#111827"))
            painter.setFont(QFont(self.font().family(), 8, QFont.Weight.DemiBold))
            painter.drawText(
                THUMB_SIZE.width() - 78,
                8,
                68,
                22,
                Qt.AlignmentFlag.AlignCenter,
                "需复核",
            )
        painter.end()
        icon = QIcon(canvas)
        self._icon_cache[key] = icon
        return icon

    def _alt_icon(self, alt) -> QIcon:
        cached = self._alt_icon_cache.get(alt.raw_path)
        if cached is not None:
            return cached
        canvas = QPixmap(ALT_THUMB_SIZE)
        canvas.fill(QColor("#e5e7eb"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        pixmap = QPixmap()
        if self.project:
            thumb = resolve_asset(self.project, alt.thumb_path)
            raw = resolve_asset(self.project, alt.raw_path)
            if thumb and thumb.is_file():
                pixmap = QPixmap(str(thumb))
            elif raw and raw.is_file():
                pixmap = QPixmap(str(raw))
        if pixmap.isNull():
            painter.setPen(QColor("#6b7280"))
            painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "缺失")
        else:
            scaled = pixmap.scaled(
                ALT_THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (ALT_THUMB_SIZE.width() - scaled.width()) // 2,
                (ALT_THUMB_SIZE.height() - scaled.height()) // 2,
                scaled,
            )
        painter.end()
        icon = QIcon(canvas)
        self._alt_icon_cache[alt.raw_path] = icon
        return icon

    def _on_page_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._updating or current is None:
            return
        self._current_page_id = current.data(Qt.ItemDataRole.UserRole)
        page = self._page_by_id(self._current_page_id)
        self._show_details(page)

    def _show_empty_details(self) -> None:
        self.page_title.setText("未选择页面")
        self.confidence_label.setText("")
        self.review_state_label.setText("")
        self.interval_label.setText("")
        self.flags_label.setText("")
        self.note_button.setText("备注…")
        self.note_button.setToolTip("")
        self.alt_list.clear()
        self.image_label.set_image(QImage())
        self._current_image = QImage()
        self._set_buttons_enabled(False)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.locate_button.setEnabled(enabled)
        self.up_button.setEnabled(enabled)
        self.down_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.skip_low_button.setEnabled(bool(self.project and self.project.pages))
        self.keep_all_button.setEnabled(bool(self.project and self.project.pages))
        self.open_button.setEnabled(enabled)
        self.note_button.setEnabled(enabled)
        self.keep_checkbox.setEnabled(enabled)
        self.alt_list.setEnabled(enabled)
        self._update_trash_button()

    def _show_details(self, page: PageCandidate | None) -> None:
        if page is None or not self.project:
            self._show_empty_details()
            return
        index = self._page_index(page.id)
        self._updating = True
        try:
            alt = page.selected_alternative()
            self._current_image = QImage()
            try:
                processed = process_selected_image(self.project, page, apply_camera=True)
                self._current_image = bgr_to_qimage(processed.image)
            except SlideImageError:
                self._current_image = QImage()
            self.image_label.set_image(self._current_image)
            self.image_label.setToolTip(
                "点击打开大图"
                if not self._current_image.isNull()
                else "截图文件缺失或无法读取"
            )
            title = f"第 {index + 1} 页 · {format_timecode(page.selected_time, milliseconds=True)}"
            if page.manually_modified:
                title += "  ·  已人工修改"
            self.page_title.setText(title)
            confidence_pct = page.confidence * 100
            color = "#15803d" if confidence_pct >= 75 else ("#b45309" if confidence_pct >= 55 else "#b91c1c")
            self.confidence_label.setText(f"置信度 {confidence_pct:.0f}%")
            self.confidence_label.setStyleSheet(f"color:{color}; font-weight:600;")
            if page.needs_review:
                self.review_state_label.setText("⚠ 建议人工复核")
                self.review_state_label.setStyleSheet("color:#b45309; font-weight:600;")
            else:
                self.review_state_label.setText("✓ 自动检测正常")
                self.review_state_label.setStyleSheet("color:#15803d;")
            self.interval_label.setText(
                f"候选区间 {format_timecode(page.interval_start, milliseconds=True)} – "
                f"{format_timecode(page.interval_end, milliseconds=True)} · "
                f"来源：{', '.join(page.sources) if page.sources else '未知'}"
            )
            if page.flags:
                self.flags_label.setText(
                    "标记：" + "、".join(FLAG_LABELS.get(flag, flag) for flag in page.flags)
                )
                self.flags_label.setStyleSheet("color:#b45309;")
            else:
                self.flags_label.setText("未发现明显异常。")
                self.flags_label.setStyleSheet("color:#6b7280;")
            self.keep_checkbox.setChecked(page.kept)
            self.note_button.setText("备注 ●" if page.review_note else "备注…")
            self.note_button.setToolTip(page.review_note or "添加复核备注")

            self.alt_list.clear()
            for alt_item in sorted(page.alternatives, key=lambda a: a.time_sec):
                flags = " ⚠" if alt_item.flags else ""
                text = f"{format_timecode(alt_item.time_sec, milliseconds=True)}{flags}"
                item = QListWidgetItem(self._alt_icon(alt_item), text)
                item.setData(Qt.ItemDataRole.UserRole, alt_item.raw_path)
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setToolTip(
                    f"{format_timecode(alt_item.time_sec, milliseconds=True)} · "
                    f"质量 {alt_item.quality * 100:.0f}%"
                    + (f" · {FLAG_LABELS.get(alt_item.flags[0], alt_item.flags[0])}" if alt_item.flags else "")
                )
                self.alt_list.addItem(item)
                if alt and alt_item.raw_path == alt.raw_path:
                    self.alt_list.setCurrentItem(item)
        finally:
            self._updating = False
        self._set_buttons_enabled(True)

    def _on_alt_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._updating or current is None or not self.project:
            return
        page = self._page_by_id(self._current_page_id) if self._current_page_id else None
        if page is None:
            return
        raw_path = current.data(Qt.ItemDataRole.UserRole)
        alt = next((a for a in page.alternatives if a.raw_path == raw_path), None)
        if alt is None or page.selected_raw_path == alt.raw_path:
            return
        page.select_alternative(alt)
        page.manually_modified = True
        self.project.history(
            "select_alternative",
            f"切换到备选帧 {format_timecode(alt.time_sec, milliseconds=True)}",
            page.id,
        )
        self._icon_cache.clear()
        row = self.page_list.currentRow()
        item = self.page_list.item(row)
        if item is not None:
            item.setIcon(self._page_icon(page))
            item.setText(self._page_item_text(page, row))
        self._show_details(page)
        self.count_label.setText(
            f"共 {len(self.project.pages)} 页 · 保留 {len(self.project.active_pages())} 页"
        )
        self.changed.emit()
        self.status_message.emit(f"已切换第 {row + 1} 页的备选帧。")

    def _on_keep_toggled(self, checked: bool) -> None:
        if self._updating or not self.project or not self._current_page_id:
            return
        page = self._page_by_id(self._current_page_id)
        if page is None or page.kept == checked:
            return
        page.kept = checked
        page.manually_modified = True
        self.project.history(
            "set_kept",
            "保留页面" if checked else "跳过页面",
            page.id,
        )
        row = self.page_list.currentRow()
        item = self.page_list.item(row)
        if item is not None:
            item.setIcon(self._page_icon(page))
            item.setText(self._page_item_text(page, row))
        self.count_label.setText(
            f"共 {len(self.project.pages)} 页 · 保留 {len(self.project.active_pages())} 页"
        )
        self.changed.emit()
        self.status_message.emit("页面已设为保留。" if checked else "页面已设为跳过。")

    def _edit_note(self) -> None:
        if self._updating or not self.project or not self._current_page_id:
            return
        page = self._page_by_id(self._current_page_id)
        if page is None:
            return
        text, accepted = QInputDialog.getText(
            self,
            "复核备注",
            "这一页的备注（会保存到项目和 JSON 清单）：",
            text=page.review_note,
        )
        if not accepted:
            return
        text = text.strip()
        if text == page.review_note:
            return
        page.review_note = text
        page.manually_modified = True
        self.project.history("set_note", text or "清空备注", page.id)
        self.note_button.setText("备注 ●" if text else "备注…")
        self.note_button.setToolTip(text or "添加复核备注")
        self.changed.emit()

    def _locate_current(self) -> None:
        page = self._page_by_id(self._current_page_id) if self._current_page_id else None
        if page is not None:
            self.locate_requested.emit(page.selected_time)

    def _open_large(self) -> None:
        if self._current_image.isNull():
            QMessageBox.information(self, "无法预览", "当前页面没有可用的截图文件。")
            return
        from ....core.ui.image_dialog import ImagePreviewDialog

        page = self._page_by_id(self._current_page_id) if self._current_page_id else None
        index = self._page_index(page.id) + 1 if page else 0
        title = (
            f"第 {index} 页 · {format_timecode(page.selected_time, milliseconds=True)}"
            if page
            else "大图预览"
        )
        ImagePreviewDialog(self._current_image, title, self).exec()

    def _move_current(self, delta: int) -> None:
        if not self.project or not self._current_page_id:
            return
        index = self._page_index(self._current_page_id)
        target = index + delta
        if index < 0 or target < 0 or target >= len(self.project.pages):
            return
        pages = self.project.pages
        pages[index], pages[target] = pages[target], pages[index]
        pages[index].manually_modified = True
        pages[target].manually_modified = True
        self.project.history(
            "reorder_page",
            f"第 {index + 1} 页移动到第 {target + 1} 页",
            self._current_page_id,
        )
        self._rebuild_list(select_page_id=self._current_page_id)
        self.changed.emit()
        self.status_message.emit("页面顺序已调整。")

    def _update_trash_button(self) -> None:
        count = len(self.project.trash) if self.project else 0
        self.trash_button.setText(f"回收站（{count}）" if count else "回收站")
        self.trash_button.setEnabled(bool(self._edit_enabled and self.project and count))
        self.trash_button.setToolTip(
            f"回收站中有 {count} 个已删除页面，可打开并恢复。" if count else "回收站为空。"
        )

    def _delete_current(self) -> None:
        if not self.project or not self._current_page_id:
            return
        page = self._page_by_id(self._current_page_id)
        index = self._page_index(self._current_page_id)
        if page is None or index < 0:
            return
        # Deletion is immediate; the page can be restored from the recycle bin.
        entry = self.project.move_page_to_trash(page.id)
        if entry is None:
            return
        self.project.history(
            "delete_page",
            f"删除第 {index + 1} 页 {format_timecode(page.selected_time, milliseconds=True)}（已移入回收站）",
            page.id,
        )
        self._current_page_id = None
        next_id = None
        if self.project.pages:
            next_index = min(index, len(self.project.pages) - 1)
            next_id = self.project.pages[next_index].id
        self._rebuild_list(select_page_id=next_id)
        self.changed.emit()
        self.status_message.emit("候选页面已移入回收站，可通过“回收站”按钮恢复。")

    def _open_trash(self) -> None:
        if not self.project:
            return
        from .trash_dialog import TrashDialog

        dialog = TrashDialog(self.project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._update_trash_button()
            return
        entries = dialog.selected_entries()
        if not entries:
            return
        restored = self.project.restore_trash_entries(
            [entry.page.id for entry in entries]
        )
        if not restored:
            return
        for page in restored:
            self.project.history(
                "restore_page",
                f"从回收站恢复 {format_timecode(page.selected_time, milliseconds=True)}",
                page.id,
            )
        self._icon_cache.clear()
        self._alt_icon_cache.clear()
        self._current_page_id = restored[0].id
        self._rebuild_list(select_page_id=restored[0].id)
        self.changed.emit()
        self.status_message.emit(f"已从回收站恢复 {len(restored)} 个候选页面。")

    def _skip_low_confidence(self) -> None:
        if not self.project:
            return
        threshold = self.project.settings.min_confidence
        targets = [
            page
            for page in self.project.pages
            if page.kept and (page.confidence < threshold or "low_confidence" in page.flags)
        ]
        if not targets:
            QMessageBox.information(self, "没有低置信度页面", "当前所有保留页面的置信度都高于阈值。")
            return
        answer = QMessageBox.question(
            self,
            "跳过低置信度页面",
            f"将跳过 {len(targets)} 个置信度低于 {threshold * 100:.0f}% 的页面。\n"
            "页面不会被删除，之后仍可重新勾选保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for page in targets:
            page.kept = False
            page.manually_modified = True
        self.project.history("skip_low_confidence", f"跳过 {len(targets)} 个低置信度页面")
        self._rebuild_list(select_page_id=self._current_page_id)
        self.changed.emit()
        self.status_message.emit(f"已跳过 {len(targets)} 个低置信度页面。")

    def _keep_all(self) -> None:
        if not self.project:
            return
        changed = 0
        for page in self.project.pages:
            if not page.kept:
                page.kept = True
                page.manually_modified = True
                changed += 1
        if changed:
            self.project.history("keep_all", f"恢复保留 {changed} 个页面")
            self._rebuild_list(select_page_id=self._current_page_id)
            self.changed.emit()
            self.status_message.emit(f"已恢复保留 {changed} 个页面。")
        else:
            self.status_message.emit("所有页面均已保留。")

    def _show_context_menu(self, position) -> None:
        item = self.page_list.itemAt(position)
        if item is None:
            return
        self.page_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("查看大图", self._open_large)
        menu.addAction("定位原视频", self._locate_current)
        menu.addSeparator()
        menu.addAction("上移", lambda: self._move_current(-1))
        menu.addAction("下移", lambda: self._move_current(1))
        menu.addAction("删除", self._delete_current)
        menu.exec(self.page_list.mapToGlobal(position))

    def focus_page(self, page_id: str) -> None:
        self._rebuild_list(select_page_id=page_id)

    def refresh_current(self) -> None:
        """Refresh processed previews without discarding the user's selection."""
        self._icon_cache.clear()
        self._alt_icon_cache.clear()
        self._rebuild_list(select_page_id=self._current_page_id)


