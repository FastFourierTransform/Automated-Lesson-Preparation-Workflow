"""Low-cost coarse scanning and transition hint generation."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from ....core.geometry import Rect
from ..models import AnalysisSettings, VideoInfo
from ....core.media.reader import VideoDecodeError, VideoReader
from ....core.media.sampler import FfmpegSampler, SamplerError
from .errors import AnalysisCancelled, AnalysisError
from .metrics import FrameDiff, compare_frames, prepare_frame
from .scenes import SceneDetectorAdapter, SceneHint

ProgressCallback = Callable[[float, str], None]
StatusCallback = Callable[[str], None]


@dataclass
class TransitionHint:
    time_sec: float
    sources: tuple[str, ...] = ("coarse",)
    strength: float = 0.5


@dataclass
class _RawChange:
    time_sec: float
    strength: float
    metrics: FrameDiff


@dataclass
class _HintGroup:
    start: float
    end: float
    strength: float
    sources: set[str] = field(default_factory=lambda: {"coarse"})


@dataclass
class CoarseScanResult:
    hints: list[TransitionHint]
    sample_count: int = 0
    raw_change_count: int = 0
    scene_cut_count: int = 0
    used_ffmpeg: bool = False
    warnings: list[str] = field(default_factory=list)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled("分析已取消")


def _change_strength(diff: FrameDiff, settings: AnalysisSettings) -> float:
    ratio = diff.changed_ratio / max(1e-6, settings.coarse_change_ratio_threshold)
    mad = diff.mad / max(1e-6, settings.coarse_mad_threshold)
    ssim = (
        max(0.0, settings.coarse_ssim_threshold - diff.ssim)
        / max(1e-6, settings.coarse_ssim_threshold)
        * 2.0
    )
    return float(min(3.0, max(ratio, mad, ssim)))


def _scan_frames(
    frames: Iterable[tuple[float, np.ndarray]],
    ppt_region: Rect,
    camera_regions: list[Rect] | None,
    settings: AnalysisSettings,
    content_start: float,
    content_end: float,
    cancel_event: threading.Event | None,
    progress_cb: ProgressCallback | None,
    status_cb: StatusCallback | None,
    scene_adapter: SceneDetectorAdapter,
) -> tuple[list[_RawChange], list[SceneHint], int]:
    previous = None
    previous_time = 0.0
    raw_changes: list[_RawChange] = []
    scene_hints: list[SceneHint] = []
    sample_count = 0
    last_progress = -10.0
    duration = max(0.001, content_end - content_start)
    for time_sec, frame in frames:
        _check_cancel(cancel_event)
        prepared = prepare_frame(
            frame,
            ppt_region,
            camera_regions,
            settings.analysis_width,
            want_color=scene_adapter.enabled,
        )
        sample_count += 1
        if scene_adapter.enabled and prepared.color is not None:
            hints = scene_adapter.feed(time_sec, prepared.color)
            for hint in hints:
                if content_start - 0.5 <= hint.time_sec <= content_end + 0.5:
                    scene_hints.append(hint)
        if previous is not None:
            diff = compare_frames(
                previous.gray,
                prepared.gray,
                prepared.mask,
                settings.pixel_diff_threshold,
            )
            if diff.is_coarse_change(settings):
                midpoint = previous_time + max(0.0, time_sec - previous_time) * 0.5
                raw_changes.append(
                    _RawChange(
                        time_sec=midpoint,
                        strength=_change_strength(diff, settings),
                        metrics=diff,
                    )
                )
        previous = prepared
        previous_time = time_sec
        progress = 100.0 * (time_sec - content_start) / duration
        if progress - last_progress >= 2.0 or sample_count == 1:
            last_progress = progress
            if progress_cb:
                progress_cb(float(min(100.0, max(0.0, progress))), f"粗扫描：{sample_count} 帧")
    return raw_changes, scene_hints, sample_count


def _group_changes(
    changes: list[_RawChange],
    scene_hints: list[SceneHint],
    content_start: float,
    content_end: float,
    settings: AnalysisSettings,
) -> tuple[list[TransitionHint], int]:
    groups: list[_HintGroup] = []
    for change in sorted(changes, key=lambda c: c.time_sec):
        if change.time_sec < content_start - 0.5 or change.time_sec > content_end + 0.5:
            continue
        if groups and change.time_sec - groups[-1].end <= settings.change_group_gap_sec:
            group = groups[-1]
            group.end = max(group.end, change.time_sec)
            group.strength = max(group.strength, change.strength)
        else:
            groups.append(
                _HintGroup(
                    start=max(content_start, change.time_sec),
                    end=min(content_end, change.time_sec),
                    strength=change.strength,
                )
            )

    # Add PySceneDetect candidates without treating them as pages.  A scene
    # cut is merged with a nearby internal hint when possible; otherwise it is
    # kept as an additional candidate for second-level verification.
    if scene_hints:
        for scene in sorted(scene_hints, key=lambda h: h.time_sec):
            if not (content_start - 0.5 <= scene.time_sec <= content_end + 0.5):
                continue
            match = None
            for group in groups:
                margin = max(0.65, settings.change_group_gap_sec)
                if group.start - margin <= scene.time_sec <= group.end + margin:
                    match = group
                    break
            if match is not None:
                match.sources.add("pyscenedetect")
                match.start = max(content_start, min(match.start, scene.time_sec))
                match.end = min(content_end, max(match.end, scene.time_sec))
            else:
                groups.append(
                    _HintGroup(
                        start=max(content_start, scene.time_sec),
                        end=min(content_end, scene.time_sec),
                        strength=0.55,
                        sources={"pyscenedetect"},
                    )
                )

    groups.sort(key=lambda g: g.start)
    deduped: list[_HintGroup] = []
    for group in groups:
        if deduped and group.start - deduped[-1].start < max(0.35, settings.change_group_gap_sec * 0.4):
            prior = deduped[-1]
            prior.end = max(prior.end, group.end)
            prior.strength = max(prior.strength, group.strength)
            prior.sources |= group.sources
        else:
            deduped.append(group)
    hints = [
        TransitionHint(
            time_sec=max(content_start, min(group.start, content_end)),
            sources=tuple(sorted(group.sources)),
            strength=group.strength,
        )
        for group in deduped
    ]
    return hints, len(scene_hints)


def run_coarse_scan(
    video_path: str | Path,
    video_info: VideoInfo,
    content_start: float,
    content_end: float,
    ppt_region: Rect,
    camera_regions: list[Rect] | None,
    settings: AnalysisSettings,
    cancel_event: threading.Event | None = None,
    progress_cb: ProgressCallback | None = None,
    status_cb: StatusCallback | None = None,
) -> CoarseScanResult:
    """Run a low-cost scan, with FFmpeg streaming and OpenCV fallback."""
    if content_end <= content_start:
        raise AnalysisError("正片结束时间必须晚于开始时间。")
    warnings: list[str] = []
    used_ffmpeg = False
    scene_errors: list[str] = []
    try:
        if not FfmpegSampler.available():
            raise SamplerError("未找到 FFmpeg")
        if status_cb:
            status_cb("使用 FFmpeg 进行粗扫描…")
        sampler = FfmpegSampler(
            video_path,
            content_start,
            content_end,
            settings.coarse_fps,
            settings.analysis_width,
            video_info,
        )
        adapter = SceneDetectorAdapter(settings, settings.coarse_fps)
        try:
            changes, scene_hints, sample_count = _scan_frames(
                sampler.iter_frames(),
                ppt_region,
                camera_regions,
                settings,
                content_start,
                content_end,
                cancel_event,
                progress_cb,
                status_cb,
                adapter,
            )
            used_ffmpeg = True
        finally:
            adapter.finish()
            sampler.close()
        if adapter.error:
            scene_errors.append(adapter.error)
    except AnalysisCancelled:
        raise
    except (SamplerError, OSError, ValueError) as exc:
        _check_cancel(cancel_event)
        warnings.append(f"FFmpeg 粗扫描失败，已切换到 OpenCV 逐帧扫描：{exc}")
        if status_cb:
            status_cb("FFmpeg 不可用，正在用 OpenCV 扫描…")
        reader = None
        adapter = SceneDetectorAdapter(settings, settings.coarse_fps)
        try:
            reader = VideoReader(video_path, video_info)
            changes, scene_hints, sample_count = _scan_frames(
                reader.iter_window(content_start, content_end, settings.coarse_fps),
                ppt_region,
                camera_regions,
                settings,
                content_start,
                content_end,
                cancel_event,
                progress_cb,
                status_cb,
                adapter,
            )
        except VideoDecodeError as reader_exc:
            raise AnalysisError(f"视频解码失败：{reader_exc}") from reader_exc
        finally:
            adapter.finish()
            if reader is not None:
                reader.close()
        if adapter.error:
            scene_errors.append(adapter.error)
    if scene_errors:
        warnings.extend(dict.fromkeys(scene_errors))
    hints, scene_count = _group_changes(
        changes,
        scene_hints,
        content_start,
        content_end,
        settings,
    )
    if not hints:
        warnings.append("粗扫描未发现明显切页，将以正片起点作为唯一起点进行稳定帧提取。")
    return CoarseScanResult(
        hints=hints,
        sample_count=sample_count,
        raw_change_count=len(changes),
        scene_cut_count=scene_count,
        used_ffmpeg=used_ffmpeg,
        warnings=warnings,
    )

