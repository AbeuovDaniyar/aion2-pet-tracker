"""Calibration wizard: drag the OCR regions over a screenshot, test them, save per resolution."""
from __future__ import annotations

import copy

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QGraphicsItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from app.ocr.capture import DEFAULT_PROFILE, ProfileStore, card_boxes, grab_monitor, load_image, scale_profile
from app.core.store import DATA

SAMPLE = DATA / "sample_screens" / "pets_konutin_worker_1080p.png"

ROI_STYLE = {
    "name": ("#ffb36a", "Pet name"),
    "insight": ("#ffdf85", "Pet Insight  Lv. x (a/b)"),
    "collection": ("#48d8e3", "Collection Status x/y"),
    "detail_panel": ("#9eafc8", "Debug crop"),
    "genus_badge": ("#c2a5ff", "Genus badge"),
    "grid_area": ("#258443", "Card grid (scroll area)"),
    "first_card": ("#3fbf6a", "First card"),
}


class _Handle(QGraphicsRectItem):
    SIZE = 10

    def __init__(self, parent: "RoiItem"):
        super().__init__(-self.SIZE / 2, -self.SIZE / 2, self.SIZE, self.SIZE, parent)
        self.setBrush(QBrush(parent.pen().color()))
        self.setPen(QPen(Qt.black, 0))
        self.setCursor(Qt.SizeFDiagCursor)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

    def mousePressEvent(self, e):
        e.accept()

    def mouseMoveEvent(self, e):
        p: RoiItem = self.parentItem()
        pos = p.mapFromScene(e.scenePos())
        r = p.rect()
        p.setRect(QRectF(r.topLeft(), QPointF(max(pos.x(), r.left() + 6), max(pos.y(), r.top() + 6))))
        p.sync_handle()
        p.on_change()


class RoiItem(QGraphicsRectItem):
    def __init__(self, key: str, box, on_change):
        x1, y1, x2, y2 = box
        super().__init__(QRectF(x1, y1, x2 - x1, y2 - y1))
        color, label = ROI_STYLE[key]
        self.key = key
        self.on_change = on_change
        pen = QPen(QColor(color), 2)
        pen.setCosmetic(True)
        self.setPen(pen)
        c = QColor(color)
        c.setAlpha(35)
        self.setBrush(c)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(Qt.SizeAllCursor)
        self.label = QGraphicsSimpleTextItem(label, self)
        self.label.setBrush(QColor(color))
        self.label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.handle = _Handle(self)
        self.sync_handle()

    def sync_handle(self):
        r = self.rect()
        self.handle.setPos(r.bottomRight())
        self.label.setPos(r.left(), r.top() - 16)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.on_change()
        return super().itemChange(change, value)

    def box(self) -> list[int]:
        r = self.mapRectToScene(self.rect())
        return [round(r.left()), round(r.top()), round(r.right()), round(r.bottom())]


class _View(QGraphicsView):
    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)


