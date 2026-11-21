from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from lesson_prep.core.geometry import Rect
from lesson_prep.stages.video_to_slides.models import CameraMode
from lesson_prep.stages.video_to_slides.project import prepare_project_path, save_project
from lesson_prep.stages.video_to_slides.ui.main_window import MainWindow
from tests.helpers import copy_project

CAMERA = Rect(0.746, 0.028, 0.231, 0.282)


def _wait_until(qapp, predicate, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        # QTest.qWait can enter a nested event loop that never returns under
        # the offscreen Qt platform in this environment.  A plain short sleep
        # keeps the GUI event loop responsive without that pitfall.
        time.sleep(0.02)
    return False


def _set_content_range(window: MainWindow, start: float, end: float) -> None:
    window.start_edit.setText(f"{start:.3f}")
    window.end_edit.setText(f"{end:.3f}")
    assert window._apply_time_edits()


def _attach_project_path(window: MainWindow, tmp_path: Path, name: str) -> Path:
    project_path = tmp_path / f"{name}.lsp.json"
    path, assets = prepare_project_path(project_path)
    window.project.project_path = path
    window.project.assets_root = assets
    save_project(window.project)
    return path


def test_import_preview_and_region_selection(qapp, demo_video, tmp_path):
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    qapp.processEvents()

    window.import_video_path(demo_video)
    qapp.processEvents()
    assert window.project is not None
    assert window.player.reader is not None
    assert window.preview.has_image()
    assert "1280" in window.info_spec.text()
    assert "30.00" in window.info_spec.text()

    window.player.seek(8.0)
    qapp.processEvents()
    assert abs(window.player.position - 8.0) < 0.2
    assert "00:00:08" in window.time_label.text()

    # Draw a PPT region with normalized output coordinates.
    window._begin_region_selection("ppt")
    qapp.processEvents()
    content = window.preview._content_rect
    assert not content.isEmpty()
    start = QPoint(
        int(content.left() + content.width() * 0.10),
        int(content.top() + content.height() * 0.15),
    )
    end = QPoint(
        int(content.left() + content.width() * 0.75),
        int(content.top() + content.height() * 0.9),
    )
    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.preview, end, delay=10)
    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=end)
    qapp.processEvents()
    region = window.project.ppt_region
    assert region.x == pytest.approx(0.10, abs=0.03)
    assert region.y == pytest.approx(0.15, abs=0.03)
    assert region.w == pytest.approx(0.65, abs=0.05)
    assert region.h == pytest.approx(0.75, abs=0.05)
    saved_region = (region.x, region.y, region.w, region.h)

    # Existing regions can be resized by dragging a border handle instead of
    # redrawing the whole rectangle.
    qapp.processEvents()
    content = window.preview._content_rect
    display_rect = window.preview._rect_to_qrect(region, content)
    border_point = QPoint(int(display_rect.right()), int(display_rect.center().y()))
    target_point = QPoint(
        int(min(content.right(), display_rect.right() + 35)),
        int(display_rect.center().y()),
    )
    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=border_point)
    QTest.mouseMove(window.preview, target_point, delay=10)
    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=target_point)
    qapp.processEvents()
    resized = window.project.ppt_region
    assert resized.x == pytest.approx(region.x, abs=1e-4)
    assert resized.y == pytest.approx(region.y, abs=1e-4)
    assert resized.w > region.w + 0.02
    assert resized.h == pytest.approx(region.h, abs=1e-4)
    saved_region = (resized.x, resized.y, resized.w, resized.h)

    # Preview scaling must not change stored normalized coordinates.
    window.resize(1200, 820)
    qapp.processEvents()
    region = window.project.ppt_region
    assert (region.x, region.y, region.w, region.h) == saved_region

    # Configure the first of multiple camera regions through the count control.
    window.camera_count_spin.setValue(1)
    qapp.processEvents()
    assert len(window.project.camera_regions) == 1
    first_camera = window.project.camera_regions[0]
    window._camera_select_buttons[first_camera.id].click()
    qapp.processEvents()
    content = window.preview._content_rect
    start = QPoint(
        int(content.left() + content.width() * 0.76),
        int(content.top() + content.height() * 0.05),
    )
    end = QPoint(
        int(content.left() + content.width() * 0.97),
        int(content.top() + content.height() * 0.31),
    )
    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.preview, end, delay=10)
    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=end)
    qapp.processEvents()
    assert first_camera.region is not None
    assert first_camera.region.area > 0.01
    camera_region = first_camera.region
    content = window.preview._content_rect
    camera_display = window.preview._rect_to_qrect(camera_region, content)
    bottom_point = QPoint(
        int(camera_display.center().x()),
        int(camera_display.bottom()),
    )
    bottom_target = QPoint(
        int(camera_display.center().x()),
        int(min(content.bottom(), camera_display.bottom() + 20)),
    )
    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=bottom_point)
    QTest.mouseMove(window.preview, bottom_target, delay=10)
    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=bottom_target)
    qapp.processEvents()
    resized_camera = first_camera.region
    assert resized_camera.x == pytest.approx(camera_region.x, abs=1e-4)
    assert resized_camera.w == pytest.approx(camera_region.w, abs=1e-4)
    assert resized_camera.h > camera_region.h
    first_combo = window._camera_mode_combos[first_camera.id]
    first_combo.setCurrentIndex(first_combo.findData(CameraMode.MASK_WHITE.value))
    qapp.processEvents()
    assert first_camera.mode == CameraMode.MASK_WHITE

    # Add a second camera region and give it an independent mode.
    window.camera_count_spin.setValue(2)
    qapp.processEvents()
    assert len(window.project.camera_regions) == 2
    second_camera = window.project.camera_regions[1]
    window._camera_select_buttons[second_camera.id].click()
    qapp.processEvents()
    content = window.preview._content_rect
    start = QPoint(
        int(content.left() + content.width() * 0.05),
        int(content.top() + content.height() * 0.65),
    )
    end = QPoint(
        int(content.left() + content.width() * 0.25),
        int(content.top() + content.height() * 0.92),
    )
    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.preview, end, delay=10)
    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=end)
    qapp.processEvents()
    assert second_camera.region is not None
    second_combo = window._camera_mode_combos[second_camera.id]
    second_combo.setCurrentIndex(second_combo.findData(CameraMode.CROP.value))
    qapp.processEvents()
    assert first_camera.mode == CameraMode.MASK_WHITE
    assert second_camera.mode == CameraMode.CROP
    assert len(window.preview._overlays) == 2

    _set_content_range(window, 4.0, 38.0)
    assert window.project.content_start == pytest.approx(4.0, abs=0.01)
    assert window.project.content_end == pytest.approx(38.0, abs=0.01)

    window.project.dirty = False
    window.close()
    qapp.processEvents()


