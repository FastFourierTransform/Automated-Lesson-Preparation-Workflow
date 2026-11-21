"""Second-level sampling, transition settling and representative frame choice."""
from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass, field

import numpy as np

from ..models import AnalysisSettings, PageCandidate, new_id
from ....core.media.reader import VideoDecodeError, VideoReader
from .coarse import TransitionHint
from .errors import AnalysisCancelled
from .metrics import (
    FrameDiff,
    compare_frames,
    prepare_frame,
    quality_flags,
    quality_score,
)

@dataclass
class RefinedAlternative:
    time_sec: float
    quality: float
    stability: float
    sharpness: float
    flags: list[str] = field(default_factory=list)
    frame_quality: dict[str, float] = field(default_factory=dict)


@dataclass
class RefinedPage:
    page: PageCandidate
    selected_gray: np.ndarray
    mask: np.ndarray
    alternatives: list[RefinedAlternative] = field(default_factory=list)


@dataclass
class _Stability:
    stable: bool = False
    observed: float = 0.0
    fully_verified: bool = False
    residual: float = 1.0


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled("分析已取消")


def _residual_ratio(diffs: list[FrameDiff], times: list[float], index: int, seconds: float = 0.6) -> float:
    if index >= len(diffs):
        return 0.0
    start = times[index]
    values = [
        diff.changed_ratio
        for k, diff in enumerate(diffs[index:], start=index)
        if times[k] <= start + seconds
    ]
    return float(np.mean(values)) if values else 0.0


def _stability_at(
    times: list[float],
    diffs: list[FrameDiff],
    index: int,
    settings: AnalysisSettings,
) -> _Stability:
    if index >= len(times) or index >= len(diffs):
        return _Stability(False, 0.0, False, 1.0)
    start_t = times[index]
    available = max(0.0, times[-1] - start_t) + (1.0 / max(settings.refine_fps, 1.0))
    target = settings.stable_duration_sec
    effective = min(target, available)
    fully_verified = available + 1e-6 >= target - 0.5 / settings.refine_fps
    stable = True
    for k in range(index, len(diffs)):
        if times[k] > start_t + target + 1e-6:
            break
        if not diffs[k].is_stable(settings):
            stable = False
            break
    if index >= len(diffs):
        stable = False
    observed = min(target, available)
    residual = _residual_ratio(diffs, times, index)
    return _Stability(stable=stable, observed=observed, fully_verified=fully_verified, residual=residual)


def _quality_is_suitable(quality: dict[str, float], settings: AnalysisSettings) -> bool:
    if quality.get("black", 0.0) >= 1.0 or quality.get("near_blank", 0.0) >= 1.0:
        return False
    return quality.get("lap_var", 0.0) >= settings.blur_lap_var_threshold * 0.5


def _fallback_index(
    times: list[float],
    diffs: list[FrameDiff],
    qualities: list[dict[str, float]],
    anchor: int,
    settings: AnalysisSettings,
) -> int:
    best_index = min(anchor, max(0, len(times) - 1))
    best_penalty = float("inf")
    for index in range(max(0, anchor), len(times)):
        residual = _residual_ratio(diffs, times, index, seconds=0.6)
        quality_penalty = 1.0 - quality_score(qualities[index], settings)
        penalty = residual / max(settings.stable_change_ratio_threshold, 1e-5) + quality_penalty
        if penalty < best_penalty:
            best_penalty = penalty
            best_index = index
    return best_index


