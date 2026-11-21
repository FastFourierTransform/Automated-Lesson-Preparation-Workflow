import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "test_artifacts"
DEMO_PATH = ARTIFACTS / "demo_lecture.mp4"


@pytest.fixture(scope="session")
def demo_video() -> Path:
    from scripts.generate_demo_video import create_demo_video

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not DEMO_PATH.is_file() or DEMO_PATH.stat().st_size < 1_000_000:
        create_demo_video(DEMO_PATH)
    return DEMO_PATH


@pytest.fixture(scope="session")
def demo_info(demo_video):
    from lesson_prep.core.media.probe import probe_video

    return probe_video(demo_video)


@pytest.fixture(scope="session")
def analysis_bundle(demo_video, demo_info, tmp_path_factory):
    from lesson_prep.stages.video_to_slides.analysis.engine import AnalysisEngine
    from lesson_prep.core.geometry import Rect
    from lesson_prep.stages.video_to_slides.models import AnalysisSettings, CameraMode, CameraRegion

    root = tmp_path_factory.mktemp("analysis")
    assets_root = root / "assets"
    run_dir = assets_root / "runs" / "run1"
    engine = AnalysisEngine(
        demo_video,
        demo_info,
        4.0,
        38.0,
        Rect.full_frame(),
        [
            CameraRegion(
                region=Rect(0.746, 0.028, 0.231, 0.282),
                mode=CameraMode.MASK,
            )
        ],
        AnalysisSettings(),
        assets_root,
        run_dir,
    )
    result = engine.analyze()
    return {
        "result": result,
        "assets_root": assets_root,
        "video_path": demo_video,
        "video_info": demo_info,
    }


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from lesson_prep.core.ui.theme import APP_STYLESHEET

    app = QApplication.instance() or QApplication([])
    for font_path in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ):
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    families = set(QFontDatabase.families())
    family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else app.font().family()
    app.setStyle("Fusion")
    app.setFont(QFont(family, 10))
    app.setStyleSheet(APP_STYLESHEET)
    yield app

