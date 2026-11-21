"""PNG, PPTX and JSON manifest export.

Exports always read from an existing reviewed project.  No video analysis is
run during export, so manual deletions, reordering, skips and alternative frame
selections can never be overwritten.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from ....core.media.utils import imwrite
from ....core.timecode import format_timecode
from ....version import APP_NAME
from ..constants import STAGE_ID, STAGE_NAME
from ..models import FLAG_LABELS, PageCandidate, SlidesProject
from ..project import resolve_asset
from .processor import SlideImageError, process_selected_image

ProgressCallback = Callable[[int, str], None]


class ExportError(RuntimeError):
    pass


class ExportCancelled(RuntimeError):
    pass


@dataclass
class ExportOptions:
    png: bool = True
    pptx: bool = True
    json_manifest: bool = True
    copy_raw_candidates: bool = True


@dataclass
class ExportedPage:
    page: PageCandidate
    png_path: Path | None
    raw_path: Path | None
    width: int
    height: int
    effective_camera_modes: list[str] = field(default_factory=list)

    @property
    def effective_camera_mode(self) -> str:
        if not self.effective_camera_modes:
            return "ignore"
        if len(self.effective_camera_modes) == 1:
            return self.effective_camera_modes[0]
        return "multiple"


@dataclass
class ExportResult:
    output_dir: Path
    png_files: list[Path] = field(default_factory=list)
    pptx_path: Path | None = None
    manifest_path: Path | None = None
    exported_pages: int = 0
    skipped_pages: int = 0
    warnings: list[str] = field(default_factory=list)


def safe_name(value: str, fallback: str = "lecture_slides") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().strip(".")
    name = re.sub(r"\s+", "_", name)
    return name[:80] or fallback


def make_export_directory(parent: str | Path, project_name: str) -> Path:
    parent = Path(parent)
    if not parent.exists() or not parent.is_dir():
        raise ExportError("导出目录不存在。")
    base = safe_name(project_name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = parent / f"{base}_slides_{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = parent / f"{base}_slides_{stamp}_{suffix}"
        suffix += 1
    try:
        candidate.mkdir(parents=True)
    except OSError as exc:
        raise ExportError(f"无法创建导出目录：{exc}") from exc
    return candidate


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ExportCancelled("导出已取消")


def _flag_labels(flags: list[str]) -> list[str]:
    return [FLAG_LABELS.get(flag, flag) for flag in flags]


def _validate_pages(project: SlidesProject) -> list[PageCandidate]:
    active_pages = project.active_pages()
    if not active_pages:
        raise ExportError("当前没有保留的页面可导出。请先保留至少一个候选页面。")
    missing: list[str] = []
    for index, page in enumerate(active_pages, start=1):
        alt = page.selected_alternative()
        if alt is None:
            missing.append(f"第 {index} 页（没有选定截图）")
            continue
        raw_path = resolve_asset(project, alt.raw_path)
        if raw_path is None or not raw_path.is_file():
            missing.append(f"第 {index} 页（文件缺失：{alt.raw_path}）")
    if missing:
        raise ExportError("以下页面无法导出：\n" + "\n".join(missing))
    return active_pages


def export_project(
    project: SlidesProject,
    output_parent: str | Path,
    options: ExportOptions | None = None,
    cancel_event: threading.Event | None = None,
    progress_cb: ProgressCallback | None = None,
) -> ExportResult:
    options = options or ExportOptions()
    if not (options.png or options.pptx or options.json_manifest):
        raise ExportError("请至少选择一种导出内容。")
    active_pages = _validate_pages(project)

    def report(value: int, message: str) -> None:
        if progress_cb:
            progress_cb(max(0, min(100, int(value))), message)

    report(1, "正在准备导出…")
    output_dir = make_export_directory(output_parent, project.name)
    png_dir = output_dir / "png"
    raw_dir = output_dir / "raw_candidates"
    # PPTX embeds PNG files.  If the user does not want a PNG sequence, use a
    # temporary staging folder and remove it after the deck is written.
    needs_png_files = options.png or options.pptx
    image_dir = png_dir if options.png else output_dir / ".pptx_images"
    temp_image_dir = None if options.png else image_dir
    if needs_png_files:
        image_dir.mkdir(parents=True, exist_ok=True)
    if options.copy_raw_candidates:
        raw_dir.mkdir(parents=True, exist_ok=True)

    exported: list[ExportedPage] = []
    warnings: list[str] = []
    total = len(active_pages)
    try:
        for index, page in enumerate(active_pages, start=1):
            _check_cancel(cancel_event)
            try:
                processed = process_selected_image(project, page, apply_camera=True)
            except SlideImageError as exc:
                raise ExportError(str(exc)) from exc
            image = processed.image
            height, width = image.shape[:2]
            png_path: Path | None = None
            if needs_png_files:
                png_path = image_dir / f"slide_{index:03d}.png"
                if not imwrite(png_path, image):
                    raise ExportError(f"无法写入 PNG：{png_path}")
            raw_target = None
            if options.copy_raw_candidates:
                raw_target = raw_dir / (
                    f"slide_{index:03d}_raw{processed.raw_path.suffix or '.jpg'}"
                )
                try:
                    shutil.copy2(processed.raw_path, raw_target)
                except OSError as exc:
                    warnings.append(f"原始候选图复制失败（第 {index} 页）：{exc}")
                    raw_target = None
            exported.append(
                ExportedPage(
                    page=page,
                    png_path=png_path,
                    raw_path=raw_target,
                    width=width,
                    height=height,
                    effective_camera_modes=list(processed.effective_camera_modes),
                )
            )
            report(5 + int(65 * index / total), f"正在导出页面 {index}/{total}")

        _check_cancel(cancel_event)
        pptx_path = None
        if options.pptx:
            report(75, "正在生成 PPTX…")
            pptx_path = output_dir / "lecture_slides.pptx"
            _write_pptx(pptx_path, exported, progress_cb=report)

        _check_cancel(cancel_event)
        manifest_path = None
        if options.json_manifest:
            report(92, "正在生成 JSON 清单…")
            manifest_path = output_dir / "manifest.json"
            _write_manifest(
                manifest_path,
                project,
                output_dir,
                exported,
                options,
                pptx_path,
            )
        report(100, "导出完成")
        return ExportResult(
            output_dir=output_dir,
            png_files=(
                [item.png_path for item in exported if item.png_path is not None]
                if options.png
                else []
            ),
            pptx_path=pptx_path,
            manifest_path=manifest_path,
            exported_pages=len(exported),
            skipped_pages=len(project.skipped_pages()),
            warnings=warnings,
        )
    except ExportCancelled:
        raise
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"导出失败：{exc}") from exc
    finally:
        if temp_image_dir is not None:
            shutil.rmtree(temp_image_dir, ignore_errors=True)


def _write_pptx(
    path: Path,
    pages: list[ExportedPage],
    progress_cb: Callable[[int, str], None] | None = None,
) -> None:
    try:
        from pptx import Presentation
        from pptx.util import Emu
    except ImportError as exc:
        raise ExportError("未安装 python-pptx，无法导出 PPTX。") from exc
    if not pages or any(item.png_path is None for item in pages):
        raise ExportError("没有可用于 PPTX 的页面图片。")
    try:
        with Image.open(pages[0].png_path) as first:
            first_w, first_h = first.size
        if first_w <= 0 or first_h <= 0:
            raise ExportError("导出图片尺寸无效。")
        aspect = first_w / first_h
        # The slide page follows the actual slide image aspect ratio.  Images
        # that share this ratio fill the whole page without stretching.
        if aspect >= 1.0:
            slide_width_in = 13.333333
            slide_height_in = slide_width_in / aspect
        else:
            slide_height_in = 13.333333
            slide_width_in = slide_height_in * aspect
        presentation = Presentation()
        presentation.slide_width = Emu(int(round(slide_width_in * 914400)))
        presentation.slide_height = Emu(int(round(slide_height_in * 914400)))
        blank_layout = presentation.slide_layouts[6]
        step = max(1, len(pages) // 10)
        for index, item in enumerate(pages, start=1):
            with Image.open(item.png_path) as img:
                img_w, img_h = img.size
            slide = presentation.slides.add_slide(blank_layout)
            scale = min(
                presentation.slide_width / img_w,
                presentation.slide_height / img_h,
            )
            draw_w = int(round(img_w * scale))
            draw_h = int(round(img_h * scale))
            left = int(round((presentation.slide_width - draw_w) / 2))
            top = int(round((presentation.slide_height - draw_h) / 2))
            slide.shapes.add_picture(
                str(item.png_path),
                left,
                top,
                width=draw_w,
                height=draw_h,
            )
            if progress_cb and index % step == 0:
                progress_cb(
                    75 + int(12 * index / max(1, len(pages))),
                    f"正在写入 PPTX {index}/{len(pages)}",
                )
        presentation.save(str(path))
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"生成 PPTX 失败：{exc}") from exc


def _write_manifest(
    path: Path,
    project: SlidesProject,
    output_dir: Path,
    exported: list[ExportedPage],
    options: ExportOptions,
    pptx_path: Path | None,
) -> None:
    export_index_by_id = {
        item.page.id: index for index, item in enumerate(exported, start=1)
    }
    item_by_id = {item.page.id: item for item in exported}
    slides = []
    for page in project.pages:
        item = item_by_id.get(page.id)
        included = item is not None
        export_index = export_index_by_id.get(page.id)
        selected = page.selected_alternative()
        slides.append(
            {
                "export_page_number": export_index,
                "page_id": page.id,
                "detected_page_number": page.detected_index + 1,
                "state": "included" if included else "skipped",
                "kept": bool(page.kept),
                "selected_time_sec": round(float(page.selected_time), 3),
                "selected_timecode": format_timecode(page.selected_time, milliseconds=True),
                "video_index": int(page.video_index),
                "source_video": (
                    project.video_sources()[page.video_index].path
                    if 0 <= page.video_index < len(project.video_sources())
                    else None
                ),
                "interval_start_sec": round(float(page.interval_start), 3),
                "interval_end_sec": round(float(page.interval_end), 3),
                "confidence": round(float(page.confidence), 4),
                "needs_review": bool(page.needs_review),
                "flags": list(page.flags),
                "flag_labels": _flag_labels(page.flags),
                "sources": list(page.sources),
                "manually_modified": bool(page.manually_modified),
                "review_note": page.review_note,
                "image_png": (
                    item.png_path.relative_to(output_dir).as_posix()
                    if item and item.png_path is not None and options.png
                    else None
                ),
                "raw_candidate": (
                    item.raw_path.relative_to(output_dir).as_posix()
                    if item and item.raw_path is not None and options.copy_raw_candidates
                    else None
                ),
                "project_raw_candidate": selected.raw_path if selected else None,
                "camera_effective_mode": item.effective_camera_mode if item else None,
                "camera_effective_modes": (
                    item.effective_camera_modes if item else None
                ),
                "alternatives": [
                    {
                        "time_sec": round(alt.time_sec, 3),
                        "timecode": format_timecode(alt.time_sec, milliseconds=True),
                        "quality": round(alt.quality, 4),
                        "stability": round(alt.stability, 4),
                        "sharpness": round(alt.sharpness, 4),
                        "flags": list(alt.flags),
                        "project_raw_path": alt.raw_path,
                    }
                    for alt in page.alternatives
                ],
                "metrics": page.metrics,
            }
        )
    payload = {
        "tool": APP_NAME,
        "stage": STAGE_ID,
        "stage_name": STAGE_NAME,
        "schema_version": 1,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_video": project.video_info.path,
        "source_video_info": project.video_info.to_dict(),
        "source_videos": [info.to_dict() for info in project.video_sources()],
        "video_count": len(project.video_sources()),
        "project_file": str(project.project_path) if project.project_path else None,
        "project_name": project.name,
        "content_range": {
            "start_sec": round(float(project.content_start), 3),
            "end_sec": round(float(project.content_end), 3),
            "start_timecode": format_timecode(project.content_start, milliseconds=True),
            "end_timecode": format_timecode(project.content_end, milliseconds=True),
        },
        "ppt_region_normalized": project.ppt_region.to_dict(),
        "analysis_region_normalized": (
            project.analysis_region.to_dict() if project.analysis_region else None
        ),
        "camera_region_normalized": (
            project.configured_camera_regions()[0].region.to_dict()
            if len(project.configured_camera_regions()) == 1
            and project.configured_camera_regions()[0].region is not None
            else None
        ),
        "camera_mode": (
            project.configured_camera_regions()[0].mode.value
            if len(project.configured_camera_regions()) == 1
            else (
                "multiple"
                if len(project.configured_camera_regions()) > 1
                else "ignore"
            )
        ),
        "camera_regions": [
            {
                "index": index,
                "id": camera.id,
                "configured": camera.is_configured(),
                "region_normalized": (
                    camera.region.to_dict() if camera.region is not None else None
                ),
                "mode": camera.mode.value,
            }
            for index, camera in enumerate(project.camera_regions, start=1)
        ],
        "camera_effective_mode_per_page": {
            str(index): item.effective_camera_mode for index, item in enumerate(exported, start=1)
        },
        "camera_effective_modes_per_page": {
            str(index): item.effective_camera_modes
            for index, item in enumerate(exported, start=1)
        },
        "analysis_settings": project.settings.to_dict(),
        "analysis_stats": project.analysis_stats,
        "analysis_warnings": list(project.warnings),
        "export": {
            "png_directory": "png" if options.png else None,
            "pptx": pptx_path.name if pptx_path else None,
            "raw_candidates_directory": "raw_candidates" if options.copy_raw_candidates else None,
            "included_pages": len(exported),
            "skipped_pages": len(project.skipped_pages()),
        },
        "slides": slides,
        "manual_changes": [change.to_dict() for change in project.manual_history],
        "removed_pages": [record.to_dict() for record in project.removed_pages],
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"生成 JSON 清单失败：{exc}") from exc


