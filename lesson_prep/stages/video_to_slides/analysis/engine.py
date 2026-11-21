"""End-to-end analysis orchestration."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ....core.geometry import Rect, crop_rect, relative_rect
from ..models import (
    AlternativeFrame,
    AnalysisSettings,
    CameraRegion,
    PageCandidate,
    VideoInfo,
    new_id,
)
from ....core.media.reader import VideoDecodeError, VideoReader
from ....core.media.utils import imwrite, save_thumbnail
from .coarse import CoarseScanResult, TransitionHint, run_coarse_scan
from .errors import AnalysisCancelled, AnalysisError
from .metrics import compare_frames, make_valid_mask, quality_flags
from .refine import RefinedAlternative, RefinedPage, refine_candidate

ProgressCallback = Callable[[int, str], None]
StatusCallback = Callable[[str], None]


@dataclass
class AnalysisResult:
    pages: list[PageCandidate]
    warnings: list[str]
    stats: dict
    analysis_region: Rect
    settings: AnalysisSettings
    run_dir: str
    run_rel: str


def _progress_adapter(outer: ProgressCallback | None, low: float, high: float):
    def report(fraction: float, message: str = "") -> None:
        if outer is None:
            return
        percent = int(round(low + (high - low) * max(0.0, min(100.0, fraction)) / 100.0))
        outer(percent, message)

    return report


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled("分析已取消")


def _merge_hint_sources(sorted_hints: list[TransitionHint], min_gap: float = 0.4) -> list[TransitionHint]:
    merged: list[TransitionHint] = []
    for hint in sorted_hints:
        if merged and abs(hint.time_sec - merged[-1].time_sec) < min_gap:
            prior = merged[-1]
            merged[-1] = TransitionHint(
                time_sec=min(prior.time_sec, hint.time_sec),
                sources=tuple(sorted(set(prior.sources) | set(hint.sources))),
                strength=max(prior.strength, hint.strength),
            )
        else:
            merged.append(hint)
    return merged


def _failed_page(hint: TransitionHint, message: str) -> RefinedPage:
    page = PageCandidate(
        id=new_id(),
        interval_start=hint.time_sec,
        interval_end=hint.time_sec,
        selected_time=hint.time_sec,
        confidence=0.0,
        needs_review=True,
        flags=["no_stable_window", "snapshot_failed", "low_confidence"],
        sources=list(hint.sources),
        review_note=f"自动提取失败：{message}"[:500],
        metrics={"detection_strength": float(hint.strength)},
    )
    return RefinedPage(
        page=page,
        selected_gray=np.zeros((2, 2), dtype=np.uint8),
        mask=np.ones((2, 2), dtype=np.uint8),
        alternatives=[],
    )


class AnalysisEngine:
    """Runs a full analysis without touching the UI or the previous project state."""

    def __init__(
        self,
        video_path: str | Path,
        video_info: VideoInfo,
        content_start: float,
        content_end: float,
        ppt_region: Rect,
        camera_regions: list[CameraRegion] | None,
        settings: AnalysisSettings,
        assets_root: str | Path,
        run_dir: str | Path,
        cancel_event: threading.Event | None = None,
        progress_cb: ProgressCallback | None = None,
        status_cb: StatusCallback | None = None,
    ):
        self.video_path = str(video_path)
        self.video_info = video_info
        self.content_start = float(content_start)
        self.content_end = float(content_end)
        self.ppt_region = ppt_region.clamped()
        self.camera_regions = [
            camera
            for camera in (camera_regions or [])
            if camera.is_configured()
        ]
        self.camera_rects = [
            camera.region.clamped()
            for camera in self.camera_regions
            if camera.region is not None
        ]
        self.settings = settings
        self.assets_root = Path(assets_root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.cancel_event = cancel_event or threading.Event()
        self.progress_cb = progress_cb
        self.status_cb = status_cb
        self.warnings: list[str] = []

    def _progress(self, value: int, message: str) -> None:
        if self.progress_cb:
            self.progress_cb(int(max(0, min(100, value))), message)

    def _status(self, message: str) -> None:
        if self.status_cb:
            self.status_cb(message)

    def analyze(self) -> AnalysisResult:
        started = time.perf_counter()
        if not self.ppt_region.is_valid():
            raise AnalysisError("PPT 区域无效，请重新框选。")
        if self.content_end - self.content_start < 0.5:
            raise AnalysisError("正片区间过短，请设置至少 0.5 秒的正片。")
        if not self.video_info.width or not self.video_info.height:
            raise AnalysisError("缺少视频尺寸信息。")
        if self.camera_rects:
            local_cameras = [
                local
                for local in (
                    relative_rect(camera_rect, self.ppt_region)
                    for camera_rect in self.camera_rects
                )
                if local is not None
            ]
            valid = make_valid_mask((100, 100), local_cameras)
            if float(valid.mean()) / 255.0 < 0.05:
                raise AnalysisError(
                    "所有摄像头区域几乎覆盖了整个 PPT 区域，无法进行有效分析。"
                )
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            run_rel = self.run_dir.relative_to(self.assets_root).as_posix()
        except ValueError as exc:
            raise AnalysisError("分析缓存目录必须位于项目资源目录内。") from exc

        self._progress(1, "正在准备分析…")
        self._status("正在读取视频并建立分析上下文…")
        reader: VideoReader | None = None
        try:
            reader = VideoReader(self.video_path, self.video_info)
            self._check_cancel()

            self._progress(2, "正在粗扫描视频…")
            coarse_progress = _progress_adapter(self.progress_cb, 2.0, 46.0)
            coarse = run_coarse_scan(
                self.video_path,
                self.video_info,
                self.content_start,
                self.content_end,
                self.ppt_region,
                self.camera_rects,
                self.settings,
                cancel_event=self.cancel_event,
                progress_cb=coarse_progress,
                status_cb=self.status_cb,
            )
            self._check_cancel()
            self.warnings.extend(coarse.warnings)
            self._status(
                f"粗扫描完成：{coarse.sample_count} 个采样帧，{coarse.raw_change_count} 个变化点，"
                f"PySceneDetect {coarse.scene_cut_count} 个场景候选。"
            )

            hints = list(coarse.hints)
            # Always analyse the beginning of the selected content range.
            hints.append(TransitionHint(self.content_start, ("start",), 1.0))
            hints = _merge_hint_sources(sorted(hints, key=lambda h: h.time_sec), min_gap=0.45)

            refined: list[RefinedPage] = []
            total = max(1, len(hints))
            for index, hint in enumerate(hints):
                self._check_cancel()
                next_time = hints[index + 1].time_sec if index + 1 < len(hints) else None
                self._status(
                    f"稳定帧提取：第 {index + 1}/{len(hints)} 个候选，时间 {hint.time_sec:.2f}s"
                )
                try:
                    page = refine_candidate(
                        reader,
                        hint,
                        self.content_start,
                        self.content_end,
                        next_time,
                        self.ppt_region,
                        self.camera_rects,
                        self.settings,
                        self.cancel_event,
                    )
                except VideoDecodeError as exc:
                    self.warnings.append(f"{hint.time_sec:.2f}s 附近解码失败：{exc}")
                    page = _failed_page(hint, str(exc))
                if page is not None:
                    refined.append(page)
                self._progress(
                    46 + int(37 * (index + 1) / total),
                    f"稳定帧提取 {index + 1}/{total}",
                )
            if not refined:
                refined.append(_failed_page(TransitionHint(self.content_start, ("start",), 1.0), "无候选"))
                self.warnings.append("未能提取到稳定的页面截图，请检查 PPT 区域和正片区间。")

            refined.sort(key=lambda item: (item.page.interval_start, item.page.selected_time))
            self._merge_duplicates(refined, coarse)

            # Finalize page intervals/order before snapshot writing.
            for index, item in enumerate(refined):
                page = item.page
                page.detected_index = index
                if index == 0:
                    page.interval_start = min(page.interval_start, self.content_start)
                if index + 1 < len(refined):
                    page.interval_end = max(page.interval_start, refined[index + 1].page.interval_start - 0.001)
                else:
                    page.interval_end = self.content_end
                if page.interval_end - page.interval_start < self.settings.short_page_sec:
                    if "short_page" not in page.flags:
                        page.flags.append("short_page")
                    page.needs_review = True

            self._progress(84, "正在保存候选截图…")
            self._save_snapshots(reader, refined, run_rel)
            self._check_cancel()

            pages = [item.page for item in refined]
            for page in pages:
                if page.confidence < self.settings.min_confidence and "low_confidence" not in page.flags:
                    page.flags.append("low_confidence")
                page.needs_review = bool(page.flags) or page.confidence < self.settings.min_confidence

            elapsed = time.perf_counter() - started
            stats = {
                "content_duration": round(self.content_end - self.content_start, 3),
                "coarse_fps": self.settings.coarse_fps,
                "refine_fps": self.settings.refine_fps,
                "coarse_sample_count": coarse.sample_count,
                "raw_change_count": coarse.raw_change_count,
                "scene_cut_count": coarse.scene_cut_count,
                "hint_count": len(hints),
                "page_count": len(pages),
                "merged_duplicate_count": getattr(self, "_merged_duplicates", 0),
                "uncertain_duplicate_count": getattr(self, "_uncertain_duplicates", 0),
                "used_ffmpeg": bool(coarse.used_ffmpeg),
                "analysis_width": self.settings.analysis_width,
                "elapsed_sec": round(elapsed, 2),
            }
            self._progress(100, "分析完成")
            self._status(
                f"分析完成：{len(pages)} 个候选页面，用时 {elapsed:.1f} 秒。"
            )
            return AnalysisResult(
                pages=pages,
                warnings=list(dict.fromkeys(self.warnings)),
                stats=stats,
                analysis_region=self.ppt_region,
                settings=self.settings,
                run_dir=str(self.run_dir),
                run_rel=run_rel,
            )
        except AnalysisCancelled:
            raise
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(f"分析失败：{exc}") from exc
        finally:
            if reader is not None:
                reader.close()

    def _check_cancel(self) -> None:
        _check_cancel(self.cancel_event)

    def _merge_duplicates(self, refined: list[RefinedPage], coarse: CoarseScanResult) -> None:
        if len(refined) < 2:
            self._merged_duplicates = 0
            self._uncertain_duplicates = 0
            return
        merged_output: list[RefinedPage] = [refined[0]]
        merged_count = 0
        uncertain_count = 0
        for current in refined[1:]:
            self._check_cancel()
            previous = merged_output[-1]
            if previous.selected_gray.shape != current.selected_gray.shape:
                merged_output.append(current)
                continue
            if previous.selected_gray.shape[0] < 4:
                merged_output.append(current)
                continue
            diff = compare_frames(
                previous.selected_gray,
                current.selected_gray,
                current.mask,
                self.settings.pixel_diff_threshold,
            )
            auto_duplicate = (
                diff.ssim >= self.settings.duplicate_ssim_threshold
                and diff.changed_ratio <= 0.30
            ) or (
                diff.changed_ratio <= self.settings.duplicate_change_ratio_threshold
                and diff.ssim >= 0.92
            )
            if auto_duplicate:
                self._merge_two(previous, current)
                merged_count += 1
                continue
            if (
                diff.ssim >= self.settings.uncertain_duplicate_ssim
                and diff.changed_ratio <= self.settings.uncertain_duplicate_change_ratio
            ):
                if "possible_duplicate" not in current.page.flags:
                    current.page.flags.append("possible_duplicate")
                current.page.needs_review = True
                current.page.metrics["ssim_to_previous"] = diff.ssim
                current.page.metrics["change_ratio_to_previous"] = diff.changed_ratio
                uncertain_count += 1
            merged_output.append(current)
        refined[:] = merged_output
        self._merged_duplicates = merged_count
        self._uncertain_duplicates = uncertain_count
        if merged_count:
            self.warnings.append(f"已自动合并 {merged_count} 个高度相似的相邻候选页面。")
        if uncertain_count:
            self.warnings.append(
                f"{uncertain_count} 个页面与上一页相似，已保留并标记为需要人工复核。"
            )

    @staticmethod
    def _merge_two(previous: RefinedPage, current: RefinedPage) -> None:
        existing_times = {round(alt.time_sec, 3) for alt in previous.alternatives}
        for alt in current.alternatives:
            if round(alt.time_sec, 3) not in existing_times:
                previous.alternatives.append(alt)
        merged_flags = list(dict.fromkeys(previous.page.flags + current.page.flags))
        previous.page.flags = merged_flags
        previous.page.sources = list(dict.fromkeys(previous.page.sources + current.page.sources))
        previous.page.confidence = max(previous.page.confidence, current.page.confidence)
        previous.page.interval_end = max(previous.page.interval_end, current.page.interval_end)
        previous.page.metrics["merged_candidates"] = previous.page.metrics.get("merged_candidates", 0.0) + 1.0
        previous.page.manually_modified = False

    def _save_snapshots(self, reader: VideoReader, refined: list[RefinedPage], run_rel: str) -> None:
        total = max(1, len(refined))
        for page_index, item in enumerate(refined):
            self._check_cancel()
            page = item.page
            page_dir = self.run_dir / "pages" / page.id
            candidates_dir = page_dir / "candidates"
            thumbs_dir = page_dir / "thumbs"
            candidates_dir.mkdir(parents=True, exist_ok=True)
            thumbs_dir.mkdir(parents=True, exist_ok=True)

            # Deduplicate alternatives by timestamp and cap the count.  Keep
            # the strongest quality frame for duplicate timestamps.
            by_time: dict[float, RefinedAlternative] = {}
            for alt in item.alternatives:
                key = round(alt.time_sec, 3)
                if key not in by_time or alt.quality > by_time[key].quality:
                    by_time[key] = alt
            alternatives = sorted(by_time.values(), key=lambda a: a.time_sec)
            if len(alternatives) > self.settings.max_alternatives:
                keep = set(
                    id(a)
                    for a in sorted(alternatives, key=lambda a: -a.quality)[
                        : self.settings.max_alternatives
                    ]
                )
                alternatives = [a for a in alternatives if id(a) in keep]

            saved: list[AlternativeFrame] = []
            for alt_index, alt in enumerate(alternatives, start=1):
                self._check_cancel()
                try:
                    actual_time, frame = reader.read_frame(alt.time_sec)
                except VideoDecodeError as exc:
                    self.warnings.append(
                        f"页面 {page_index + 1} 的候选帧 {alt.time_sec:.2f}s 读取失败：{exc}"
                    )
                    continue
                crop = crop_rect(frame, self.ppt_region)
                if crop.size == 0:
                    continue
                milliseconds = int(round(alt.time_sec * 1000))
                filename = f"alt_{alt_index:02d}_{milliseconds:09d}.jpg"
                raw_path = candidates_dir / filename
                thumb_path = thumbs_dir / filename
                if not imwrite(raw_path, crop, quality=self.settings.snapshot_jpeg_quality):
                    self.warnings.append(f"无法保存候选截图：{raw_path.name}")
                    continue
                if not save_thumbnail(
                    crop,
                    thumb_path,
                    width=self.settings.thumbnail_width,
                    quality=85,
                ):
                    thumb_rel = ""
                else:
                    thumb_rel = thumb_path.relative_to(self.assets_root).as_posix()
                raw_rel = raw_path.relative_to(self.assets_root).as_posix()
                alt_flags = quality_flags(alt.frame_quality, self.settings) if alt.frame_quality else alt.flags
                saved.append(
                    AlternativeFrame(
                        time_sec=float(actual_time),
                        raw_path=raw_rel,
                        thumb_path=thumb_rel,
                        quality=float(alt.quality),
                        stability=float(alt.stability),
                        sharpness=float(alt.sharpness),
                        flags=list(dict.fromkeys(alt_flags)),
                    )
                )
                remaining_fraction = (alt_index / max(1, len(alternatives))) / total
                self._progress(
                    min(98, 84 + int(14 * (page_index + remaining_fraction) / total)),
                    f"保存候选截图 {page_index + 1}/{total}",
                )
            page.alternatives = saved
            if not saved:
                if "snapshot_failed" not in page.flags:
                    page.flags.append("snapshot_failed")
                page.needs_review = True
                page.selected_raw_path = ""
            else:
                # The initial selection is the best-scoring alternative, but
                # the user can later choose any other candidate timestamp.
                best = max(saved, key=lambda alt: alt.quality)
                page.select_alternative(best)
                if page.selected_time <= 0 and saved:
                    page.selected_time = saved[0].time_sec
            self._progress(
                min(98, 84 + int(14 * (page_index + 1) / total)),
                f"保存候选截图 {page_index + 1}/{total}",
            )

