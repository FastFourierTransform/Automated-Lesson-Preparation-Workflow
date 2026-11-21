"""Main desktop window."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ....core.geometry import Rect
from ....core.media.models import VideoInfo
from ....core.media.probe import VideoError, ffmpeg_available, ffprobe_available, probe_video
from ....core.timecode import format_timecode, parse_timecode
from ....core.ui.preview_canvas import PreviewCanvas
from .... import __version__
from ....version import APP_NAME, PROJECT_SCHEMA_VERSION
from ..analysis.errors import AnalysisError
from ..constants import STAGE_NAME
from ..export.service import ExportOptions
from ..models import AnalysisSettings, CameraMode, CameraRegion, SlidesProject
from ..project import (
    ProjectError,
    load_project,
    prepare_project_path,
    save_project,
    suggested_project_path,
)
from .config import AppPreferences
from .export_dialog import ExportDialog
from .review_panel import ReviewPanel
from .settings_dialog import AnalysisSettingsDialog
from .workers import AnalysisWorker, ExportWorker


def _format_region_label(region: Rect | None) -> str:
    if region is None:
        return "未设置"
    return f"x={region.x:.3f}  y={region.y:.3f}  w={region.w:.3f}  h={region.h:.3f}"


def _format_size(size: int) -> str:
    if not size:
        return "未知"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


class MainWindow(QMainWindow):
    def __init__(self, preferences: AppPreferences | None = None, parent=None):
        super().__init__(parent)
        self.prefs = preferences or AppPreferences.load()
        self.project: SlidesProject | None = None
        self.analysis_worker: AnalysisWorker | None = None
        self.export_worker: ExportWorker | None = None
        self._busy_kind: str | None = None
        self._selecting_region: str | None = None
        self._loading_project = False
        self._scrubbing = False
        self._resume_after_scrub = False
        self._closing = False
        self._last_saved_dirty = False

        self.setAcceptDrops(True)
        self.setMinimumSize(1180, 790)
        self.resize(1500, 960)
        from ....core.ui.player import VideoPlayer

        self.player = VideoPlayer(self)
        self._build_actions()
        self._build_ui()
        self._build_menu_and_toolbar()
        self._connect_signals()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(1500)
        self.autosave_timer.timeout.connect(self._autosave)

        self._update_title()
        self._update_ui_state()
        self._show_project(None)
        self.statusBar().showMessage("请导入视频或打开已有项目。", 7000)

    # ------------------------------------------------------------------ UI
    def _build_actions(self) -> None:
        style = self.style()
        self.import_action = QAction("导入视频…", self)
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.import_action.triggered.connect(self.import_video)

        self.open_action = QAction("打开项目…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.open_action.triggered.connect(self.open_project)

        self.save_action = QAction("保存项目", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.save_action.triggered.connect(lambda: self._save_project(silent=False))

        self.export_action = QAction("导出幻灯片…", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.export_action.triggered.connect(self.export_slides)

        self.analyze_action = QAction("开始分析", self)
        self.analyze_action.setShortcut(QKeySequence("Ctrl+R"))
        self.analyze_action.triggered.connect(self.start_analysis)

        self.exit_action = QAction("退出", self)
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_action.triggered.connect(self.close)

        self.help_action = QAction("使用说明", self)
        self.help_action.triggered.connect(self._show_help)
        self.about_action = QAction("关于", self)
        self.about_action.triggered.connect(self._show_about)

    def _build_menu_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.analyze_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.help_action)
        help_menu.addAction(self.about_action)

        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.import_action)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        toolbar.addAction(self.analyze_action)
        toolbar.addAction(self.export_action)
        self.addToolBar(toolbar)
        self.toolbar = toolbar

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        vertical_splitter.setChildrenCollapsible(False)
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)

        preview_card = QFrame()
        preview_card.setObjectName("previewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(10, 8, 10, 10)
        preview_layout.setSpacing(6)
        preview_header = QHBoxLayout()
        preview_title = QLabel("视频预览")
        preview_title.setObjectName("sectionTitle")
        preview_header.addWidget(preview_title)
        self.video_name_label = QLabel("未导入视频")
        self.video_name_label.setObjectName("mutedLabel")
        preview_header.addWidget(self.video_name_label, 1)
        self.selection_hint_label = QLabel("")
        self.selection_hint_label.setObjectName("mutedLabel")
        preview_header.addWidget(self.selection_hint_label)
        preview_layout.addLayout(preview_header)

        self.preview = PreviewCanvas()
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview, 1)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.play_button = QToolButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setText("▶")
        self.play_button.setToolTip("播放 / 暂停")
        self.play_button.setFixedSize(34, 34)
        controls.addWidget(self.play_button)
        self.back_button = QToolButton()
        self.back_button.setText("−5s")
        self.back_button.setToolTip("后退 5 秒")
        controls.addWidget(self.back_button)
        self.forward_button = QToolButton()
        self.forward_button.setText("+5s")
        self.forward_button.setToolTip("前进 5 秒")
        controls.addWidget(self.forward_button)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setSingleStep(500)
        self.position_slider.setPageStep(5000)
        controls.addWidget(self.position_slider, 1)
        self.time_label = QLabel("00:00:00.000 / 00:00:00")
        self.time_label.setObjectName("mutedLabel")
        self.time_label.setMinimumWidth(190)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls.addWidget(self.time_label)
        preview_layout.addLayout(controls)

        top_splitter.addWidget(preview_card)

        side_container = QWidget()
        side_container.setObjectName("sidePanel")
        side_container.setMinimumWidth(390)
        side_container.setMaximumWidth(470)
        side_container_layout = QVBoxLayout(side_container)
        side_container_layout.setContentsMargins(8, 0, 4, 0)
        side_container_layout.setSpacing(8)

        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        side_inner = QWidget()
        side_inner.setObjectName("sidePanel")
        side_layout = QVBoxLayout(side_inner)
        side_layout.setContentsMargins(0, 0, 2, 0)
        side_layout.setSpacing(8)

        side_layout.addWidget(self._build_video_group())
        side_layout.addWidget(self._build_range_group())
        side_layout.addWidget(self._build_region_group())
        side_layout.addWidget(self._build_analysis_options_group())
        self.analysis_summary = QLabel("分析完成后，这里会显示页数与异常提示。")
        self.analysis_summary.setObjectName("mutedLabel")
        self.analysis_summary.setWordWrap(True)
        side_layout.addWidget(self.analysis_summary)
        side_layout.addStretch(1)
        side_scroll.setWidget(side_inner)
        side_container_layout.addWidget(side_scroll, 1)
        # Keep the primary action and progress visible even when the settings
        # panel is scrolled.
        side_container_layout.addWidget(self._build_task_group())
        top_splitter.addWidget(side_container)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 0)
        top_splitter.setSizes([1010, 420])

        vertical_splitter.addWidget(top_splitter)
        self.review = ReviewPanel()
        vertical_splitter.addWidget(self.review)
        vertical_splitter.setStretchFactor(0, 3)
        vertical_splitter.setStretchFactor(1, 2)
        vertical_splitter.setSizes([530, 360])
        root.addWidget(vertical_splitter, 1)
        self.setCentralWidget(central)

        status = QStatusBar(self)
        self.setStatusBar(status)
        self.project_status_label = QLabel("未加载项目")
        self.project_status_label.setObjectName("mutedLabel")
        status.addPermanentWidget(self.project_status_label)

    def _group_box(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        # QGroupBox styling is in the global theme.
        from PySide6.QtWidgets import QGroupBox

        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        return box, layout

    def _build_video_group(self) -> QFrame:
        group, layout = self._group_box("视频信息")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        self.info_file = QLabel("未导入")
        self.info_file.setWordWrap(True)
        self.info_file.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_file.setObjectName("videoInfoValue")
        self.info_spec = QLabel("—")
        self.info_spec.setWordWrap(True)
        self.info_spec.setObjectName("videoInfoValue")
        form.addRow("文件", self.info_file)
        form.addRow("规格", self.info_spec)
        layout.addLayout(form)
        self.ffmpeg_label = QLabel("")
        self.ffmpeg_label.setWordWrap(True)
        self.ffmpeg_label.setObjectName("mutedLabel")
        layout.addWidget(self.ffmpeg_label)
        return group

    def _build_range_group(self) -> QFrame:
        group, layout = self._group_box("正片区间")
        row_start = QHBoxLayout()
        row_start.addWidget(QLabel("开始"))
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("HH:MM:SS.mmm")
        self.start_edit.setMinimumWidth(105)
        row_start.addWidget(self.start_edit, 1)
        self.set_start_button = QPushButton("取当前")
        self.set_start_button.setFixedWidth(60)
        row_start.addWidget(self.set_start_button)
        layout.addLayout(row_start)
        row_end = QHBoxLayout()
        row_end.addWidget(QLabel("结束"))
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("HH:MM:SS.mmm")
        row_end.addWidget(self.end_edit, 1)
        self.set_end_button = QPushButton("取当前")
        self.set_end_button.setFixedWidth(60)
        row_end.addWidget(self.set_end_button)
        layout.addLayout(row_end)
        self.start_edit.setToolTip("正片开始时间，可输入 HH:MM:SS.mmm；也可用“取当前”。")
        self.end_edit.setToolTip("正片结束时间，必须晚于开始时间。")
        self.start_edit.editingFinished.connect(self._apply_time_edits)
        self.end_edit.editingFinished.connect(self._apply_time_edits)
        self.set_start_button.clicked.connect(lambda: self._set_time_from_player("start"))
        self.set_end_button.clicked.connect(lambda: self._set_time_from_player("end"))
        return group

    def _build_region_group(self) -> QFrame:
        group, layout = self._group_box("画面区域")
        ppt_title = QHBoxLayout()
        ppt_title.addWidget(QLabel("PPT 区域"))
        ppt_title.addStretch(1)
        self.ppt_select_button = QPushButton("框选 PPT 区域")
        self.reset_ppt_button = QPushButton("全画面")
        self.reset_ppt_button.setFixedWidth(64)
        ppt_title.addWidget(self.ppt_select_button)
        ppt_title.addWidget(self.reset_ppt_button)
        layout.addLayout(ppt_title)
        self.ppt_region_label = QLabel("全画面")
        self.ppt_region_label.setObjectName("mutedLabel")
        self.ppt_region_label.setWordWrap(True)
        layout.addWidget(self.ppt_region_label)

        cam_title = QHBoxLayout()
        cam_title.addWidget(QLabel("摄像头区域"))
        cam_title.addStretch(1)
        cam_title.addWidget(QLabel("数量"))
        self.camera_count_spin = QSpinBox()
        self.camera_count_spin.setRange(0, 6)
        self.camera_count_spin.setValue(0)
        self.camera_count_spin.setFixedWidth(58)
        self.camera_count_spin.setToolTip(
            "0 表示不处理摄像头。每个摄像头区域可单独框选并设置导出处理方式。"
        )
        cam_title.addWidget(self.camera_count_spin)
        layout.addLayout(cam_title)

        self.camera_empty_label = QLabel("未设置摄像头区域。可先选择数量，再逐个框选。")
        self.camera_empty_label.setObjectName("mutedLabel")
        self.camera_empty_label.setWordWrap(True)
        layout.addWidget(self.camera_empty_label)

        self.camera_rows_container = QWidget()
        self.camera_rows_layout = QVBoxLayout(self.camera_rows_container)
        self.camera_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_rows_layout.setSpacing(5)
        layout.addWidget(self.camera_rows_container)
        self._camera_coord_labels: dict[str, QLabel] = {}
        self._camera_select_buttons: dict[str, QPushButton] = {}
        self._camera_clear_buttons: dict[str, QPushButton] = {}
        self._camera_mode_combos: dict[str, QComboBox] = {}
        self._camera_row_widgets: list[QWidget] = []

        self.camera_count_spin.valueChanged.connect(self._on_camera_count_changed)
        self.ppt_select_button.setToolTip(
            "在预览画面中拖拽重新框选 PPT 区域；也可直接拖动区域边框/控制点调整；按 Esc 取消框选。"
        )
        self.ppt_select_button.clicked.connect(lambda: self._begin_region_selection("ppt"))
        self.reset_ppt_button.clicked.connect(self._reset_ppt_region)
        camera_note = QLabel(
            "每个摄像头区域可分别选择忽略、裁剪、黑色遮罩或白色遮罩。"
            "分析时所有已设置摄像头区域都会被排除。"
        )
        camera_note.setObjectName("mutedLabel")
        camera_note.setWordWrap(True)
        layout.addWidget(camera_note)
        return group

    def _clear_camera_rows(self) -> None:
        while self.camera_rows_layout.count():
            item = self.camera_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._camera_coord_labels.clear()
        self._camera_select_buttons.clear()
        self._camera_clear_buttons.clear()
        self._camera_mode_combos.clear()
        self._camera_row_widgets.clear()

    def _rebuild_camera_rows(self) -> None:
        self._clear_camera_rows()
        cameras = self.project.camera_regions if self.project else []
        self.camera_empty_label.setVisible(not cameras)
        self.camera_rows_container.setVisible(bool(cameras))
        for index, camera in enumerate(cameras):
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 4)
            row_layout.setSpacing(3)

            header = QHBoxLayout()
            name = QLabel(f"摄像头 {index + 1}")
            name.setObjectName("subTitle")
            header.addWidget(name)
            header.addStretch(1)
            select_button = QPushButton("框选")
            select_button.setFixedWidth(54)
            clear_button = QPushButton("清除")
            clear_button.setFixedWidth(48)
            header.addWidget(select_button)
            header.addWidget(clear_button)
            row_layout.addLayout(header)

            coord_label = QLabel(_format_region_label(camera.region))
            coord_label.setObjectName("mutedLabel")
            coord_label.setWordWrap(True)
            row_layout.addWidget(coord_label)

            mode_row = QHBoxLayout()
            mode_row.addWidget(QLabel("处理"))
            mode_combo = QComboBox()
            for mode in (
                CameraMode.IGNORE,
                CameraMode.CROP,
                CameraMode.MASK,
                CameraMode.MASK_WHITE,
            ):
                mode_combo.addItem(mode.label, mode.value)
            mode_index = mode_combo.findData(camera.mode.value)
            mode_combo.setCurrentIndex(max(0, mode_index))
            mode_combo.setToolTip(
                "该摄像头区域单独设置分析排除和导出处理方式。"
            )
            mode_row.addWidget(mode_combo, 1)
            row_layout.addLayout(mode_row)

            self.camera_rows_layout.addWidget(row)
            self._camera_row_widgets.append(row)
            self._camera_coord_labels[camera.id] = coord_label
            self._camera_select_buttons[camera.id] = select_button
            self._camera_clear_buttons[camera.id] = clear_button
            self._camera_mode_combos[camera.id] = mode_combo
            select_button.clicked.connect(
                lambda _checked=False, camera_id=camera.id: self._begin_region_selection(
                    "camera", camera_id
                )
            )
            clear_button.clicked.connect(
                lambda _checked=False, camera_id=camera.id: self._clear_camera_region(
                    camera_id
                )
            )
            mode_combo.currentIndexChanged.connect(
                lambda _index, camera_id=camera.id, combo=mode_combo: self._on_camera_mode_changed(
                    camera_id, combo
                )
            )
        self._refresh_camera_row_labels()

    def _camera_index(self, camera_id: str) -> int:
        if self.project is None:
            return -1
        return next(
            (
                index
                for index, camera in enumerate(self.project.camera_regions)
                if camera.id == camera_id
            ),
            -1,
        )

    def _camera_overlays(self) -> list[tuple[str, str, Rect]]:
        if self.project is None:
            return []
        return [
            (f"camera:{camera.id}", f"摄像头 {index + 1}", camera.region)
            for index, camera in enumerate(self.project.camera_regions)
            if camera.region is not None and camera.is_configured()
        ]

    def _sync_camera_preview(self) -> None:
        self.preview.set_regions(
            self.project.ppt_region if self.project else None,
            self._camera_overlays(),
            primary_kind="ppt",
            primary_label="PPT 区域",
        )

    def _refresh_camera_row_labels(self) -> None:
        if self.project is None:
            return
        for camera in self.project.camera_regions:
            coord_label = self._camera_coord_labels.get(camera.id)
            if coord_label is not None:
                coord_label.setText(_format_region_label(camera.region))
            select_button = self._camera_select_buttons.get(camera.id)
            if select_button is not None:
                active = self._selecting_region == f"camera:{camera.id}"
                select_button.setText("拖拽中…" if active else "框选")
            combo = self._camera_mode_combos.get(camera.id)
            if combo is not None:
                index = combo.findData(camera.mode.value)
                if index >= 0 and combo.currentIndex() != index:
                    blocked = combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(blocked)

    def _on_camera_count_changed(self, count: int) -> None:
        if self._loading_project or self.project is None:
            return
        count = max(0, min(int(count), 6))
        current = len(self.project.camera_regions)
        if count == current:
            return
        if self._selecting_region is not None:
            self.preview.cancel_selection()
        if count > current:
            for _ in range(count - current):
                self.project.camera_regions.append(CameraRegion())
        else:
            del self.project.camera_regions[count:]
        self.project.history("set_camera_count", f"摄像头区域数量：{count}")
        self.project.touch()
        self._rebuild_camera_rows()
        self._sync_camera_preview()
        self.review.refresh_current()
        self._update_title()
        self.autosave_timer.start()
        self._update_ui_state()
        if self.project.pages:
            self.analysis_warning.setText(
                "摄像头区域数量已更改；新设置会用于导出，重新分析后才会更新自动检测。"
            )
        self.statusBar().showMessage(
            f"摄像头区域数量已设为 {count}。请分别为每个区域框选位置并选择处理方式。",
            6000,
        )

    def _build_analysis_options_group(self) -> QFrame:
        group, layout = self._group_box("分析参数")
        self.settings_summary = QLabel("")
        self.settings_summary.setObjectName("mutedLabel")
        self.settings_summary.setWordWrap(True)
        layout.addWidget(self.settings_summary)
        self.settings_button = QPushButton("修改分析参数…")
        self.settings_button.clicked.connect(self._edit_settings)
        layout.addWidget(self.settings_button)
        return group

    def _build_task_group(self) -> QFrame:
        group, layout = self._group_box("分析与导出")
        self.analyze_button = QPushButton("开始分析")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.setMinimumHeight(38)
        self.analyze_button.clicked.connect(self.start_analysis)
        layout.addWidget(self.analyze_button)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setObjectName("danger")
        self.cancel_button.clicked.connect(self._cancel_current_task)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.task_status = QLabel("等待导入视频。")
        self.task_status.setObjectName("mutedLabel")
        self.task_status.setWordWrap(True)
        layout.addWidget(self.task_status)
        self.analysis_warning = QLabel("")
        self.analysis_warning.setWordWrap(True)
        self.analysis_warning.setStyleSheet("color:#b45309; font-size:9pt;")
        layout.addWidget(self.analysis_warning)
        return group

    def _connect_signals(self) -> None:
        self.player.frame_ready.connect(self.preview.set_image)
        self.player.position_changed.connect(self._on_position_changed)
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.playing_changed.connect(self._on_playing_changed)
        self.player.error.connect(self._on_player_error)
        self.play_button.clicked.connect(self.player.toggle)
        self.back_button.clicked.connect(lambda: self.player.seek(max(0.0, self.player.position - 5.0)))
        self.forward_button.clicked.connect(lambda: self.player.seek(self.player.position + 5.0))
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.preview.region_committed.connect(self._on_region_committed)
        self.preview.region_edit_started.connect(self._on_region_edit_started)
        self.preview.selection_cancelled.connect(self._on_selection_cancelled)
        self.review.changed.connect(self._on_review_changed)
        self.review.locate_requested.connect(self._locate_video)
        self.review.status_message.connect(lambda message: self.statusBar().showMessage(message, 6000))

    # --------------------------------------------------------------- Project
    def _show_project(self, project: SlidesProject | None, open_video: bool = True) -> None:
        self.project = project
        self._loading_project = True
        try:
            if project is None:
                self.player.close()
                self.preview.clear_image()
                self.preview.set_regions(None, [])
                self.info_file.setText("未导入")
                self.info_spec.setText("—")
                self.video_name_label.setText("未导入视频")
                self.start_edit.clear()
                self.end_edit.clear()
                self.camera_count_spin.blockSignals(True)
                self.camera_count_spin.setValue(0)
                self.camera_count_spin.blockSignals(False)
                self._rebuild_camera_rows()
                self.analysis_summary.setText("分析完成后，这里会显示页数与异常提示。")
                self.analysis_warning.clear()
                self.settings_summary.setText("")
                self.review.set_project(None)
                self._selecting_region = None
                self._reset_selection_buttons()
                return
            info = project.video_info
            self.video_name_label.setText(Path(info.path).name if info.path else "（视频路径缺失）")
            self.info_file.setText(Path(info.path).name if info.path else "（路径缺失）")
            self.info_file.setToolTip(info.path)
            spec = (
                f"{format_timecode(info.duration_sec)} · {info.resolution}"
                + (f" · {info.fps:.2f} fps" if info.fps else "")
                + f" · {info.codec or '未知编码'} · {_format_size(info.file_size)}"
            )
            self.info_spec.setText(spec)
            if not ffmpeg_available():
                self.ffmpeg_label.setText("⚠ 未找到 FFmpeg：分析会回退到较慢的 OpenCV 扫描。")
                self.ffmpeg_label.setStyleSheet("color:#b45309;")
            elif not ffprobe_available():
                self.ffmpeg_label.setText("FFmpeg 可用；FFprobe 未找到，部分元数据可能不准确。")
                self.ffmpeg_label.setStyleSheet("color:#6b7280;")
            else:
                self.ffmpeg_label.setText("FFmpeg / FFprobe：可用")
                self.ffmpeg_label.setStyleSheet("color:#15803d;")
            self.start_edit.setText(format_timecode(project.content_start, milliseconds=True))
            self.end_edit.setText(format_timecode(project.content_end, milliseconds=True))
            self.ppt_region_label.setText(_format_region_label(project.ppt_region))
            self.camera_count_spin.blockSignals(True)
            self.camera_count_spin.setValue(len(project.camera_regions))
            self.camera_count_spin.blockSignals(False)
            self._rebuild_camera_rows()
            self._sync_camera_preview()
            self.review.set_project(project)
            self._refresh_settings_summary()
            self._refresh_analysis_summary()
            self._update_range_display()
            if open_video:
                path = Path(info.path) if info.path else None
                if path and path.is_file():
                    try:
                        self.player.open(str(path), info)
                    except Exception as exc:
                        self.player.close()
                        self.preview.clear_image()
                        QMessageBox.warning(
                            self,
                            "视频预览失败",
                            f"项目已打开，但视频无法预览：\n{exc}\n\n仍可查看已有截图并导出。",
                        )
                else:
                    self.player.close()
                    self.preview.clear_image()
                    QMessageBox.warning(
                        self,
                        "视频文件缺失",
                        "项目引用的视频文件不存在。候选截图仍可查看和导出，但无法预览或重新分析。",
                    )
        finally:
            self._loading_project = False
            self._update_title()
            self._update_ui_state()

    def import_video(self) -> None:
        if self._busy_kind:
            return
        if not self._maybe_save_changes():
            return
        start_dir = self.prefs.last_video_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入网课视频",
            start_dir,
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv *.wmv *.ts *.mts *.m2ts);;所有文件 (*)",
        )
        if not path:
            return
        self.prefs.last_video_dir = str(Path(path).parent)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = probe_video(path)
        except (VideoError, Exception) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "无法导入视频", str(exc))
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        settings = AnalysisSettings.from_dict(self.prefs.analysis_settings.to_dict())
        project = SlidesProject(
            name=Path(path).stem,
            video_info=info,
            content_start=0.0,
            content_end=info.duration_sec,
            ppt_region=Rect.full_frame(),
            camera_regions=[],
            settings=settings,
        )
        project.project_path = None
        project.assets_root = None
        project.dirty = False
        self._show_project(project)
        self._reset_player_to_zero()
        self.statusBar().showMessage(
            f"已导入 {Path(path).name}，请设置正片区间和 PPT 区域。", 8000
        )
        self.task_status.setText(
            "视频已就绪。区域可直接拖动边框/控制点调整；设置完成后点击“开始分析”。"
        )
        if not ffmpeg_available():
            QMessageBox.warning(
                self,
                "FFmpeg 不可用",
                "当前环境未找到 FFmpeg。视频分析会回退到 OpenCV 逐帧扫描，长视频可能明显变慢。\n"
                "建议安装 FFmpeg 并加入 PATH。",
            )

    def _reset_player_to_zero(self) -> None:
        if self.player.reader is not None:
            self.player.seek(0.0)
            self._update_range_display()

    def open_project(self) -> None:
        if self._busy_kind:
            return
        if not self._maybe_save_changes():
            return
        start_dir = self.prefs.last_project_dir or self.prefs.last_video_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开课件提取项目",
            start_dir,
            "课件提取项目 (*.lsp.json *.json);;所有文件 (*)",
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            project = load_project(path)
        except (ProjectError, Exception) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "无法打开项目", str(exc))
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        self.prefs.last_project_dir = str(Path(path).parent)
        self._show_project(project)
        self.statusBar().showMessage(f"已打开项目：{Path(path).name}", 7000)
        self.task_status.setText(
            f"项目已载入：{len(project.pages)} 个候选页面，保留 {len(project.active_pages())} 页。"
            if project.pages
            else "项目已载入，尚未分析。"
        )
        if project.warnings:
            self.analysis_warning.setText("上次分析提示：" + "；".join(project.warnings[:4]))

    def _maybe_save_changes(self) -> bool:
        if self.project is None or not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "保存项目",
            "当前项目有未保存的更改，是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self._save_project(silent=False)
        self.project.dirty = False
        self._update_title()
        return True

    def _project_save_path_dialog(self) -> bool:
        if self.project is None:
            return False
        if self.project.project_path:
            return True
        suggested = (
            suggested_project_path(self.project.video_info.path)
            if self.project.video_info.path
            else Path(self.prefs.last_project_dir or Path.home()) / (self.project.name + ".lsp.json")
        )
        start_dir = self.prefs.last_project_dir or (
            str(suggested.parent) if suggested.parent else str(Path.home())
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存课件提取项目",
            str(suggested) if suggested.parent else start_dir,
            "课件提取项目 (*.lsp.json);;JSON 文件 (*.json)",
        )
        if not path:
            return False
        try:
            project_path, assets_root = prepare_project_path(path)
        except OSError as exc:
            QMessageBox.critical(self, "无法创建项目目录", str(exc))
            return False
        self.project.project_path = project_path
        self.project.assets_root = assets_root
        self.prefs.last_project_dir = str(project_path.parent)
        return True

    def _save_project(self, silent: bool = False) -> bool:
        if self.project is None:
            return False
        if not self._project_save_path_dialog():
            return False
        try:
            save_project(self.project)
        except ProjectError as exc:
            if not silent:
                QMessageBox.critical(self, "保存项目失败", str(exc))
            else:
                self.task_status.setText(f"项目自动保存失败：{exc}")
            return False
        self.prefs.last_project_dir = str(Path(self.project.project_path).parent)
        self._update_title()
        self._update_ui_state()
        if not silent:
            self.statusBar().showMessage("项目已保存。", 5000)
        return True

    def _autosave(self) -> None:
        if (
            self.project is None
            or self._busy_kind
            or not self.project.project_path
            or not self.project.dirty
        ):
            return
        if self._save_project(silent=True):
            self.statusBar().showMessage("已自动保存项目。", 3000)

    def _mark_dirty(self) -> None:
        if self.project is None:
            return
        self.project.touch()
        self._update_title()
        self.autosave_timer.start()

    def _update_title(self) -> None:
        if self.project is None:
            self.setWindowTitle(f"{STAGE_NAME} — {APP_NAME}")
            return
        star = " *" if self.project.dirty else ""
        path_part = f" — {Path(self.project.project_path).name}" if self.project.project_path else ""
        self.setWindowTitle(
            f"{self.project.name}{star}{path_part} — {STAGE_NAME} · {APP_NAME}"
        )
        self.project_status_label.setText(
            ("已保存" if not self.project.dirty else "未保存")
            + (" · " + Path(self.project.project_path).name if self.project.project_path else " · 尚未保存项目")
        )

    # --------------------------------------------------------------- Controls
    def _on_duration_changed(self, duration: float) -> None:
        self.position_slider.setRange(0, int(max(0.0, duration) * 1000))
        self._update_range_display()

    def _on_position_changed(self, position: float) -> None:
        if not self._scrubbing:
            self.position_slider.setValue(int(max(0.0, position) * 1000))
        self._update_range_display(position)

    def _update_range_display(self, position: float | None = None) -> None:
        if position is None:
            position = self.player.position
        total = self.player.duration or (
            self.project.video_info.duration_sec if self.project else 0.0
        )
        self.time_label.setText(
            f"{format_timecode(position, milliseconds=True)} / {format_timecode(total)}"
        )

    def _on_playing_changed(self, playing: bool) -> None:
        self.play_button.setText("❚❚" if playing else "▶")
        self.play_button.setToolTip("暂停" if playing else "播放")

    def _on_player_error(self, message: str) -> None:
        self.statusBar().showMessage(f"预览错误：{message}", 8000)

    def _on_slider_pressed(self) -> None:
        self._scrubbing = True
        self._resume_after_scrub = self.player.is_playing
        self.player.pause()

    def _on_slider_moved(self, value: int) -> None:
        self._update_range_display(value / 1000.0)

    def _on_slider_released(self) -> None:
        value = self.position_slider.value()
        self._scrubbing = False
        self.player.seek(value / 1000.0)
        if self._resume_after_scrub:
            self.player.play()
        self._update_range_display()

    def _apply_time_edits(self) -> bool:
        if self._loading_project or self.project is None:
            return True
        duration = self.project.video_info.duration_sec or self.player.duration
        try:
            start = parse_timecode(self.start_edit.text(), duration)
            end = parse_timecode(self.end_edit.text(), duration)
        except ValueError as exc:
            QMessageBox.warning(self, "时间格式无效", str(exc))
            self._sync_time_edits()
            return False
        if end - start < 0.5:
            QMessageBox.warning(self, "正片区间无效", "结束时间必须比开始时间至少晚 0.5 秒。")
            self._sync_time_edits()
            return False
        if (
            abs(start - self.project.content_start) < 1e-6
            and abs(end - self.project.content_end) < 1e-6
        ):
            return True
        self.project.content_start = start
        self.project.content_end = end
        self.project.history(
            "set_content_range",
            f"{format_timecode(start, milliseconds=True)} – {format_timecode(end, milliseconds=True)}",
        )
        self._update_range_display()
        self._update_title()
        self.autosave_timer.start()
        if self.project.pages:
            self.statusBar().showMessage("正片区间已更新；重新分析后新区间才会生效。", 7000)
        return True

    def _sync_time_edits(self) -> None:
        if self.project is None:
            return
        self.start_edit.setText(format_timecode(self.project.content_start, milliseconds=True))
        self.end_edit.setText(format_timecode(self.project.content_end, milliseconds=True))

    def _set_time_from_player(self, which: str) -> None:
        if self.project is None or self.player.reader is None:
            return
        position = min(max(0.0, self.player.position), self.project.video_info.duration_sec)
        if which == "start":
            if position >= self.project.content_end:
                QMessageBox.warning(self, "无效的开始时间", "开始时间必须早于结束时间。")
                return
            self.start_edit.setText(format_timecode(position, milliseconds=True))
        else:
            if position <= self.project.content_start:
                QMessageBox.warning(self, "无效的结束时间", "结束时间必须晚于开始时间。")
                return
            self.end_edit.setText(format_timecode(position, milliseconds=True))
        self._apply_time_edits()
        if self.project:
            self._sync_time_edits()

    def _begin_region_selection(self, kind: str, camera_id: str | None = None) -> None:
        if self.project is None or self.player.reader is None or self._busy_kind:
            return
        if kind == "ppt":
            target = "ppt"
            label = "PPT 区域"
        elif kind == "camera" and camera_id:
            index = self._camera_index(camera_id)
            if index < 0:
                return
            target = f"camera:{camera_id}"
            label = f"摄像头 {index + 1}"
        else:
            return
        if self.preview.selection_mode is not None:
            same = self._selecting_region == target
            self.preview.cancel_selection()
            if same:
                return
        self.player.pause()
        self._selecting_region = target
        self.preview.start_selection(target, label=label)
        self.selection_hint_label.setText("拖拽框选，Esc 取消")
        self.ppt_select_button.setText(
            "拖拽中选择…" if target == "ppt" else "框选 PPT 区域"
        )
        self._refresh_camera_row_labels()
        self.statusBar().showMessage(
            f"请在预览画面中拖拽框选{label}（坐标按原始视频归一化保存）。"
        )

    def _reset_selection_buttons(self) -> None:
        self.ppt_select_button.setText("框选 PPT 区域")
        self.selection_hint_label.setText("")
        self._refresh_camera_row_labels()

    def _on_region_committed(self, kind: str, region) -> None:
        self._selecting_region = None
        self._reset_selection_buttons()
        if self.project is None:
            return
        region = region.clamped()
        if kind == "ppt":
            self.project.ppt_region = region
            self.project.history("set_ppt_region", region.format())
            if self.project.pages:
                self.analysis_warning.setText(
                    "PPT 区域已更改。当前候选截图仍对应分析时的旧区域，请重新分析以应用新区域。"
                )
            message = "PPT 区域已更新。"
        elif kind.startswith("camera:"):
            camera_id = kind.split(":", 1)[1]
            camera_index = self._camera_index(camera_id)
            if camera_index < 0:
                return
            camera = self.project.camera_regions[camera_index]
            camera.region = region
            self.project.history(
                "set_camera_region",
                f"摄像头 {camera_index + 1}: {region.format()}",
            )
            if self.project.pages:
                self.analysis_warning.setText(
                    "摄像头区域已更改：导出会立即使用新区域处理截图；重新分析后才会更新自动检测。"
                )
            message = f"摄像头 {camera_index + 1} 区域已更新。"
        else:
            return
        self.project.touch()
        self._sync_camera_preview()
        self.ppt_region_label.setText(_format_region_label(self.project.ppt_region))
        self._refresh_camera_row_labels()
        self.review.refresh_current()
        self._update_title()
        self.autosave_timer.start()
        self.statusBar().showMessage(
            message + "导出时将按各摄像头区域的处理方式应用。", 6000
        )
        self._update_ui_state()

    def _on_region_edit_started(self) -> None:
        self.player.pause()
        self.statusBar().showMessage("正在拖动区域边框；松开鼠标后自动保存。", 4000)

    def _on_selection_cancelled(self) -> None:
        self._selecting_region = None
        self._reset_selection_buttons()
        self.statusBar().showMessage("已取消区域框选。", 3000)

    def _reset_ppt_region(self) -> None:
        if self.project is None or self._busy_kind:
            return
        self.project.ppt_region = Rect.full_frame()
        self.project.history("set_ppt_region", "重置为全画面")
        self.project.touch()
        if self.project.pages:
            self.analysis_warning.setText(
                "PPT 区域已重置。已有候选截图仍按旧区域生成，请重新分析以应用新区域。"
            )
        self._sync_camera_preview()
        self.ppt_region_label.setText(_format_region_label(self.project.ppt_region))
        self.review.refresh_current()
        self._update_title()
        self.autosave_timer.start()
        self.statusBar().showMessage("PPT 区域已重置为全画面。", 4000)

    def _clear_camera_region(self, camera_id: str) -> None:
        if self.project is None or self._busy_kind:
            return
        index = self._camera_index(camera_id)
        if index < 0:
            return
        camera = self.project.camera_regions[index]
        if camera.region is None:
            return
        if self._selecting_region == f"camera:{camera.id}":
            self.preview.cancel_selection()
        camera.region = None
        self.project.history("clear_camera_region", f"清除摄像头 {index + 1} 区域")
        self.project.touch()
        self._sync_camera_preview()
        self._refresh_camera_row_labels()
        if self.project.pages:
            self.analysis_warning.setText(
                f"摄像头 {index + 1} 区域已清除；重新分析后才会更新自动检测。"
            )
        self.review.refresh_current()
        self._update_title()
        self.autosave_timer.start()
        self.statusBar().showMessage(f"摄像头 {index + 1} 区域已清除。", 4000)

    def _on_camera_mode_changed(self, camera_id: str, combo: QComboBox) -> None:
        if self._loading_project or self.project is None:
            return
        index = self._camera_index(camera_id)
        if index < 0:
            return
        value = combo.currentData()
        try:
            mode = CameraMode(str(value))
        except ValueError:
            return
        camera = self.project.camera_regions[index]
        if mode == camera.mode:
            return
        camera.mode = mode
        self.project.history(
            "set_camera_mode",
            f"摄像头 {index + 1}: {mode.label}",
        )
        self.project.touch()
        if self.project.pages:
            self.analysis_warning.setText(
                f"摄像头 {index + 1} 的处理方式已更改：该设置用于导出，已立即生效。"
            )
        self.review.refresh_current()
        self._update_title()
        self.autosave_timer.start()
        self.statusBar().showMessage(
            f"摄像头 {index + 1} 的处理方式已设为：{mode.label}", 5000
        )

    def _refresh_settings_summary(self) -> None:
        if self.project is None:
            self.settings_summary.setText("")
            return
        s = self.project.settings
        self.settings_summary.setText(
            f"粗扫描 {s.coarse_fps:g} fps · 稳定帧 {s.refine_fps:g} fps\n"
            f"稳定 {s.stable_duration_sec:g}s · 变化区域≥{s.coarse_change_ratio_threshold * 100:.1f}% · "
            f"低置信度<{s.min_confidence * 100:.0f}%"
        )

    def _refresh_analysis_summary(self) -> None:
        if self.project is None:
            self.analysis_summary.setText("分析完成后，这里会显示页数与异常提示。")
            self.analysis_warning.clear()
            return
        stats = self.project.analysis_stats or {}
        if self.project.pages or stats:
            pages = len(self.project.pages)
            kept = len(self.project.active_pages())
            review = sum(1 for p in self.project.pages if p.needs_review)
            lines = [
                f"候选页面：{pages} 页（保留 {kept} 页，待复核 {review} 页）",
            ]
            if stats:
                lines.append(
                    f"上次分析：{stats.get('elapsed_sec', '—')} 秒 · 粗采样 {stats.get('coarse_sample_count', '—')} 帧"
                    + (" · FFmpeg 快速扫描" if stats.get("used_ffmpeg") else " · OpenCV 扫描")
                )
            self.analysis_summary.setText("\n".join(lines))
            if self.project.warnings:
                self.analysis_warning.setText(
                    "分析提示：" + "；".join(str(w) for w in self.project.warnings[:4])
                )
            else:
                self.analysis_warning.clear()
        else:
            self.analysis_summary.setText("尚未分析。设置参数后点击“开始分析”。")
            self.analysis_warning.clear()

    def _edit_settings(self) -> None:
        if self.project is None:
            return
        dialog = AnalysisSettingsDialog(self.project.settings, self)
        if dialog.exec() != AnalysisSettingsDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        self.project.settings = settings
        self.prefs.analysis_settings = AnalysisSettings.from_dict(settings.to_dict())
        self.prefs.save()
        self.project.history("update_analysis_settings", "更新分析参数")
        self.project.touch()
        self._refresh_settings_summary()
        self._update_title()
        self.autosave_timer.start()
        if self.project.pages:
            QMessageBox.information(
                self,
                "参数已更新",
                "新的分析参数已保存。现有候选页面不会自动变化；点击“开始分析”重新分析后生效。",
            )
        self.statusBar().showMessage("分析参数已更新。", 4000)

    # --------------------------------------------------------------- Analysis
    def start_analysis(self) -> None:
        if self._busy_kind:
            return
        if self.project is None:
            QMessageBox.information(self, "尚未导入视频", "请先导入一段网课视频。")
            return
        if not self.project.video_info.path or not Path(self.project.video_info.path).is_file():
            QMessageBox.critical(self, "视频文件不可用", "项目引用的视频文件不存在，无法分析。")
            return
        if not self._apply_time_edits():
            return
        if not self.project.ppt_region.is_valid():
            QMessageBox.warning(self, "PPT 区域无效", "请重新框选 PPT 区域。")
            return
        if self.project.content_end - self.project.content_start < 0.5:
            QMessageBox.warning(self, "正片区间无效", "请设置至少 0.5 秒的正片区间。")
            return
        if self.project.pages or self.project.trash:
            extra = (
                "\n回收站中的已删除页面也会被清空。"
                if self.project.trash
                else ""
            )
            answer = QMessageBox.question(
                self,
                "重新分析",
                "重新分析会替换当前全部候选页面，并覆盖已进行的人工删除、排序、跳过和备选帧选择。"
                + extra
                + "\n\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if not self._save_project(silent=True):
            return
        assert self.project.assets_root is not None
        run_dir = (
            Path(self.project.assets_root)
            / "runs"
            / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "无法创建分析缓存", str(exc))
            return
        self.player.pause()
        self.analysis_worker = AnalysisWorker(
            self.project.video_info.path,
            self.project.video_info,
            self.project.content_start,
            self.project.content_end,
            self.project.ppt_region,
            self.project.camera_regions,
            self.project.settings,
            self.project.assets_root,
            run_dir,
            self,
        )
        worker = self.analysis_worker
        worker.progress.connect(self._on_analysis_progress)
        worker.status.connect(self._on_analysis_status)
        worker.completed.connect(self._on_analysis_completed)
        worker.failed.connect(self._on_analysis_failed)
        worker.cancelled.connect(self._on_analysis_cancelled)
        worker.finished.connect(lambda: self._on_analysis_thread_finished(worker))
        self._set_busy("analysis")
        self.task_status.setText("正在准备分析…")
        self.analysis_warning.clear()
        self.statusBar().showMessage("分析中：视频解码与页面检测在后台线程运行。")
        worker.start()

    def _on_analysis_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        if message:
            self.task_status.setText(message)

    def _on_analysis_status(self, message: str) -> None:
        if message:
            self.task_status.setText(message)

    def _on_analysis_completed(self, result) -> None:
        if self.project is None:
            return
        self.project.pages = result.pages
        self.project.analysis_region = result.analysis_region
        self.project.analysis_stats = result.stats
        self.project.warnings = result.warnings
        self.project.settings = result.settings
        self.project.removed_pages = []
        self.project.trash = []
        self.project.touch()
        self.review.set_project(self.project)
        self._refresh_analysis_summary()
        self._refresh_settings_summary()
        self.task_status.setText(
            f"分析完成：{len(result.pages)} 个候选页面，用时 {result.stats.get('elapsed_sec', '—')} 秒。"
        )
        self.progress_bar.setValue(100)
        saved = self._save_project(silent=True)
        if not saved:
            self.analysis_warning.setText("分析结果已生成，但项目自动保存失败，请手动保存（Ctrl+S）。")
        self.statusBar().showMessage(
            f"分析完成：{len(result.pages)} 页。请在下方复核，然后导出。", 10000
        )
        self._update_ui_state()

    def _on_analysis_failed(self, message: str) -> None:
        self.task_status.setText("分析失败：" + message)
        self.progress_bar.setValue(0)
        self._update_ui_state()
        QMessageBox.critical(self, "分析失败", message)

    def _on_analysis_cancelled(self) -> None:
        self.task_status.setText("分析已取消，原有项目内容未改变。")
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("分析已取消。", 5000)
        self._update_ui_state()

    def _on_analysis_thread_finished(self, worker) -> None:
        if self.analysis_worker is worker:
            self.analysis_worker = None
        worker.deleteLater()
        if self._busy_kind == "analysis":
            self._set_busy(None)
        self._update_ui_state()

    def _cancel_current_task(self) -> None:
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            self.analysis_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.task_status.setText("正在取消分析…")
            self.statusBar().showMessage("正在取消分析，请稍候…")
            return
        if self.export_worker is not None and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.task_status.setText("正在取消导出…")
            self.statusBar().showMessage("正在取消导出，请稍候…")

    def _set_busy(self, kind: str | None) -> None:
        self._busy_kind = kind
        busy = kind is not None
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setValue(0)
            self.task_status.setText("正在准备…")
        else:
            self.progress_bar.setValue(0)
        self.review.set_edit_enabled(not busy)
        self._update_ui_state()

    # ----------------------------------------------------------------- Export
    def export_slides(self) -> None:
        if self._busy_kind or self.project is None:
            return
        if not self.project.pages:
            QMessageBox.information(self, "没有页面", "请先完成分析并复核页面。")
            return
        if not self.project.active_pages():
            QMessageBox.warning(self, "没有保留页面", "所有页面都被跳过了，请至少保留一页再导出。")
            return
        if not self._save_project(silent=True):
            return
        start_dir = (
            self.prefs.last_export_dir
            or (
                str(Path(self.project.video_info.path).parent)
                if self.project.video_info.path
                else str(Path.home())
            )
        )
        dialog = ExportDialog(
            start_dir,
            self.prefs.export_options,
            len(self.project.active_pages()),
            len(self.project.skipped_pages()),
            self,
        )
        if dialog.exec() != ExportDialog.DialogCode.Accepted:
            return
        self.prefs.export_options = dialog.export_options()
        self.prefs.last_export_dir = dialog.output_parent()
        self.prefs.save()
        self.export_worker = ExportWorker(
            self.project,
            dialog.output_parent(),
            dialog.export_options(),
            self,
        )
        worker = self.export_worker
        worker.progress.connect(self._on_export_progress)
        worker.status.connect(self._on_export_status)
        worker.completed.connect(self._on_export_completed)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.finished.connect(lambda: self._on_export_thread_finished(worker))
        self._set_busy("export")
        self.task_status.setText("正在导出…")
        self.statusBar().showMessage("正在导出 PNG / PPTX / JSON…")
        worker.start()

    def _on_export_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        if message:
            self.task_status.setText(message)

    def _on_export_status(self, message: str) -> None:
        if message:
            self.task_status.setText(message)

    def _on_export_completed(self, result) -> None:
        self.progress_bar.setValue(100)
        self.task_status.setText(f"导出完成：{result.exported_pages} 页。")
        self.statusBar().showMessage(f"导出完成：{result.output_dir}", 10000)
        details = f"导出目录：\n{result.output_dir}\n\n"
        details += f"保留页面：{result.exported_pages} · 跳过页面：{result.skipped_pages}"
        if result.warnings:
            details += "\n\n提示：\n" + "\n".join(result.warnings)
        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("幻灯片已成功导出。")
        box.setInformativeText(details)
        open_button = box.addButton("打开导出文件夹", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.output_dir)))
        self._update_ui_state()

    def _on_export_failed(self, message: str) -> None:
        self.task_status.setText("导出失败：" + message)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "导出失败", message)
        self._update_ui_state()

    def _on_export_cancelled(self) -> None:
        self.task_status.setText("导出已取消。未完成的导出文件夹可能保留部分文件。")
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("导出已取消。", 5000)
        self._update_ui_state()

    def _on_export_thread_finished(self, worker) -> None:
        if self.export_worker is worker:
            self.export_worker = None
        worker.deleteLater()
        if self._busy_kind == "export":
            self._set_busy(None)
        self._update_ui_state()

    # --------------------------------------------------------------- State
    def _on_review_changed(self) -> None:
        self._mark_dirty()
        self._refresh_analysis_summary()
        self._update_ui_state()

    def _locate_video(self, seconds: float) -> None:
        if self.player.reader is None:
            self.statusBar().showMessage("视频不可用，无法定位。", 5000)
            return
        self.player.pause()
        self.player.seek(seconds)
        self._update_range_display(seconds)
        self.statusBar().showMessage(
            f"已定位到 {format_timecode(seconds, milliseconds=True)}", 4000
        )

    def _update_ui_state(self) -> None:
        busy = self._busy_kind is not None
        has_project = self.project is not None
        has_video = self.player.reader is not None
        has_pages = bool(self.project.pages) if self.project else False
        has_trash = bool(self.project.trash) if self.project else False
        self.import_action.setEnabled(not busy)
        self.open_action.setEnabled(not busy)
        self.save_action.setEnabled(has_project and not busy)
        self.export_action.setEnabled(has_pages and not busy)
        self.analyze_action.setEnabled(has_project and has_video and not busy)
        self.analyze_button.setEnabled(has_project and has_video and not busy)
        self.settings_button.setEnabled(has_project and not busy)
        for widget in (
            self.start_edit,
            self.end_edit,
            self.set_start_button,
            self.set_end_button,
            self.ppt_select_button,
            self.reset_ppt_button,
            self.camera_count_spin,
            self.play_button,
            self.back_button,
            self.forward_button,
            self.position_slider,
        ):
            widget.setEnabled(has_video and not busy)
        for button in self._camera_select_buttons.values():
            button.setEnabled(has_video and not busy)
        for button in self._camera_clear_buttons.values():
            button.setEnabled(has_video and not busy)
        for combo in self._camera_mode_combos.values():
            combo.setEnabled(has_video and not busy)
        self.save_action.setEnabled(has_project and not busy)
        self.review.set_edit_enabled((has_pages or has_trash) and not busy)
        self.preview.set_regions_editable(has_project and has_video and not busy)
        if self._busy_kind == "analysis":
            self.analyze_button.setText("分析中…")
        elif self._busy_kind == "export":
            self.analyze_button.setText("导出中…")
        else:
            self.analyze_button.setText("开始分析")

    # -------------------------------------------------------------- Messages
    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "使用说明",
            "1. 导入视频，预览并设置正片开始/结束时间。\n"
            "2. 框选 PPT 区域；如老师摄像头在 PPT 上，可在“画面区域”中设置摄像头数量，"
            "再逐个框选并为每个区域选择忽略、裁剪、黑色遮罩或白色遮罩。\n"
            "   已有区域可直接拖动边框或四角/边中点控制点微调，无需重新框选。\n"
            "3. 点击“开始分析”。系统先低采样率粗扫，再在疑似切页处提高采样率寻找稳定帧。\n"
            "4. 在下方复核：删除、上移/下移、跳过、切换备选帧、打开大图、定位原视频时间。\n"
            "5. 点击“导出”（或 Ctrl+E）生成 PNG、PPTX 和 JSON 清单。\n"
            "6. 项目会随人工修改自动保存到 .lsp.json 文件及同名 _assets 文件夹。\n\n"
            "说明：分析时始终排除所有已设置摄像头区域；各区域的导出处理方式可以不同。"
            "笔迹和小范围动画通常不会被视为新页面。",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            f"<b>{APP_NAME} · {STAGE_NAME}</b><br>"
            f"版本 {__version__} · 项目格式 v{PROJECT_SCHEMA_VERSION}<br><br>"
            "本地运行，不上传视频。使用 PySide6、OpenCV、FFmpeg、PySceneDetect 和 python-pptx。"
            "<br>预览不含音频；本阶段用于提取幻灯片，不用于完整播放授课视频。",
        )

    # ----------------------------------------------------------- Drag & drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.is_file():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.is_file():
                continue
            if path.suffix.lower() == ".json":
                self.open_project_path(path)
            else:
                self.import_video_path(path)
            event.acceptProposedAction()
            return
        event.ignore()

    def open_project_path(self, path: str | Path) -> None:
        if self._busy_kind:
            return
        if not self._maybe_save_changes():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            project = load_project(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "无法打开项目", str(exc))
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        self.prefs.last_project_dir = str(Path(path).parent)
        self._show_project(project)
        self.task_status.setText(
            f"项目已载入：{len(project.pages)} 个候选页面，保留 {len(project.active_pages())} 页。"
            if project.pages
            else "项目已载入，尚未分析。"
        )
        self.statusBar().showMessage(f"已打开项目：{Path(path).name}", 7000)

    def import_video_path(self, path: str | Path) -> None:
        if self._busy_kind:
            return
        if not self._maybe_save_changes():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = probe_video(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "无法导入视频", str(exc))
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        project = SlidesProject(
            name=Path(path).stem,
            video_info=info,
            content_start=0.0,
            content_end=info.duration_sec,
            ppt_region=Rect.full_frame(),
            camera_regions=[],
            settings=AnalysisSettings.from_dict(self.prefs.analysis_settings.to_dict()),
        )
        self._show_project(project)
        self.task_status.setText(
            "视频已就绪。区域可直接拖动边框/控制点调整；设置完成后点击“开始分析”。"
        )
        self.statusBar().showMessage(f"已导入 {Path(path).name}", 7000)

    # ---------------------------------------------------------------- Closing
    def closeEvent(self, event) -> None:
        if not self._confirm_stop_tasks_for_close():
            event.ignore()
            return
        if not self._maybe_save_changes():
            event.ignore()
            return
        self.prefs.save()
        self.player.close()
        self.autosave_timer.stop()
        super().closeEvent(event)

    def _confirm_stop_tasks_for_close(self) -> bool:
        running = None
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            running = self.analysis_worker
            label = "视频分析"
        elif self.export_worker is not None and self.export_worker.isRunning():
            running = self.export_worker
            label = "导出"
        if running is None:
            return True
        answer = QMessageBox.question(
            self,
            "任务仍在运行",
            f"{label}正在后台运行。是否取消任务并退出？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        running.cancel()
        if not running.wait(8000):
            QMessageBox.warning(
                self,
                "任务仍在停止",
                "后台任务尚未结束，请稍候再次关闭窗口。",
            )
            return False
        return True




