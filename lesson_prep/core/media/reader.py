"""Frame-accurate video reading without loading a whole video into memory."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from .models import VideoInfo


class VideoDecodeError(RuntimeError):
    pass


def _capture(path: str | Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    orientation_auto = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    if orientation_auto is not None:
        try:
            cap.set(orientation_auto, 1)
        except cv2.error:
            pass
    return cap


class VideoReader:
    """A lightweight, sequential/seekable OpenCV reader.

    Never caches raw frames.  Call ``close`` when finished; the reader is also
    a context manager.
    """

    def __init__(self, path: str | Path, info: VideoInfo | None = None):
        self.path = str(path)
        self.info = info
        self.cap: cv2.VideoCapture | None = None
        self._fps = 0.0
        self._frame_count = 0
        self._duration = 0.0
        self._width = 0
        self._height = 0
        self._open()

    def _open(self) -> None:
        cap = _capture(self.path)
        if not cap.isOpened():
            cap.release()
            raise VideoDecodeError("无法打开视频，文件可能损坏或编码不受支持。")
        self.cap = cap
        info = self.info
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if info is not None and info.fps > 0:
            fps = info.fps
        if not (0 < fps < 480):
            fps = 25.0
        self._fps = fps
        self._frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if info is not None and info.frame_count > 0:
            self._frame_count = info.frame_count
        self._duration = float(info.duration_sec) if info and info.duration_sec > 0 else 0.0
        if self._duration <= 0 and self._frame_count > 0:
            self._duration = self._frame_count / fps
        # The first frame determines the coordinate system used everywhere.
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            self.cap = None
            raise VideoDecodeError("视频无法解码出画面。")
        self._height, self._width = frame.shape[:2]
        if self._duration <= 0:
            try:
                cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0)
                self._duration = max(0.0, float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0)
            except cv2.error:
                pass
        self.seek(0.0)

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def is_open(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def _ensure_open(self) -> cv2.VideoCapture:
        if self.cap is None or not self.cap.isOpened():
            raise VideoDecodeError("视频读取器已关闭。")
        return self.cap

    def seek(self, time_sec: float) -> float:
        cap = self._ensure_open()
        target = max(0.0, min(float(time_sec), max(0.0, self._duration - 1.0 / max(self._fps, 1.0))))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
        except cv2.error as exc:
            raise VideoDecodeError(f"无法定位视频时间 {target:.2f}s") from exc
        return target

    def read_next(self) -> tuple[float, np.ndarray] | None:
        cap = self._ensure_open()
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        time_sec = self._position_seconds(cap)
        return time_sec, frame

    def read_frame(self, time_sec: float) -> tuple[float, np.ndarray]:
        self.seek(time_sec)
        result = self.read_next()
        if result is None:
            # Seeking exactly to EOF sometimes yields no frame; retry slightly
            # before the end.
            retry = max(0.0, min(time_sec, self._duration - 0.15))
            self.seek(retry)
            result = self.read_next()
        if result is None:
            raise VideoDecodeError(f"无法读取 {float(time_sec):.2f}s 处的视频帧。")
        return result

    def iter_window(self, start_sec: float, end_sec: float, rate: float) -> Iterator[tuple[float, np.ndarray]]:
        """Sequentially decode a window and yield frames at approximately ``rate``.

        Memory use stays constant, so multi-GB videos are safe.  The caller can
        break out of the generator at any time.
        """
        if rate <= 0:
            raise ValueError("采样率必须大于 0")
        cap = self._ensure_open()
        start = max(0.0, min(float(start_sec), self._duration))
        end = max(start, min(float(end_sec), self._duration))
        if end - start <= 1e-6:
            return
        self.seek(start)
        step = 1.0 / float(rate)
        next_target = start
        previous_pos = start - max(step, 1.0 / max(self._fps, 1.0))
        # A small tolerance avoids skipping a sample because of frame rounding.
        tolerance = 0.45 / max(self._fps, 1.0)
        while True:
            ok = cap.grab()
            if not ok:
                break
            pos = self._position_seconds(cap, fallback=previous_pos + 1.0 / max(self._fps, 1.0))
            if not math.isfinite(pos):
                pos = previous_pos + 1.0 / max(self._fps, 1.0)
            if pos <= previous_pos + 1e-5:
                pos = previous_pos + 1.0 / max(self._fps, 1.0)
            previous_pos = pos
            if pos < start - tolerance:
                continue
            if pos > end + tolerance:
                break
            if pos + tolerance >= next_target:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    yield (max(start, min(pos, end)), frame)
                    next_target = max(next_target + step, pos + step * 0.5)
            if next_target > end + step:
                break

    def _position_seconds(self, cap: cv2.VideoCapture, fallback: float | None = None) -> float:
        try:
            value = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        except cv2.error:
            value = float("nan")
        if not math.isfinite(value) or value <= 0:
            if fallback is not None:
                return fallback
            try:
                frame_index = float(cap.get(cv2.CAP_PROP_POS_FRAMES) or 0.0)
                return frame_index / max(self._fps, 1.0)
            except cv2.error:
                return 0.0
        return value

    def close(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
