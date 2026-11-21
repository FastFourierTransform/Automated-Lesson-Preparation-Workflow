from __future__ import annotations

import json
from pathlib import Path

import pytest

from lesson_prep.stages.video_to_slides.export.service import ExportOptions, export_project
from lesson_prep.core.geometry import Rect, relative_rect
from lesson_prep.stages.video_to_slides.models import CameraMode, CameraRegion
from lesson_prep.stages.video_to_slides.project import assets_dir_for_project, load_project, save_project
from tests.helpers import copy_project, mark_manual_changes


def test_project_roundtrip_preserves_manual_review(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "roundtrip")
    mark_manual_changes(project)
    original_order = [p.id for p in project.pages]
    original_selected = [
        (p.id, p.selected_raw_path, p.kept, p.review_note, p.manually_modified) for p in project.pages
    ]
    original_history = [change.to_dict() for change in project.manual_history]
    original_removed = [record.to_dict() for record in project.removed_pages]
    saved_path = save_project(project)
    assert saved_path.is_file()
    assert project.assets_root == assets_dir_for_project(saved_path)
    payload = json.loads(saved_path.read_text(encoding="utf-8"))
    assert payload["project"]["pages"]

    loaded = load_project(saved_path)
    assert [p.id for p in loaded.pages] == original_order
    assert [
        (p.id, p.selected_raw_path, p.kept, p.review_note, p.manually_modified)
        for p in loaded.pages
    ] == original_selected
    assert [change.to_dict() for change in loaded.manual_history] == original_history
    assert [record.to_dict() for record in loaded.removed_pages] == original_removed
    assert len(loaded.camera_regions) == 1
    assert loaded.camera_regions[0].mode.value == "mask"
    assert loaded.content_start == 4.0
    assert loaded.content_end == 38.0
    assert loaded.analysis_region is not None
    assert all(p.alternatives for p in loaded.pages)

    # Saving/reloading again must be stable.
    save_project(loaded)
    loaded_again = load_project(saved_path)
    assert [p.selected_raw_path for p in loaded_again.pages] == [
        p[1] for p in original_selected
    ]


def test_export_respects_review_and_writes_all_formats(analysis_bundle, tmp_path):
    from PIL import Image
    from pptx import Presentation

    project = copy_project(analysis_bundle, tmp_path, "export")
    mark_manual_changes(project)
    saved_path = save_project(project)
    # Export the reloaded project, proving persisted manual decisions are used.
    project = load_project(saved_path)
    source_video = Path(analysis_bundle["video_info"].path)
    source_stat = (source_video.stat().st_size, source_video.stat().st_mtime_ns)
    raw_snapshot = project.assets_root / project.pages[0].selected_raw_path
    raw_stat = (raw_snapshot.stat().st_size, raw_snapshot.stat().st_mtime_ns)
    before = {
        "order": [p.id for p in project.pages],
        "selected": [p.selected_raw_path for p in project.pages],
        "kept": [p.kept for p in project.pages],
        "history": [c.to_dict() for c in project.manual_history],
    }
    active = project.active_pages()
    assert 0 < len(active) < len(project.pages)

    output_parent = tmp_path / "exports"
    output_parent.mkdir()
    result = export_project(project, output_parent)
    assert (source_video.stat().st_size, source_video.stat().st_mtime_ns) == source_stat
    assert (raw_snapshot.stat().st_size, raw_snapshot.stat().st_mtime_ns) == raw_stat

    # Review decisions must not be touched by export.
    assert [p.id for p in project.pages] == before["order"]
    assert [p.selected_raw_path for p in project.pages] == before["selected"]
    assert [p.kept for p in project.pages] == before["kept"]
    assert [c.to_dict() for c in project.manual_history] == before["history"]

    assert result.exported_pages == len(active)
    assert result.skipped_pages == len(project.skipped_pages())
    assert result.output_dir.is_dir()
    assert len(result.png_files) == len(active)
    assert all(path.is_file() for path in result.png_files)
    assert result.pptx_path and result.pptx_path.is_file()
    assert result.manifest_path and result.manifest_path.is_file()

    first_size = None
    for path in result.png_files:
        with Image.open(path) as image:
            assert image.format == "PNG"
            if first_size is None:
                first_size = image.size
            # All synthetic frames are the same raw crop size.
            assert image.size == first_size

    raw_files = sorted((result.output_dir / "raw_candidates").glob("*.jpg"))
    assert len(raw_files) == len(active)

    presentation = Presentation(str(result.pptx_path))
    assert len(presentation.slides) == len(active)
    slide_ratio = presentation.slide_width / presentation.slide_height
    with Image.open(result.png_files[0]) as first_image:
        image_ratio = first_image.width / first_image.height
    assert abs(slide_ratio - image_ratio) < 1e-3
    for slide, png in zip(presentation.slides, result.png_files):
        pictures = [shape for shape in slide.shapes if shape.shape_type == 13]
        assert len(pictures) == 1
        picture = pictures[0]
        with Image.open(png) as image:
            assert abs((picture.width / picture.height) - (image.width / image.height)) < 1e-3
            # With a matching slide aspect ratio the picture should fill the page.
            assert picture.width == presentation.slide_width
            assert picture.height == presentation.slide_height

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_video"] == str(analysis_bundle["video_info"].path)
    assert manifest["content_range"]["start_sec"] == 4.0
    assert manifest["camera_mode"] == "mask"
    assert manifest["export"]["included_pages"] == len(active)
    assert len(manifest["slides"]) == len(project.pages)
    included = [s for s in manifest["slides"] if s["state"] == "included"]
    skipped = [s for s in manifest["slides"] if s["state"] == "skipped"]
    assert len(included) == len(active)
    assert skipped
    assert all(s["image_png"] for s in included)
    assert all(not s["image_png"] for s in skipped)
    assert manifest["manual_changes"]
    assert manifest["removed_pages"]

    # A second export goes to a fresh directory.
    result2 = export_project(project, output_parent)
    assert result2.output_dir != result.output_dir
    assert result2.output_dir.is_dir()


