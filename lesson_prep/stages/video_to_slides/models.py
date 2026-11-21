"""Data models for the video-to-slides stage."""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum
from typing import Any, Iterable

from ...core.geometry import Rect
from ...core.media.models import VideoInfo


class CameraMode(str, Enum):
    IGNORE = "ignore"
    CROP = "crop"
    MASK = "mask"
    MASK_WHITE = "mask_white"

    @property
    def label(self) -> str:
        return {
            CameraMode.IGNORE: "忽略（仅分析排除，画面保留）",
            CameraMode.CROP: "裁剪（导出时移除摄像头）",
            CameraMode.MASK: "遮罩（黑色覆盖摄像头）",
            CameraMode.MASK_WHITE: "遮罩（白色覆盖摄像头）",
        }[self]


@dataclass
class CameraRegion:
    """One configurable teacher-camera area and its export policy."""

    id: str = field(default_factory=lambda: f"cam_{uuid.uuid4().hex[:10]}")
    region: Rect | None = None
    mode: CameraMode = CameraMode.IGNORE

    def is_configured(self) -> bool:
        return self.region is not None and self.region.is_valid()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "region": self.region.to_dict() if self.region is not None else None,
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CameraRegion":
        try:
            mode = CameraMode(str(data.get("mode") or "ignore"))
        except ValueError:
            mode = CameraMode.IGNORE
        return cls(
            id=str(data.get("id") or f"cam_{uuid.uuid4().hex[:10]}"),
            region=Rect.from_dict(data.get("region"), None),
            mode=mode,
        )


FLAG_LABELS = {
    "low_confidence": "置信度偏低",
    "blurry": "画面模糊",
    "black_frame": "疑似黑屏/过渡",
    "near_blank": "画面接近纯色",
    "possible_transition": "疑似过渡未完成",
    "unstable": "稳定时间不足",
    "no_stable_window": "未找到稳定窗口",
    "possible_duplicate": "可能与上一页重复",
    "short_page": "页面停留时间很短",
    "snapshot_failed": "截图保存失败",
    "missing_image": "图片文件缺失",
}


