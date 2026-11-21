"""Virtual concatenation of several videos into one continuous timeline.

The video-to-slides stage analyses multiple source videos as if they were one
long recording.  This module owns the offset arithmetic so the player, the
analysis engine, the project file and the UI all agree on the mapping between
the combined (global) time axis and each source video's local time.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import VideoInfo


@dataclass(frozen=True)
class VideoSegment:
    """One source video placed on the combined timeline."""

    index: int
    video_info: VideoInfo
    start_sec: float
    duration_sec: float

    @property
    def end_sec(self) -> float:
        return self.start_sec + self.duration_sec

    @property
    def path(self) -> str:
        return self.video_info.path

    def global_time(self, local_time: float) -> float:
        return self.start_sec + max(0.0, min(float(local_time), self.duration_sec))


def effective_duration(video_info: VideoInfo) -> float:
    """Best available duration for one source video."""
    duration = float(video_info.duration_sec or 0.0)
    if duration > 0:
        return duration
    fps = float(video_info.fps or 0.0)
    frames = int(video_info.frame_count or 0)
    if fps > 0 and frames > 0:
        return frames / fps
    return 0.0


def build_timeline(videos: Iterable[VideoInfo]) -> list[VideoSegment]:
    """Assign consecutive global start offsets to the given videos."""
    segments: list[VideoSegment] = []
    offset = 0.0
    for index, info in enumerate(videos):
        duration = effective_duration(info)
        segments.append(
            VideoSegment(
                index=index,
                video_info=info,
                start_sec=offset,
                duration_sec=duration,
            )
        )
        offset += duration
    return segments


def timeline_duration(segments: Sequence[VideoSegment]) -> float:
    return segments[-1].end_sec if segments else 0.0


def segment_for_time(
    segments: Sequence[VideoSegment],
    time_sec: float,
) -> tuple[VideoSegment | None, float]:
    """Return the segment containing ``time_sec`` and its local time."""
    if not segments:
        return None, 0.0
    total = timeline_duration(segments)
    time_sec = max(0.0, min(float(time_sec), total))
    if time_sec >= total:
        segment = segments[-1]
        return segment, segment.duration_sec
    starts = [segment.start_sec for segment in segments]
    index = max(0, bisect_right(starts, time_sec) - 1)
    segment = segments[min(index, len(segments) - 1)]
    local = max(0.0, min(time_sec - segment.start_sec, segment.duration_sec))
    return segment, local


def segments_for_range(
    segments: Sequence[VideoSegment],
    start_sec: float,
    end_sec: float,
) -> list[tuple[VideoSegment, float, float]]:
    """Intersect a global range with each source video.

    Returns ``(segment, local_start, local_end)`` triples in timeline order.
    Empty intersections are omitted.
    """
    result: list[tuple[VideoSegment, float, float]] = []
    start_sec = max(0.0, float(start_sec))
    end_sec = max(start_sec, float(end_sec))
    for segment in segments:
        if segment.duration_sec <= 0:
            continue
        local_start = max(0.0, start_sec - segment.start_sec)
        local_end = min(segment.duration_sec, end_sec - segment.start_sec)
        if local_end - local_start <= 1e-6:
            continue
        result.append((segment, local_start, local_end))
    return result
