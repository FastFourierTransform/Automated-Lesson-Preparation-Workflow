from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from lesson_prep.stages.video_to_slides.analysis.engine import AnalysisEngine
from lesson_prep.stages.video_to_slides.analysis.errors import AnalysisCancelled, AnalysisError
from lesson_prep.stages.video_to_slides.analysis.metrics import compare_frames, prepare_frame
from lesson_prep.core.geometry import Rect
from lesson_prep.stages.video_to_slides.models import AnalysisSettings, CameraMode, CameraRegion
from lesson_prep.core.media.probe import VideoError, probe_video
from lesson_prep.core.media.reader import VideoReader

CAMERA = Rect(0.746, 0.028, 0.231, 0.282)
CAMERA_2 = Rect(0.04, 0.60, 0.20, 0.28)


class TestMetrics:
    def test_camera_motion_is_excluded(self):
        slide = np.full((720, 1280, 3), 238, dtype=np.uint8)
        first = slide.copy()
        second = slide.copy()
        h, w = 720, 1280
        # Two independent camera regions change completely between frames
        # while the slide itself is identical.
        for camera in (CAMERA, CAMERA_2):
            x, y, cw, ch = camera.to_pixels(w, h)
            first[y : y + ch, x : x + cw] = 0
            second[y : y + ch, x : x + cw] = 255
        p1 = prepare_frame(first, Rect.full_frame(), [CAMERA, CAMERA_2], 384)
        p2 = prepare_frame(second, Rect.full_frame(), [CAMERA, CAMERA_2], 384)
        with_camera_excluded = compare_frames(p1.gray, p2.gray, p2.mask, 25)
        without_exclusion = compare_frames(
            p1.gray, p2.gray, np.full_like(p2.mask, 255), 25
        )
        assert with_camera_excluded.changed_ratio < 0.005
        assert with_camera_excluded.is_stable(AnalysisSettings())
        assert without_exclusion.changed_ratio > 0.04
        assert not without_exclusion.is_stable(AnalysisSettings())

    def test_pen_stroke_is_not_a_coarse_change(self, demo_video, demo_info):
        with VideoReader(demo_video, demo_info) as reader:
            _, f1 = reader.read_frame(12.55)
            _, f2 = reader.read_frame(13.2)
        p1 = prepare_frame(f1, Rect.full_frame(), CAMERA, 384)
        p2 = prepare_frame(f2, Rect.full_frame(), CAMERA, 384)
        diff = compare_frames(p1.gray, p2.gray, p2.mask, 25)
        assert not diff.is_coarse_change(AnalysisSettings())
        assert diff.changed_ratio < 0.08


class TestAnalysisEngine:
    def test_synthetic_lecture_pages(self, analysis_bundle):
        result = analysis_bundle["result"]
        pages = result.pages
        assert len(pages) == 5, [(p.selected_time, p.flags) for p in pages]
        times = [p.selected_time for p in pages]
        assert times == sorted(times)
        assert 3.5 <= times[0] <= 5.0
        assert 10.0 <= times[1] < 12.5
        assert 18.8 <= times[2] < 20.5
        assert 25.8 <= times[3] < 27.5
        assert 33.0 <= times[4] < 35.0
        # Pen-only changes and a small pop-in animation must not create pages.
        assert all(not (12.5 < t < 16.0) for t in times)
        assert all(not (29.9 < t < 30.5) for t in times)
        for page in pages:
            assert page.confidence >= 0.6
            assert page.alternatives
            assert len(page.alternatives) >= 2
            assert page.selected_raw_path
            raw = Path(analysis_bundle["assets_root"]) / page.selected_raw_path
            assert raw.is_file() and raw.stat().st_size > 0
            for alt in page.alternatives:
                assert (Path(analysis_bundle["assets_root"]) / alt.raw_path).is_file()
        stats = result.stats
        assert stats["used_ffmpeg"] is True
        assert stats["page_count"] == 5
        assert stats["scene_cut_count"] >= 1

    def test_cancellation(self, demo_video, demo_info, tmp_path):
        cancel = threading.Event()
        cancel.set()
        engine = AnalysisEngine(
            demo_video,
            demo_info,
            4.0,
            38.0,
            Rect.full_frame(),
            [CameraRegion(region=CAMERA, mode=CameraMode.MASK)],
            AnalysisSettings(),
            tmp_path / "assets",
            tmp_path / "assets" / "runs" / "cancel",
            cancel_event=cancel,
        )
        with pytest.raises(AnalysisCancelled):
            engine.analyze()

    def test_invalid_video(self, tmp_path):
        bad = tmp_path / "bad.mp4"
        bad.write_bytes(b"not a video")
        with pytest.raises(VideoError):
            probe_video(bad)
        missing = tmp_path / "missing.mp4"
        with pytest.raises(VideoError):
            probe_video(missing)

    def test_camera_covering_everything_rejected(self, demo_video, demo_info, tmp_path):
        engine = AnalysisEngine(
            demo_video,
            demo_info,
            4.0,
            38.0,
            Rect.full_frame(),
            [CameraRegion(region=Rect(0, 0, 1, 1), mode=CameraMode.MASK)],
            AnalysisSettings(),
            tmp_path / "assets",
            tmp_path / "assets" / "runs" / "bad",
        )
        with pytest.raises(AnalysisError):
            engine.analyze()

    def test_fallback_without_ffmpeg(self, demo_video, demo_info, tmp_path, monkeypatch):
        from lesson_prep.stages.video_to_slides.analysis.coarse import FfmpegSampler

        monkeypatch.setattr(FfmpegSampler, "available", staticmethod(lambda: False))
        engine = AnalysisEngine(
            demo_video,
            demo_info,
            4.0,
            20.0,
            Rect.full_frame(),
            [CameraRegion(region=CAMERA, mode=CameraMode.MASK)],
            AnalysisSettings(),
            tmp_path / "assets",
            tmp_path / "assets" / "runs" / "fallback",
        )
        result = engine.analyze()
        assert result.stats["used_ffmpeg"] is False
        assert result.pages
        assert any("FFmpeg" in warning for warning in result.warnings)

