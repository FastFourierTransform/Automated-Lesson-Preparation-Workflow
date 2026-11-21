"""Small persisted UI preferences (recent folders, last analysis settings)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSettings

from ..export.service import ExportOptions
from ..models import AnalysisSettings
from ....version import APP_ID


@dataclass
class AppPreferences:
    analysis_settings: AnalysisSettings = field(default_factory=AnalysisSettings)
    export_options: ExportOptions = field(default_factory=ExportOptions)
    last_video_dir: str = ""
    last_project_dir: str = ""
    last_export_dir: str = ""

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
        return cls(
            analysis_settings=settings,
            export_options=options,
            last_video_dir=str(store.value("paths/video", "") or ""),
            last_project_dir=str(store.value("paths/project", "") or ""),
            last_export_dir=str(store.value("paths/export", "") or ""),
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
        store.sync()


def existing_dir(path: str | Path | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    return str(candidate) if candidate.is_dir() else ""

