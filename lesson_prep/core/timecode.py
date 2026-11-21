"""Timecode parsing and formatting helpers."""
from __future__ import annotations

import math
import re


def format_timecode(seconds: float, milliseconds: bool = False) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if milliseconds:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    return f"{hours:02d}:{minutes:02d}:{int(secs):02d}"


def parse_timecode(value: str, duration: float | None = None) -> float:
    """Parse ``HH:MM:SS``, ``MM:SS`` or plain seconds.

    Raises ValueError for invalid input.  The value is clamped to ``duration``
    when a duration is provided.
    """
    if value is None:
        raise ValueError("时间不能为空")
    text = str(value).strip()
    if not text:
        raise ValueError("时间不能为空")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        seconds = float(text)
    else:
        parts = text.split(":")
        if len(parts) not in (2, 3):
            raise ValueError("时间格式应为 HH:MM:SS 或 MM:SS")
        try:
            numbers = [float(p) for p in parts]
        except ValueError as exc:
            raise ValueError("时间只能包含数字和冒号") from exc
        if len(numbers) == 2:
            minutes, secs = numbers
            if minutes < 0 or secs < 0 or secs >= 60:
                raise ValueError("秒数必须在 0 到 60 之间")
            seconds = minutes * 60 + secs
        else:
            hours, minutes, secs = numbers
            if hours < 0 or minutes < 0 or secs < 0 or minutes >= 60 or secs >= 60:
                raise ValueError("分钟和秒数必须在 0 到 60 之间")
            seconds = hours * 3600 + minutes * 60 + secs
    if not math.isfinite(seconds):
        raise ValueError("时间无效")
    if seconds < 0:
        raise ValueError("时间不能为负数")
    if duration is not None:
        seconds = min(seconds, max(0.0, duration))
    return seconds
