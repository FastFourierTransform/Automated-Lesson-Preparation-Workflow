"""Advanced, user-editable analysis parameters."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import AnalysisSettings


class AnalysisSettingsDialog(QDialog):
    def __init__(self, settings: AnalysisSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分析参数")
        self.resize(720, 760)
        self._initial = replace(settings)
        self._controls: dict[str, object] = {}
        root = QVBoxLayout(self)
        note = QLabel(
            "修改参数后需要重新分析视频。默认参数适合大多数网课录屏；"
            "若漏检，可降低变化阈值；若误检笔迹/动画，可提高变化阈值或稳定时间。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#4b5563; padding:4px;")
        root.addWidget(note)

        tabs = QTabWidget()
        tabs.addTab(self._build_basic_tab(settings), "基础")
        tabs.addTab(self._build_threshold_tab(settings), "变化检测")
        tabs.addTab(self._build_stability_tab(settings), "稳定与合并")
        tabs.addTab(self._build_quality_tab(settings), "画质与保存")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        restore = QPushButton("恢复默认")
        restore.clicked.connect(self._restore_defaults)
        buttons.addButton(restore, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _scroll_form(self, groups: list[QGroupBox]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        for group in groups:
            layout.addWidget(group)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Reparent for ownership; tabs take ownership of the scroll area.
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll)
        scroll.setWidget(widget)
        return wrapper

    def _double(
        self,
        key: str,
        value: float,
        minimum: float,
        maximum: float,
        decimals: int = 2,
        step: float = 0.1,
        suffix: str = "",
        tooltip: str = "",
        scale: float = 1.0,
    ) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(minimum * scale, maximum * scale)
        box.setDecimals(decimals)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        box.setValue(value * scale)
        box.setToolTip(tooltip)
        box.setKeyboardTracking(False)
        self._controls[key] = (box, scale)
        return box

    def _integer(
        self,
        key: str,
        value: int,
        minimum: int,
        maximum: int,
        step: int = 1,
        suffix: str = "",
        tooltip: str = "",
    ) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        box.setValue(int(value))
        box.setToolTip(tooltip)
        box.setKeyboardTracking(False)
        self._controls[key] = (box, 1)
        return box

    def _build_basic_tab(self, settings: AnalysisSettings) -> QWidget:
        scan = QGroupBox("采样")
        form = QFormLayout(scan)
        form.addRow(
            "粗扫描采样率（帧/秒）",
            self._double(
                "coarse_fps", settings.coarse_fps, 0.5, 12, 1, 0.5, " fps",
                "第一级低成本扫描。默认 3 fps，适合大多数网课。",
            ),
        )
        form.addRow(
            "稳定帧采样率（帧/秒）",
            self._double(
                "refine_fps", settings.refine_fps, 2, 30, 1, 1, " fps",
                "第二级在疑似切页附近提高采样率。默认 8 fps。",
            ),
        )
        form.addRow(
            "分析缩放宽度（像素）",
            self._integer(
                "analysis_width", settings.analysis_width, 160, 1280, 32, " px",
                "仅影响分析，不影响导出图片的原始分辨率。",
            ),
        )

        stability = QGroupBox("页面稳定")
        form2 = QFormLayout(stability)
        form2.addRow(
            "稳定持续时间（秒）",
            self._double(
                "stable_duration_sec", settings.stable_duration_sec, 0.1, 10, 2, 0.05, " s",
                "页面需持续稳定这么久，才会被视为切页完成。",
            ),
        )
        form2.addRow(
            "每页最多备选帧",
            self._integer(
                "max_alternatives", settings.max_alternatives, 1, 12, 1, " 个",
                "每个候选页面保存的备选时间点数量。",
            ),
        )
        form2.addRow(
            "备选帧最小间隔（秒）",
            self._double(
                "alternative_min_gap_sec", settings.alternative_min_gap_sec, 0.05, 5, 2, 0.1, " s"
            ),
        )
        form2.addRow(
            "备选帧最大跨度（秒）",
            self._double(
                "max_alternative_span_sec", settings.max_alternative_span_sec, 1, 60, 1, 1, " s"
            ),
        )
        form2.addRow(
            "低置信度阈值",
            self._double(
                "min_confidence", settings.min_confidence, 0, 1, 0, 5, " %",
                "低于此分数的页面会标记为需要人工复核（不会自动删除）。",
                scale=100,
            ),
        )

        scene = QGroupBox("PySceneDetect 辅助候选")
        form3 = QFormLayout(scene)
        self._scene_enabled = QCheckBox("启用 PySceneDetect 场景候选（推荐）")
        self._scene_enabled.setChecked(settings.use_pyscenedetect)
        self._scene_enabled.setToolTip("只作为候选来源；仍会经过稳定帧与差异验证，不会把每个场景切换直接当作一页。")
        form3.addRow(self._scene_enabled)
        form3.addRow(
            "场景检测阈值",
            self._double(
                "pyscenedetect_threshold", settings.pyscenedetect_threshold, 1, 100, 1, 1,
                tooltip="ContentDetector 阈值，越低越敏感。默认 27。",
            ),
        )
        form3.addRow(
            "最小场景长度（秒）",
            self._double(
                "pyscenedetect_min_scene_sec", settings.pyscenedetect_min_scene_sec,
                0.1, 30, 1, 0.1, " s",
            ),
        )
        return self._scroll_form([scan, stability, scene])

    def _build_threshold_tab(self, settings: AnalysisSettings) -> QWidget:
        coarse = QGroupBox("粗扫描变化判定")
        form = QFormLayout(coarse)
        form.addRow(
            "像素差异阈值（灰度级）",
            self._integer(
                "pixel_diff_threshold", settings.pixel_diff_threshold, 1, 128, 1,
                tooltip="单个像素差值超过此值才计入变化区域。默认 25。",
            ),
        )
        form.addRow(
            "变化区域比例阈值",
            self._double(
                "coarse_change_ratio_threshold", settings.coarse_change_ratio_threshold,
                0.005, 0.9, 1, 0.5, " %",
                "发生变化像素占 PPT 有效区域的比例。默认 8%。",
                scale=100,
            ),
        )
        form.addRow(
            "SSIM 相似度阈值",
            self._double(
                "coarse_ssim_threshold", settings.coarse_ssim_threshold,
                0.1, 0.999, 3, 0.005,
                "结构相似度低于此值时视为可能切页。默认 0.86。",
            ),
        )
        form.addRow(
            "平均绝对差异阈值",
            self._double(
                "coarse_mad_threshold", settings.coarse_mad_threshold,
                1, 100, 1, 0.5,
                "灰度平均绝对差。默认 12。",
            ),
        )
        grouping = QGroupBox("候选区间合并")
        form2 = QFormLayout(grouping)
        form2.addRow(
            "变化分组间隔（秒）",
            self._double(
                "change_group_gap_sec", settings.change_group_gap_sec, 0.05, 10, 2, 0.05, " s",
                "间隔在此范围内的变化点视为同一次过渡。",
            ),
        )
        form2.addRow(
            "短页面阈值（秒）",
            self._double(
                "short_page_sec", settings.short_page_sec, 0.05, 10, 2, 0.05, " s",
                "页面持续时间低于此值时标记为需要复核。",
            ),
        )
        return self._scroll_form([coarse, grouping])

    def _build_stability_tab(self, settings: AnalysisSettings) -> QWidget:
        stable = QGroupBox("稳定帧判定")
        form = QFormLayout(stable)
        form.addRow(
            "稳定区域变化比例",
            self._double(
                "stable_change_ratio_threshold", settings.stable_change_ratio_threshold,
                0.001, 0.5, 1, 0.1, " %",
                "低于此值可视为页面几乎未变化。笔迹通常只覆盖很小区域。",
                scale=100,
            ),
        )
        form.addRow(
            "稳定 SSIM 阈值",
            self._double(
                "stable_ssim_threshold", settings.stable_ssim_threshold,
                0.5, 0.9999, 4, 0.001,
                "相邻采样帧的 SSIM 高于此值表示稳定。默认 0.975。",
            ),
        )
        form.addRow(
            "稳定平均差异阈值",
            self._double(
                "stable_mad_threshold", settings.stable_mad_threshold,
                0.2, 60, 2, 0.2,
                "相邻采样帧的平均绝对差低于此值表示稳定。默认 6。",
            ),
        )
        refine = QGroupBox("第二级采样窗口")
        form2 = QFormLayout(refine)
        form2.addRow(
            "向前回看（秒）",
            self._double(
                "refine_before_sec", settings.refine_before_sec, 0, 10, 2, 0.1, " s"
            ),
        )
        form2.addRow(
            "向后搜索（秒）",
            self._double(
                "refine_after_sec", settings.refine_after_sec, 1, 30, 2, 0.5, " s",
                "在切页后多长时间内寻找稳定画面。",
            ),
        )
        duplicate = QGroupBox("重复页面合并")
        form3 = QFormLayout(duplicate)
        form3.addRow(
            "自动合并 SSIM",
            self._double(
                "duplicate_ssim_threshold", settings.duplicate_ssim_threshold,
                0.8, 0.9999, 4, 0.001,
                "相邻页面图像非常相似时自动合并。",
            ),
        )
        form3.addRow(
            "自动合并变化比例",
            self._double(
                "duplicate_change_ratio_threshold", settings.duplicate_change_ratio_threshold,
                0, 0.5, 1, 0.1, " %", scale=100,
            ),
        )
        form3.addRow(
            "可疑重复 SSIM",
            self._double(
                "uncertain_duplicate_ssim", settings.uncertain_duplicate_ssim,
                0.5, 0.9999, 4, 0.001,
                "相似但未达到自动合并条件时，保留并标记人工复核。",
            ),
        )
        form3.addRow(
            "可疑重复变化比例",
            self._double(
                "uncertain_duplicate_change_ratio", settings.uncertain_duplicate_change_ratio,
                0, 0.9, 1, 0.5, " %", scale=100,
            ),
        )
        return self._scroll_form([stable, refine, duplicate])

    def _build_quality_tab(self, settings: AnalysisSettings) -> QWidget:
        quality = QGroupBox("画质异常标记")
        form = QFormLayout(quality)
        form.addRow(
            "黑屏亮度阈值",
            self._double(
                "black_luma_threshold", settings.black_luma_threshold, 0, 100, 1, 1,
                "平均亮度低于此值且对比度低时视为黑屏。",
            ),
        )
        form.addRow(
            "黑屏对比度阈值",
            self._double(
                "black_std_threshold", settings.black_std_threshold, 0, 80, 1, 1,
            ),
        )
        form.addRow(
            "模糊拉普拉斯阈值",
            self._double(
                "blur_lap_var_threshold", settings.blur_lap_var_threshold,
                1, 5000, 1, 5,
                "低于此值标记为画面模糊，仍会保留。",
            ),
        )
        form.addRow(
            "清晰参考值",
            self._double(
                "blur_good_lap_var", settings.blur_good_lap_var, 10, 10000, 1, 10,
                "用于计算清晰度得分，不是硬性过滤。",
            ),
        )
        storage = QGroupBox("截图保存")
        form2 = QFormLayout(storage)
        form2.addRow(
            "候选 JPEG 质量",
            self._integer(
                "snapshot_jpeg_quality", settings.snapshot_jpeg_quality, 50, 100, 1,
                tooltip="原始候选帧以 JPEG 保存以节省磁盘；导出 PNG 由这些原始帧转换。",
            ),
        )
        form2.addRow(
            "缩略图宽度",
            self._integer("thumbnail_width", settings.thumbnail_width, 120, 960, 20, " px"),
        )
        note = QLabel(
            "说明：候选截图按 PPT 区域裁剪并以 JPEG 保存；导出时再按摄像头处理方式生成 PNG，"
            "原始候选图与导出结果分开存放。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280;")
        return self._scroll_form([quality, storage, note])

    def _restore_defaults(self) -> None:
        defaults = AnalysisSettings()
        for key, (widget, scale) in self._controls.items():
            value = getattr(defaults, key)
            if isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            else:
                widget.setValue(float(value) * scale)
        self._scene_enabled.setChecked(defaults.use_pyscenedetect)

    def settings(self) -> AnalysisSettings:
        values: dict = {}
        for key, (widget, scale) in self._controls.items():
            values[key] = widget.value() / scale if scale != 1 else widget.value()
        values["use_pyscenedetect"] = self._scene_enabled.isChecked()
        return AnalysisSettings.from_dict(values)

