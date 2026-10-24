"""Colours, stylesheet and small painted icons."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from app.core.models import GENUS_COLORS

UNKNOWN_COLOR = "#6b7686"
BG = "#0d1525"
PANEL = "#142039"
PANEL_2 = "#1b2a47"
TEXT = "#f1f4f8"
MUTED = "#9eafc8"
ACCENT = "#ffb36a"
GOLD = "#ffdf85"

STYLESHEET = f"""
* {{ font-family: "Segoe UI", sans-serif; font-size: 10pt; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; color: {TEXT}; }}
QTextEdit {{ background: {PANEL}; border: none; border-radius: 6px; font-family: Consolas, monospace; }}
QWidget {{ color: {TEXT}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[heading="true"] {{ color: {ACCENT}; font-weight: 600; font-size: 9pt; letter-spacing: 1px; }}
QFrame#panel, QScrollArea#panel > QWidget > QWidget {{ background: {PANEL}; border-radius: 8px; }}
QScrollArea {{ border: none; background: transparent; }}
QLineEdit, QSpinBox, QComboBox {{
    background: {PANEL_2}; border: 1px solid #2c3d60; border-radius: 5px; padding: 4px 6px;
    selection-background-color: #2f4f86;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; selection-background-color: #2f4f86; }}
QPushButton {{
    background: {PANEL_2}; border: 1px solid #2c3d60; border-radius: 5px; padding: 5px 10px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: #2a3c63; border-color: {ACCENT}; }}
QCheckBox::indicator, QTreeView::indicator {{
    width: 13px; height: 13px; border: 1px solid #5a6f96; border-radius: 3px; background: #0f1a2e;
}}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
    image: url(CHECK_SVG);
}}
QRadioButton::indicator {{ width: 12px; height: 12px; border: 1px solid #5a6f96; border-radius: 7px; background: #0f1a2e; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox:disabled {{ color: #56637a; }}
QTreeWidget, QListWidget {{
    background: {PANEL}; border: none; border-radius: 8px; alternate-background-color: #172543;
    outline: 0;
}}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: #2a3c63; color: {TEXT}; }}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none; padding: 6px; font-weight: 600;
}}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 8px 18px; border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QScrollArea > QWidget > QWidget#sidebar {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #2c3d60; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #3b5180; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea {{ background: transparent; }}
QAbstractScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QCheckBox, QRadioButton {{ spacing: 6px; }}
QStatusBar {{ color: {MUTED}; }}
QMenu {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid #2c3d60; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; color: {TEXT}; }}
QMenu::item:selected {{ background: #2f4f86; }}
QMenu::item:disabled {{ color: #56637a; }}
QMenu::separator {{ height: 1px; background: #2c3d60; margin: 4px 8px; }}
QMenu::indicator {{ width: 13px; height: 13px; left: 4px; }}
QMessageBox {{ background: {BG}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QPushButton#autoscan {{ font-weight: 700; padding: 5px 14px; }}
QPushButton#autoscan:checked {{ background: #1f5f3a; border-color: #3fbf6a; color: white; }}
QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:hover {{ background: #2c3d60; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid #2c3d60; }}
"""

from app.paths import ASSETS  # noqa: E402

STYLESHEET = STYLESHEET.replace("CHECK_SVG", (ASSETS / "check.svg").as_posix())


def genus_color(genus: str | None) -> str:
    return GENUS_COLORS.get(genus or "", UNKNOWN_COLOR)


@lru_cache(maxsize=32)
def dot_icon(genus: str | None, size: int = 12, hollow: bool = False) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(genus_color(genus))
    if hollow:
        p.setPen(c)
        p.setBrush(Qt.NoBrush)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(c)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)


class StoreSignals(QObject):
    """Qt bridge for Store change notifications."""
    changed = Signal(object)  # set[str] of pet ids

    def __init__(self, store):
        super().__init__()
        store.subscribe(lambda ids: self.changed.emit(set(ids)))
