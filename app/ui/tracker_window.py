"""Main tracker window: filter sidebar, pet list, detail panel, route tab."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton, QRadioButton, QScrollArea,
    QSpinBox, QSplitter, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QAbstractSpinBox, QMenu,
)

from app.core.filters import STATUS_CHOICES, FilterSpec, area_label, best_source, filter_pets, group_by_area
from app.core.models import GENERA, SOURCE_TYPES, ZONES, Pet
from app.core.store import Store
from app.ui.theme import ACCENT, GOLD, MUTED, StoreSignals, dot_icon, genus_color
from app.ui.widgets.genus_chips import GenusChips
from app.ui.widgets.progress_delegate import COLOR_ROLE, FRACTION_ROLE, LABEL_ROLE, ProgressDelegate

PET_ROLE = Qt.UserRole
SOURCE_TYPE_LABELS = {"monster": "Monster", "chest_merchant": "Chest / merchant", "boss": "Boss", "dungeon": "Dungeon"}
COL_MAX, COL_PET, COL_PROG, COL_SRC = range(4)


def heading(text: str) -> QLabel:
    l = QLabel(text.upper())
    l.setProperty("heading", True)
    return l


def muted(text: str = "") -> QLabel:
    l = QLabel(text)
    l.setProperty("muted", True)
    l.setWordWrap(True)
    return l


def panel() -> QFrame:
    f = QFrame()
    f.setObjectName("panel")
    return f


class PetTree(QTreeWidget):
    space_pressed = Signal()
    genus_key = Signal(int)
    slash_pressed = Signal()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space:
            self.space_pressed.emit()
            return
        if Qt.Key_1 <= k <= Qt.Key_4 and not e.modifiers():
            self.genus_key.emit(k - Qt.Key_1)
            return
        if k == Qt.Key_Slash:
            self.slash_pressed.emit()
            return
        super().keyPressEvent(e)


# ------------------------------------------------------------------------- filters sidebar


class FilterSidebar(QWidget):
    changed = Signal()

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.setObjectName("sidebar")
        self.setFixedWidth(250)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search pet or monster  ( / )")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.changed)
        lay.addWidget(self.search)

        lay.addWidget(heading("Genus"))
        self.chips = GenusChips()
        self.chips.changed.connect(lambda _: self.changed.emit())
        lay.addWidget(self.chips)
        self.unknown_genus = QCheckBox("Unknown genus")
        self.unknown_genus.toggled.connect(self.changed)
        self.needs_review = QCheckBox("Genus needs review")
        self.needs_review.setToolTip("Genus unknown, or only guessed from the p3/p8 checkbox colour")
        self.needs_review.toggled.connect(self.changed)
        row = QHBoxLayout()
        row.addWidget(self.unknown_genus)
        row.addWidget(self.needs_review)
        lay.addLayout(row)

        lay.addWidget(heading("Status"))
        self.status = QComboBox()
        for k, v in STATUS_CHOICES.items():
            self.status.addItem(v, k)
        self.status.setCurrentIndex(list(STATUS_CHOICES).index("not_maxed"))
        self.status.currentIndexChanged.connect(self.changed)
        lay.addWidget(self.status)

        lay.addWidget(heading("Zone"))
        self.zone_boxes: dict[str, QCheckBox] = {}
        grid = QVBoxLayout()
        grid.setSpacing(2)
        for z in ZONES:
            cb = QCheckBox(z if z != "Other" else "Other (chests, bosses)")
            cb.toggled.connect(self.changed)
            self.zone_boxes[z] = cb
            grid.addWidget(cb)
        lay.addLayout(grid)

        lay.addWidget(heading("Source type"))
        self.type_boxes: dict[str, QCheckBox] = {}
        for t in SOURCE_TYPES:
            cb = QCheckBox(SOURCE_TYPE_LABELS[t])
            cb.toggled.connect(self.changed)
            self.type_boxes[t] = cb
            lay.addWidget(cb)

        lay.addWidget(heading("Options"))
        self.priority = QCheckBox("Priority additions only ( * )")
        self.priority.toggled.connect(self.changed)
        self.hide_elite = QCheckBox("Hide elite sources")
        self.hide_elite.toggled.connect(self.changed)
        lay.addWidget(self.priority)
        lay.addWidget(self.hide_elite)

        lay.addWidget(heading("Group by"))
        self.group_pet = QRadioButton("Pet")
        self.group_zone = QRadioButton("Zone → Area")
        self.group_pet.setChecked(True)
        g = QButtonGroup(self)
        g.addButton(self.group_pet)
        g.addButton(self.group_zone)
        self.group_pet.toggled.connect(self.changed)
        row = QHBoxLayout()
        row.addWidget(self.group_pet)
        row.addWidget(self.group_zone)
        lay.addLayout(row)

        clear = QPushButton("Clear filters")
        clear.clicked.connect(self.clear)
        lay.addWidget(clear)
        lay.addStretch(1)

    def spec(self) -> FilterSpec:
        genera = set(self.chips.selected())
        if self.unknown_genus.isChecked():
            genera.add("Unknown")
        return FilterSpec(
            genera=genera,
            zones={z for z, cb in self.zone_boxes.items() if cb.isChecked()},
            status=self.status.currentData(),
            source_types={t for t, cb in self.type_boxes.items() if cb.isChecked()},
            priority_only=self.priority.isChecked(),
            hide_elite=self.hide_elite.isChecked(),
            needs_review=self.needs_review.isChecked(),
            text=self.search.text().strip(),
        )

    def group_by_zone(self) -> bool:
        return self.group_zone.isChecked()

    def clear(self):
        widgets = [*self.zone_boxes.values(), *self.type_boxes.values(), self.priority, self.hide_elite,
                   self.unknown_genus, self.needs_review, self.search, self.status]
        for w in widgets:
            w.blockSignals(True)
        for cb in [*self.zone_boxes.values(), *self.type_boxes.values(), self.priority, self.hide_elite,
                   self.unknown_genus, self.needs_review]:
            cb.setChecked(False)
        self.search.clear()
        self.status.setCurrentIndex(0)
        for w in widgets:
            w.blockSignals(False)
        self.chips.clear()  # emits once


# ------------------------------------------------------------------------- detail panel


class DetailPanel(QWidget):
    show_map = Signal(str)

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.pet_id: str | None = None
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.title = QLabel("Select a pet")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.title)
        self.subtitle = muted()
        lay.addWidget(self.subtitle)
        self.flags = QLabel()
        self.flags.setWordWrap(True)
        lay.addWidget(self.flags)
        self.map_btn = QPushButton("Show on map  ▸")
        self.map_btn.setToolTip("Open the Map page for this pet (or double-click the pet)")
        self.map_btn.clicked.connect(lambda: self.pet_id and self.show_map.emit(self.pet_id))
        lay.addWidget(self.map_btn)

        lay.addWidget(heading("Genus"))
        grow = QHBoxLayout()
        self.genus = QComboBox()
        self.genus.addItem("Unknown", None)
        for g in GENERA:
            self.genus.addItem(dot_icon(g), g, g)
        self.genus.activated.connect(self._genus_changed)
        grow.addWidget(self.genus, 1)
        self.reset_genus = QPushButton("Use guide value")
        self.reset_genus.clicked.connect(self._genus_reset)
        grow.addWidget(self.reset_genus)
        lay.addLayout(grow)
        self.genus_note = muted()
        lay.addWidget(self.genus_note)

        lay.addWidget(heading("Progress"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.unlocked = QCheckBox("Owned / unlocked")
        self.maxed = QCheckBox("Maxed  (Space)")
        self.level = QSpinBox()
        self.level.setRange(0, 10)
        self.level.setSpecialValueText("—")
        self.have = QSpinBox()
        self.have.setRange(-1, 100000)
        self.have.setSpecialValueText("—")
        self.need = QSpinBox()
        self.need.setRange(-1, 100000)
        self.need.setSpecialValueText("—")
        self.max_level = QSpinBox()
        self.max_level.setRange(0, 10)
        self.max_level.setSpecialValueText(f"default ({store.default_max})")
        self.lock = QCheckBox("Lock from OCR (scans never overwrite)")
        for w in (self.level, self.have, self.need, self.max_level):
            w.setButtonSymbols(QAbstractSpinBox.PlusMinus)
            w.setKeyboardTracking(False)
        form.addRow(self.unlocked)
        form.addRow(self.maxed)
        form.addRow("Level", self.level)
        souls = QHBoxLayout()
        souls.addWidget(self.have)
        souls.addWidget(QLabel("/"))
        souls.addWidget(self.need)
        form.addRow("Souls", souls)
        form.addRow("Max level", self.max_level)
        form.addRow(self.lock)
        lay.addLayout(form)
        self.remaining = QLabel()
        self.remaining.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        lay.addWidget(self.remaining)
        self.updated = muted()
        lay.addWidget(self.updated)

        self.unlocked.toggled.connect(self._unlocked_changed)
        self.maxed.toggled.connect(self._maxed_changed)
        for w in (self.level, self.have, self.need, self.max_level):
            w.valueChanged.connect(self._numbers_changed)
        self.lock.toggled.connect(self._numbers_changed)

        lay.addWidget(heading("Where to get it"))
        self.sources = QTextBrowser()
        self.sources.setOpenLinks(False)
        self.sources.setFrameShape(QFrame.NoFrame)
        self.sources.setStyleSheet("background: transparent;")
        lay.addWidget(self.sources, 1)
        self._set_enabled(False)

    def _set_enabled(self, on: bool):
        for w in (self.genus, self.reset_genus, self.unlocked, self.maxed, self.level, self.have, self.need,
                  self.max_level, self.lock, self.map_btn):
            w.setEnabled(on)

    # -- population
    def show_pet(self, pet_id: str | None):
        self.pet_id = pet_id
        if not pet_id:
            self.title.setText("Select a pet")
            self.title.setStyleSheet("font-size: 17pt; font-weight: 700;")
            for w in (self.subtitle, self.genus_note, self.remaining, self.updated):
                w.clear()
            for w in (self.level, self.max_level):
                w.setValue(0)
            for w in (self.have, self.need):
                w.setValue(-1)
            self.flags.hide()
            self.sources.clear()
            self._set_enabled(False)
            return
        self._set_enabled(True)
        self.refresh()

    def refresh(self):
        if not self.pet_id:
            return
        pet: Pet = self.store.pets[self.pet_id]
        pr = self.store.progress(pet.id)
        self.title.setText(pet.name)
        self.title.setStyleSheet(f"color: {genus_color(pet.genus) if pet.genus else '#f1f4f8'};"
                                 " font-size: 17pt; font-weight: 700;")
        self.subtitle.setText(f"{pet.genus or 'Unknown genus'} · PDF field {pet.id}")
        flags = []
        if pet.held:
            flags.append(f"<span style='color:{GOLD}'>Held entry</span> — the guide omits its disputed continent source.")
        if pet.unconfirmed_note:
            flags.append(f"<span style='color:{GOLD}'>Unconfirmed alternate reward:</span> {pet.unconfirmed_note}")
        if any(s.priority_addition for s in pet.sources):
            flags.append(f"<span style='color:{GOLD}'>★ Priority addition</span> on an island/Abyss table.")
        self.flags.setText("<br>".join(flags))
        self.flags.setVisible(bool(flags))

        widgets = (self.genus, self.unlocked, self.maxed, self.level, self.have, self.need, self.max_level, self.lock)
        for w in widgets:
            w.blockSignals(True)
        self.genus.setCurrentIndex(self.genus.findData(pet.genus) if pet.genus else 0)
        conf = {"high": "From the guide (dot or chest heading).",
                "low": "Guessed from the checkbox colour. Confirm in game.",
                "atlas": "From the Pet Soul Atlas (Global data).",
                "override": "Your override (genus_overrides.json)."}.get(pet.genus_confidence or "",
                                                                        "Not in the guide. Set it here.")
        self.genus_note.setText(conf)
        self.reset_genus.setVisible(pet.genus_confidence == "override")
        self.unlocked.setChecked(pr.unlocked)
        self.maxed.setChecked(pr.maxed)
        self.level.setValue(pr.level or 0)
        self.have.setValue(pr.souls_have if pr.souls_have is not None else -1)
        self.need.setValue(pr.souls_need if pr.souls_need is not None else -1)
        self.max_level.setValue(pr.max_level or 0)
        self.lock.setChecked(pr.manual_lock)
        for w in widgets:
            w.blockSignals(False)
        self.remaining.setText(self.store.remaining_text(pet.id))
        self.updated.setText(f"Updated {pr.updated_at} by {pr.updated_by}" if pr.updated_at else "")
        self.sources.setHtml(self._sources_html(pet))

    def _sources_html(self, pet: Pet) -> str:
        if not pet.sources:
            return f"<span style='color:{MUTED}'>No source listed in the guide.</span>"
        rows = []
        for s in sorted(pet.sources, key=lambda s: (s.page or 0)):
            head = f"<b>{s.zone}</b> · {area_label(s)}"
            if s.sub_location and s.sub_location not in head:
                head += f" · {s.sub_location}"
            bits = []
            if s.monster:
                verb = "Boss" if s.source_type in ("boss", "dungeon") else "Kill"
                bits.append(f"{verb}: <span style='color:{ACCENT}'><b>{s.monster}</b></span>")
            if s.elite:
                bits.append(f"<span style='color:{GOLD}'>[ELITE]</span>")
            if s.priority_addition:
                bits.append(f"<span style='color:{GOLD}'>★</span>")
            meta = []
            if s.pin:
                meta.append(f"pin {s.pin}")
            if s.level:
                meta.append(f"Lv {s.level}")
            if s.spawns:
                meta.append(f"{s.spawns} spawns")
            meta.append("atlas" if s.origin == "atlas" else f"p{s.page}")
            rows.append(f"{head}<br>{' '.join(bits)} <span style='color:{MUTED}'>({', '.join(meta)})</span>")
        return "<br><br>".join(rows)

    # -- edits
    def _genus_changed(self, _idx):
        if self.pet_id:
            self.store.set_genus_override(self.pet_id, self.genus.currentData())

    def _genus_reset(self):
        if self.pet_id:
            self.store.set_genus_override(self.pet_id, None)

    def _unlocked_changed(self, on):
        if self.pet_id:
            self.store.set_unlocked(self.pet_id, on)

    def _maxed_changed(self, on):
        if self.pet_id:
            self.store.set_maxed(self.pet_id, on)

    def _numbers_changed(self, *_):
        if not self.pet_id:
            return
        pr = self.store.progress(self.pet_id)
        pr.level = self.level.value() or None
        pr.souls_have = self.have.value() if self.have.value() >= 0 else None
        pr.souls_need = self.need.value() if self.need.value() >= 0 else None
        pr.max_level = self.max_level.value() or None
        pr.manual_lock = self.lock.isChecked()
        if pr.level is not None and pr.souls_need:
            self.store.record_level_requirement(pr.level, pr.souls_need)
        mx = pr.max_level or self.store.default_max
        pr.maxed = pr.level is not None and pr.level >= mx
        self.store.save_progress(pr, by="manual")


# ------------------------------------------------------------------------- tracker tab


class TrackerTab(QWidget):
    filter_changed = Signal()
    pet_selected = Signal(str)
    open_map = Signal(str)

    def __init__(self, store: Store, signals: StoreSignals):
        super().__init__()
        self.store = store
        self._pending_ids: set[str] = set()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)

        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFixedWidth(270)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar = FilterSidebar(store)
        side_scroll.setWidget(self.sidebar)
        lay.addWidget(side_scroll)

        split = QSplitter(Qt.Horizontal)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        self.count_label = muted()
        cl.addWidget(self.count_label)
        self.tree = PetTree()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["✓", "Pet", "Progress", "Best source"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setItemDelegateForColumn(COL_PROG, ProgressDelegate(self.tree))
        h = self.tree.header()
        h.setSectionResizeMode(COL_MAX, QHeaderView.Fixed)
        h.resizeSection(COL_MAX, 34)
        h.resizeSection(COL_PET, 230)
        h.resizeSection(COL_PROG, 200)
        h.setStretchLastSection(True)
        cl.addWidget(self.tree)
        split.addWidget(center)
        self.detail = DetailPanel(store)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

        self.sidebar.changed.connect(self._on_filter)
        self.tree.currentItemChanged.connect(self._on_select)
        self.tree.itemDoubleClicked.connect(
            lambda it, col: it.data(0, PET_ROLE) and col != COL_MAX and self.open_map.emit(it.data(0, PET_ROLE)))
        self.detail.show_map.connect(self.open_map)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.space_pressed.connect(self.toggle_selected_maxed)
        self.tree.genus_key.connect(self.sidebar.chips.toggle_index)
        self.tree.slash_pressed.connect(self.focus_search)
        signals.changed.connect(self._on_store_changed)
        self.rebuild()

    def focus_search(self):
        self.sidebar.search.setFocus()
        self.sidebar.search.selectAll()

    def spec(self) -> FilterSpec:
        return self.sidebar.spec()

    def _on_filter(self):
        self.rebuild()
        self.filter_changed.emit()

    # -- list building
    def _fill_row(self, it: QTreeWidgetItem, pet: Pet, source_text: str):
        pr = self.store.progress(pet.id)
        it.setData(0, PET_ROLE, pet.id)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(COL_MAX, Qt.Checked if pr.maxed else Qt.Unchecked)
        it.setToolTip(COL_MAX, "Maxed (Space)")
        it.setText(COL_PET, pet.name)
        it.setIcon(COL_PET, dot_icon(pet.genus, hollow=pet.genus_confidence == "low"))
        tip = f"{pet.genus or 'Unknown genus'}" + (" (guessed)" if pet.genus_confidence == "low" else "")
        it.setToolTip(COL_PET, tip)
        it.setData(COL_PROG, FRACTION_ROLE, pr.fraction(self.store.default_max))
        it.setData(COL_PROG, LABEL_ROLE, self.store.remaining_text(pet.id))
        it.setData(COL_PROG, COLOR_ROLE, genus_color(pet.genus))
        it.setText(COL_SRC, source_text)
        it.setToolTip(COL_SRC, source_text)

    def rebuild(self):
        cur = self.tree.currentItem()
        cur_id = cur.data(0, PET_ROLE) if cur else None
        cur_row = self.tree.indexOfTopLevelItem(cur) if cur else -1
        scroll = self.tree.verticalScrollBar().value()
        spec = self.spec()
        pets = filter_pets(self.store.pets.values(), self.store.progress, spec)
        self.tree.blockSignals(True)
        self.tree.clear()
        self.items: dict[str, list[QTreeWidgetItem]] = {}
        if self.sidebar.group_by_zone():
            self.tree.setRootIsDecorated(True)
            zone_items: dict[str, QTreeWidgetItem] = {}
            for zone, area, rows in group_by_area(pets, spec):
                zi = zone_items.get(zone)
                if zi is None:
                    zi = QTreeWidgetItem([" ", zone])
                    zi.setFirstColumnSpanned(True)
                    f = zi.font(0)
                    f.setBold(True)
                    zi.setFont(0, f)
                    zi.setForeground(0, Qt.white)
                    self.tree.addTopLevelItem(zi)
                    zone_items[zone] = zi
                ai = QTreeWidgetItem(zi, [f"{area}  ({len(rows)})"])
                ai.setFirstColumnSpanned(True)
                ai.setForeground(0, Qt.gray)
                for pet, s in rows:
                    it = QTreeWidgetItem(ai)
                    mon = s.monster or s.source_type.replace("_", " / ")
                    extra = (" [ELITE]" if s.elite else "") + (f"  · pin {s.pin}" if s.pin else "") + \
                            (f"  · Lv {s.level}" if s.level else "")
                    self._fill_row(it, pet, f"{'kill ' if s.source_type == 'monster' else ''}{mon}{extra}")
                    self.items.setdefault(pet.id, []).append(it)
            self.tree.expandAll()
        else:
            self.tree.setRootIsDecorated(False)
            for pet in pets:
                it = QTreeWidgetItem()
                s = best_source(pet, spec)
                self._fill_row(it, pet, s.summary() if s else "—")
                self.tree.addTopLevelItem(it)
                self.items.setdefault(pet.id, []).append(it)
        self.tree.blockSignals(False)
        self.count_label.setText(f"Showing {len(pets)} pet{'s' if len(pets) != 1 else ''}"
                                 + ("" if not self.sidebar.group_by_zone() else
                                    f" across {sum(len(v) for v in self.items.values())} source rows"))
        # restore selection: same pet, else the row that took its place
        target = None
        if cur_id and cur_id in self.items:
            target = self.items[cur_id][0]
        elif cur_row >= 0 and not self.sidebar.group_by_zone() and self.tree.topLevelItemCount():
            target = self.tree.topLevelItem(min(cur_row, self.tree.topLevelItemCount() - 1))
        self.tree.verticalScrollBar().setValue(scroll)
        if target:
            self.tree.setCurrentItem(target)
        else:
            self.detail.show_pet(None)

    def _on_store_changed(self, ids: set[str]):
        """Queue the update. Rebuilding right here could delete the very row (or checkbox) whose
        click caused the change while Qt is still handling that click -> crash. Applying it on the
        next event-loop turn also merges bursts of changes into one redraw."""
        first = not self._pending_ids
        self._pending_ids |= set(ids)
        if first:
            QTimer.singleShot(0, self._flush_store_changes)

    def _flush_store_changes(self):
        ids, self._pending_ids = self._pending_ids, set()
        ids = {i for i in ids if i in self.store.pets}
        if not ids:
            return
        spec = self.spec()
        still = all(filter_pets([self.store.pets[i]], self.store.progress, spec) for i in ids)
        if still and all(i in self.items for i in ids):
            # update in place (keeps the user's place in the list)
            self.tree.blockSignals(True)
            for i in ids:
                for it in self.items[i]:
                    self._fill_row(it, self.store.pets[i], it.text(COL_SRC))
            self.tree.blockSignals(False)
            self.tree.viewport().update()
        else:
            self.rebuild()
        if self.detail.pet_id in ids:
            self.detail.refresh()

    def _on_select(self, cur, _prev):
        pid = cur.data(0, PET_ROLE) if cur else None
        if pid:
            self.detail.show_pet(pid)
            self.pet_selected.emit(pid)

    def _on_item_changed(self, it: QTreeWidgetItem, col: int):
        pid = it.data(0, PET_ROLE)
        if col == COL_MAX and pid:
            on = it.checkState(COL_MAX) == Qt.Checked
            # never change the store (which may rebuild the list) inside the item's own signal
            QTimer.singleShot(0, lambda: self.store.set_maxed(pid, on))

    def toggle_selected_maxed(self):
        it = self.tree.currentItem()
        pid = it.data(0, PET_ROLE) if it else None
        if pid:
            self.store.set_maxed(pid, not self.store.progress(pid).maxed)


# ------------------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    def __init__(self, store: Store, signals: StoreSignals):
        super().__init__()
        from app.ui.map_view import MapTab
        from app.ui.route_view import RouteTab  # local import keeps modules small

        self.store = store
        from app import __version__
        self.setWindowTitle(f"AION 2 Pet Tracker {__version__} — Asmodian")
        self.resize(1440, 900)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 4)
        title = QLabel("AION 2 PET TRACKER")
        title.setStyleSheet(f"color: {ACCENT}; font-weight: 700; letter-spacing: 2px;")
        hl.addWidget(title)
        hl.addSpacing(20)
        self.stat_labels: dict[str, QLabel] = {}
        for g in (*GENERA, "Unknown", "Overall"):
            l = QLabel()
            l.setStyleSheet(f"color: {genus_color(g) if g in GENERA else '#c8d2e0'}; font-weight: 600;")
            hl.addWidget(l)
            hl.addSpacing(12)
            self.stat_labels[g] = l
        hl.addStretch(1)
        self.collection = QLabel()
        self.collection.setProperty("muted", True)
        hl.addWidget(self.collection)
        self.auto_btn = QPushButton("▶  Auto-scan")
        self.auto_btn.setObjectName("autoscan")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setToolTip("Watch the in-game Pets window and save each pet you click. Beeps when saved.")
        hl.addWidget(self.auto_btn)
        self.scan_btn = QPushButton("Scan ▾")
        self.scan_menu = QMenu(self.scan_btn)
        self.scan_btn.setMenu(self.scan_menu)
        hl.addWidget(self.scan_btn)
        from PySide6.QtGui import QActionGroup
        from app.ui.overlay import SIZES

        self.overlay_btn = QPushButton("Overlay ▾")
        self.overlay_menu = QMenu(self.overlay_btn)
        self.overlay_btn.setMenu(self.overlay_menu)
        self.overlay_show = self.overlay_menu.addAction("Show overlay")
        self.overlay_show.setCheckable(True)
        self.overlay_move = self.overlay_menu.addAction("Move / resize  (drag it; side edges set width)")
        self.overlay_move.setCheckable(True)
        size_menu = self.overlay_menu.addMenu("Text size")
        self.overlay_sizes: dict[float, QAction] = {}
        group = QActionGroup(size_menu)
        for label, scale in SIZES.items():
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setData(scale)
            group.addAction(a)
            self.overlay_sizes[scale] = a
        hl.addWidget(self.overlay_btn)
        v.addWidget(header)

        # Banner shown while a scan waits for confirmation.
        self.pending_bar = QFrame()
        self.pending_bar.setStyleSheet(f"QFrame {{ background: #2a2410; border: 1px solid {GOLD}; border-radius: 6px; }}"
                                       " QLabel { border: none; background: transparent; }")
        pb = QHBoxLayout(self.pending_bar)
        pb.setContentsMargins(10, 6, 10, 6)
        self.pending_label = QLabel()
        self.pending_label.setTextFormat(Qt.RichText)
        pb.addWidget(self.pending_label, 1)
        self.pending_buttons = QHBoxLayout()
        pb.addLayout(self.pending_buttons)
        self.pending_bar.hide()
        wrap = QHBoxLayout()
        wrap.setContentsMargins(16, 4, 16, 4)
        wrap.addWidget(self.pending_bar)
        v.addLayout(wrap)
        self.on_confirm = None  # set by main: callable(pet_id | None)

        self.tabs = QTabWidget()
        self.tracker = TrackerTab(store, signals)
        self.route = RouteTab(store, signals)
        self.tabs.addTab(self.tracker, "Tracker")
        self.tabs.addTab(self.route, "Route")
        self.map = MapTab(store, signals)
        self.tabs.addTab(self.map, "Map")
        self.tracker.pet_selected.connect(self.map.show_pet)
        self.tracker.open_map.connect(self.open_map)
        v.addWidget(self.tabs, 1)

        QShortcut(QKeySequence("Ctrl+F"), self, self.tracker.focus_search)
        signals.changed.connect(lambda _: self.update_stats())
        self.ingame_collection: tuple[int, int] | None = None
        self.update_stats()

    def open_map(self, pet_id: str):
        self.map.show_pet(pet_id)
        self.tabs.setCurrentWidget(self.map)

    def set_ingame_collection(self, x: int, y: int):
        self.ingame_collection = (x, y)
        self.update_stats()

    def show_pending(self, scan):
        while self.pending_buttons.count():
            w = self.pending_buttons.takeAt(0).widget()
            if w:
                w.deleteLater()
        if scan is None:
            self.pending_bar.hide()
            return
        why = scan.match.reason if scan.match else scan.error
        self.pending_label.setText(f"<b style='color:{GOLD}'>Confirm scan:</b> {scan.summary()}"
                                   f" <span style='color:{MUTED}'>— read “{scan.name}”, {why}</span>")
        for c in (scan.match.candidates if scan.match else [])[:3]:
            b = QPushButton(f"{c.name} ({c.score:.0f})")
            b.clicked.connect(lambda _=False, pid=c.pet_id: self.on_confirm and self.on_confirm(pid))
            self.pending_buttons.addWidget(b)
        no = QPushButton("Discard")
        no.clicked.connect(lambda: self.on_confirm and self.on_confirm(None))
        self.pending_buttons.addWidget(no)
        self.pending_bar.show()

    def update_stats(self):
        stats = self.store.genus_stats()
        for g, (m, t) in stats.items():
            if g in self.stat_labels:
                self.stat_labels[g].setText(f"{g} {m}/{t}")
                self.stat_labels[g].setToolTip(f"{m} of {t} {g} pets maxed")
                self.stat_labels[g].setVisible(t > 0)
        m = sum(v[0] for v in stats.values())
        t = sum(v[1] for v in stats.values())
        self.stat_labels["Overall"].setText(f"Overall {m}/{t} maxed")
        owned = self.store.unlocked_count()
        txt = f"Owned in app: {owned}/{t}"
        if self.ingame_collection:
            x, y = self.ingame_collection
            txt += f"  ·  in game: {x}/{y}"
            if x != owned:
                txt += "  ⚠ out of sync"
        self.collection.setText(txt)

    def keyPressEvent(self, e):
        # Fallback shortcuts when focus isn't in a text field.
        if e.key() == Qt.Key_Slash:
            self.tracker.focus_search()
            return
        if e.key() == Qt.Key_Space and self.tabs.currentWidget() is self.tracker:
            self.tracker.toggle_selected_maxed()
            return
        if Qt.Key_1 <= e.key() <= Qt.Key_4 and not e.modifiers() and self.tabs.currentWidget() is self.tracker:
            self.tracker.sidebar.chips.toggle_index(e.key() - Qt.Key_1)
            return
        super().keyPressEvent(e)
