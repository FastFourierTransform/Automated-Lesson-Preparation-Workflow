"""Application-wide Qt stylesheet."""
from __future__ import annotations

APP_STYLESHEET = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC",
                 "WenQuanYi Micro Hei", "PingFang SC", "Segoe UI", sans-serif;
}
QMainWindow, QDialog {
    background: #eef2f7;
    color: #0f172a;
}
QToolTip {
    background: #111827;
    color: #f9fafb;
    border: none;
    padding: 5px 8px;
}
QMenuBar {
    background: #ffffff;
    border-bottom: 1px solid #dbe3ee;
    padding: 2px 6px;
}
QMenuBar::item {
    padding: 5px 10px;
    background: transparent;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background: #e0e7ff;
}
QMenu {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    padding: 5px;
}
QMenu::item {
    padding: 6px 28px 6px 18px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #e0e7ff;
    color: #1e3a8a;
}
QToolBar {
    background: #ffffff;
    border-bottom: 1px solid #dbe3ee;
    padding: 5px 8px;
    spacing: 5px;
}
QToolBar::separator {
    background: #dbe3ee;
    width: 1px;
    margin: 4px 6px;
}
QToolButton {
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 8px;
    background: transparent;
    color: #334155;
}
QToolButton:hover {
    background: #f1f5f9;
    border-color: #e2e8f0;
}
QToolButton:pressed {
    background: #e2e8f0;
}
QToolButton#reviewTool {
    border: 1px solid #d7dfe9;
    background: #ffffff;
    padding: 4px 9px;
    color: #334155;
    font-size: 9pt;
}
QToolButton#reviewTool:hover {
    background: #eff6ff;
    border-color: #93c5fd;
}
QToolButton#reviewTool:disabled {
    color: #9ca3af;
    background: #f8fafc;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 12px;
    color: #1f2937;
}
QPushButton:hover {
    background: #f8fafc;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background: #e2e8f0;
}
QPushButton:disabled {
    background: #f1f5f9;
    color: #94a3b8;
    border-color: #e2e8f0;
}
QPushButton#primary {
    background: #1d4ed8;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    font-weight: 600;
    padding: 9px 16px;
}
QPushButton#primary:hover {
    background: #1e40af;
}
QPushButton#primary:disabled {
    background: #93a9d8;
    color: #eef2ff;
}
QPushButton#danger {
    background: #fff1f2;
    color: #b91c1c;
    border: 1px solid #fecdd3;
}
QPushButton#danger:hover {
    background: #ffe4e6;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dbe3ee;
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
    color: #334155;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #334155;
}
QGroupBox QLabel {
    font-weight: 400;
    color: #374151;
}
QLabel#sectionTitle {
    font-size: 13pt;
    font-weight: 700;
    color: #0f172a;
}
QLabel#subTitle {
    font-weight: 600;
    color: #334155;
}
QLabel#mutedLabel {
    color: #64748b;
    font-size: 9pt;
    font-weight: 400;
}
QLabel#pageTitle {
    font-size: 10.5pt;
    font-weight: 600;
    color: #0f172a;
}
QLabel#emptyState {
    color: #64748b;
    font-size: 10.5pt;
    background: #f8fafc;
    border: 1px dashed #cbd5e1;
    border-radius: 10px;
    padding: 30px;
}
QLabel#videoInfoValue {
    color: #1f2937;
}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 7px;
    min-height: 20px;
    color: #111827;
    selection-background-color: #bfdbfe;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #dbeafe;
    outline: none;
}
QScrollArea {
    border: none;
    background: transparent;
}
QWidget#sidePanel {
    background: transparent;
}
QFrame#previewCard {
    background: #ffffff;
    border: 1px solid #dbe3ee;
    border-radius: 10px;
}
QWidget#detailsPanel {
    background: #f8fafc;
    border: 1px solid #dbe3ee;
    border-radius: 9px;
}
QListWidget#pageGrid {
    background: #f6f8fb;
    border: 1px solid #dbe3ee;
    border-radius: 9px;
    padding: 5px;
    outline: none;
}
QListWidget#pageGrid::item {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 6px;
    margin: 4px;
    color: #334155;
}
QListWidget#pageGrid::item:selected {
    background: #eff6ff;
    border: 2px solid #2563eb;
    color: #1e3a8a;
}
QListWidget#altGrid {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 7px;
    outline: none;
}
QListWidget#altGrid::item {
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 2px;
    color: #475569;
    font-size: 8pt;
}
QListWidget#altGrid::item:selected {
    border: 2px solid #2563eb;
    background: #eff6ff;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #cbd5e1;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #2563eb;
    width: 13px;
    margin: -5px 0;
    border-radius: 7px;
}
QProgressBar {
    background: #e2e8f0;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 4px;
}
QSplitter::handle {
    background: #dbe3ee;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 3px;
}
QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 4px;
    min-height: 25px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    border-radius: 4px;
    min-width: 25px;
}
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #dbe3ee;
    color: #475569;
}
QCheckBox {
    spacing: 7px;
    color: #334155;
}
QTabWidget::pane {
    border: 1px solid #dbe3ee;
    background: #ffffff;
    border-radius: 6px;
}
QTabBar::tab {
    background: #e2e8f0;
    color: #475569;
    padding: 6px 14px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1e3a8a;
    font-weight: 600;
}
QToolButton#playButton {
    background: #1d4ed8;
    border: none;
    border-radius: 16px;
    padding: 6px;
}
QToolButton#playButton:hover {
    background: #1e40af;
}
"""
