"""Four toggle chips coloured like the guide legend."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.core.models import GENERA
from app.ui.theme import genus_color


class GenusChips(QWidget):
    changed = Signal(set)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.buttons: dict[str, QPushButton] = {}
        for i, g in enumerate(GENERA, 1):
            b = QPushButton(g)
            b.setCheckable(True)
            b.setToolTip(f"Show {g} pets (key {i})")
            c = genus_color(g)
            b.setStyleSheet(
                f"QPushButton {{ border: 1px solid {c}; color: {c}; border-radius: 11px; padding: 3px 8px; "
                f"background: transparent; font-weight: 600; }}"
                f"QPushButton:checked {{ background: {c}; color: white; }}"
            )
            b.toggled.connect(lambda _=False: self.changed.emit(self.selected()))
            lay.addWidget(b)
            self.buttons[g] = b

    def selected(self) -> set[str]:
        return {g for g, b in self.buttons.items() if b.isChecked()}

    def toggle_index(self, i: int) -> None:
        g = GENERA[i]
        self.buttons[g].toggle()

    def clear(self) -> None:
        for b in self.buttons.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self.changed.emit(set())
