"""Video probing with FFprobe plus an OpenCV validation pass."""
from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import cv2

from .models import VideoInfo

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".flv",
    ".wmv",
    ".ts",
    ".mts",
    ".m2ts",
    ".mpeg",
    ".mpg",
}


class VideoError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _parse_fraction(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        frac = Fraction(value)
        return float(frac) if frac.denominator else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _ffprobe_json(path: Path) -> dict | None:
    executable = shutil.which("ffprobe")
    if not executable:
        return None
    command = [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _rotation(video_stream: dict) -> int:
    tags = video_stream.get("tags") or {}
    for key in ("rotate", "ROTATE"):
        try:
            return int(float(tags.get(key)))
        except (TypeError, ValueError):
            pass
    for side_data in video_stream.get("side_data_list") or []:
        if "rotation" in side_data:
            try:
                return int(float(side_data["rotation"]))
            except (TypeError, ValueError):
                pass
    return 0


def _open_capture(path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    orientation_auto = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    if orientation_auto is not None:
        try:
            cap.set(orientation_auto, 1)
        except cv2.error:
            pass
    return cap


def probe_video(path: str | Path) -> VideoInfo:
    path = Path(path)
    if not path.exists():
        raise VideoError(f"文件不存在：{path}")
    if not path.is_file():
        raise VideoError("所选路径不是文件。")
    if path.stat().st_size <= 0:
        raise VideoError("视频文件为空。")
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        # Do not reject outright: OpenCV/FFmpeg may still decode it, but warn
        # through a clear error only if decoding also fails.
        pass

    metadata = _ffprobe_json(path) or {}
    streams = metadata.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = metadata.get("format") or {}

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    rotation = _rotation(video_stream)
    duration = 0.0
    try:
        duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    fps = _parse_fraction(video_stream.get("avg_frame_rate")) or _parse_fraction(
        video_stream.get("r_frame_rate")
    )

    cap = _open_capture(path)
    if not cap.isOpened():
        cap.release()
        raise VideoError(
            "无法打开视频。请确认文件未损坏，并检查 OpenCV/FFmpeg 是否支持该编码格式。"
        )
    frame = None
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise VideoError("视频无法解码出任何画面，文件可能损坏或编码不受支持。")
        frame_height, frame_width = frame.shape[:2]
        cap_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cap_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    finally:
        cap.release()

    if not width or not height:
        width, height = int(frame_width), int(frame_height)
    # Use the actual decoded frame size: all normalized regions are relative to
    # frames returned by VideoReader (not to container metadata).
    width, height = int(frame_width), int(frame_height)
    if fps <= 0 or fps > 480:
        fps = cap_fps if 0 < cap_fps < 480 else 25.0
    if duration <= 0 and cap_count > 0 and fps > 0:
        duration = cap_count / fps
    if duration <= 0:
        # Last-resort estimate through seeking.
        cap = _open_capture(path)
        try:
            cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0)
            duration = max(0.0, float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0)
        finally:
            cap.release()
    if not cap_count and duration > 0 and fps > 0:
        cap_count = int(round(duration * fps))
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0

    return VideoInfo(
        path=str(path.resolve()),
        width=width,
        height=height,
        fps=fps,
        duration_sec=duration,
        frame_count=cap_count,
        codec=str(video_stream.get("codec_name") or ""),
        rotation=rotation,
        has_audio=audio_stream is not None,
        file_size=file_size,
    )
