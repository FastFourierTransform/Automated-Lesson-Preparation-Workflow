"""Workflow stage registry.

Add a new stage by creating ``lesson_prep/stages/<stage_id>/__init__.py`` that
exports a :class:`~lesson_prep.core.stage.Stage` as ``STAGE`` and registering
it in ``STAGES`` below.  Stages with ``status="planned"`` can be registered
before their implementation exists.
"""
from __future__ import annotations

from ..core.stage import Stage
from .ppt_to_handout import STAGE as PPT_TO_HANDOUT
from .video_to_handout import STAGE as VIDEO_TO_HANDOUT
from .video_to_slides import STAGE as VIDEO_TO_SLIDES

STAGES: tuple[Stage, ...] = tuple(
    sorted(
        (VIDEO_TO_SLIDES, VIDEO_TO_HANDOUT, PPT_TO_HANDOUT),
        key=lambda stage: stage.info.order,
    )
)
DEFAULT_STAGE_ID = VIDEO_TO_SLIDES.info.id


def get_stage(stage_id: str | None) -> Stage | None:
    if not stage_id:
        return None
    for stage in STAGES:
        if stage.info.id == stage_id:
            return stage
    return None


def available_stages() -> tuple[Stage, ...]:
    return tuple(stage for stage in STAGES if stage.available)


def stage_for_path(path) -> Stage | None:
    """Pick the first registered stage that declares a matching file suffix.

    Planned stages are included so that opening e.g. a PPTX reports
    "not implemented yet" instead of trying to parse it as a video.
    """
    suffix = str(getattr(path, "suffix", "") or "").lower()
    for stage in STAGES:
        if suffix and suffix in stage.file_suffixes:
            return stage
    return None


__all__ = [
    "STAGES",
    "DEFAULT_STAGE_ID",
    "available_stages",
    "get_stage",
    "stage_for_path",
]
