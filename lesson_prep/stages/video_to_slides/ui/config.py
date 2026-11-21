"""Small persisted UI preferences (recent folders, last regions, settings)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSettings

from ....core.geometry import Rect
from ..export.service import ExportOptions
from ..models import AnalysisSettings, CameraRegion
from ....version import APP_ID


@dataclass
class AppPreferences:
    analysis_settings: AnalysisSettings = field(default_factory=AnalysisSettings)
    export_options: ExportOptions = field(default_factory=ExportOptions)
    last_video_dir: str = ""
    last_project_dir: str = ""
    last_export_dir: str = ""
    # Remember the most recent region selection so new videos can reuse it
    # instead of forcing the user to draw the same rectangles again.
    last_ppt_region: Rect = field(default_factory=Rect.full_frame)
    last_camera_regions: list[CameraRegion] = field(default_factory=list)

    @classmethod
    def load(cls) -> "AppPreferences":
        store = QSettings(APP_ID, APP_ID)
        settings = AnalysisSettings()
        raw_settings = store.value("analysis/settings", "")
        if raw_settings:
            try:
                settings = AnalysisSettings.from_dict(json.loads(str(raw_settings)))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        options = ExportOptions()
        raw_options = store.value("export/options", "")
        if raw_options:
            try:
                data = json.loads(str(raw_options))
                if isinstance(data, dict):
                    options = ExportOptions(
                        png=bool(data.get("png", True)),
                        pptx=bool(data.get("pptx", True)),
                        json_manifest=bool(data.get("json_manifest", True)),
                        copy_raw_candidates=bool(data.get("copy_raw_candidates", True)),
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        ppt_region = Rect.full_frame()
        raw_ppt_region = store.value("regions/ppt_region", "")
        if raw_ppt_region:
            try:
                value = json.loads(str(raw_ppt_region))
                candidate = Rect.from_dict(value, None)
                if candidate is not None and candidate.is_valid():
                    ppt_region = candidate
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        camera_regions: list[CameraRegion] = []
        raw_cameras = store.value("regions/camera_regions", "")
        if raw_cameras:
            try:
                value = json.loads(str(raw_cameras))
                if isinstance(value, list):
                    camera_regions = [
                        CameraRegion.from_dict(item)
                        for item in value
                        if isinstance(item, dict)
                    ]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return cls(
            analysis_settings=settings,
            export_options=options,
            last_video_dir=str(store.value("paths/video", "") or ""),
            last_project_dir=str(store.value("paths/project", "") or ""),
            last_export_dir=str(store.value("paths/export", "") or ""),
            last_ppt_region=ppt_region,
            last_camera_regions=camera_regions,
        )

    def save(self) -> None:
        store = QSettings(APP_ID, APP_ID)
        store.setValue("analysis/settings", json.dumps(self.analysis_settings.to_dict()))
        store.setValue(
            "export/options",
            json.dumps(
                {
                    "png": self.export_options.png,
                    "pptx": self.export_options.pptx,
                    "json_manifest": self.export_options.json_manifest,
                    "copy_raw_candidates": self.export_options.copy_raw_candidates,
                }
            ),
        )
        store.setValue("paths/video", self.last_video_dir)
        store.setValue("paths/project", self.last_project_dir)
        store.setValue("paths/export", self.last_export_dir)
        store.setValue(
            "regions/ppt_region",
            json.dumps(self.last_ppt_region.to_dict(), ensure_ascii=False),
        )
        store.setValue(
            "regions/camera_regions",
            json.dumps(
                [camera.to_dict() for camera in self.last_camera_regions],
                ensure_ascii=False,
            ),
        )
        store.sync()

    def remember_regions(
        self,
        ppt_region: Rect | None,
        camera_regions: list[CameraRegion] | None,
    ) -> None:
        """Persist the current PPT/camera selection for future imports."""
        self.last_ppt_region = (
            ppt_region.clamped() if ppt_region is not None else Rect.full_frame()
        )
        self.last_camera_regions = copy.deepcopy(list(camera_regions or []))
        self.save()

    def region_preset(self) -> tuple[Rect, list[CameraRegion]]:
        """Return a detached copy of the remembered PPT/camera selection."""
        ppt_region = self.last_ppt_region.clamped()
        if not ppt_region.is_valid():
            ppt_region = Rect.full_frame()
        return ppt_region, copy.deepcopy(self.last_camera_regions)


def existing_dir(path: str | Path | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    return str(candidate) if candidate.is_dir() else ""

