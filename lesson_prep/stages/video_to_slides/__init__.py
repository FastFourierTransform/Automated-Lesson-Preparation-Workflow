"""Workflow stage: video -> slide images / PPTX.

This package is self-contained: models, two-level analysis, manual-review UI
and PNG/PPTX/JSON export all live here.  Shared media decoding and UI widgets
come from :mod:`lesson_prep.core`.
"""
from __future__ import annotations

from pathlib import Path

from ...core.stage import Stage, StageInfo
from .constants import STAGE_ID, STAGE_NAME


def _create_window():
    from .ui.main_window import MainWindow

    return MainWindow()


def _open_path(window, path: Path) -> bool:
    if path.suffix.lower() == ".json":
        window.open_project_path(path)
    else:
        window.import_video_path(path)
    return True


STAGE = Stage(
    info=StageInfo(
        id=STAGE_ID,
        name=STAGE_NAME,
        summary="检测网课视频中的 PPT 页面切换，复核后导出 PNG、PPTX 和 JSON 清单。",
        inputs="网课视频（MP4/MKV/AVI 等）",
        outputs="PNG 图片序列、PPTX、manifest.json、.lsp.json 项目",
        status="available",
        order=10,
    ),
    create_window=_create_window,
    open_path=_open_path,
    file_suffixes=(
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
        ".json",
    ),
)

__all__ = ["STAGE", "STAGE_ID", "STAGE_NAME"]