def _choose_alternatives(
    times: list[float],
    diffs: list[FrameDiff],
    qualities: list[dict[str, float]],
    selected_index: int,
    stable_index: int,
    stable: _Stability,
    settings: AnalysisSettings,
) -> list[RefinedAlternative]:
    best_time_window = times[selected_index] + settings.max_alternative_span_sec
    candidate_indices = [
        i
        for i in range(selected_index, len(times))
        if times[i] <= best_time_window
        and qualities[i].get("black", 0.0) < 1.0
        and qualities[i].get("near_blank", 0.0) < 1.0
    ]
    if not candidate_indices:
        candidate_indices = [selected_index]
    if stable_index not in candidate_indices:
        candidate_indices.append(stable_index)

    scored: list[tuple[float, int, float]] = []
    for index in candidate_indices:
        status = _stability_at(times, diffs, index, settings)
        stability_component = min(1.0, status.observed / max(settings.stable_duration_sec, 1e-6))
        residual = _residual_ratio(diffs, times, index)
        stillness = 1.0 - min(
            1.0,
            residual / max(settings.stable_change_ratio_threshold * 2.5, 1e-5),
        )
        sharpness = quality_score(qualities[index], settings)
        score = 0.55 * sharpness + 0.25 * stillness + 0.20 * stability_component
        if qualities[index].get("lap_var", 0.0) < settings.blur_lap_var_threshold:
            score *= 0.72
        scored.append((float(np.clip(score, 0.0, 1.0)), index, status.observed))

    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[float, int, float]] = []
    # Always retain the beginning of the stable window; it is useful when the
    # automatically chosen "sharpest" frame still contains a late transition.
    seed_indices = [stable_index, selected_index]
    for index in seed_indices:
        status = _stability_at(times, diffs, index, settings)
        sharpness = quality_score(qualities[index], settings)
        chosen.append((sharpness, index, status.observed))
    for score, index, observed in scored:
        if len(chosen) >= settings.max_alternatives:
            break
        if any(abs(times[index] - times[item[1]]) < settings.alternative_min_gap_sec for item in chosen):
            continue
        chosen.append((score, index, observed))
    if not chosen:
        chosen.append((0.0, selected_index, stable.observed))

    # Keep the stable-start frame as an alternative unless the cap is 1.
    chosen_by_index: dict[int, tuple[float, int, float]] = {item[1]: item for item in chosen}
    chosen = list(chosen_by_index.values())
    if len(chosen) > settings.max_alternatives:
        # Preserve the stable-start seed, then best scores.
        stable_seed = next((c for c in chosen if c[1] == stable_index), None)
        chosen.sort(key=lambda item: -item[0])
        chosen = chosen[: settings.max_alternatives]
        if stable_seed and stable_seed[1] not in {c[1] for c in chosen}:
            chosen[-1] = stable_seed
    chosen.sort(key=lambda item: times[item[1]])

    alternatives: list[RefinedAlternative] = []
    for score, index, observed in chosen:
        flags = quality_flags(qualities[index], settings)
        alternatives.append(
            RefinedAlternative(
                time_sec=float(times[index]),
                quality=float(np.clip(score, 0.0, 1.0)),
                stability=float(
                    min(1.0, observed / max(settings.stable_duration_sec, 1e-6))
                ),
                sharpness=float(quality_score(qualities[index], settings)),
                flags=flags,
                frame_quality=dict(qualities[index]),
            )
        )
    return alternatives


