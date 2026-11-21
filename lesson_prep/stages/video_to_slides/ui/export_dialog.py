"""Export options dialog."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..export.service import ExportOptions


class ExportDialog(QDialog):
    def __init__(
        self,
        default_dir: str,
        options: ExportOptions,
        page_count: int,
        skipped_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("导出幻灯片")
        self.resize(620, 420)
        self._page_count = page_count
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        heading = QLabel(f"将导出 {page_count} 个保留页面" + (f"，跳过 {skipped_count} 页" if skipped_count else ""))
        heading.setStyleSheet("font-size:13pt; font-weight:600; color:#111827;")
        root.addWidget(heading)
        note = QLabel("每次导出都会自动创建一个带时间戳的新文件夹，不会覆盖源视频或原始候选截图。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280;")
        root.addWidget(note)

        folder_box = QGroupBox("导出位置")
        folder_layout = QHBoxLayout(folder_box)
        self.folder_edit = QLineEdit(default_dir)
        self.folder_edit.setPlaceholderText("选择导出父文件夹")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        folder_layout.addWidget(self.folder_edit, 1)
        folder_layout.addWidget(browse)
        root.addWidget(folder_box)

        contents = QGroupBox("导出内容")
        contents_layout = QVBoxLayout(contents)
        self.png_check = QCheckBox("PNG 图片序列（png/slide_001.png …）")
        self.ppt_check = QCheckBox("PPTX 文件（每张图片一页，页面比例匹配图片）")
        self.json_check = QCheckBox("JSON 清单（来源、时间戳、页码、候选状态和人工修改记录）")
        self.raw_check = QCheckBox("在 raw_candidates/ 中保留选定原始候选图")
        self.png_check.setChecked(options.png)
        self.ppt_check.setChecked(options.pptx)
        self.json_check.setChecked(options.json_manifest)
        self.raw_check.setChecked(options.copy_raw_candidates)
        contents_layout.addWidget(self.png_check)
        contents_layout.addWidget(self.ppt_check)
        contents_layout.addWidget(self.json_check)
        contents_layout.addWidget(self.raw_check)
        root.addWidget(contents)
        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("开始导出")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择导出父文件夹", start)
        if folder:
            self.folder_edit.setText(folder)

    def _accept(self) -> None:
        if not any(
            box.isChecked()
            for box in (self.png_check, self.ppt_check, self.json_check)
        ):
            QMessageBox.warning(self, "请选择导出内容", "请至少勾选 PNG、PPTX 或 JSON 清单中的一项。")
            return
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self, "导出目录无效", "请选择一个存在的文件夹。")
            return
        self.accept()

    def output_parent(self) -> str:
        return self.folder_edit.text().strip()

    def export_options(self) -> ExportOptions:
        return ExportOptions(
            png=self.png_check.isChecked(),
            pptx=self.ppt_check.isChecked(),
            json_manifest=self.json_check.isChecked(),
            copy_raw_candidates=self.raw_check.isChecked(),
        )

