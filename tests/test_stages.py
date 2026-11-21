from __future__ import annotations

from pathlib import Path

from lesson_prep.stages import (
    DEFAULT_STAGE_ID,
    STAGES,
    available_stages,
    get_stage,
    stage_for_path,
)


def test_stage_registry_ids_are_unique():
    ids = [stage.info.id for stage in STAGES]
    assert len(ids) == len(set(ids))


def test_default_stage_is_available():
    default = get_stage(DEFAULT_STAGE_ID)
    assert default is not None
    assert default.available is True


def test_planned_stages_are_registered_but_not_startable():
    planned = {stage.info.id: stage for stage in STAGES if not stage.available}
    assert "video_to_handout" in planned
    assert "ppt_to_handout" in planned
    assert all(stage.create_window is None for stage in planned.values())


def test_available_stages_are_subset_of_registry():
    assert set(available_stages()).issubset(set(STAGES))


def test_stage_selection_by_file_suffix():
    assert stage_for_path(Path("lesson.mp4")).info.id == "video_to_slides"
    assert stage_for_path(Path("lesson.lsp.json")).info.id == "video_to_slides"
    assert stage_for_path(Path("lesson.pptx")).info.id == "ppt_to_handout"
    assert stage_for_path(Path("lesson.unknown")) is None