def test_background_analysis_review_and_reload(qapp, demo_video, tmp_path, monkeypatch):
    window = MainWindow()
    window.resize(1500, 960)
    window.show()
    window.import_video_path(demo_video)
    _set_content_range(window, 4.0, 38.0)
    window.camera_count_spin.setValue(1)
    qapp.processEvents()
    camera = window.project.camera_regions[0]
    camera.region = CAMERA
    camera.mode = CameraMode.MASK
    window._rebuild_camera_rows()
    window._sync_camera_preview()
    window._update_ui_state()
    project_path = _attach_project_path(window, tmp_path, "ui_session")
    assert window.project.dirty is False

    ticks = {"count": 0}
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.__setitem__("count", ticks["count"] + 1))
    timer.start()

    window.start_analysis()
    assert window._busy_kind == "analysis"
    assert window.analysis_worker is not None
    finished = _wait_until(
        qapp,
        lambda: window.analysis_worker is None and window._busy_kind is None,
        timeout=120,
    )
    timer.stop()
    assert finished
    assert ticks["count"] > 10, "UI event loop was blocked during analysis"
    assert window.project.pages
    assert len(window.project.pages) == 5
    assert window.review.page_list.count() == 5
    assert window.progress_bar.value() == 100 or window._busy_kind is None
    assert window.project.dirty is False
    assert Path(project_path).is_file()

    # Switch the first page to another candidate frame.
    window.review.page_list.setCurrentRow(0)
    qapp.processEvents()
    page = window.project.pages[0]
    old_selected = page.selected_raw_path
    review = window.review
    target_row = None
    for row in range(review.alt_list.count()):
        if review.alt_list.item(row).data(Qt.ItemDataRole.UserRole) != old_selected:
            target_row = row
            break
    assert target_row is not None
    review.alt_list.setCurrentRow(target_row)
    qapp.processEvents()
    assert page.selected_raw_path != old_selected
    assert page.manually_modified is True
    assert any(c.action == "select_alternative" for c in window.project.manual_history)

    # Skip the current page.
    window.review.keep_checkbox.setChecked(False)
    qapp.processEvents()
    assert page.kept is False

    # Reorder the current page down.
    page_ids_before = [p.id for p in window.project.pages]
    window.review.keep_checkbox.setChecked(True)
    qapp.processEvents()
    window.review.page_list.setCurrentRow(0)
    window.review.down_button.click()
    qapp.processEvents()
    page_ids_moved = [p.id for p in window.project.pages]
    assert page_ids_moved[0] == page_ids_before[1]
    assert page_ids_moved[1] == page_ids_before[0]

    # Delete a page immediately (no confirmation dialog); it goes to trash.
    window.review.page_list.setCurrentRow(1)
    deleted_page_id = window.project.pages[1].id
    before_count = len(window.project.pages)
    window.review.delete_button.click()
    qapp.processEvents()
    assert len(window.project.pages) == before_count - 1
    assert len(window.project.trash) == 1
    assert window.project.trash[0].page.id == deleted_page_id
    assert window.project.removed_pages
    assert any(c.action == "delete_page" for c in window.project.manual_history)
    assert "1" in window.review.trash_button.text()
    assert window.review.trash_button.isEnabled()

    # Persist and reload; page deletion and the recycle bin must survive.
    expected_ids = [p.id for p in window.project.pages]
    expected_selected = [p.selected_raw_path for p in window.project.pages]
    expected_kept = [p.kept for p in window.project.pages]
    expected_notes = [p.review_note for p in window.project.pages]
    assert window._save_project(silent=True)
    assert window.project.dirty is False
    window.close()
    qapp.processEvents()

    window2 = MainWindow()
    window2.resize(1400, 900)
    window2.show()
    window2.open_project_path(project_path)
    qapp.processEvents()
    assert [p.id for p in window2.project.pages] == expected_ids
    assert [p.selected_raw_path for p in window2.project.pages] == expected_selected
    assert [p.kept for p in window2.project.pages] == expected_kept
    assert [p.review_note for p in window2.project.pages] == expected_notes
    assert any(c.action == "delete_page" for c in window2.project.manual_history)
    assert window2.review.page_list.count() == len(expected_ids)
    assert len(window2.project.trash) == 1
    assert window2.review.trash_button.isEnabled()

    # Restore the deleted page through the recycle-bin dialog.  The dialog's
    # selection UI is covered separately; here we auto-select its first entry.
    def fake_trash_exec(dialog):
        dialog.list_widget.setCurrentRow(0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr("lesson_prep.stages.video_to_slides.ui.trash_dialog.TrashDialog.exec", fake_trash_exec)
    window2.review.trash_button.click()
    qapp.processEvents()
    assert len(window2.project.pages) == len(expected_ids) + 1
    assert window2.project.pages[1].id == deleted_page_id
    assert window2.project.trash == []
    assert not any(r.page_id == deleted_page_id for r in window2.project.removed_pages)
    assert any(c.action == "restore_page" for c in window2.project.manual_history)
    assert window2.review.page_list.count() == len(expected_ids) + 1
    assert window2.review.trash_button.text() == "回收站"
    assert window2._save_project(silent=True)
    window2.project.dirty = False
    window2.close()
    qapp.processEvents()


def test_export_through_ui_worker(qapp, analysis_bundle, tmp_path, monkeypatch):
    project = copy_project(analysis_bundle, tmp_path, "ui_export")
    project.pages = project.pages[:2]
    for page in project.pages:
        page.kept = True
    project_path = save_project(project)
    output_parent = tmp_path / "ui_exports"
    output_parent.mkdir()

    def fake_dialog_exec(dialog):
        dialog.folder_edit.setText(str(output_parent))
        dialog.png_check.setChecked(True)
        dialog.ppt_check.setChecked(True)
        dialog.json_check.setChecked(True)
        dialog.raw_check.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "lesson_prep.stages.video_to_slides.ui.export_dialog.ExportDialog.exec",
        fake_dialog_exec,
    )
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda self: QMessageBox.StandardButton.Ok,
    )

    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window.open_project_path(project_path)
    qapp.processEvents()
    assert window.project is not None
    assert window.review.page_list.count() == 2
    window.export_slides()
    assert window._busy_kind == "export"
    finished = _wait_until(
        qapp,
        lambda: window.export_worker is None and window._busy_kind is None,
        timeout=60,
    )
    assert finished
    folders = list(output_parent.glob("ui_export_slides_*"))
    assert folders, "UI export did not create an output folder"
    output_dir = folders[0]
    assert (output_dir / "lecture_slides.pptx").is_file()
    assert (output_dir / "manifest.json").is_file()
    assert len(list((output_dir / "png").glob("*.png"))) == 2
    window.project.dirty = False
    window.close()
    qapp.processEvents()


