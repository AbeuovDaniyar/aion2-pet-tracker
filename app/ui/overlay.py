"""Always-on-top overlay. Click-through by default; it never takes focus or input.

Compact by default: just the pets whose monsters are on screen, their genus and souls to max,
plus short toasts for important events. Move mode (hotkey) lets you drag it, change its width,
and optionally show the tracker's unfinished list or the current route under it.
It only draws on screen. It sends nothing to the game.
"""
from __future__ import annotations

import sys
from html import escape

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.filters import best_source, filter_pets
from app.core.store import Store, save_settings
from app.ui.theme import ACCENT, GOLD, MUTED, genus_color

BASE_FLAGS = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
MIN_W, MAX_W = 220, 900
EDGE = 8           # px from the left/right edge that start a width drag in move mode
SIZES = {"Small": 0.85, "Normal": 1.0, "Large": 1.25, "Extra large": 1.5}


def genus_pill(genus: str | None, size: float = 7.5) -> str:
    c = genus_color(genus)
    label = (genus or "?").upper()
    return (f"<span style='background:{c}; color:white; font-weight:700; font-size:{size:.1f}pt;'>"
            f"&nbsp;{label}&nbsp;</span>")


class Overlay(QWidget):
    geometry_changed = Signal()
    interactive_changed = Signal(bool)
    scale_changed = Signal(float)

    def __init__(self, store: Store, settings: dict, tracker_tab, route_tab):
        super().__init__(None, BASE_FLAGS | Qt.WindowTransparentForInput)
        self.store = store
        self.settings = settings
        self.tracker = tracker_tab
        self.route = route_tab
        self.interactive = False
        self.capture_excluded = False
        self.scan_state = ""          # "", "field", "pets"
        self._rows: list[dict] = []
        self._drag: QPoint | None = None
        self._resize: tuple | None = None      # (edge, start mouse x, start geometry)
        self.scale = float(settings["overlay"].get("scale", 1.0))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        o = settings["overlay"]
        width = max(MIN_W, min(MAX_W, o.get("compact_width", 300)))
        self.move(o["x"], o["y"])
        self.resize(width, 60)
        self.setWindowOpacity(o["opacity"])
        self.setWindowTitle("Pet overlay")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        top.addWidget(self.status, 1)
        self.mode = QComboBox()
        self.mode.addItem("Show: nearby pets", "nearby")
        self.mode.addItem("Show: + tracker list", "filter")
        self.mode.addItem("Show: + current route", "route")
        i = self.mode.findData(o.get("show", "nearby"))
        self.mode.setCurrentIndex(max(i, 0))
        self.mode.setVisible(False)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        top.addWidget(self.mode)
        lay.addLayout(top)

        self.nearby = QLabel()
        self.nearby.setTextFormat(Qt.RichText)
        self.nearby.setWordWrap(True)
        lay.addWidget(self.nearby)
        self.toast = QLabel()
        self.toast.setWordWrap(True)
        self.toast.setTextFormat(Qt.RichText)
        self.toast.hide()
        lay.addWidget(self.toast)
        self.map_title = QLabel()
        self.map_title.setTextFormat(Qt.RichText)
        self.map_title.hide()
        lay.addWidget(self.map_title)
        self.map_box = QWidget()
        QVBoxLayout(self.map_box).setContentsMargins(0, 0, 0, 0)
        self.map_box.hide()
        lay.addWidget(self.map_box)
        self.map_view = None   # live atlas map, created the first time a pet is selected
        self.body = QLabel()
        self.body.setTextFormat(Qt.RichText)
        self.body.setWordWrap(True)
        self.body.hide()
        lay.addWidget(self.body)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.hide()
        lay.addWidget(self.hint)
        self._apply_scale_styles()
        self._toast_timer = QTimer(self, singleShot=True, timeout=self.clear_toast)

        tracker_tab.filter_changed.connect(self.refresh)
        route_tab.route_changed.connect(self.refresh)
        self._render_status()
        self._render_nearby()
        self.refresh()

    # ------------------------------------------------------------------ size
    def pt(self, size: float) -> float:
        return round(size * self.scale, 1)

    def pill(self, genus: str | None) -> str:
        return genus_pill(genus, self.pt(7.5))

    def _apply_scale_styles(self):
        self.setStyleSheet(f"QLabel {{ font-size: {self.pt(10)}pt; }}")
        self.status.setStyleSheet(f"color: {MUTED}; font-size: {self.pt(8)}pt; font-weight: 600;")
        self.hint.setStyleSheet(f"color: {MUTED}; font-size: {self.pt(7.5)}pt;")

    def set_scale(self, scale: float):
        self.scale = max(0.6, min(2.5, round(scale, 2)))
        self.settings["overlay"]["scale"] = self.scale
        save_settings(self.settings)
        self._apply_scale_styles()
        self._render_status()
        self._render_nearby()
        self.refresh()
        self.scale_changed.emit(self.scale)

    # ------------------------------------------------------------------ content
    def set_scan_state(self, state: str):
        """'' = auto-scan off, 'field' = watching the world, 'pets' = reading the Pets window."""
        self.scan_state = state
        self._render_status()
        self._render_nearby()

    def set_status(self, text: str):
        # Kept for callers that still pass a label; the pill text comes from scan_state.
        self._render_status()

    def _render_status(self):
        s = self.scan_state
        if s == "field":
            pill = "<span style='color:#3fbf6a'>●</span> WATCHING FOR PETS"
        elif s == "pets":
            pill = "<span style='color:#3fbf6a'>●</span> SCANNING PETS WINDOW"
        else:
            pill = "<span style='color:#56637a'>●</span> AUTO-SCAN OFF"
        self.status.setText(pill)

    # ------------------------------------------------------------------ live map
    def show_pet_map(self, name: str, genus: str | None, url: str):
        """Compact live map of where this pet's monsters spawn (Pets window mode)."""
        if not self.settings["overlay"].get("show_map", True) or not url:
            return
        if self.map_view is None:
            from app.ui.atlas_view import AtlasView
            self.map_view = AtlasView(compact=True)
            self.map_box.layout().addWidget(self.map_view)
        self.map_title.setText(f"{self.pill(genus)} <b style='color:#e6ebf2'>{escape(name)}</b>"
                               f" <span style='color:{MUTED}'>· spawns</span>")
        self.map_title.show()
        self.map_box.setFixedHeight(int(self.width() * 0.62))
        self.map_box.show()
        self.map_view.show_url(url)
        self._fit()

    def hide_map(self):
        if self.map_box.isVisible():
            self.map_box.hide()
            self.map_title.hide()
            self._fit()

    def set_nearby_rows(self, rows: list[dict]):
        """rows: {name, genus, text, targeted, maxed, alert}"""
        if rows == self._rows:
            return  # nothing changed: don't redraw over the game
        self._rows = rows
        self._render_nearby()

    def set_nearby(self, html: str):
        """Back-compat: an empty string clears the list."""
        if not html:
            self.set_nearby_rows([])

    def _render_nearby(self):
        if self._rows:
            parts = ["<table width='100%' cellspacing='0' cellpadding='2'>"]
            for r in self._rows:
                op = "opacity:0.5;" if r.get("maxed") else ""
                name_color = "#ffffff" if r.get("alert") else "#e6ebf2"
                new = f" <span style='color:{MUTED}; font-size:{self.pt(7.5)}pt'>new</span>" if r.get("new") else ""
                kill = ", ".join(r.get("monsters") or [])
                kill = (f"<span style='color:{MUTED}; font-size:{self.pt(8)}pt'> · kill "
                        f"<span style='color:#c8d2e0'>{escape(kill)}</span></span>") if kill else ""
                parts.append(
                    f"<tr style='{op}'><td width='1%' style='white-space:nowrap'>{self.pill(r.get('genus'))}</td>"
                    f"<td>&nbsp;<b style='color:{name_color}'>{escape(r['name'])}</b>{new}{kill}</td>"
                    f"<td align='right' style='white-space:nowrap; color:{MUTED if r.get('maxed') else GOLD}'>"
                    f"<b>{escape(r['text'])}</b></td></tr>")
            parts.append("</table>")
            self.nearby.setText("".join(parts))
            self.nearby.show()
        elif self.scan_state == "field":
            self.nearby.setText(f"<span style='color:{MUTED}'>No guide pets on screen</span>")
            self.nearby.show()
        else:
            self.nearby.hide()
        self._fit()

    def refresh(self, *_):
        """Optional list under the nearby pets (move mode ▸ Show)."""
        mode = self.mode.currentData()
        if mode == "nearby":
            self.body.hide()
            self._fit()
            return
        n = self.settings["overlay"].get("top_n", 8)
        if mode == "route":
            stops = self.route.stops(include_done=False)
            title = self.route.title()
            rows = [(st.pet, st.monster) for st in stops[:n]]
            total = len(stops)
        else:
            spec = self.tracker.spec()
            pets = [p for p in filter_pets(self.store.pets.values(), self.store.progress, spec)
                    if not self.store.progress(p.id).maxed]
            title = "Unfinished · " + (", ".join(sorted(spec.genera)) or "all genera")
            rows = []
            for p in pets[:n]:
                s = best_source(p, spec)
                rows.append((p, s.monster if s and s.monster else "chest / merchant" if s else "—"))
            total = len(pets)
        html = [f"<div style='color:{ACCENT}; font-size:{self.pt(7.5)}pt; font-weight:700'>{escape(title.upper())}</div>",
                "<table width='100%' cellspacing='0' cellpadding='1'>"]
        for pet, where in rows:
            html.append(f"<tr><td width='1%'>{self.pill(pet.genus)}</td>"
                        f"<td>&nbsp;{escape(pet.name)}<span style='color:{MUTED}; font-size:{self.pt(7.5)}pt'>"
                        f" · {escape(where)}</span></td></tr>")
        html.append("</table>")
        if total > len(rows):
            html.append(f"<div style='color:{MUTED}; font-size:{self.pt(7.5)}pt'>+{total - len(rows)} more</div>")
        self.body.setText("".join(html))
        self.body.show()
        self._fit()

    def show_toast(self, text: str, ms: int = 4000, accent: str | None = None):
        """ms=0 keeps the toast until replaced (used while a scan waits for confirmation)."""
        border = f"border-left: 3px solid {accent};" if accent else ""
        self.toast.setStyleSheet(f"background: rgba(20,32,57,235); color: {GOLD}; border-radius: 5px;"
                                 f" padding: 5px 7px; {border}")
        self.toast.setText(text)
        self.toast.show()
        self._toast_timer.stop()
        if ms:
            self._toast_timer.start(ms)
        self._fit()

    def clear_toast(self):
        self._toast_timer.stop()
        self.toast.hide()
        self._fit()

    def _fit(self):
        """Height follows the content; width is the user's choice."""
        lay = self.layout()
        if lay is None:
            return
        lay.activate()
        w = self.width()
        h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height()
        if h != self.height():
            self.resize(w, max(h, 30))

    # ------------------------------------------------------------------ capture exclusion
    def showEvent(self, e):
        super().showEvent(e)
        self._apply_capture_mode()
        self.geometry_changed.emit()
        QTimer.singleShot(0, self._fit)

    def set_capture_hidden(self, hidden: bool):
        self.settings["overlay"]["hide_from_capture"] = hidden
        save_settings(self.settings)
        self._apply_capture_mode()
        self.geometry_changed.emit()

    def _apply_capture_mode(self):
        """Visible in screenshots / Discord / OBS by default. With 'hide_from_capture' on, Windows leaves
        the overlay out of every capture (Windows 10 2004+). Auto-scan masks the overlay itself either way."""
        hide = bool(self.settings["overlay"].get("hide_from_capture", False))
        self.capture_excluded = False
        if sys.platform != "win32":
            return
        try:
            import ctypes
            WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
            ok = ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()),
                                                              WDA_EXCLUDEFROMCAPTURE if hide else WDA_NONE)
            self.capture_excluded = bool(ok) and hide
        except Exception:
            pass

    # ------------------------------------------------------------------ modes
    def _mode_changed(self, *_):
        self.settings["overlay"]["show"] = self.mode.currentData()
        save_settings(self.settings)
        self.refresh()

    def set_interactive(self, on: bool):
        self.interactive = on
        geo = self.geometry()
        visible = self.isVisible()
        flags = BASE_FLAGS if on else BASE_FLAGS | Qt.WindowTransparentForInput
        if on:
            flags &= ~Qt.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        self.setGeometry(geo)
        self.mode.setVisible(on)
        self.setMouseTracking(on)
        for child in self.findChildren(QLabel):
            child.setMouseTracking(on)
            child.setAttribute(Qt.WA_TransparentForMouseEvents, on)  # let drags reach the overlay itself
        hk = self.settings["hotkeys"]
        self.hint.setText("Drag to move · drag the left or right edge for width · Ctrl+wheel for text size<br>"
                          f"Click Done in the tracker's Overlay menu (or {hk['overlay_interactive']}) when finished")
        self.hint.setVisible(on)
        if visible:
            self.show()
        if not on:
            self._save_geometry()
        self._fit()
        self.update()
        self.interactive_changed.emit(on)

    def toggle_interactive(self):
        self.set_interactive(not self.interactive)

    def toggle_visible(self):
        self.setVisible(not self.isVisible())
        self.settings["overlay"]["visible"] = self.isVisible()
        save_settings(self.settings)

    def _save_geometry(self):
        g = self.geometry()
        self.settings["overlay"].update(x=g.x(), y=g.y(), compact_width=g.width())
        save_settings(self.settings)

    # ------------------------------------------------------------------ painting / dragging
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(13, 21, 37, 200))
        p.setPen(QPen(QColor(ACCENT if self.interactive else "#2c3d60"), 1.5 if self.interactive else 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        if self.interactive:  # grab bars on both side edges
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            mid, half = self.height() / 2, min(18, self.height() / 2 - 6)
            p.drawRoundedRect(2, int(mid - half), 4, int(2 * half), 2, 2)
            p.drawRoundedRect(self.width() - 6, int(mid - half), 4, int(2 * half), 2, 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            if self.map_box.isVisible():
                self.map_box.setFixedHeight(int(self.width() * 0.62))
            QTimer.singleShot(0, self._fit)
        self.geometry_changed.emit()

    def moveEvent(self, e):
        super().moveEvent(e)
        self.geometry_changed.emit()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.geometry_changed.emit()

    def _edge_at(self, x: float) -> str | None:
        if x <= EDGE:
            return "left"
        if x >= self.width() - EDGE:
            return "right"
        return None

    def mousePressEvent(self, e):
        if not (self.interactive and e.button() == Qt.LeftButton):
            return
        edge = self._edge_at(e.position().x())
        if edge:
            self._resize = (edge, e.globalPosition().x(), self.geometry())
        else:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if not self.interactive:
            return
        if self._resize:
            edge, x0, g = self._resize
            dx = e.globalPosition().x() - x0
            if edge == "right":
                w = max(MIN_W, min(MAX_W, int(g.width() + dx)))
                self.setGeometry(g.x(), g.y(), w, self.height())
            else:
                w = max(MIN_W, min(MAX_W, int(g.width() - dx)))
                self.setGeometry(g.x() + g.width() - w, g.y(), w, self.height())
            self._fit()
        elif self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
        else:
            self.setCursor(QCursor(Qt.SizeHorCursor if self._edge_at(e.position().x()) else Qt.SizeAllCursor))

    def mouseReleaseEvent(self, _e):
        if self._drag is not None or self._resize is not None:
            self._drag = self._resize = None
            self._save_geometry()

    def wheelEvent(self, e):
        if self.interactive and e.modifiers() & Qt.ControlModifier:
            self.set_scale(self.scale + (0.1 if e.angleDelta().y() > 0 else -0.1))
