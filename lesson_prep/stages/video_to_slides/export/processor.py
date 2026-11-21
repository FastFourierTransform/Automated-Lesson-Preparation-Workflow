"""Load a selected raw candidate and apply the current camera policy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ....core.geometry import Rect, relative_rect
from ....core.media.utils import imread
from ..imaging import apply_camera_policies
from ..models import PageCandidate, SlidesProject
from ..project import resolve_asset


class SlideImageError(RuntimeError):
    pass


@dataclass
class ProcessedSlide:
    image: np.ndarray
    raw_path: Path
    effective_camera_modes: list[str]
    camera_adjusted: bool

    @property
    def effective_camera_mode(self) -> str:
        """Legacy single-region summary (used by old callers/tests)."""
        if not self.effective_camera_modes:
            return "ignore"
        if len(self.effective_camera_modes) == 1:
            return self.effective_camera_modes[0]
        return "multiple"


def _analysis_region(project: SlidesProject) -> Rect:
    return project.analysis_region or project.ppt_region


def process_selected_image(
    project: SlidesProject,
    page: PageCandidate,
    apply_camera: bool = True,
) -> ProcessedSlide:
    alt = page.selected_alternative()
    if alt is None:
        raise SlideImageError(f"页面 {page.detected_index + 1} 没有可用的候选截图。")
    raw_path = resolve_asset(project, alt.raw_path)
    if raw_path is None or not raw_path.is_file():
        raise SlideImageError(
            f"页面 {page.detected_index + 1} 的候选截图缺失：{alt.raw_path}"
        )
    image = imread(raw_path)
    if image is None or image.size == 0:
        raise SlideImageError(f"页面 {page.detected_index + 1} 的截图无法读取。")
    if not apply_camera:
        return ProcessedSlide(image, raw_path, [], False)

    analysis_region = _analysis_region(project)
    camera_policies: list[tuple[Rect | None, str]] = []
    for camera in project.configured_camera_regions():
        if camera.region is None:
            continue
        local = relative_rect(camera.region, analysis_region)
        camera_policies.append((local, camera.mode.value))

    processed, effective_modes = apply_camera_policies(image, camera_policies)
    return ProcessedSlide(
        image=processed,
        raw_path=raw_path,
        effective_camera_modes=effective_modes,
        camera_adjusted=any(mode != "ignore" for mode in effective_modes),
    )