def test_trash_dialog_lists_and_selects_deleted_pages(qapp, analysis_bundle, tmp_path):
    from lesson_prep.stages.video_to_slides.ui.trash_dialog import TrashDialog

    project = copy_project(analysis_bundle, tmp_path, "trash_dialog")
    deleted_id = project.pages[1].id
    project.move_page_to_trash(deleted_id)
    dialog = TrashDialog(project)
    dialog.show()
    qapp.processEvents()
    assert dialog.list_widget.count() == 1
    assert dialog.stack.currentIndex() == 1
    assert not dialog.restore_button.isEnabled()
    dialog.list_widget.setCurrentRow(0)
    qapp.processEvents()
    assert dialog.restore_button.isEnabled()
    selected = dialog.selected_entries()
    assert len(selected) == 1
    assert selected[0].page.id == deleted_id
    # Selecting all keeps the dialog usable for bulk restore.
    dialog.select_all_button.click()
    qapp.processEvents()
    assert len(dialog.selected_entries()) == 1
    dialog.close()
    qapp.processEvents()


def test_cancel_analysis_returns_to_idle(qapp, demo_video, tmp_path):
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window.import_video_path(demo_video)
    _set_content_range(window, 4.0, 38.0)
    window.camera_count_spin.setValue(1)
    camera = window.project.camera_regions[0]
    camera.region = CAMERA
    camera.mode = CameraMode.MASK
    window._sync_camera_preview()
    project_path = _attach_project_path(window, tmp_path, "cancel_session")
    runs_dir = Path(window.project.assets_root) / "runs"
    window.start_analysis()
    assert window.analysis_worker is not None
    window._cancel_current_task()
    finished = _wait_until(
        qapp,
        lambda: window.analysis_worker is None and window._busy_kind is None,
        timeout=30,
    )
    assert finished
    assert window.project.pages == []
    assert window.analysis_worker is None
    assert window._busy_kind is None
    assert window.cancel_button.isVisible() is False
    # The cancelled run's staging directory is removed.
    if runs_dir.exists():
        assert not any(runs_dir.iterdir())
    assert Path(project_path).is_file()
    window.project.dirty = False
    window.close()
    qapp.processEvents()

