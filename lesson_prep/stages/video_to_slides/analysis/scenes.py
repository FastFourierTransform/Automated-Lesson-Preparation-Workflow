"""Optional PySceneDetect candidate generation on the coarse sample stream.

In this project PySceneDetect is used as a *candidate source*, not as page
ground truth.  Its ContentDetector runs on the same downscaled, camera-masked
PPT crops that the cheap scan already produced, so scene detection adds no
extra video decode pass.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..models import AnalysisSettings


@dataclass
class SceneHint:
    time_sec: float


class SceneDetectorAdapter:
    def __init__(self, settings: AnalysisSettings, coarse_fps: float):
        self.settings = settings
        self.coarse_fps = max(0.5, coarse_fps)
        self.detector = None
        self.error: str | None = None
        self.enabled = bool(settings.use_pyscenedetect)
        if not self.enabled:
            return
        try:
            from scenedetect.detectors import ContentDetector

            min_scene_frames = max(1, int(round(settings.pyscenedetect_min_scene_sec * self.coarse_fps)))
            self.detector = ContentDetector(
                threshold=settings.pyscenedetect_threshold,
                min_scene_len=min_scene_frames,
                luma_only=False,
            )
        except Exception as exc:  # pragma: no cover - optional dependency
            self.error = f"PySceneDetect 不可用：{exc}"
            self.enabled = False

    def feed(self, time_sec: float, color_frame: np.ndarray) -> list[SceneHint]:
        if not self.enabled or self.detector is None:
            return []
        try:
            from scenedetect import FrameTimecode

            timecode = FrameTimecode(timecode=float(time_sec), fps=self.coarse_fps)
            cuts = self.detector.process_frame(timecode, color_frame)
            hints: list[SceneHint] = []
            for cut in cuts or []:
                try:
                    seconds = getattr(cut, "seconds", None)
                    if seconds is None:
                        seconds = cut.get_seconds()
                    hints.append(SceneHint(float(seconds)))
                except Exception:
                    continue
            return hints
        except Exception as exc:
            self.error = f"PySceneDetect 处理失败，后续仅使用内置检测：{exc}"
            self.enabled = False
            self.detector = None
            return []

    def finish(self) -> None:
        self.detector = None

