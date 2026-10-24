"""Route mode: one zone or loop at a time, unfinished stops only, big copyable monster names."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.core.filters import FilterSpec, area_label, group_by_area
from app.core.models import ZONES, Pet
from app.core.store import Store
from app.ui.theme import ACCENT, GOLD, MUTED, PANEL, StoreSignals, genus_color


@dataclass
class RouteStop:
    pet: Pet
    monster: str
    pocket: str | None
    group: str
    elite: bool = False
    level: int | None = None
    priority: bool = False


class RouteTab(QWidget):
    route_changed = Signal()

    def __init__(self, store: Store, signals: StoreSignals):
        super().__init__()
        self.store = store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)

        top = QHBoxLayout()
        top.addWidget(QLabel("Route:"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(380)
        for z in ZONES:
            if z != "Other":
                self.picker.addItem(f"{z} — all areas", ("zone", z))
        self.picker.insertSeparator(self.picker.count())
        for i, c in enumerate(store.circuits):
            lv = f"  (Lv {c.level_range})" if c.level_range else ""
            self.picker.addItem(f"{c.zone} loop — {c.name}{lv}", ("circuit", i))
        top.addWidget(self.picker)
        self.hide_elite = QCheckBox("Hide elite")
        self.show_done = QCheckBox("Show maxed")
        top.addWidget(self.hide_elite)
        top.addWidget(self.show_done)
        top.addStretch(1)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        top.addWidget(self.summary)
        lay.addLayout(top)
        self.note = QLabel()
        self.note.setProperty("muted", True)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        lay.addWidget(self.scroll, 1)

        self.picker.currentIndexChanged.connect(self.rebuild)
        self.hide_elite.toggled.connect(self.rebuild)
        self.show_done.toggled.connect(self.rebuild)
        # Rebuild on the next event-loop turn: the change may come from a checkbox on a card that a
        # rebuild deletes, and deleting it inside its own signal crashes.
        self._rebuild_queued = False
        signals.changed.connect(lambda _: self._queue_rebuild())
        self.rebuild()

    # -- data
    def stops(self, include_done: bool | None = None) -> list[RouteStop]:
        include_done = self.show_done.isChecked() if include_done is None else include_done
        kind, key = self.picker.currentData() or ("zone", "Altgard")
        out: list[RouteStop] = []
        if kind == "circuit":
            c = self.store.circuits[key]
            for st in c.stops:
                out.append(RouteStop(self.store.pets[st.pet_id], st.monster, st.pocket, c.name))
        else:
            spec = FilterSpec(zones={key}, hide_elite=self.hide_elite.isChecked(), source_types={"monster", "boss"})
            pets = [p for p in self.store.pets.values()]
            for zone, area, rows in group_by_area(pets, spec):
                for pet, s in rows:
                    out.append(RouteStop(pet, s.monster or "?", s.pin, area, s.elite, s.level, s.priority_addition))
        if not include_done:
            out = [s for s in out if not self.store.progress(s.pet.id).maxed]
        if self.hide_elite.isChecked():
            out = [s for s in out if not s.elite]
        return out

    def _queue_rebuild(self):
        if not self._rebuild_queued:
            self._rebuild_queued = True
            QTimer.singleShot(0, self._run_queued_rebuild)

    def _run_queued_rebuild(self):
        self._rebuild_queued = False
        self.rebuild()

    def title(self) -> str:
        return self.picker.currentText()

    # -- view
    def rebuild(self):
        kind, key = self.picker.currentData() or ("zone", "Altgard")
        if kind == "circuit":
            c = self.store.circuits[key]
            self.note.setText(f"{c.note or ''}  ·  guide page {c.page}")
        else:
            self.note.setText("Areas in the guide's numbered order. Pockets / pins match the PDF maps.")
        stops = self.stops()
        total = len(self.stops(include_done=True))
        self.summary.setText(f"{len([s for s in stops if not self.store.progress(s.pet.id).maxed])} unfinished "
                             f"of {total} stops")

        body = QWidget()
        body.setObjectName("root")
        v = QVBoxLayout(body)
        v.setSpacing(6)
        if not stops:
            done = QLabel("Everything on this route is maxed. 🎉")
            done.setStyleSheet(f"color: {ACCENT}; font-size: 14pt; padding: 20px;")
            v.addWidget(done)
        group = None
        for st in stops:
            if st.group != group:
                group = st.group
                h = QLabel(group.upper())
                h.setStyleSheet(f"color: {ACCENT}; font-weight: 700; letter-spacing: 1px; padding-top: 10px;")
                v.addWidget(h)
            v.addWidget(self._card(st))
        v.addStretch(1)
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(body)
        self.route_changed.emit()

    def _card(self, st: RouteStop) -> QFrame:
        pr = self.store.progress(st.pet.id)
        f = QFrame()
        f.setStyleSheet(f"QFrame#card {{ background: {PANEL}; border-radius: 8px; "
                        f"border-left: 4px solid {genus_color(st.pet.genus)}; }}")
        f.setObjectName("card")
        g = QGridLayout(f)
        g.setContentsMargins(12, 8, 12, 8)
        g.setHorizontalSpacing(12)
        badge = QLabel(st.pocket or "·")
        badge.setFixedWidth(30)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"color: {ACCENT}; font-size: 15pt; font-weight: 700;")
        g.addWidget(badge, 0, 0, 2, 1)
        mon = QLabel(st.monster)
        mon.setStyleSheet("font-size: 15pt; font-weight: 700;")
        mon.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(mon, 0, 1)
        tags = []
        if st.elite:
            tags.append(f"<span style='color:{GOLD}'>[ELITE]</span>")
        if st.level:
            tags.append(f"Lv {st.level}")
        if st.priority:
            tags.append(f"<span style='color:{GOLD}'>★ priority</span>")
        pet = QLabel(f"→ <b style='color:{genus_color(st.pet.genus)}'>{st.pet.name}</b>"
                     f" <span style='color:{MUTED}'>({st.pet.genus or 'genus ?'})</span> &nbsp; {' · '.join(tags)}")
        pet.setTextFormat(Qt.RichText)
        g.addWidget(pet, 1, 1)
        rem = QLabel(self.store.remaining_text(st.pet.id))
        rem.setStyleSheet(f"color: {MUTED};")
        g.addWidget(rem, 0, 2, Qt.AlignRight)
        btns = QHBoxLayout()
        copy = QPushButton("Copy name")
        copy.setToolTip("Copy the exact monster name")
        copy.clicked.connect(lambda _=False, m=st.monster: QGuiApplication.clipboard().setText(m))
        done = QCheckBox("Maxed")
        done.setChecked(pr.maxed)
        done.toggled.connect(lambda on, pid=st.pet.id: QTimer.singleShot(0, lambda: self.store.set_maxed(pid, on)))
        btns.addWidget(copy)
        btns.addWidget(done)
        g.addLayout(btns, 1, 2, Qt.AlignRight)
        g.setColumnStretch(1, 1)
        return f
