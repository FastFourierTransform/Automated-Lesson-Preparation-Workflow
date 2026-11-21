"""QThread workers for analysis and export.

The analysis worker owns a staging directory.  It is removed on cancel/failure
so a previous reviewed project is never replaced by a partial result.
"""
from __future__ import annotations

import copy
import shutil
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ....core.geometry import Rect
from ....core.media.models import VideoInfo
from ..analysis.engine import AnalysisEngine
from ..analysis.errors import AnalysisCancelled, AnalysisError
from ..export.service import ExportCancelled, ExportError, ExportOptions, export_project
from ..models import AnalysisSettings, CameraRegion, SlidesProject


class AnalysisWorker(QThread):
    progress = Signal(int, str)
    status = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        video_path: str,
        video_info: VideoInfo,
        content_start: float,
        content_end: float,
        ppt_region: Rect,
        camera_regions: list[CameraRegion] | None,
        settings: AnalysisSettings,
        assets_root: str | Path,
        run_dir: str | Path,
        parent=None,
        video_sources: list[VideoInfo] | None = None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.video_info = video_info
        self.video_sources = copy.deepcopy(video_sources or [])
        self.content_start = content_start
        self.content_end = content_end
        self.ppt_region = ppt_region
        self.camera_regions = copy.deepcopy(camera_regions or [])
        self.settings = settings
        self.assets_root = Path(assets_root)
        self.run_dir = Path(run_dir)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            engine = AnalysisEngine(
                self.video_path,
                self.video_info,
                self.content_start,
                self.content_end,
                self.ppt_region,
                self.camera_regions,
                self.settings,
                self.assets_root,
                self.run_dir,
                cancel_event=self._cancel_event,
                progress_cb=lambda value, message: self.progress.emit(value, message),
                status_cb=lambda message: self.status.emit(message),
                video_sources=self.video_sources or None,
            )
            result = engine.analyze()
            self.completed.emit(result)
        except AnalysisCancelled:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.cancelled.emit()
        except AnalysisError as exc:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.failed.emit(str(exc))
        except Exception as exc:  # unexpected bug: keep the traceback in logs
            traceback.print_exc()
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.failed.emit(f"分析发生未预期错误：{exc}")


class ExportWorker(QThread):
    progress = Signal(int, str)
    status = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        project: SlidesProject,
        output_parent: str | Path,
        options: ExportOptions,
        parent=None,
    ):
        super().__init__(parent)
        self.project = project
        self.output_parent = str(output_parent)
        self.options = options
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result = export_project(
                self.project,
                self.output_parent,
                self.options,
                cancel_event=self._cancel_event,
                progress_cb=lambda value, message: self.progress.emit(value, message),
            )
            self.completed.emit(result)
        except ExportCancelled:
            self.cancelled.emit()
        except ExportError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(f"导出发生未预期错误：{exc}")