def new_id(prefix: str = "page") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AlternativeFrame:
    time_sec: float
    raw_path: str
    thumb_path: str = ""
    quality: float = 0.0
    stability: float = 0.0
    sharpness: float = 0.0
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "time_sec": round(float(self.time_sec), 3),
            "raw_path": self.raw_path,
            "thumb_path": self.thumb_path,
            "quality": round(float(self.quality), 4),
            "stability": round(float(self.stability), 4),
            "sharpness": round(float(self.sharpness), 4),
            "flags": list(self.flags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AlternativeFrame":
        return cls(
            time_sec=float(data.get("time_sec") or 0.0),
            raw_path=str(data.get("raw_path") or ""),
            thumb_path=str(data.get("thumb_path") or ""),
            quality=float(data.get("quality") or 0.0),
            stability=float(data.get("stability") or 0.0),
            sharpness=float(data.get("sharpness") or 0.0),
            flags=list(data.get("flags") or []),
        )


@dataclass
class PageCandidate:
    id: str
    detected_index: int = 0
    interval_start: float = 0.0
    interval_end: float = 0.0
    selected_time: float = 0.0
    selected_raw_path: str = ""
    confidence: float = 0.0
    needs_review: bool = False
    flags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    kept: bool = True
    manually_modified: bool = False
    review_note: str = ""
    alternatives: list[AlternativeFrame] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def selected_alternative(self) -> AlternativeFrame | None:
        if not self.alternatives:
            return None
        if self.selected_raw_path:
            for alt in self.alternatives:
                if alt.raw_path == self.selected_raw_path:
                    return alt
        # Fall back to nearest timestamp for older project files.
        return min(self.alternatives, key=lambda a: abs(a.time_sec - self.selected_time))

    def select_alternative(self, alt: AlternativeFrame) -> None:
        self.selected_raw_path = alt.raw_path
        self.selected_time = alt.time_sec

    @property
    def selected_thumb_path(self) -> str:
        alt = self.selected_alternative()
        return alt.thumb_path if alt else ""

    @property
    def label_flags(self) -> str:
        return "、".join(FLAG_LABELS.get(f, f) for f in self.flags if f != "low_confidence")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "detected_index": int(self.detected_index),
            "interval_start": round(float(self.interval_start), 3),
            "interval_end": round(float(self.interval_end), 3),
            "selected_time": round(float(self.selected_time), 3),
            "selected_raw_path": self.selected_raw_path,
            "confidence": round(float(self.confidence), 4),
            "needs_review": bool(self.needs_review),
            "flags": list(self.flags),
            "sources": list(self.sources),
            "kept": bool(self.kept),
            "manually_modified": bool(self.manually_modified),
            "review_note": self.review_note,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "metrics": {k: round(float(v), 5) for k, v in self.metrics.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PageCandidate":
        page = cls(
            id=str(data.get("id") or new_id()),
            detected_index=int(data.get("detected_index") or 0),
            interval_start=float(data.get("interval_start") or 0.0),
            interval_end=float(data.get("interval_end") or 0.0),
            selected_time=float(data.get("selected_time") or 0.0),
            selected_raw_path=str(data.get("selected_raw_path") or ""),
            confidence=float(data.get("confidence") or 0.0),
            needs_review=bool(data.get("needs_review")),
            flags=list(data.get("flags") or []),
            sources=list(data.get("sources") or []),
            kept=bool(data.get("kept", True)),
            manually_modified=bool(data.get("manually_modified")),
            review_note=str(data.get("review_note") or ""),
            alternatives=[AlternativeFrame.from_dict(a) for a in (data.get("alternatives") or [])],
            metrics={k: float(v) for k, v in (data.get("metrics") or {}).items()},
        )
        if page.alternatives and not page.selected_raw_path:
            alt = page.selected_alternative()
            if alt is not None:
                page.selected_raw_path = alt.raw_path
                page.selected_time = alt.time_sec
        return page


@dataclass
class RemovedPageRecord:
    page_id: str
    time_sec: float
    confidence: float
    removed_at: str = field(default_factory=_now_iso)
    reason: str = "用户删除"
    page_number: int = 0

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "page_number": int(self.page_number),
            "time_sec": round(float(self.time_sec), 3),
            "confidence": round(float(self.confidence), 4),
            "removed_at": self.removed_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RemovedPageRecord":
        return cls(
            page_id=str(data.get("page_id") or ""),
            page_number=int(data.get("page_number") or 0),
            time_sec=float(data.get("time_sec") or 0.0),
            confidence=float(data.get("confidence") or 0.0),
            removed_at=str(data.get("removed_at") or ""),
            reason=str(data.get("reason") or "用户删除"),
        )


@dataclass
class TrashEntry:
    """A deleted candidate page retained for later restoration."""

    page: PageCandidate
    original_index: int = 0
    deleted_at: str = field(default_factory=_now_iso)
    reason: str = "用户删除"
    previous_page_id: str = ""
    next_page_id: str = ""

    def to_dict(self) -> dict:
        return {
            "page": self.page.to_dict(),
            "original_index": int(self.original_index),
            "deleted_at": self.deleted_at,
            "reason": self.reason,
            "previous_page_id": self.previous_page_id,
            "next_page_id": self.next_page_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrashEntry":
        return cls(
            page=PageCandidate.from_dict(data.get("page") or {}),
            original_index=int(data.get("original_index") or 0),
            deleted_at=str(data.get("deleted_at") or ""),
            reason=str(data.get("reason") or "用户删除"),
            previous_page_id=str(data.get("previous_page_id") or ""),
            next_page_id=str(data.get("next_page_id") or ""),
        )


@dataclass
class ManualChange:
    action: str
    detail: str = ""
    page_id: str = ""
    at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {"at": self.at, "action": self.action, "page_id": self.page_id, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict) -> "ManualChange":
        return cls(
            action=str(data.get("action") or ""),
            detail=str(data.get("detail") or ""),
            page_id=str(data.get("page_id") or ""),
            at=str(data.get("at") or ""),
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class AnalysisSettings:
    """Tunable parameters for coarse scanning and stable-frame refinement."""

    coarse_fps: float = 3.0
    refine_fps: float = 8.0
    analysis_width: int = 384

    pixel_diff_threshold: int = 25
    coarse_change_ratio_threshold: float = 0.08
    coarse_ssim_threshold: float = 0.86
    coarse_mad_threshold: float = 12.0

    change_group_gap_sec: float = 0.8
    stable_change_ratio_threshold: float = 0.025
    stable_ssim_threshold: float = 0.975
    stable_mad_threshold: float = 6.0
    stable_duration_sec: float = 0.75

    refine_before_sec: float = 1.0
    refine_after_sec: float = 4.5
    max_alternatives: int = 5
    alternative_min_gap_sec: float = 0.6
    max_alternative_span_sec: float = 10.0
    short_page_sec: float = 0.8

    duplicate_ssim_threshold: float = 0.978
    duplicate_change_ratio_threshold: float = 0.025
    uncertain_duplicate_ssim: float = 0.93
    uncertain_duplicate_change_ratio: float = 0.10

    black_luma_threshold: float = 18.0
    black_std_threshold: float = 12.0
    blur_lap_var_threshold: float = 40.0
    blur_good_lap_var: float = 220.0
    min_confidence: float = 0.55

    use_pyscenedetect: bool = True
    pyscenedetect_threshold: float = 27.0
    pyscenedetect_min_scene_sec: float = 1.0

    snapshot_jpeg_quality: int = 92
    thumbnail_width: int = 360

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "AnalysisSettings":
        data = data or {}
        obj = cls()
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in known:
                continue
            try:
                setattr(obj, key, value)
            except Exception:
                pass
        obj.sanitized()
        return obj

    def sanitized(self) -> "AnalysisSettings":
        self.coarse_fps = _clamp(float(self.coarse_fps), 0.5, 12.0)
        self.refine_fps = _clamp(float(self.refine_fps), 2.0, 30.0)
        self.analysis_width = int(_clamp(int(self.analysis_width), 160, 1280))
        self.pixel_diff_threshold = int(_clamp(int(self.pixel_diff_threshold), 1, 128))
        self.coarse_change_ratio_threshold = _clamp(float(self.coarse_change_ratio_threshold), 0.005, 0.9)
        self.coarse_ssim_threshold = _clamp(float(self.coarse_ssim_threshold), 0.1, 0.999)
        self.coarse_mad_threshold = _clamp(float(self.coarse_mad_threshold), 1.0, 100.0)
        self.change_group_gap_sec = _clamp(float(self.change_group_gap_sec), 0.05, 10.0)
        self.stable_change_ratio_threshold = _clamp(float(self.stable_change_ratio_threshold), 0.001, 0.5)
        self.stable_ssim_threshold = _clamp(float(self.stable_ssim_threshold), 0.5, 0.9999)
        self.stable_mad_threshold = _clamp(float(self.stable_mad_threshold), 0.2, 60.0)
        self.stable_duration_sec = _clamp(float(self.stable_duration_sec), 0.1, 10.0)
        self.refine_before_sec = _clamp(float(self.refine_before_sec), 0.0, 10.0)
        self.refine_after_sec = _clamp(float(self.refine_after_sec), 1.0, 30.0)
        self.max_alternatives = int(_clamp(int(self.max_alternatives), 1, 12))
        self.alternative_min_gap_sec = _clamp(float(self.alternative_min_gap_sec), 0.05, 5.0)
        self.max_alternative_span_sec = _clamp(float(self.max_alternative_span_sec), 1.0, 60.0)
        self.short_page_sec = _clamp(float(self.short_page_sec), 0.05, 10.0)
        self.duplicate_ssim_threshold = _clamp(float(self.duplicate_ssim_threshold), 0.8, 0.9999)
        self.duplicate_change_ratio_threshold = _clamp(float(self.duplicate_change_ratio_threshold), 0.0, 0.5)
        self.uncertain_duplicate_ssim = _clamp(float(self.uncertain_duplicate_ssim), 0.5, 0.9999)
        self.uncertain_duplicate_change_ratio = _clamp(float(self.uncertain_duplicate_change_ratio), 0.0, 0.9)
        self.black_luma_threshold = _clamp(float(self.black_luma_threshold), 0.0, 100.0)
        self.black_std_threshold = _clamp(float(self.black_std_threshold), 0.0, 80.0)
        self.blur_lap_var_threshold = _clamp(float(self.blur_lap_var_threshold), 1.0, 5000.0)
        self.blur_good_lap_var = _clamp(float(self.blur_good_lap_var), 10.0, 10000.0)
        if self.blur_good_lap_var < self.blur_lap_var_threshold:
            self.blur_good_lap_var = self.blur_lap_var_threshold
        self.min_confidence = _clamp(float(self.min_confidence), 0.0, 1.0)
        self.pyscenedetect_threshold = _clamp(float(self.pyscenedetect_threshold), 1.0, 100.0)
        self.pyscenedetect_min_scene_sec = _clamp(float(self.pyscenedetect_min_scene_sec), 0.1, 30.0)
        self.snapshot_jpeg_quality = int(_clamp(int(self.snapshot_jpeg_quality), 50, 100))
        self.thumbnail_width = int(_clamp(int(self.thumbnail_width), 120, 960))
        return self


@dataclass
class SlidesProject:
    """Project state for one video-to-slides extraction session."""
    name: str = "未命名项目"
    video_info: VideoInfo = field(default_factory=VideoInfo)
    content_start: float = 0.0
    content_end: float = 0.0
    ppt_region: Rect = field(default_factory=Rect.full_frame)
    camera_regions: list[CameraRegion] = field(default_factory=list)
    settings: AnalysisSettings = field(default_factory=AnalysisSettings)
    pages: list[PageCandidate] = field(default_factory=list)
    analysis_region: Rect | None = None
    analysis_stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    manual_history: list[ManualChange] = field(default_factory=list)
    removed_pages: list[RemovedPageRecord] = field(default_factory=list)
    trash: list[TrashEntry] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # Runtime-only state (not serialized).
    project_path: Any = None
    assets_root: Any = None
    dirty: bool = False

    def active_pages(self) -> list[PageCandidate]:
        return [p for p in self.pages if p.kept]

    def skipped_pages(self) -> list[PageCandidate]:
        return [p for p in self.pages if not p.kept]

    def configured_camera_regions(self) -> list[CameraRegion]:
        return [camera for camera in self.camera_regions if camera.is_configured()]

    def move_page_to_trash(self, page_id: str, reason: str = "用户删除") -> TrashEntry | None:
        """Remove a page from the review list and retain all of its data."""
        index = next((i for i, page in enumerate(self.pages) if page.id == page_id), -1)
        if index < 0:
            return None
        page = self.pages[index]
        entry = TrashEntry(
            page=copy.deepcopy(page),
            original_index=index,
            reason=reason,
            previous_page_id=self.pages[index - 1].id if index > 0 else "",
            next_page_id=self.pages[index + 1].id if index + 1 < len(self.pages) else "",
        )
        self.pages.pop(index)
        self.trash.append(entry)
        self.removed_pages.append(
            RemovedPageRecord(
                page_id=page.id,
                page_number=index + 1,
                time_sec=page.selected_time,
                confidence=page.confidence,
                removed_at=entry.deleted_at,
                reason=reason,
            )
        )
        self.touch()
        return entry

    def restore_trash_entries(self, page_ids: Iterable[str]) -> list[PageCandidate]:
        """Restore selected trash entries at their original positions.

        Entries are inserted in ascending original-index order so restoring
        several adjacent pages preserves their previous sequence.  The
        corresponding "removed page" audit records are deleted; the original
        delete/restore actions remain in ``manual_history``.
        """
        wanted = set(page_ids)
        entries = [entry for entry in self.trash if entry.page.id in wanted]
        if not entries:
            return []
        entries.sort(key=lambda entry: (entry.original_index, entry.deleted_at))
        restored: list[PageCandidate] = []
        for entry in entries:
            if entry in self.trash:
                self.trash.remove(entry)
            insert_at = self._restore_insert_index(entry)
            self.pages.insert(insert_at, entry.page)
            restored.append(entry.page)
        restored_ids = {page.id for page in restored}
        self.removed_pages = [
            record for record in self.removed_pages if record.page_id not in restored_ids
        ]
        self.touch()
        return restored

    def _restore_insert_index(self, entry: TrashEntry) -> int:
        """Prefer neighbors captured at deletion time, then the old index."""
        if entry.next_page_id:
            next_index = next(
                (i for i, page in enumerate(self.pages) if page.id == entry.next_page_id),
                None,
            )
            if next_index is not None:
                return next_index
        if entry.previous_page_id:
            previous_index = next(
                (i for i, page in enumerate(self.pages) if page.id == entry.previous_page_id),
                None,
            )
            if previous_index is not None:
                return previous_index + 1
        return max(0, min(entry.original_index, len(self.pages)))

    def history(self, action: str, detail: str = "", page_id: str = "") -> None:
        self.manual_history.append(ManualChange(action=action, detail=detail, page_id=page_id))
        self.dirty = True

    def touch(self) -> None:
        self.updated_at = _now_iso()
        self.dirty = True
