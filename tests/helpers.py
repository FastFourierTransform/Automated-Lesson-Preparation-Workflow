"""Helpers for constructing mutable projects from one shared analysis run."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

from lesson_prep.core.geometry import Rect
from lesson_prep.stages.video_to_slides.models import (
    AnalysisSettings,
    AlternativeFrame,
    CameraMode,
    CameraRegion,
    PageCandidate,
    RemovedPageRecord,
    SlidesProject,
    VideoInfo,
)


def copy_project(
    analysis_bundle,
    tmp_path: Path,
    name: str = "lesson",
    camera_mode: CameraMode = CameraMode.MASK,
) -> SlidesProject:
    assets_root = tmp_path / f"{name}_assets"
    shutil.copytree(analysis_bundle["assets_root"], assets_root)
    result = analysis_bundle["result"]
    project = SlidesProject(
        name=name,
        video_info=VideoInfo.from_dict(analysis_bundle["video_info"].to_dict()),
        content_start=4.0,
        content_end=38.0,
        ppt_region=result.analysis_region,
        camera_regions=[
            CameraRegion(
                region=Rect(0.746, 0.028, 0.231, 0.282),
                mode=camera_mode,
            )
        ],
        settings=AnalysisSettings.from_dict(result.settings.to_dict()),
        pages=copy.deepcopy(result.pages),
        analysis_region=result.analysis_region,
        analysis_stats=dict(result.stats),
        warnings=list(result.warnings),
    )
    project.project_path = tmp_path / f"{name}.lsp.json"
    project.assets_root = assets_root
    return project


def select_second_alternative(page: PageCandidate) -> AlternativeFrame | None:
    if len(page.alternatives) < 2:
        return None
    alt = page.alternatives[1]
    page.select_alternative(alt)
    page.manually_modified = True
    return alt


def mark_manual_changes(project: SlidesProject) -> None:
    if not project.pages:
        return
    page = project.pages[0]
    alt = select_second_alternative(page)
    if alt is not None:
        project.history("select_alternative", "test alternative", page.id)
    page.review_note = "测试备注"
    page.manually_modified = True
    project.history("set_note", "测试备注", page.id)
    if len(project.pages) > 1:
        project.pages[1].kept = False
        project.pages[1].manually_modified = True
        project.history("set_kept", "跳过页面", project.pages[1].id)
    if len(project.pages) >= 4:
        old = project.pages[3]
        project.pages.pop(3)
        project.removed_pages.append(
            RemovedPageRecord(
                page_id=old.id,
                page_number=4,
                time_sec=old.selected_time,
                confidence=old.confidence,
                reason="用户删除",
            )
        )
        project.history("delete_page", "测试删除", old.id)
    if len(project.pages) >= 3:
        project.pages[0], project.pages[2] = project.pages[2], project.pages[0]
        project.history("reorder_page", "测试排序")
    project.touch()


