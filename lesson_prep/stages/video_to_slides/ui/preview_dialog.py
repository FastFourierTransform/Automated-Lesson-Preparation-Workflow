"""Large, resizable video preview with region selection.

The dialog shares the main window's VideoPlayer, so playback stays in sync and
user selections are committed through the same signals as the inline preview.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
)

from ....core.timecode import format_timecode
from ....core.ui.preview_canvas import PreviewCanvas
from ..models import SlidesProject


class LargePreviewDialog(QDialog):
    selection_requested = Signal(str)
    reset_ppt_requested = Signal()
    clear_region_requested = Signal(str)
    closed = Signal()

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.project: SlidesProject | None = None
        self._scrubbing = False
        self._resume_after_scrub = False
        self.setWindowTitle("视频预览（放大）")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setMinimumSize(760, 520)
        self._build_ui()
        self._connect_player()
        screen = parent.screen() if parent is not None and parent.screen() else QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                max(760, int(available.width() * 0.9)),
                max(540, int(available.height() * 0.88)),
            )
            self.move(available.center() - self.rect().center())
        if not player.last_image.isNull():
            self.canvas.set_image(player.last_image)

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("视频预览（放大）")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        self.source_label = QLabel("")
        self.source_label.setObjectName("mutedLabel")
        header.addWidget(self.source_label, 1)
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("mutedLabel")
        header.addWidget(self.hint_label)
        root.addLayout(header)

        self.canvas = PreviewCanvas()
        self.canvas.setMinimumSize(640, 360)
        root.addWidget(self.canvas, 1)

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
        self.time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        controls.addWidget(self.time_label)
        root.addLayout(controls)

        selection_row = QHBoxLayout()
        selection_row.setSpacing(6)
        selection_row.addWidget(QLabel("框选目标"))
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(150)
        self.target_combo.addItem("PPT 区域", "ppt")
        selection_row.addWidget(self.target_combo)
        self.select_button = QPushButton("框选")
        self.select_button.setToolTip(
            "在放大预览中拖拽框选；已有区域可直接拖动边框/控制点调整。"
        )
        selection_row.addWidget(self.select_button)
        self.reset_button = QPushButton("全画面")
        self.reset_button.setToolTip("将 PPT 区域重置为整个视频画面。")
        selection_row.addWidget(self.reset_button)
        self.clear_button = QPushButton("清除区域")
        self.clear_button.setToolTip("清除当前摄像头区域。")
        selection_row.addWidget(self.clear_button)
        selection_row.addStretch(1)
        self.close_button = QPushButton("关闭")
        selection_row.addWidget(self.close_button)
        root.addLayout(selection_row)

        self.region_hint = QLabel(
            "选择目标后点“框选”，然后在此窗口中拖拽。区域坐标为归一化坐标，"
            "与主窗口和项目文件实时同步。"
        )
        self.region_hint.setObjectName("mutedLabel")
        self.region_hint.setWordWrap(True)
        root.addWidget(self.region_hint)

        self.play_button.clicked.connect(self.player.toggle)
        self.back_button.clicked.connect(
            lambda: self.player.seek(max(0.0, self.player.position - 5.0))
        )
        self.forward_button.clicked.connect(
            lambda: self.player.seek(self.player.position + 5.0)
        )
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        self.select_button.clicked.connect(self._request_selection)
        self.reset_button.clicked.connect(self.reset_ppt_requested.emit)
        self.clear_button.clicked.connect(self._request_clear)
        self.close_button.clicked.connect(self.close)
        self._on_target_changed()

    def _connect_player(self) -> None:
        self.player.frame_ready.connect(self.canvas.set_image)
        self.player.position_changed.connect(self._on_position_changed)
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.playing_changed.connect(self._on_playing_changed)
        self.player.video_changed.connect(lambda _index: self._update_source_label())

    # ------------------------------------------------------------- project
    def set_project(self, project: SlidesProject | None, editable: bool = True) -> None:
        self.project = project
        self._refresh_targets()
        self._refresh_regions()
        has_video = project is not None and self.player.reader is not None
        self.canvas.set_regions_editable(editable and has_video)
        self._set_controls_enabled(editable and has_video)
        self._update_source_label()
        if not has_video:
            self.set_selection_idle()

    def _refresh_targets(self) -> None:
        current = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        try:
            self.target_combo.clear()
            self.target_combo.addItem("PPT 区域", "ppt")
            cameras = self.project.camera_regions if self.project else []
            for index, camera in enumerate(cameras):
                self.target_combo.addItem(f"摄像头 {index + 1}", f"camera:{camera.id}")
            target_index = self.target_combo.findData(current) if current else 0
            self.target_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        finally:
            self.target_combo.blockSignals(False)
        self._on_target_changed()

    def _refresh_regions(self) -> None:
        overlays: list[tuple[str, str, object]] = []
        if self.project is not None:
            for index, camera in enumerate(self.project.camera_regions):
                if camera.region is not None and camera.is_configured():
                    overlays.append(
                        (f"camera:{camera.id}", f"摄像头 {index + 1}", camera.region)
                    )
        self.canvas.set_regions(
            self.project.ppt_region if self.project is not None else None,
            overlays,
            primary_kind="ppt",
            primary_label="PPT 区域",
        )

    def _selected_target(self) -> str:
        return str(self.target_combo.currentData() or "ppt")

    def _on_target_changed(self, *_args) -> None:
        target = self._selected_target()
        is_ppt = target == "ppt"
        self.reset_button.setEnabled(is_ppt and self.project is not None)
        self.clear_button.setEnabled(not is_ppt and self.project is not None)
        self.select_button.setEnabled(self.project is not None)
        if not self.canvas.selection_mode:
            self.select_button.setText("框选")

    def _request_selection(self) -> None:
        target = self._selected_target()
        if target:
            self.selection_requested.emit(target)

    def _request_clear(self) -> None:
        target = self._selected_target()
        if target.startswith("camera:"):
            self.clear_region_requested.emit(target)

    # ----------------------------------------------------------- selection
    def set_selection_started(self, kind: str, label: str) -> None:
        index = self.target_combo.findData(kind)
        if index >= 0:
            blocked = self.target_combo.blockSignals(True)
            self.target_combo.setCurrentIndex(index)
            self.target_combo.blockSignals(blocked)
        self.canvas.start_selection(kind, label=label)
        if kind == "ppt":
            self.canvas.set_regions_editable(True)
        self.select_button.setText("拖拽中…")
        self.hint_label.setText("拖拽框选，Esc 取消")
        self.region_hint.setText(
            f"正在框选{label}：在放大画面中拖拽，松开鼠标后立即保存；按 Esc 取消。"
        )

    def set_selection_idle(self) -> None:
        if self.canvas.selection_mode is not None:
            self.canvas.cancel_selection()
        self.select_button.setText("框选")
        self.hint_label.setText("")
        self.region_hint.setText(
            "选择目标后点“框选”，然后在此窗口中拖拽。区域坐标为归一化坐标，"
            "与主窗口和项目文件实时同步。"
        )

    def cancel_selection(self) -> None:
        if self.canvas.selection_mode is not None:
            self.canvas.cancel_selection()

    def is_selecting(self) -> bool:
        return self.canvas.selection_mode is not None

    def set_editable(self, editable: bool) -> None:
        has_video = self.project is not None and self.player.reader is not None
        self.canvas.set_regions_editable(editable and has_video)
        self._set_controls_enabled(has_video and editable)
        if not editable:
            self.set_selection_idle()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.play_button,
            self.back_button,
            self.forward_button,
            self.position_slider,
            self.target_combo,
            self.select_button,
            self.reset_button,
            self.clear_button,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._on_target_changed()

    # ------------------------------------------------------------ playback
    def _on_duration_changed(self, duration: float) -> None:
        self.position_slider.setRange(0, int(max(0.0, duration) * 1000))
        self._update_time_label(self.player.position, duration)

    def _on_position_changed(self, position: float) -> None:
        if not self._scrubbing:
            self.position_slider.setValue(int(max(0.0, position) * 1000))
        self._update_time_label(position, self.player.duration)

    def _update_time_label(self, position: float, duration: float) -> None:
        self.time_label.setText(
            f"{format_timecode(position, milliseconds=True)} / {format_timecode(duration)}"
        )

    def _on_playing_changed(self, playing: bool) -> None:
        self.play_button.setText("❚❚" if playing else "▶")
        self.play_button.setToolTip("暂停" if playing else "播放")

    def _on_slider_pressed(self) -> None:
        self._scrubbing = True
        self._resume_after_scrub = self.player.is_playing
        self.player.pause()

    def _on_slider_moved(self, value: int) -> None:
        self._update_time_label(value / 1000.0, self.player.duration)

    def _on_slider_released(self) -> None:
        value = self.position_slider.value()
        self._scrubbing = False
        self.player.seek(value / 1000.0)
        if self._resume_after_scrub:
            self.player.play()
        self._update_time_label(self.player.position, self.player.duration)

    def update_source_label(self) -> None:
        self._update_source_label()

    def _update_source_label(self) -> None:
        if self.project is None:
            self.source_label.setText("")
            return
        index = max(0, self.player.video_index)
        name = ""
        sources = self.project.video_sources()
        if 0 <= index < len(sources) and sources[index].path:
            name = sources[index].path.replace("\\", "/").rsplit("/", 1)[-1]
        total = self.project.total_duration_sec()
        suffix = f" · 当前：视频 {index + 1}/{max(1, len(sources))} {name}"
        self.source_label.setText(
            f"总时长 {format_timecode(total)}"
            + (suffix if len(sources) > 1 or name else "")
        )

    # --------------------------------------------------------------- close
    def closeEvent(self, event) -> None:
        self.cancel_selection()
        self.closed.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return
        super().keyPressEvent(event)