@pytest.mark.parametrize(
    "camera_mode,fill",
    [
        ("mask", 0),
        ("mask_white", 255),
    ],
)
def test_export_masks_camera_area(analysis_bundle, tmp_path, camera_mode, fill):
    import numpy as np
    from PIL import Image

    from lesson_prep.core.geometry import relative_rect
    from lesson_prep.stages.video_to_slides.models import CameraMode
    from lesson_prep.stages.video_to_slides.project import load_project

    project = copy_project(
        analysis_bundle,
        tmp_path / camera_mode,
        "mask",
        camera_mode=CameraMode(camera_mode),
    )
    # Export only one page to keep this focused.
    project.pages = project.pages[:1]
    project.pages[0].kept = True
    project_path = save_project(project)
    project = load_project(project_path)
    local = relative_rect(
        project.camera_regions[0].region, project.analysis_region
    )
    assert local is not None
    output = tmp_path / camera_mode / "out"
    output.mkdir(parents=True)
    result = export_project(project, output)
    image = np.asarray(Image.open(result.png_files[0]).convert("RGB"))
    h, w = image.shape[:2]
    x, y, cw, ch = local.to_pixels(w, h)
    # Sample an inner part of the camera region; it should be filled.
    inner = image[y + ch // 4 : y + 3 * ch // 4, x + cw // 4 : x + 3 * cw // 4]
    if fill == 0:
        assert inner.max() <= 5
    else:
        assert inner.min() >= 250
    # The rest of the slide is untouched.
    outside = image[: max(1, h // 5), : max(1, w // 5)]
    assert outside.mean() > 50
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["camera_mode"] == camera_mode
    assert manifest["camera_effective_mode_per_page"]["1"] == camera_mode


def test_legacy_single_camera_project_is_migrated(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "legacy_camera")
    path = save_project(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Simulate a project written before multi-region support.
    payload["project"].pop("camera_regions", None)
    payload["project"]["camera_region"] = {
        "x": 0.746,
        "y": 0.028,
        "w": 0.231,
        "h": 0.282,
    }
    payload["project"]["camera_mode"] = "mask_white"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_project(path)
    assert len(loaded.camera_regions) == 1
    camera = loaded.camera_regions[0]
    assert camera.region is not None
    assert camera.region.x == pytest.approx(0.746)
    assert camera.mode == CameraMode.MASK_WHITE


def test_multiple_camera_regions_have_independent_export_modes(analysis_bundle, tmp_path):
    import numpy as np
    from PIL import Image

    project = copy_project(analysis_bundle, tmp_path, "multi_camera")
    second_region = Rect(0.04, 0.62, 0.20, 0.28)
    project.camera_regions = [
        CameraRegion(
            region=Rect(0.746, 0.028, 0.231, 0.282),
            mode=CameraMode.MASK,
        ),
        CameraRegion(region=second_region, mode=CameraMode.MASK_WHITE),
    ]
    project.pages = project.pages[:1]
    project.pages[0].kept = True
    project_path = save_project(project)
    project = load_project(project_path)
    assert len(project.camera_regions) == 2
    assert [cam.mode for cam in project.camera_regions] == [
        CameraMode.MASK,
        CameraMode.MASK_WHITE,
    ]

    local_first = relative_rect(project.camera_regions[0].region, project.analysis_region)
    local_second = relative_rect(project.camera_regions[1].region, project.analysis_region)
    output = tmp_path / "multi_out"
    output.mkdir()
    result = export_project(project, output)
    image = np.asarray(Image.open(result.png_files[0]).convert("RGB"))
    h, w = image.shape[:2]
    for local, fill in ((local_first, 0), (local_second, 255)):
        assert local is not None
        x, y, cw, ch = local.to_pixels(w, h)
        inner = image[y + ch // 4 : y + 3 * ch // 4, x + cw // 4 : x + 3 * cw // 4]
        if fill == 0:
            assert inner.max() <= 5
        else:
            assert inner.min() >= 250

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["camera_mode"] == "multiple"
    assert len(manifest["camera_regions"]) == 2
    assert [region["mode"] for region in manifest["camera_regions"]] == [
        "mask",
        "mask_white",
    ]
    assert manifest["camera_effective_modes_per_page"]["1"] == ["mask", "mask_white"]
    assert manifest["camera_effective_mode_per_page"]["1"] == "multiple"


def test_pptx_only_uses_temporary_pngs_and_cleans_them(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "pptx_only")
    project.pages = project.pages[:2]
    for page in project.pages:
        page.kept = True
    output = tmp_path / "out"
    output.mkdir()
    result = export_project(
        project,
        output,
        ExportOptions(png=False, pptx=True, json_manifest=True, copy_raw_candidates=False),
    )
    assert result.exported_pages == 2
    assert result.png_files == []
    assert not (result.output_dir / "png").exists()
    assert not (result.output_dir / ".pptx_images").exists()
    assert result.pptx_path and result.pptx_path.is_file()
    assert result.manifest_path and result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert all(slide["image_png"] is None for slide in manifest["slides"])

