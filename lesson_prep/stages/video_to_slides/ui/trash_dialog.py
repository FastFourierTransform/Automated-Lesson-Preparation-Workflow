"""Recycle bin dialog for deleted candidate pages."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from ....core.project import resolve_asset
from ....core.timecode import format_timecode
from ..models import SlidesProject, TrashEntry

TRASH_THUMB_SIZE = QSize(220, 124)


class TrashDialog(QDialog):
    """Display deleted pages and return the entries selected for restoration."""

    def __init__(self, project: SlidesProject, parent=None):
        super().__init__(parent)
        self.project = project
        self._entries = sorted(
            project.trash,
            key=lambda entry: entry.deleted_at or "",
            reverse=True,
        )
        self.setWindowTitle("页面回收站")
        self.resize(940, 620)
        self.setMinimumSize(760, 500)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("页面回收站")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        self.count_label = QLabel(f"{len(self._entries)} 个已删除页面")
        self.count_label.setObjectName("mutedLabel")
        header.addWidget(self.count_label)
        header.addStretch(1)
        root.addLayout(header)

        note = QLabel(
            "删除的候选页面会保留在这里，原始截图不会被删除。"
            "可选择一个或多个页面恢复；恢复后会回到删除前的位置。"
        )
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        root.addWidget(note)

        self.stack = QStackedWidget()
        empty = QLabel("回收站为空。\n\n删除候选页面后，可在这里撤销删除。")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setObjectName("emptyState")
        self.stack.addWidget(empty)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setMovement(QListWidget.Movement.Static)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setIconSize(TRASH_THUMB_SIZE)
        self.list_widget.setGridSize(QSize(250, 205))
        self.list_widget.setSpacing(6)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setWordWrap(True)
        self.list_widget.setObjectName("pageGrid")
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept())
        self.stack.addWidget(self.list_widget)
        root.addWidget(self.stack, 1)

        if self._entries:
            for entry in self._entries:
                page = entry.page
                deleted = (entry.deleted_at or "")[:16].replace("T", " ")
                text = (
                    f"第 {entry.original_index + 1:02d} 页 · "
                    f"{format_timecode(page.selected_time)}\n"
                    f"删除于 {deleted}\n"
                    f"置信度 {page.confidence * 100:.0f}%"
                )
                item = QListWidgetItem(self._icon_for_entry(entry), text)
                item.setData(Qt.ItemDataRole.UserRole, page.id)
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setToolTip(
                    f"删除前第 {entry.original_index + 1} 页\n"
                    f"时间 {format_timecode(page.selected_time, milliseconds=True)}\n"
                    f"删除原因：{entry.reason}"
                )
                self.list_widget.addItem(item)
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

        buttons = QHBoxLayout()
        self.select_all_button = QPushButton("全选")
        self.select_all_button.clicked.connect(self._select_all)
        self.select_all_button.setEnabled(bool(self._entries))
        buttons.addWidget(self.select_all_button)
        buttons.addStretch(1)
        cancel = QPushButton("关闭")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.restore_button = QPushButton("恢复所选")
        self.restore_button.setObjectName("primary")
        self.restore_button.clicked.connect(self._accept)
        buttons.addWidget(self.restore_button)
        root.addLayout(buttons)
        self._update_buttons()

    def _icon_for_entry(self, entry: TrashEntry) -> QIcon:
        canvas = QPixmap(TRASH_THUMB_SIZE)
        canvas.fill(QColor("#e5e7eb"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        page = entry.page
        alt = page.selected_alternative()
        pixmap = QPixmap()
        if alt is not None:
            thumb = resolve_asset(self.project, alt.thumb_path)
            raw = resolve_asset(self.project, alt.raw_path)
            if thumb and thumb.is_file():
                pixmap = QPixmap(str(thumb))
            elif raw and raw.is_file():
                pixmap = QPixmap(str(raw))
        if pixmap.isNull():
            painter.setPen(QColor("#6b7280"))
            painter.setFont(QFont(self.font().family(), 9))
            painter.drawText(
                canvas.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "截图文件缺失",
            )
        else:
            scaled = pixmap.scaled(
                TRASH_THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (TRASH_THUMB_SIZE.width() - scaled.width()) // 2,
                (TRASH_THUMB_SIZE.height() - scaled.height()) // 2,
                scaled,
            )
        painter.end()
        return QIcon(canvas)

    def _select_all(self) -> None:
        self.list_widget.selectAll()
        self._update_buttons()

    def _update_buttons(self) -> None:
        selected = len(self.list_widget.selectedItems()) if self._entries else 0
        self.restore_button.setEnabled(selected > 0)
        if selected:
            self.restore_button.setText(f"恢复所选（{selected}）")
        else:
            self.restore_button.setText("恢复所选")

    def _accept(self) -> None:
        if not self.selected_entries():
            QMessageBox.information(self, "未选择页面", "请先选择要恢复的页面。")
            return
        self.accept()

    def selected_entries(self) -> list[TrashEntry]:
        selected_ids = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.list_widget.selectedItems()
        }
        return [entry for entry in self._entries if entry.page.id in selected_ids]