class CalibrationDialog(QDialog):
    def __init__(self, profiles: ProfileStore, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrate OCR regions")
        self.resize(1400, 860)
        self.profiles = profiles
        self.settings = settings
        self.img = None
        self.items: dict[str, RoiItem] = {}
        self.preview: list = []

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        b_cap = QPushButton("Capture screen in 3 s")
        b_cap.clicked.connect(self.capture)
        b_load = QPushButton("Load screenshot…")
        b_load.clicked.connect(self.load)
        b_sample = QPushButton("Use sample (1080p)")
        b_sample.clicked.connect(lambda: self.set_image(load_image(SAMPLE)))
        b_sample.setEnabled(SAMPLE.exists())
        for b in (b_cap, b_load, b_sample):
            top.addWidget(b)
        top.addSpacing(20)
        self.res_label = QLabel()
        top.addWidget(self.res_label, 1)
        lay.addLayout(top)
        tip = QLabel("Open the in-game Pets window with a pet selected, then capture. Drag boxes to move them; "
                     "drag the corner square to resize; mouse wheel zooms. Set the first card's box, then the "
                     "spacing to the next card — the dashed preview should sit on every card.")
        tip.setWordWrap(True)
        tip.setProperty("muted", True)
        lay.addWidget(tip)

        split = QSplitter(Qt.Horizontal)
        self.scene = QGraphicsScene()
        self.view = _View(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setBackgroundBrush(QColor("#05080f"))
        split.addWidget(self.view)

        side = QWidget()
        sl = QVBoxLayout(side)
        grid_row = QHBoxLayout()
        self.pitch_x = self._spin(1, 2000)
        self.pitch_y = self._spin(1, 2000)
        self.cols = self._spin(1, 10)
        self.rows = self._spin(1, 20)
        for lbl, w in (("Spacing x", self.pitch_x), ("y", self.pitch_y), ("Cols", self.cols), ("Rows", self.rows)):
            grid_row.addWidget(QLabel(lbl))
            grid_row.addWidget(w)
        sl.addLayout(grid_row)
        btns = QHBoxLayout()
        b_test = QPushButton("Test OCR")
        b_test.clicked.connect(self.test)
        b_reset = QPushButton("Reset to default")
        b_reset.clicked.connect(self.reset)
        self.b_save = QPushButton("Save")
        self.b_save.clicked.connect(self.save)
        for b in (b_test, b_reset, self.b_save):
            btns.addWidget(b)
        sl.addLayout(btns)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        sl.addWidget(self.out, 1)
        split.addWidget(side)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

        if SAMPLE.exists():
            self.set_image(load_image(SAMPLE))

    def _spin(self, lo, hi):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.valueChanged.connect(self.redraw_preview)
        return s

    # ------------------------------------------------------------------ image sources
    def capture(self):
        self.hide()
        QApplication.processEvents()

        def grab():
            try:
                img = grab_monitor(self.settings.get("monitor_index", 1))
            finally:
                self.show()
            self.set_image(img)

        QTimer.singleShot(3000, grab)

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load screenshot", str(DATA / "sample_screens"),
                                              "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.set_image(load_image(path))

    def set_image(self, img):
        self.img = img
        profile, calibrated = self.profiles.get(img.width, img.height)
        self.scene.clear()
        self.items.clear()
        self.preview.clear()
        self.scene.addPixmap(QPixmap.fromImage(ImageQt(img)))
        self.scene.setSceneRect(0, 0, img.width, img.height)
        self.res_label.setText(f"{img.width}×{img.height} · " + ("saved calibration" if calibrated else
                                                                   "default regions (not calibrated yet)"))
        self.b_save.setText(f"Save for {img.width}×{img.height}")
        self.load_profile(profile)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    # ------------------------------------------------------------------ profile <-> items
    def load_profile(self, profile: dict):
        for it in self.items.values():
            self.scene.removeItem(it)
        self.items.clear()
        self.base = copy.deepcopy(profile)
        boxes = {k: profile[k] for k in ("name", "insight", "collection", "detail_panel", "genus_badge")}
        boxes["grid_area"] = profile["grid"]["area"]
        boxes["first_card"] = profile["grid"]["first_card"]
        for k, b in boxes.items():
            it = RoiItem(k, b, self.redraw_preview)
            self.scene.addItem(it)
            self.items[k] = it
        g = profile["grid"]
        for w, v in ((self.pitch_x, g["pitch"][0]), (self.pitch_y, g["pitch"][1]), (self.cols, g["cols"]),
                     (self.rows, g["rows"])):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.redraw_preview()

    def current_profile(self) -> dict:
        p = copy.deepcopy(self.base)
        for k in ("name", "insight", "collection", "detail_panel", "genus_badge"):
            p[k] = self.items[k].box()
        p["grid"]["area"] = self.items["grid_area"].box()
        p["grid"]["first_card"] = self.items["first_card"].box()
        p["grid"]["pitch"] = [self.pitch_x.value(), self.pitch_y.value()]
        p["grid"]["cols"] = self.cols.value()
        p["grid"]["rows"] = self.rows.value()
        return p

    def redraw_preview(self, *_):
        if not self.items:
            return
        for it in self.preview:
            self.scene.removeItem(it)
        self.preview.clear()
        dash = QPen(QColor("#3fbf6a"), 1, Qt.DashLine)
        dash.setCosmetic(True)
        corner = QPen(QColor("#ffb36a"), 1)
        corner.setCosmetic(True)
        for cb in card_boxes(self.current_profile()):
            for box, pen in ((cb.card, dash), (cb.level, corner), (cb.progress, corner)):
                x1, y1, x2, y2 = box
                r = self.scene.addRect(QRectF(x1, y1, x2 - x1, y2 - y1), pen)
                r.setZValue(-1 if pen is dash else 0)
                self.preview.append(r)

    # ------------------------------------------------------------------ actions
    def reset(self):
        if self.img is None:
            return
        self.load_profile(scale_profile(DEFAULT_PROFILE, self.img.width / 1920, self.img.height / 1080))

    def save(self):
        if self.img is None:
            return
        self.profiles.save(self.img.width, self.img.height, self.current_profile())
        self.res_label.setText(f"{self.img.width}×{self.img.height} · saved calibration")
        QMessageBox.information(self, "Saved", f"Regions saved for {self.img.width}×{self.img.height} "
                                               f"in config/ocr_profiles.json.")

    def test(self):
        if self.img is None:
            return
        from app.core.store import Store
        from app.ocr.engine import make_engine
        from app.ocr.scanner import Scanner

        class _Tmp(ProfileStore):
            def __init__(self, prof):
                self.profiles, self._p = {}, prof

            def get(self, w, h):
                return copy.deepcopy(self._p), True

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            store = self.parent().store if hasattr(self.parent(), "store") else Store()
            if not hasattr(self, "_engine"):
                self._engine = make_engine(self.settings.get("ocr_engine", "rapidocr"))
            sc = Scanner(store, self._engine, _Tmp(self.current_profile()), self.settings)
            s = sc.detail_scan(self.img)
            cards = sc.grid_read(self.img)
        except Exception as e:
            self.out.setPlainText(f"OCR failed: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        m = s.match
        lines = [
            f"Name read:  “{s.raw_name}”",
            f"Matched:    {m.name if m else '—'}  ({m.score:.0f}, {'auto' if m and m.auto else 'needs confirm'}"
            f"{' — ' + m.reason if m else ''})",
            f"Insight:    “{s.raw_insight}”  →  Lv {s.level}  {s.have}/{s.need}{'  MAX' if s.maxed else ''}",
            f"Collection: “{s.raw_collection}”  →  {s.collection}",
        ]
        if s.error:
            lines.append(f"Problem:    {s.error}")
        lines += ["", f"Cards ({len(cards)} read):"]
        for c in cards:
            prog = "MAX" if c.maxed else (f"{c.have}/{c.need}" if c.need else "?")
            lines.append(f"  row {c.row + 1} col {c.col + 1}:  Lv {c.level if c.level is not None else '?'}  {prog}")
        self.out.setPlainText("\n".join(lines))
