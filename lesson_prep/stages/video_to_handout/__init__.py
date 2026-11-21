"""Workflow stage: video -> lecture handout (planned)."""
from __future__ import annotations

from ...core.stage import Stage, StageInfo

STAGE = Stage(
    info=StageInfo(
        id="video_to_handout",
        name="视频转讲义",
        summary="从网课视频中提取讲解结构、时间轴与图文内容，生成可编辑讲义。",
        inputs="网课视频",
        outputs="讲义草稿（Markdown / Word / PDF，待定）",
        status="planned",
        order=20,
    ),
    file_suffixes=(".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"),
)

__all__ = ["STAGE"]
