"""Map page: the guide's maps with the selected pet's farming spots marked."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCompleter, QComboBox, QGraphicsEllipseItem, QGraphicsItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter, QStackedWidget,
    QVBoxLayout,
    QWidget, QGraphicsRectItem,
)

from app.core.filters import area_label
from app.core.models import Pet, Source
from app.core.store import Store
from app.ui.theme import ACCENT, GOLD, MUTED, PANEL, StoreSignals, dot_icon, genus_color


@dataclass
class Location:
    title: str                  # list text
    detail: str                 # what to do there
    panel: Optional[str]        # map panel id, None = no map
    label: Optional[str]        # pin label on that panel
    overview: bool = False      # zoomed-out context view (island on mainland, Abyss overview)


def locations_for(store: Store, pet: Pet) -> list[Location]:
    out: list[Location] = []
    for s in pet.sources:
        what = _what(s)
        where = f"{s.zone} · {area_label(s)}"
        if s.sub_location and s.sub_location not in where:
            where += f" · {s.sub_location}"
        if not s.map:
            out.append(Location(where, what + "  · no map", None, None))
            continue
        for i, (panel, label) in enumerate(s.map):
            if panel not in store.maps:
                continue
            if i == 0:
                out.append(Location(where, what, panel, label))
            else:
                out.append(Location(f"   ↳ {store.maps[panel]['title']}", f"{s.zone} is marked {label} here",
                                    panel, label, overview=True))
    for c in store.circuits:
        for st in c.stops:
            if st.pet_id == pet.id and c.panel:
                out.append(Location(f"{c.zone} loop · {c.name}", f"Pocket {st.pocket}: kill {st.monster}"
                                    + (f"  (Lv {c.level_range})" if c.level_range else ""), c.panel, st.pocket))
    return out


def _what(s: Source) -> str:
    if s.source_type == "chest_merchant":
        return "Genus chests / random merchants"
    verb = "Boss" if s.source_type in ("boss", "dungeon") else "Kill"
    bits = [f"{verb}: {s.monster}" if s.monster else verb]
    if s.elite:
        bits.append("[ELITE]")
    if s.level:
        bits.append(f"Lv {s.level}")
    if s.pin:
        bits.append(f"pin {s.pin}")
    if s.priority_addition:
        bits.append("★")
    return "  ".join(bits)


class MapView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#05080f"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self._anims: list[QVariantAnimation] = []
        self._auto_view = None  # ("fit",) or ("focus", QRectF, QPointF) until the user zooms/pans

    def wheelEvent(self, e):
        self._auto_view = None
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def mousePressEvent(self, e):
        self._auto_view = None
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._auto_view = None
        self.scale(1.6, 1.6)
        self.centerOn(self.mapToScene(e.position().toPoint()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_auto_view()  # keep the marker framed while the page is still laying out

    def _apply_auto_view(self):
        v = self._auto_view
        if not v:
            return
        self.resetTransform()
        if v[0] == "fit":
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        else:
            self.fitInView(v[1], Qt.KeepAspectRatio)
            self.centerOn(v[2])

    def fit(self):
        self._auto_view = ("fit",)
        self._apply_auto_view()

    def show_map(self, pixmap: QPixmap, markers: list[tuple[QPointF, str, bool]], color: str, focus: Optional[QPointF]):
        for a in self._anims:
            a.stop()
        self._anims.clear()
        sc = self.scene()
        sc.clear()
        sc.addPixmap(pixmap)
        sc.setSceneRect(QRectF(pixmap.rect()))
        unit = max(pixmap.width(), pixmap.height()) / 1800
        for pt, text, primary in markers:
            self._marker(pt, text, primary, color, unit)
        if focus is not None:
            # Show the spot with some surroundings (about 45% of the map).
            w = pixmap.width() * 0.45
            h = pixmap.height() * 0.45
            self._auto_view = ("focus", QRectF(focus.x() - w / 2, focus.y() - h / 2, w, h), focus)
        else:
            self._auto_view = ("fit",)
        self._apply_auto_view()

    def _marker(self, pt: QPointF, text: str, primary: bool, color: str, unit: float):
        sc = self.scene()
        r = 44 * unit
        c = QColor(color)
        if primary:
            pulse = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            pulse.setPos(pt)
            pen = QPen(c, 6 * unit)
            pulse.setPen(pen)
            pulse.setBrush(Qt.NoBrush)
            sc.addItem(pulse)
            anim = QVariantAnimation(self, startValue=1.0, endValue=2.6, duration=1400, loopCount=-1)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def step(v, item=pulse):
                item.setScale(v)
                item.setOpacity(max(0.0, 1.0 - (v - 1.0) / 1.6))

            anim.valueChanged.connect(step)
            anim.start()
            self._anims.append(anim)
        ring = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
        ring.setPos(pt)
        ring.setPen(QPen(QColor(GOLD) if primary else c, (8 if primary else 5) * unit))
        fill = QColor(c)
        fill.setAlpha(70 if primary else 35)
        ring.setBrush(QBrush(fill))
        sc.addItem(ring)
        if text:
            tag = QGraphicsSimpleTextItem(text)
            f = QFont("Segoe UI")
            f.setPixelSize(int((30 if primary else 24) * unit))
            f.setBold(primary)
            tag.setFont(f)
            tag.setBrush(QColor("white"))
            br = tag.boundingRect()
            bg = QGraphicsRectItem(br.adjusted(-10 * unit, -5 * unit, 10 * unit, 5 * unit))
            bg.setBrush(QColor(13, 21, 37, 225))
            bg.setPen(QPen(QColor(GOLD) if primary else c, 2 * unit))
            bg.setPos(pt.x() + r + 10 * unit, pt.y() - br.height() / 2)
            tag.setParentItem(bg)
            bg.setFlag(QGraphicsItem.ItemIgnoresTransformations, False)
            sc.addItem(bg)


class MapTab(QWidget):
    pet_changed = Signal(str)

    def __init__(self, store: Store, signals: StoreSignals):
        super().__init__()
        self.store = store
        self.pet_id: Optional[str] = None
        self.locs: list[Location] = []
        self._pix: dict[str, QPixmap] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)

        top = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.setEditable(True)
        self.picker.setInsertPolicy(QComboBox.NoInsert)
        self.picker.setMinimumWidth(280)
        for p in sorted(store.pets.values(), key=lambda p: p.name.lower()):
            self.picker.addItem(dot_icon(p.genus), p.name, p.id)
        comp = QCompleter([self.picker.itemText(i) for i in range(self.picker.count())], self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.picker.setCompleter(comp)
        self.picker.activated.connect(lambda i: self.show_pet(self.picker.itemData(i)))
        top.addWidget(QLabel("Pet:"))
        top.addWidget(self.picker)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 15pt; font-weight: 700;")
        top.addWidget(self.title)
        self.progress = QLabel()
        self.progress.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        top.addWidget(self.progress)
        top.addStretch(1)
        self.live_btn = QPushButton("Live map")
        self.live_btn.setToolTip("Interactive Pet Soul Atlas map with every spawn of this pet")
        self.guide_btn = QPushButton("Guide map")
        self.guide_btn.setToolTip("The guide's own maps with its numbered pins")
        for b in (self.live_btn, self.guide_btn):
            b.setCheckable(True)
            b.setAutoExclusive(True)
            top.addWidget(b)
        self.live_btn.setChecked(True)
        self.live_btn.toggled.connect(self._mode_changed)
        top.addSpacing(12)
        self.atlas_btn = QPushButton("Open in browser ↗")
        self.atlas_btn.setToolTip("Open this pet on the Pet Soul Atlas (petsouls.dev) in your browser")
        self.atlas_btn.clicked.connect(lambda: self._open("atlas"))
        self.db_btn = QPushButton("Database ↗")
        self.db_btn.clicked.connect(lambda: self._open("database"))
        self.fit_btn = fit = QPushButton("Whole map")
        fit.clicked.connect(lambda: self.view.fit())
        fit.hide()
        for b in (self.atlas_btn, self.db_btn, fit):
            top.addWidget(b)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        h = QLabel("WHERE TO FARM")
        h.setProperty("heading", True)
        ll.addWidget(h)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._on_loc)
        ll.addWidget(self.list, 1)
        self.hint = QLabel("Wheel to zoom · drag to move · double-click to zoom in")
        self.hint.setProperty("muted", True)
        ll.addWidget(self.hint)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.map_title = QLabel()
        self.map_title.setStyleSheet(f"color: {ACCENT}; font-weight: 700; letter-spacing: 1px;")
        rl.addWidget(self.map_title)
        self.view = MapView()
        rl.addWidget(self.view, 1)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {MUTED}; font-size: 12pt; background: {PANEL}; border-radius: 8px;")
        self.empty.hide()
        rl.addWidget(self.empty, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([380, 1000])
        self.stack = QStackedWidget()
        self.live_page = QWidget()
        QVBoxLayout(self.live_page).setContentsMargins(0, 0, 0, 0)
        self.live_view = None  # created the first time the live map is shown (starts a browser engine)
        self.stack.addWidget(self.live_page)
        self.stack.addWidget(split)
        lay.addWidget(self.stack, 1)
        signals.changed.connect(lambda ids: self._refresh_header() if self.pet_id in ids else None)

    # ------------------------------------------------------------------ data
    def show_pet(self, pet_id: Optional[str]):
        if not pet_id or pet_id not in self.store.pets:
            return
        self.pet_id = pet_id
        pet = self.store.pets[pet_id]
        i = self.picker.findData(pet_id)
        if i >= 0:
            self.picker.setCurrentIndex(i)
        self._refresh_header()
        self._update_live()
        self.atlas_btn.setEnabled("atlas" in pet.links)
        self.db_btn.setEnabled("database" in pet.links)
        self.locs = locations_for(self.store, pet)
        self.list.blockSignals(True)
        self.list.clear()
        first_map = None
        for n, loc in enumerate(self.locs):
            it = QListWidgetItem(f"{loc.title}\n{loc.detail}")
            if loc.panel is None:
                it.setForeground(QColor(MUTED))
            elif loc.overview:
                it.setForeground(QColor("#b9c4d6"))
            elif first_map is None:
                first_map = n
            self.list.addItem(it)
        self.list.blockSignals(False)
        if first_map is not None:
            self.list.setCurrentRow(first_map)
        else:
            self._no_map(pet)
        self.pet_changed.emit(pet_id)

    # ------------------------------------------------------------------ live map
    def live_mode(self) -> bool:
        return self.live_btn.isChecked()

    def _mode_changed(self, live: bool):
        self.stack.setCurrentIndex(0 if live else 1)
        self.fit_btn.setVisible(not live)
        self._update_live()

    def _update_live(self):
        if not (self.live_mode() and self.isVisible() and self.pet_id):
            return
        if self.live_view is None:
            from app.ui.atlas_view import AtlasView
            self.live_view = AtlasView(compact=False)
            self.live_page.layout().addWidget(self.live_view)
        self.live_view.show_url(self.store.pets[self.pet_id].links.get("atlas", ""))

    def showEvent(self, e):
        super().showEvent(e)
        self._update_live()

    def _refresh_header(self):
        if not self.pet_id:
            return
        pet = self.store.pets[self.pet_id]
        self.title.setText(pet.name)
        self.title.setStyleSheet(f"font-size: 15pt; font-weight: 700; color: {genus_color(pet.genus)};")
        self.progress.setText(f"{pet.genus or 'genus ?'} · {self.store.remaining_text(pet.id)}")

    def _no_map(self, pet: Pet):
        self.view.hide()
        self.map_title.setText("")
        kinds = {s.source_type for s in pet.sources}
        if not pet.sources:
            msg = "The guide lists no source for this pet."
        elif kinds == {"chest_merchant"}:
            msg = "No farming spot: this pet comes from genus chests and random merchants."
        else:
            msg = "No map in the guide for this source (dungeon or another region)."
        self.empty.setText(msg + ("\n\nTry “Live spawn map ↗” for the online atlas." if "atlas" in pet.links else ""))
        self.empty.show()

    def _on_loc(self, row: int):
        if not (0 <= row < len(self.locs)) or not self.pet_id:
            return
        loc = self.locs[row]
        if loc.panel is None:
            self._no_map(self.store.pets[self.pet_id])
            return
        self.empty.hide()
        self.view.show()
        m = self.store.maps[loc.panel]
        pix = self._pix.get(loc.panel)
        if pix is None:
            pix = QPixmap(str(self.store.maps_dir / m["image"]))
            self._pix[loc.panel] = pix
        if pix.isNull():
            self.empty.setText(f"Map image missing: {m['image']}\nRun tools/parse_pdf.py to rebuild the maps.")
            self.empty.show()
            self.view.hide()
            return
        # Primary marker for the chosen spot, dimmer markers for this pet's other spots on the same map.
        markers = []
        seen = set()
        for other in self.locs:
            if other.panel != loc.panel or other.label in seen or other.label not in m["labels"]:
                continue
            seen.add(other.label)
            x, y = m["labels"][other.label]
            primary = other.label == loc.label
            text = loc.detail.split("  ")[0] if primary and not loc.overview else ("" if primary else "")
            markers.append((QPointF(x, y), text, primary))
        markers.sort(key=lambda t: t[2])  # primary drawn last (on top)
        pt = m["labels"].get(loc.label)
        self.map_title.setText(f"{m['title'].upper()}  ·  guide page {m['page']}")
        self.view.show_map(pix, markers, genus_color(self.store.pets[self.pet_id].genus),
                           QPointF(*pt) if pt and not loc.overview else None)

    def _open(self, key: str):
        if self.pet_id:
            url = self.store.pets[self.pet_id].links.get(key)
            if url:
                QDesktopServices.openUrl(QUrl(url))
