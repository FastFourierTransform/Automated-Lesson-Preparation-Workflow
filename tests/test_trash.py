from __future__ import annotations

from lesson_prep.stages.video_to_slides.project import load_project, save_project
from tests.helpers import copy_project


def test_delete_to_trash_and_restore_roundtrip(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "trash_roundtrip")
    original_ids = [page.id for page in project.pages]
    page = project.pages[1]
    selected_before = page.selected_raw_path
    note_before = page.review_note
    kept_before = page.kept
    entry = project.move_page_to_trash(page.id, reason="测试删除")
    assert entry is not None
    assert entry.original_index == 1
    assert entry.page.id == page.id
    assert entry.page.selected_raw_path == selected_before
    assert len(project.trash) == 1
    assert page.id not in [p.id for p in project.pages]
    assert [r.page_id for r in project.removed_pages] == [page.id]

    path = save_project(project)
    loaded = load_project(path)
    assert len(loaded.trash) == 1
    assert loaded.trash[0].page.id == page.id
    assert loaded.trash[0].original_index == 1
    assert loaded.trash[0].page.selected_raw_path == selected_before
    assert loaded.trash[0].page.review_note == note_before
    assert loaded.trash[0].page.kept == kept_before
    assert loaded.trash[0].reason == "测试删除"
    assert [r.page_id for r in loaded.removed_pages] == [page.id]

    restored = loaded.restore_trash_entries([page.id])
    assert [p.id for p in restored] == [page.id]
    assert [p.id for p in loaded.pages] == original_ids
    assert loaded.trash == []
    assert not any(record.page_id == page.id for record in loaded.removed_pages)

    path2 = save_project(loaded)
    loaded2 = load_project(path2)
    assert [p.id for p in loaded2.pages] == original_ids
    assert loaded2.trash == []
    assert not loaded2.removed_pages


def test_restore_multiple_pages_preserves_order(analysis_bundle, tmp_path):
    project = copy_project(analysis_bundle, tmp_path, "trash_multi")
    original_ids = [page.id for page in project.pages]
    first_deleted = project.pages[1].id
    second_deleted = project.pages[3].id
    project.move_page_to_trash(first_deleted)
    project.move_page_to_trash(second_deleted)
    assert [page.id for page in project.pages] == [
        original_ids[0],
        original_ids[2],
        original_ids[4],
    ]
    assert len(project.trash) == 2

    # Neighbor anchors and page data survive project persistence.
    path = save_project(project)
    project = load_project(path)
    assert len(project.trash) == 2
    assert all(entry.next_page_id or entry.previous_page_id for entry in project.trash)

    # Restore in reverse order; the model inserts by anchors/original position.
    restored = project.restore_trash_entries([second_deleted, first_deleted])
    assert {page.id for page in restored} == {first_deleted, second_deleted}
    assert [page.id for page in project.pages] == original_ids
    assert project.trash == []
    assert not project.removed_pages

