"""Application entry point for the lesson-preparation workflow.

The launcher is stage-agnostic: it selects a stage, creates its window and
forwards an optional file path.  Stage-specific behaviour stays inside
``lesson_prep.stages.<stage_id>``.
"""
from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTimer, QTranslator
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from .core.ui.icons import make_app_icon
from .core.ui.theme import APP_STYLESHEET
from .stages import DEFAULT_STAGE_ID, STAGES, get_stage, stage_for_path
from .version import APP_ID, APP_NAME


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lesson-prep",
        description="自动化备课工作流：视频转 PPT、视频转讲义、PPT 转讲义等阶段。",
    )
    parser.add_argument("path", nargs="?", help="启动后打开的视频或项目文件")
    parser.add_argument("--stage", metavar="ID", help="指定要启动的阶段 ID")
    parser.add_argument(
        "--list-stages",
        action="store_true",
        help="列出所有阶段及其状态后退出",
    )
    return parser


def _stage_table() -> str:
    lines = ["备课工作流阶段：", ""]
    for stage in STAGES:
        status = "已实现" if stage.available else "规划中"
        lines.append(f"  {stage.info.id:<18} {stage.info.name}  [{status}]")
        lines.append(f"      输入：{stage.info.inputs}")
        lines.append(f"      输出：{stage.info.outputs}")
        lines.append(f"      说明：{stage.info.summary}")
        lines.append("")
    lines.append("新增阶段：在 lesson_prep/stages/<id>/ 中导出 STAGE，并注册到 stages/__init__.py。")
    return "\n".join(lines)


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _register_fonts() -> str:
    """Register common CJK fonts explicitly.

    Qt's offscreen backend (used by tests) does not always enumerate Windows
    fonts.  Loading the normal system font explicitly also makes rendering
    deterministic on systems where font fallback is incomplete.
    """
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for path in candidates:
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    families = set(QFontDatabase.families())
    for preferred in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "PingFang SC",
        "Segoe UI",
    ):
        if preferred in families:
            return preferred
    return QApplication.font().family()


def _resolve_stage(args: argparse.Namespace):
    path = Path(args.path) if args.path else None
    if args.stage:
        stage = get_stage(args.stage)
        if stage is None:
            raise SystemExit(
                f"未知阶段：{args.stage}\n\n{_stage_table()}"
            )
        return stage, path
    if path is not None:
        stage = stage_for_path(path)
        if stage is not None:
            return stage, path
    return get_stage(DEFAULT_STAGE_ID), path


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv if argv is None else argv)
    args, qt_args = _build_parser().parse_known_args(args_list[1:])
    if args.list_stages:
        print(_stage_table())
        return 0

    stage, path = _resolve_stage(args)
    if stage is None or not stage.available:
        name = stage.info.name if stage is not None else args.stage
        print(
            f"阶段“{name}”尚未实现。运行 `python run.py --list-stages` 查看全部阶段。",
            file=sys.stderr,
        )
        return 2

    _set_windows_app_id()
    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    program = args_list[0] if args_list else "lesson-prep"
    app = QApplication([program, *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setStyle("Fusion")
    translator = QTranslator(app)
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations):
        app.installTranslator(translator)
    app._qt_translator = translator  # keep a strong reference
    family = _register_fonts()
    app.setFont(QFont(family, 10))
    app.setStyleSheet(APP_STYLESHEET)

    window = stage.create_window()
    window.setWindowIcon(QIcon(make_app_icon()))
    store = QSettings(APP_ID, APP_ID)
    geometry = store.value("window/geometry")
    if geometry:
        try:
            window.restoreGeometry(geometry)
        except Exception:
            pass

    def _save_window_state() -> None:
        try:
            store.setValue("window/geometry", window.saveGeometry())
            store.sync()
        except Exception:
            pass

    app.aboutToQuit.connect(_save_window_state)
    window.show()

    if path is not None and path.is_file():
        QTimer.singleShot(200, lambda: _open_path(stage, window, path))
    return app.exec()


def _open_path(stage, window, path: Path) -> None:
    if stage.open_path is None:
        return
    try:
        stage.open_path(window, path)
    except Exception as exc:
        # The stage shows its own detailed errors; this is a last-resort guard
        # for launcher-level failures.
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(window, "无法打开文件", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
