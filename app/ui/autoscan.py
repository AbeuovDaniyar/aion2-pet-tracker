"""Auto-scan, on its own thread. Two modes, switched automatically:

* PETS  - the in-game Pets window is open. ~4 times a second grab only the pet panel strip,
          compare a tiny thumbnail with the last one, and only when it changed and then held
          still for one tick grab the screen and OCR it. Each new pet is read and saved.
* FIELD - out in the world. Every interval, grab a few small regions: the target frame (or the
          whole middle of the screen in "full" mode), the "Pet Insight" line (to notice the Pets
          window) and the chat box. Only regions that changed since the last read are OCR'd.

Everything is built to stay out of the game's way: small screen grabs, OCR only on change,
a low-priority thread, and a capped number of OCR threads (see app.main / ocr_threads).
"""
from __future__ import annotations

import time
import traceback
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app.ocr.chat import ChatTracker, chat_lines, soul_gains
from app.ocr.field import MonsterIndex, find_monsters, is_pets_window
from app.ocr.scanner import Scanner, panel_signature, signature_diff

CHANGE_THRESHOLD = 6.0      # mean grey-level difference that counts as "a different panel"
PART_THRESHOLD = 3.0        # same, for field regions (target frame, chat)
COLLECTION_EVERY_S = 15     # re-read "Collection Status x/y" at most this often
IDLE_STOP_S = 10 * 60       # (field mode off) stop by itself after this long without seeing a pet

# Default field regions as screen fractions (x1, y1, x2, y2), measured at 1920x1080.
TARGET_REGION = (0.36, 0.01, 0.64, 0.09)     # target frame: level, name, distance, genus tag
FULL_REGION = (0.02, 0.02, 0.86, 0.76)       # whole middle of the screen (nameplates)
CHAT_REGION = (0.005, 0.80, 0.2, 0.95)


def _thumb(img, size=(48, 12)):
    import numpy as np
    from PIL import Image

    return np.asarray(img.convert("L").resize(size, Image.BILINEAR), dtype=np.int16).ravel()


