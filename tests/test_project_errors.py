from __future__ import annotations

import json

import pytest

from lesson_prep.stages.video_to_slides.export.service import ExportError, export_project
from lesson_prep.stages.video_to_slides.project import ProjectError, load_project, save_project
from tests.helpers import copy_project


def test_missing_project_file(tmp_path):
    with pytest.raises(ProjectError):
        load_project(tmp_path / "missing.lsp.json")


def test_invalid_project_json(tmp_path):
    path = tmp_path / "bad.lsp.json"
    path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(path)


def test_project_from_another_stage_is_rejected(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "wrong_stage")
    path = save_project(project)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["stage"] = "ppt_to_handout"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ProjectError, match="无法打开"):
        load_project(path)


def test_export_without_kept_pages(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "none")
    for page in project.pages:
        page.kept = False
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ExportError):
        export_project(project, output)


def test_export_missing_image_fails_cleanly(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "missing")
    path = project.assets_root / project.pages[0].selected_raw_path
    path.unlink()
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ExportError):
        export_project(project, output)

