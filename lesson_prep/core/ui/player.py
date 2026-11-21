"""OpenCV-backed preview playback for one or several source videos.

Only one decoded frame is held at a time.  Several videos are presented as a
single continuous, audio-less timeline: playback crosses video boundaries
automatically, and ``seek`` accepts a combined-timeline position.
"""
from __future__ import annotations

from typing import Iterable

import cv2
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from ..geometry import bgr_to_qimage
from ..media.models import VideoInfo
from ..media.reader import VideoDecodeError, VideoReader
from ..media.timeline import (
    VideoSegment,
    build_timeline,
    segment_for_time,
    timeline_duration,
)


class VideoPlayer(QObject):
    frame_ready = Signal(object)
    position_changed = Signal(float)
    duration_changed = Signal(float)
    playing_changed = Signal(bool)
    video_opened = Signal()
    video_changed = Signal(int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader: VideoReader | None = None
        self.info: VideoInfo | None = None
        self._segments: list[VideoSegment] = []
        self._video_index = -1
        self._position = 0.0
        self._duration = 0.0
        self._playing = False
        self._last_image = QImage()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._preview_max_width = 1600

    # ------------------------------------------------------------- properties
    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position(self) -> float:
        return self._position

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def segments(self) -> list[VideoSegment]:
        return list(self._segments)

    @property
    def video_index(self) -> int:
        return self._video_index

    @property
    def current_segment(self) -> VideoSegment | None:
        if 0 <= self._video_index < len(self._segments):
            return self._segments[self._video_index]
        return None

    @property
    def current_video_info(self) -> VideoInfo | None:
        segment = self.current_segment
        return segment.video_info if segment is not None else None

    @property
    def local_position(self) -> float:
        segment = self.current_segment
        if segment is None:
            return 0.0
        return max(0.0, min(self._position - segment.start_sec, segment.duration_sec))

    @property
    def last_image(self) -> QImage:
        return self._last_image

    # ------------------------------------------------------------------ open
    def open(self, path: str, info: VideoInfo | None = None) -> None:
        """Open a single video (compatibility API)."""
        if info is None or info.duration_sec <= 0:
            info = info or VideoInfo(path=str(path))
            info.path = str(path)
            if info.duration_sec <= 0:
                probe = None
                try:
                    probe = VideoReader(path, info)
                    info.duration_sec = probe.duration
                    info.fps = info.fps or probe.fps
                    info.width = info.width or probe.width
                    info.height = info.height or probe.height
                    info.frame_count = info.frame_count or probe.frame_count
                finally:
                    if probe is not None:
                        probe.close()
        self.open_playlist([info])

    def open_playlist(
        self,
        videos: Iterable[VideoInfo],
        position: float = 0.0,
    ) -> None:
        """Open several videos as one continuous timeline."""
        sources = list(videos)
        self.close()
        if not sources:
            return
        segments = build_timeline(sources)
        if not segments:
            return
        invalid = [
            segment.video_info.path or f"视频 {segment.index + 1}"
            for segment in segments
            if segment.duration_sec <= 0
        ]
        if invalid:
            raise RuntimeError(
                "以下视频缺少有效时长，无法建立连续时间轴：\n" + "\n".join(invalid)
            )
        self._segments = segments
        self._duration = timeline_duration(segments)
        self.duration_changed.emit(self._duration)
        target = max(0.0, min(float(position), max(0.0, self._duration - 0.05)))
        segment, _local = segment_for_time(segments, target)
        if segment is None:
            self.close()
            return
        try:
            self._open_segment(segment.index)
        except VideoDecodeError as exc:
            self.close()
            raise RuntimeError(str(exc)) from exc
        self.video_opened.emit()
        self.seek(target, emit_state=False)
        self.position_changed.emit(self._position)

    def _open_segment(self, index: int) -> None:
        if index < 0 or index >= len(self._segments):
            raise VideoDecodeError("视频片段索引无效。")
        if self._video_index == index and self.reader is not None:
            return
        self._release_reader()
        segment = self._segments[index]
        self.reader = VideoReader(segment.video_info.path, segment.video_info)
        self._video_index = index
        self.info = segment.video_info
        fps = self.reader.fps or segment.video_info.fps or 25.0
        interval = int(round(1000.0 / max(1.0, fps)))
        self.timer.setInterval(max(16, min(80, interval)))
        self.video_changed.emit(index)

    # -------------------------------------------------------------- playback
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
        if not self._segments:
            return
        target = max(0.0, min(float(time_sec), max(0.0, self._duration - 0.05)))
        segment, local = segment_for_time(self._segments, target)
        if segment is None:
            return
        try:
            self._open_segment(segment.index)
            actual, frame = self.reader.read_frame(local)
        except VideoDecodeError as exc:
            self.pause()
            self.error.emit(str(exc))
            return
        self._position = segment.global_time(actual)
        self._emit_frame(frame)
        self.position_changed.emit(self._position)
        if emit_state:
            self.playing_changed.emit(self._playing)

    def _tick(self) -> None:
        if not self._playing or self.reader is None:
            return
        result = self.reader.read_next()
        if result is None:
            # Move to the next source video automatically.  A few empty
            # sources should not stop playback of the whole timeline.
            result = self._read_first_frame_of_next_segment()
            if result is None:
                self.pause()
                self._position = self._duration
                self.position_changed.emit(self._duration)
                return
        position, frame = result
        segment = self.current_segment
        if segment is None:
            self.pause()
            return
        self._position = segment.global_time(position)
        self._emit_frame(frame)
        self.position_changed.emit(self._position)
        if self._duration > 0 and self._position >= self._duration - 0.02:
            self.pause()

    def _read_first_frame_of_next_segment(self):
        while self._video_index + 1 < len(self._segments):
            try:
                self._open_segment(self._video_index + 1)
                result = self.reader.read_next() if self.reader is not None else None
            except VideoDecodeError as exc:
                self.pause()
                self.error.emit(str(exc))
                return None
            if result is not None:
                return result
        return None

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
        self._last_image = image
        self.frame_ready.emit(image)

    def _release_reader(self) -> None:
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    def close(self) -> None:
        self.timer.stop()
        if self._playing:
            self._playing = False
            self.playing_changed.emit(False)
        self._release_reader()
        self.info = None
        self._segments = []
        self._video_index = -1
        self._position = 0.0
        self._duration = 0.0
        self._last_image = QImage()
        self.duration_changed.emit(0.0)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
