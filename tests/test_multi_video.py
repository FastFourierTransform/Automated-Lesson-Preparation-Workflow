from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from lesson_prep.core.geometry import Rect
from lesson_prep.stages.video_to_slides.analysis.engine import AnalysisEngine
from lesson_prep.stages.video_to_slides.models import (
    AnalysisSettings,
    CameraMode,
    CameraRegion,
)
from lesson_prep.stages.video_to_slides.project import (
    load_project,
    prepare_project_path,
    save_project,
)
from lesson_prep.stages.video_to_slides.ui.config import AppPreferences
from lesson_prep.stages.video_to_slides.ui.main_window import MainWindow


def _draw_region(canvas, left: float, top: float, right: float, bottom: float) -> None:
    content = canvas._content_rect
    assert not content.isEmpty()
    start = QPoint(
        int(content.left() + content.width() * left),
        int(content.top() + content.height() * top),
    )
    end = QPoint(
        int(content.left() + content.width() * right),
        int(content.top() + content.height() * bottom),
    )
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=10)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)


def test_multi_video_import_playback_and_project_roundtrip(
    qapp, demo_video, demo_info, tmp_path
):
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    qapp.processEvents()

    window.import_video_paths([demo_video, demo_video])
    qapp.processEvents()
    assert window.project is not None
    assert len(window.project.video_sources()) == 2
    assert window.video_list.count() == 2
    expected_total = demo_info.duration_sec * 2
    assert window.project.total_duration_sec() == pytest.approx(expected_total, abs=0.05)
    assert window.player.duration == pytest.approx(expected_total, abs=0.05)

    # Seeking past the first video automatically switches the source.
    target = demo_info.duration_sec + 3.0
    window.player.seek(target)
    qapp.processEvents()
    assert window.player.video_index == 1
    assert window.player.local_position == pytest.approx(3.0, abs=0.25)
    assert window.player.position == pytest.approx(target, abs=0.25)
    assert window.video_list.currentRow() == 1

    # Persist and reload both sources with their order intact.
    project_path = tmp_path / "multi.lsp.json"
    path, assets = prepare_project_path(project_path)
    window.project.project_path = path
    window.project.assets_root = assets
    save_project(window.project)
    loaded = load_project(path)
    assert len(loaded.video_sources()) == 2
    assert [info.path for info in loaded.video_sources()] == [
        str(demo_video.resolve()),
        str(demo_video.resolve()),
    ]

    window.project.dirty = False
    window.close()
    qapp.processEvents()


def test_multi_video_analysis_uses_one_combined_timeline(
    demo_video, demo_info, tmp_path
):
    assets_root = tmp_path / "assets"
    engine = AnalysisEngine(
        demo_video,
        demo_info,
        4.0,
        demo_info.duration_sec + 20.0,
        Rect.full_frame(),
        [],
        AnalysisSettings(),
        assets_root,
        assets_root / "runs" / "multi",
        video_sources=[demo_info, demo_info],
    )
    result = engine.analyze()
    assert result.stats["video_count"] == 2
    assert len(result.pages) >= 6
    assert any(page.video_index == 1 for page in result.pages)
    assert any(
        page.selected_time > demo_info.duration_sec for page in result.pages
    )
    times = [page.selected_time for page in result.pages]
    assert times == sorted(times)
    for page in result.pages:
        assert page.video_index in (0, 1)
        for alt in page.alternatives:
            assert alt.video_index == page.video_index
            assert (assets_root / alt.raw_path).is_file()
            if page.video_index == 1:
                assert alt.time_sec > demo_info.duration_sec


def test_region_preset_is_remembered_and_applied_to_new_import(
    qapp, demo_video
):
    preset_ppt = Rect(0.08, 0.12, 0.80, 0.76)
    preset_camera = CameraRegion(
        region=Rect(0.74, 0.03, 0.23, 0.28),
        mode=CameraMode.MASK_WHITE,
    )
    prefs = AppPreferences()
    prefs.remember_regions(preset_ppt, [preset_camera])

    loaded = AppPreferences.load()
    assert loaded.last_ppt_region.x == pytest.approx(preset_ppt.x, abs=1e-4)
    assert loaded.last_ppt_region.w == pytest.approx(preset_ppt.w, abs=1e-4)
    assert len(loaded.last_camera_regions) == 1
    assert loaded.last_camera_regions[0].mode == CameraMode.MASK_WHITE

    window = MainWindow(preferences=loaded)
    window.resize(1400, 900)
    window.show()
    qapp.processEvents()
    window.import_video_path(demo_video)
    qapp.processEvents()
    assert window.project is not None
    assert window.project.ppt_region.x == pytest.approx(preset_ppt.x, abs=1e-4)
    assert window.project.ppt_region.h == pytest.approx(preset_ppt.h, abs=1e-4)
    assert len(window.project.camera_regions) == 1
    assert window.project.camera_regions[0].mode == CameraMode.MASK_WHITE
    assert window.camera_count_spin.value() == 1

    window.project.dirty = False
    window.close()
    qapp.processEvents()


def test_large_preview_can_select_ppt_and_camera_regions(qapp, demo_video):
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    qapp.processEvents()
    window.import_video_path(demo_video)
    qapp.processEvents()

    window.open_large_preview()
    qapp.processEvents()
    dialog = window.preview_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.canvas.has_image()

    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("ppt"))
    dialog.select_button.click()
    qapp.processEvents()
    assert dialog.canvas.selection_mode == "ppt"
    assert window.preview.selection_mode is None
    _draw_region(dialog.canvas, 0.10, 0.12, 0.76, 0.88)
    qapp.processEvents()
    assert dialog.canvas.selection_mode is None
    assert window.project.ppt_region.x == pytest.approx(0.10, abs=0.03)
    assert window.project.ppt_region.w == pytest.approx(0.66, abs=0.05)
    assert window.preview._primary_region.x == pytest.approx(
        window.project.ppt_region.x, abs=1e-6
    )

    window.camera_count_spin.setValue(1)
    qapp.processEvents()
    camera = window.project.camera_regions[0]
    dialog.target_combo.setCurrentIndex(
        dialog.target_combo.findData(f"camera:{camera.id}")
    )
    dialog.select_button.click()
    qapp.processEvents()
    assert dialog.canvas.selection_mode == f"camera:{camera.id}"
    _draw_region(dialog.canvas, 0.75, 0.04, 0.96, 0.30)
    qapp.processEvents()
    assert camera.region is not None
    assert camera.region.x == pytest.approx(0.75, abs=0.04)
    assert camera.region.h == pytest.approx(0.26, abs=0.05)
    assert len(window.preview._overlays) == 1

    # Both selections were persisted for the next import/restart.
    saved = AppPreferences.load()
    assert saved.last_ppt_region.x == pytest.approx(0.10, abs=0.03)
    assert len(saved.last_camera_regions) == 1
    assert saved.last_camera_regions[0].region is not None
    assert saved.last_camera_regions[0].region.x == pytest.approx(0.75, abs=0.04)

    dialog.close()
    qapp.processEvents()
    assert window.preview_dialog is None
    window.project.dirty = False
    window.close()
    qapp.processEvents()
