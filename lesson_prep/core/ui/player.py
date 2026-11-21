"""OpenCV-backed preview playback.

Only one decoded frame is held at a time.  Playback is intentionally
audio-less; the preview is for locating frames, not for watching a full
lesson.
"""
from __future__ import annotations

import cv2
from PySide6.QtCore import QObject, QTimer, Signal

from ..geometry import bgr_to_qimage
from ..media.models import VideoInfo
from ..media.reader import VideoDecodeError, VideoReader


class VideoPlayer(QObject):
    frame_ready = Signal(object)
    position_changed = Signal(float)
    duration_changed = Signal(float)
    playing_changed = Signal(bool)
    video_opened = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader: VideoReader | None = None
        self.info: VideoInfo | None = None
        self._position = 0.0
        self._duration = 0.0
        self._playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._preview_max_width = 1280

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    def open(self, path: str, info: VideoInfo | None = None) -> None:
        self.close()
        try:
            self.reader = VideoReader(path, info)
        except VideoDecodeError as exc:
            self.reader = None
            raise RuntimeError(str(exc)) from exc
        self.info = info
        self._duration = self.reader.duration
        interval = int(round(1000.0 / max(1.0, self.reader.fps)))
        self.timer.setInterval(max(16, min(80, interval)))
        self.duration_changed.emit(self._duration)
        self.video_opened.emit()
        self.seek(0.0, emit_state=False)
        self.position_changed.emit(self._position)

    def play(self) -> None:
        if self.reader is None or self._playing:
            return
        if self._duration > 0 and self._position >= self._duration - 0.08:
            self.seek(0.0, emit_state=False)
        self._playing = True
        self.timer.start()
        self.playing_changed.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self.timer.stop()
        self.playing_changed.emit(False)

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, time_sec: float, emit_state: bool = True) -> None:
        if self.reader is None:
            return
        target = max(0.0, min(float(time_sec), max(0.0, self._duration - 0.05)))
        try:
            actual, frame = self.reader.read_frame(target)
        except VideoDecodeError as exc:
            self.pause()
            self.error.emit(str(exc))
            return
        self._position = float(actual)
        self._emit_frame(frame)
        self.position_changed.emit(self._position)
        if emit_state:
            self.playing_changed.emit(self._playing)

    def _tick(self) -> None:
        if not self._playing or self.reader is None:
            return
        result = self.reader.read_next()
        if result is None:
            self.pause()
            self.position_changed.emit(self._duration)
            return
        position, frame = result
        self._position = float(position)
        self._emit_frame(frame)
        self.position_changed.emit(self._position)
        if self._duration > 0 and self._position >= self._duration - 0.02:
            self.pause()

    def _emit_frame(self, frame) -> None:
        if frame is None:
            return
        if frame.shape[1] > self._preview_max_width:
            scale = self._preview_max_width / frame.shape[1]
            new_size = (
                self._preview_max_width,
                max(1, int(round(frame.shape[0] * scale))),
            )
            frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)
        image = bgr_to_qimage(frame)
        self.frame_ready.emit(image)

    def close(self) -> None:
        self.timer.stop()
        if self._playing:
            self._playing = False
            self.playing_changed.emit(False)
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        self.info = None
        self._position = 0.0
        self._duration = 0.0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
