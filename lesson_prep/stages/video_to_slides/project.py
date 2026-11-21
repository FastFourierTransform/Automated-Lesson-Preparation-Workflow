"""Project file (JSON) persistence.

A project consists of one ``*.lsp.json`` file and a sibling asset folder
``*_assets``.  All candidate image paths inside the project are stored relative
to that asset folder, so the pair can be moved together without breaking.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ...core.geometry import Rect
from ...core.project import (
    assets_dir_for_project as _assets_dir_for_project,
    prepare_project_path as _prepare_project_path,
    resolve_asset,
    suggested_project_path as _suggested_project_path,
)
from ...version import PROJECT_SCHEMA_VERSION
from ... import __version__
from .constants import PROJECT_SUFFIX, STAGE_ID, STAGE_NAME
from .models import (
    AnalysisSettings,
    CameraMode,
    CameraRegion,
    ManualChange,
    PageCandidate,
    RemovedPageRecord,
    SlidesProject,
    TrashEntry,
    VideoInfo,
)


class ProjectError(RuntimeError):
    pass


# The stage uses a dedicated suffix so project type is visible in the file name.
PROJECT_SUFFIXES = (PROJECT_SUFFIX, ".json")


def assets_dir_for_project(project_path: str | Path) -> Path:
    return _assets_dir_for_project(project_path, PROJECT_SUFFIXES)


def suggested_project_path(video_path: str | Path) -> Path:
    return _suggested_project_path(video_path, PROJECT_SUFFIX)


def prepare_project_path(project_path: str | Path) -> tuple[Path, Path]:
    return _prepare_project_path(project_path, PROJECT_SUFFIX, PROJECT_SUFFIXES)


def _to_dict(project: SlidesProject) -> dict[str, Any]:
    assets_name = ""
    if project.assets_root:
        assets_name = Path(project.assets_root).name
    return {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "stage": STAGE_ID,
        "app_version": __version__,
        "assets_folder": assets_name,
        "project": {
            "name": project.name,
            "video_info": project.video_info.to_dict(),
            "content_start": round(float(project.content_start), 3),
            "content_end": round(float(project.content_end), 3),
            "ppt_region": project.ppt_region.to_dict(),
            # New multi-region format.
            "camera_regions": [camera.to_dict() for camera in project.camera_regions],
            # Legacy single-region fields are still written for one camera so
            # older versions can read the common case.
            "camera_region": (
                project.camera_regions[0].region.to_dict()
                if len(project.camera_regions) == 1
                and project.camera_regions[0].region is not None
                else None
            ),
            "camera_mode": (
                project.camera_regions[0].mode.value
                if len(project.camera_regions) == 1
                else ("multiple" if project.camera_regions else "ignore")
            ),
            "settings": project.settings.to_dict(),
            "analysis_region": project.analysis_region.to_dict() if project.analysis_region else None,
            "analysis_stats": project.analysis_stats,
            "warnings": list(project.warnings),
            "pages": [page.to_dict() for page in project.pages],
            "manual_history": [change.to_dict() for change in project.manual_history],
            "removed_pages": [record.to_dict() for record in project.removed_pages],
            "trash": [entry.to_dict() for entry in project.trash],
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        },
    }


def _from_dict(data: dict[str, Any], project_path: Path, assets_root: Path) -> SlidesProject:
    schema = int(data.get("schema_version") or 1)
    if schema > PROJECT_SCHEMA_VERSION:
        raise ProjectError(
            f"项目文件版本 {schema} 高于当前程序支持的版本 {PROJECT_SCHEMA_VERSION}。"
            "请升级程序后再打开。"
        )
    stage = str(data.get("stage") or STAGE_ID)
    if stage != STAGE_ID:
        raise ProjectError(
            f"该项目属于“{stage}”阶段，当前“{STAGE_NAME}”阶段无法打开。"
        )
    body = data.get("project") or data
    video_info = VideoInfo.from_dict(body.get("video_info"))
    if not video_info.path:
        video_info.path = str(data.get("video_path") or "")
    settings = AnalysisSettings.from_dict(body.get("settings"))
    raw_camera_regions = body.get("camera_regions")
    if raw_camera_regions is not None:
        camera_regions = [
            CameraRegion.from_dict(item)
            for item in raw_camera_regions
            if isinstance(item, dict)
        ]
    else:
        # Migrate projects created before multiple camera regions existed.
        legacy_region = Rect.from_dict(body.get("camera_region"), None)
        camera_raw = str(body.get("camera_mode") or "ignore")
        try:
            legacy_mode = CameraMode(camera_raw)
        except ValueError:
            legacy_mode = CameraMode.IGNORE
        camera_regions = (
            [CameraRegion(region=legacy_region, mode=legacy_mode)]
            if legacy_region is not None and legacy_region.is_valid()
            else []
        )
    pages = [PageCandidate.from_dict(item) for item in (body.get("pages") or [])]
    history = [ManualChange.from_dict(item) for item in (body.get("manual_history") or [])]
    removed = [RemovedPageRecord.from_dict(item) for item in (body.get("removed_pages") or [])]
    trash = [TrashEntry.from_dict(item) for item in (body.get("trash") or [])]
    content_end = float(body.get("content_end") or video_info.duration_sec or 0.0)
    project = SlidesProject(
        name=str(body.get("name") or project_path.stem),
        video_info=video_info,
        content_start=float(body.get("content_start") or 0.0),
        content_end=content_end,
        ppt_region=Rect.from_dict(body.get("ppt_region"), Rect.full_frame()) or Rect.full_frame(),
        camera_regions=camera_regions,
        settings=settings,
        pages=pages,
        analysis_region=Rect.from_dict(body.get("analysis_region"), None),
        analysis_stats=dict(body.get("analysis_stats") or {}),
        warnings=[str(w) for w in (body.get("warnings") or [])],
        manual_history=history,
        removed_pages=removed,
        trash=trash,
        created_at=str(body.get("created_at") or ""),
        updated_at=str(body.get("updated_at") or ""),
    )
    project.project_path = project_path
    project.assets_root = assets_root
    project.dirty = False

    # Mark missing files instead of deleting any candidate silently.
    for page in pages:
        if not page.alternatives:
            if "snapshot_failed" not in page.flags:
                page.flags.append("snapshot_failed")
            page.needs_review = True
            continue
        missing = [
            alt
            for alt in page.alternatives
            if alt.raw_path and not (assets_root / alt.raw_path.replace("/", os.sep)).is_file()
        ]
        if missing:
            if "missing_image" not in page.flags:
                page.flags.append("missing_image")
            page.needs_review = True
    return project


def save_project(project: SlidesProject, project_path: str | Path | None = None) -> Path:
    path = Path(project_path) if project_path else getattr(project, "project_path", None)
    if not path:
        raise ProjectError("尚未设置项目文件路径。")
    path = Path(path)
    assets_root = getattr(project, "assets_root", None)
    if not assets_root:
        assets_root = assets_dir_for_project(path)
        project.assets_root = assets_root
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(assets_root).mkdir(parents=True, exist_ok=True)
    payload = _to_dict(project)
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as exc:
        raise ProjectError(f"项目数据无法序列化：{exc}") from exc
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=path.stem + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise ProjectError(f"保存项目失败：{exc}") from exc
    project.project_path = path
    project.assets_root = Path(assets_root)
    project.dirty = False
    return path


def load_project(project_path: str | Path) -> SlidesProject:
    path = Path(project_path)
    if not path.exists():
        raise ProjectError(f"项目文件不存在：{path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"无法读取项目文件：{exc}") from exc
    if not isinstance(data, dict):
        raise ProjectError("项目文件格式无效。")
    saved_name = str(data.get("assets_folder") or "")
    assets_root = path.parent / saved_name if saved_name else assets_dir_for_project(path)
    if not assets_root.exists():
        # Still load the metadata; image files will be shown as missing.
        assets_root.mkdir(parents=True, exist_ok=True)
    return _from_dict(data, path.resolve(), assets_root.resolve())