class AutoScanWorker(QObject):
    result = Signal(object)         # DetailScan with a pet name
    field_hits = Signal(object)     # list[FieldHit] from one field read (may be empty)
    souls = Signal(object)          # list[SoulGain] newly seen in chat
    mode_changed = Signal(str)      # "pets" | "field"
    status = Signal(str)            # short human status for the overlay
    stopped = Signal(str)           # reason
    error = Signal(str)

    def __init__(self, scanner_factory, interval_ms: int = 250, field: Optional[dict] = None):
        super().__init__()
        self._factory = scanner_factory
        self._scanner: Optional[Scanner] = None
        self.interval_ms = interval_ms
        self.field = dict(field or {})
        self._index: Optional[MonsterIndex] = None
        self._masks: list[tuple[int, int, int, int]] = []  # screen rects to black out (our overlay)
        self._chat = ChatTracker()
        self._pet_names: Optional[dict[str, str]] = None
        self._mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        self._timer: Optional[QTimer] = None
        self._sct = None
        self.monitor_index = 1
        self.stats = {"grabs": 0, "full_grabs": 0, "ocr": 0, "skipped": 0}
        self._reset()

    def _reset(self):
        self._last_sig = None       # signature of the last pet panel we OCR'd
        self._candidate = None      # changed signature waiting to hold still
        self._busy = False
        self._backoff_until = 0.0
        self._last_collection = 0.0
        self._last_seen = time.monotonic()
        self._waiting_reported = False
        self._last_field = 0.0
        self._part_sigs: dict[str, object] = {}
        self._last_hits: list = []
        self.mode = "field" if self.field.get("enabled", True) else "pets"

    # ------------------------------------------------------------------ setup
    @Slot()
    def warm_up(self):
        try:
            if self._scanner is None:
                self._scanner = self._factory()
            from PIL import Image
            self._scanner.engine.read(Image.new("RGB", (830, 240)))
        except Exception:  # pragma: no cover
            traceback.print_exc()

    @Slot(object)
    def scan_once(self, img):
        """Single scan of a given image (menu / file scans share this thread and engine)."""
        try:
            if self._scanner is None:
                self._scanner = self._factory()
            self.result.emit(self._scanner.detail_scan(img))
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self.error.emit(f"{type(e).__name__}: {e}")

    @Slot(int)
    def start(self, monitor_index: int):
        import mss

        self.monitor_index = monitor_index
        self._reset()
        if self._scanner is None:
            self._scanner = self._factory()
        if self._sct is None:
            self._sct = (getattr(mss, "MSS", None) or mss.mss)()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
        self._timer.start(self.interval_ms)
        self.mode_changed.emit(self.mode)
        if self.mode == "field":
            self.status.emit("Auto-scan on — watching for monsters · open the Pets window to scan pets")
        else:
            self.status.emit("Auto-scan on — open the Pets window and click pets")

    @Slot(object)
    def set_field(self, field: dict):
        self.field = dict(field)
        self._part_sigs.clear()

    @Slot(object)
    def set_masks(self, rects):
        """Screen rects (global pixels) to black out before a field read, e.g. our own overlay."""
        self._masks = list(rects)

    def _set_mode(self, mode: str):
        if mode != self.mode:
            self.mode = mode
            self._last_sig = self._candidate = None
            self._last_field = 0.0
            self._part_sigs.clear()
            self.mode_changed.emit(mode)

    @Slot()
    def stop(self, reason: str = "stopped"):
        if self._timer and self._timer.isActive():
            self._timer.stop()
            self.stopped.emit(reason)

    # ------------------------------------------------------------------ screen grabs
    def _monitor(self) -> dict:
        if self._sct is not None:
            mons = self._sct.monitors
            self._mon = mons[self.monitor_index] if 0 < self.monitor_index < len(mons) else mons[1]
        return self._mon

    @property
    def _mon_origin(self):
        return self._mon["left"], self._mon["top"]

    def _grab(self):
        """Whole monitor. Only used when an OCR read actually needs it."""
        from PIL import Image

        mon = self._monitor()
        shot = self._sct.grab(mon)
        self.stats["full_grabs"] += 1
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def _grab_box(self, box):
        """A small part of the monitor; box in monitor pixels (x1, y1, x2, y2)."""
        from PIL import Image

        if self._sct is None:  # tests: crop from the injected screenshot instead of the real screen
            img = self._grab()
            self._mon = {"left": 0, "top": 0, "width": img.width, "height": img.height}
            return img.crop(tuple(int(v) for v in box))
        mon = self._monitor()
        x1, y1, x2, y2 = (int(v) for v in box)
        rect = {"left": mon["left"] + x1, "top": mon["top"] + y1, "width": max(1, x2 - x1), "height": max(1, y2 - y1)}
        shot = self._sct.grab(rect)
        self.stats["grabs"] += 1
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def _profile(self):
        mon = self._monitor()
        return self._scanner.profiles.get(mon["width"], mon["height"])[0]

    # ------------------------------------------------------------------ PETS mode
    def _panel_sig_from(self, crop, origin, profile):
        """Same thumbnail as panel_signature(), computed from a grab of just the panel area."""
        import numpy as np
        from PIL import Image

        ox, oy = origin
        parts = []
        for key, size in (("name", (64, 10)), ("insight", (64, 6))):
            x1, y1, x2, y2 = profile[key]
            sub = crop.crop((x1 - ox, y1 - oy, x2 - ox, y2 - oy)).convert("L").resize(size, Image.BILINEAR)
            parts.append(np.asarray(sub, dtype=np.int16).ravel())
        return np.concatenate(parts)

    def _tick(self):
        if self._busy:
            return
        now = time.monotonic()
        if self.mode == "field":
            self._field_tick(now)
            return
        if not self.field.get("enabled", True) and now - self._last_seen > IDLE_STOP_S:
            self.stop("no Pets window for 10 minutes")
            return
        try:
            profile = self._profile()
            n, i = profile["name"], profile["insight"]
            box = (min(n[0], i[0]), min(n[1], i[1]), max(n[2], i[2]), max(n[3], i[3]))
            sig = self._panel_sig_from(self._grab_box(box), box[:2], profile)
            if signature_diff(sig, self._last_sig) < CHANGE_THRESHOLD:
                return                                  # same panel as last read
            if signature_diff(sig, self._candidate) >= CHANGE_THRESHOLD:
                self._candidate = sig                   # changed: wait one tick for it to settle
                return
            if now < self._backoff_until:
                return
            self._busy = True
            img = self._grab()
            want_coll = now - self._last_collection > COLLECTION_EVERY_S
            scan = self._scanner.detail_scan(img, with_collection=want_coll, fast=True)
            self.stats["ocr"] += 1
            self._last_sig, self._candidate = sig, None
            if scan.name:
                self._last_seen = time.monotonic()
                self._backoff_until = 0.0
                self._waiting_reported = False
                if want_coll:
                    self._last_collection = now
                self.result.emit(scan)
            elif self.field.get("enabled", True):
                self._set_mode("field")            # Pets window closed: back to watching the world
            else:
                self._backoff_until = time.monotonic() + 1.5
                if not self._waiting_reported:
                    self._waiting_reported = True
                    self.status.emit("Auto-scan on — waiting for the Pets window")
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self._busy = False

    # ------------------------------------------------------------------ FIELD mode
    def _field_parts(self, W: int, H: int, profile) -> list[tuple[str, tuple, float]]:
        """[(name, box in monitor px, scale)] for this read."""
        def frac(f):
            return (int(f[0] * W), int(f[1] * H), int(f[2] * W), int(f[3] * H))

        full = self.field.get("mode", "target") == "full"
        main = frac(self.field.get("region", FULL_REGION)) if full else \
            frac(self.field.get("target_region", TARGET_REGION))
        ins = profile["insight"]
        parts = [("main", main, self.field.get("scale", 1.5)),
                 ("insight", (ins[0], ins[1], ins[2], ins[3]), 1.5)]
        if self.field.get("track_souls", True):
            parts.append(("chat", frac(self.field.get("chat_region", CHAT_REGION)), 1.0))
        return parts

    def _field_tick(self, now: float):
        if now - self._last_field < self.field.get("interval_ms", 1500) / 1000:
            return
        self._busy = True
        try:
            self._last_field = now
            mon = self._monitor()
            if self._scanner is None:
                self._scanner = self._factory()
            profile = self._profile()
            parts = self._field_parts(mon["width"], mon["height"], profile)
            crops = []
            for name, box, sc in parts:
                crop = self._mask(self._grab_box(box), box)
                sig = _thumb(crop)
                if signature_diff(sig, self._part_sigs.get(name)) >= PART_THRESHOLD:
                    crops.append((name, box, sc, crop, sig))
            if not crops:
                self.stats["skipped"] += 1
                if self._last_hits:
                    self.field_hits.emit(self._last_hits)   # same target as before: keep it "nearby"
                return
            by_part = self._ocr_parts(crops)
            for name, _, _, _, sig in crops:
                self._part_sigs[name] = sig
            if "insight" in by_part and is_pets_window(by_part["insight"]):
                self._enter_pets(now)
                return
            if "chat" in by_part:
                self._handle_chat(by_part["chat"])
            if "main" in by_part:
                self._last_hits = find_monsters(by_part["main"], self._index_get())
            self.field_hits.emit(self._last_hits)
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self._busy = False

    def _enter_pets(self, now: float):
        self._set_mode("pets")
        # Read the selected pet straight away instead of waiting for the next ticks.
        img = self._grab()
        profile, _ = self._scanner.profiles.get(img.width, img.height)
        scan = self._scanner.detail_scan(img, with_collection=True, fast=True)
        self.stats["ocr"] += 1
        self._last_sig = panel_signature(img, profile)
        if scan.name:
            self._last_seen = time.monotonic()
            self._last_collection = now
            self.result.emit(scan)

    def _index_get(self) -> MonsterIndex:
        if self._index is None:
            self._index = MonsterIndex(self._scanner.store)
        return self._index

    def _mask(self, crop, box):
        if not self._masks:
            return crop
        from PIL import ImageDraw

        d = ImageDraw.Draw(crop)
        ox, oy = self._mon_origin[0] + box[0], self._mon_origin[1] + box[1]
        for x1, y1, x2, y2 in self._masks:
            d.rectangle((x1 - ox, y1 - oy, x2 - ox, y2 - oy), fill=(0, 0, 0))
        return crop

    def _ocr_parts(self, crops) -> dict[str, list]:
        """One OCR pass over the changed regions stacked vertically. Boxes come back in monitor pixels."""
        from PIL import Image

        gap = 30
        scaled = []
        for name, box, sc, crop, _ in crops:
            img = crop.resize((int(crop.width * sc), int(crop.height * sc)), Image.LANCZOS) if sc != 1 else crop
            scaled.append((name, box, sc, img))
        canvas = Image.new("RGB", (max(i.width for *_, i in scaled), sum(i.height for *_, i in scaled)
                                   + gap * (len(scaled) - 1)), (0, 0, 0))
        spans, y = [], 0
        for name, box, sc, img in scaled:
            canvas.paste(img, (0, y))
            spans.append((y, y + img.height, name, box, sc))
            y += img.height + gap
        self.stats["ocr"] += 1
        out: dict[str, list] = {name: [] for name, *_ in scaled}
        for ln in self._scanner.engine.read(canvas):
            x0, y0, x1, y1 = ln.box
            cy = (y0 + y1) / 2
            for top, bottom, name, box, sc in spans:
                if top <= cy <= bottom:
                    ln.box = (box[0] + x0 / sc, box[1] + (y0 - top) / sc, box[0] + x1 / sc, box[1] + (y1 - top) / sc)
                    out[name].append(ln)
                    break
        return out

    def read_field(self, img):
        """Field read of a whole screenshot (tests, single scans). Returns (main_lines, chat_lines or None)."""
        if self._scanner is None:
            self._scanner = self._factory()
        profile, _ = self._scanner.profiles.get(img.width, img.height)
        parts = self._field_parts(img.width, img.height, profile)
        crops = [(name, box, sc, self._mask(img.crop(box), box), None) for name, box, sc in parts]
        by_part = self._ocr_parts(crops)
        main = by_part.get("main", []) + by_part.get("insight", [])
        return main, (by_part.get("chat") if self.field.get("track_souls", True) else None)

    def _handle_chat(self, lines):
        if self._pet_names is None:
            self._pet_names = {pid: p.name for pid, p in self._scanner.store.pets.items()}
        new = self._chat.feed(chat_lines(lines))
        if new:
            gains = soul_gains(new, self._pet_names)
            if gains:
                self.souls.emit(gains)

    @Slot()
    def shutdown(self):
        if self._timer:
            self._timer.stop()
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