def refine_candidate(
    reader: VideoReader,
    hint: TransitionHint,
    content_start: float,
    content_end: float,
    next_hint_time: float | None,
    ppt_region,
    camera_regions,
    settings: AnalysisSettings,
    cancel_event: threading.Event | None = None,
) -> RefinedPage | None:
    """Refine one transition hint into a page candidate with alternatives."""
    _check_cancel(cancel_event)
    hint_time = max(content_start, min(float(hint.time_sec), content_end))
    window_start = max(content_start, hint_time - settings.refine_before_sec)
    window_end = min(
        content_end,
        hint_time + settings.refine_after_sec + settings.stable_duration_sec,
    )
    if next_hint_time is not None and next_hint_time > hint_time:
        window_end = min(window_end, next_hint_time + 0.25)
    if window_end - window_start < 0.25:
        window_end = min(content_end, window_start + 1.0)
    if window_end <= window_start:
        return None

    times: list[float] = []
    grays: list[np.ndarray] = []
    qualities: list[dict[str, float]] = []
    mask = None
    # Keep only downscaled grayscale frames. Full-resolution frames are
    # re-read only for the final, chosen timestamps.
    try:
        for time_sec, frame in reader.iter_window(window_start, window_end, settings.refine_fps):
            _check_cancel(cancel_event)
            prepared = prepare_frame(
                frame,
                ppt_region,
                camera_regions,
                settings.analysis_width,
                want_color=False,
            )
            if mask is None:
                mask = prepared.mask
            if times and time_sec <= times[-1] + 1e-4:
                continue
            times.append(float(time_sec))
            grays.append(prepared.gray)
            qualities.append(prepared.quality)
    except VideoDecodeError:
        # The caller records the warning and keeps the page marked for review.
        raise

    if not times:
        page = PageCandidate(
            id=new_id(),
            interval_start=hint_time,
            interval_end=window_end,
            selected_time=hint_time,
            confidence=0.0,
            needs_review=True,
            flags=["no_stable_window", "snapshot_failed", "low_confidence"],
            sources=list(hint.sources),
            metrics={"detection_strength": float(hint.strength)},
        )
        empty = np.zeros((2, 2), dtype=np.uint8)
        return RefinedPage(page=page, selected_gray=empty, mask=np.ones((2, 2), dtype=np.uint8))

    diffs = [
        compare_frames(grays[i], grays[i + 1], mask, settings.pixel_diff_threshold)
        for i in range(len(grays) - 1)
    ]
    anchor = bisect.bisect_left(times, hint_time - 1.0 / max(settings.refine_fps, 1.0))
    anchor = max(0, min(anchor, len(times) - 1))

    stable_index = None
    stability = _Stability(False, 0.0, False, 1.0)
    # Preferred pass: a real, non-blank, reasonably sharp stable frame.
    for index in range(anchor, len(times)):
        status = _stability_at(times, diffs, index, settings)
        if status.stable and _quality_is_suitable(qualities[index], settings):
            stable_index = index
            stability = status
            break
    if stable_index is None:
        for index in range(anchor, len(times)):
            status = _stability_at(times, diffs, index, settings)
            if status.stable:
                stable_index = index
                stability = status
                break
    if stable_index is None:
        stable_index = _fallback_index(times, diffs, qualities, anchor, settings)
        stability = _stability_at(times, diffs, stable_index, settings)
        stability.stable = False

    # Choose the representative from the stable window, favoring sharp and
    # still frames.  This is intentionally separate from the earliest stable
    # timestamp, which remains available as an alternative.
    alternatives = _choose_alternatives(
        times,
        diffs,
        qualities,
        selected_index=stable_index,
        stable_index=stable_index,
        stable=stability,
        settings=settings,
    )
    if not alternatives:
        alternatives = [
            RefinedAlternative(
                time_sec=times[stable_index],
                quality=quality_score(qualities[stable_index], settings),
                stability=0.0,
                sharpness=quality_score(qualities[stable_index], settings),
                flags=quality_flags(qualities[stable_index], settings),
                frame_quality=dict(qualities[stable_index]),
            )
        ]
    selected_alt = max(alternatives, key=lambda alt: alt.quality)
    selected_index = min(
        range(len(times)),
        key=lambda i: abs(times[i] - selected_alt.time_sec),
    )

    quality = qualities[selected_index]
    sharpness = quality_score(quality, settings)
    stability_score = min(1.0, stability.observed / max(settings.stable_duration_sec, 1e-6))
    stillness = 1.0 - min(
        1.0,
        stability.residual / max(settings.stable_change_ratio_threshold * 2.5, 1e-5),
    )
    detection = min(1.0, max(0.0, hint.strength) / 1.5)
    if "pyscenedetect" in hint.sources and "coarse" not in hint.sources:
        detection = max(detection, 0.6)
    confidence = (
        0.32 * stability_score
        + 0.24 * sharpness
        + 0.24 * stillness
        + 0.20 * detection
    )
    flags = quality_flags(quality, settings)
    if not stability.stable:
        flags.append("no_stable_window")
        flags.append("possible_transition")
        confidence *= 0.72
    elif not stability.fully_verified:
        flags.append("unstable")
        confidence *= 0.85
    if stability.residual > settings.stable_change_ratio_threshold * 2.5:
        flags.append("possible_transition")
    if quality.get("black", 0.0) >= 1.0:
        confidence *= 0.35
    elif quality.get("near_blank", 0.0) >= 1.0:
        confidence *= 0.55
    if "blurry" in flags:
        confidence *= 0.7
    confidence = float(np.clip(confidence, 0.0, 1.0))
    if confidence < settings.min_confidence and "low_confidence" not in flags:
        flags.append("low_confidence")
    flags = list(dict.fromkeys(flags))
    needs_review = bool(flags) or confidence < settings.min_confidence

    page = PageCandidate(
        id=new_id(),
        interval_start=min(times[stable_index], selected_alt.time_sec),
        interval_end=window_end,
        selected_time=selected_alt.time_sec,
        confidence=confidence,
        needs_review=needs_review,
        flags=flags,
        sources=list(hint.sources),
        metrics={
            "detection_strength": float(hint.strength),
            "stable_seconds": float(stability.observed),
            "residual_change": float(stability.residual),
            "sharpness": float(sharpness),
            "lap_var": float(quality.get("lap_var", 0.0)),
            "mean_luma": float(quality.get("mean", 0.0)),
        },
    )
    return RefinedPage(
        page=page,
        selected_gray=grays[selected_index].copy(),
        mask=mask.copy() if mask is not None else np.ones_like(grays[selected_index]),
        alternatives=alternatives,
    )

