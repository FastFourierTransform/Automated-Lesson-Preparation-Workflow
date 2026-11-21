"""Workflow stage: PPT -> lecture handout (planned)."""
from __future__ import annotations

from ...core.stage import Stage, StageInfo

STAGE = Stage(
    info=StageInfo(
        id="ppt_to_handout",
        name="PPT 转讲义",
        summary="读取已有 PPT/PPTX 的页面、标题、备注和图片，整理为结构化讲义。",
        inputs="PPT / PPTX 文件",
        outputs="讲义草稿（Markdown / Word / PDF，待定）",
        status="planned",
        order=30,
    ),
    file_suffixes=(".pptx", ".ppt"),
)

__all__ = ["STAGE"]
