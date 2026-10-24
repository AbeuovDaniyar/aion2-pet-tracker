"""Glue between hotkeys, the scan worker thread, the overlay, sounds and the store."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app.core.store import Store
from app.ocr.capture import ProfileStore, grab_monitor, load_image
from app.ocr.scanner import DetailScan, Scanner
from app.ui.autoscan import AutoScanWorker
from app.ui.sounds import Sounds

CONFIRM_ACTIONS = ("confirm_yes", "confirm_no", "pick_1", "pick_2", "pick_3")


class _NoEngine:
    """The GUI-thread scanner only writes results; OCR runs on the worker thread."""
    name = "none"

    def read(self, img):  # pragma: no cover
        raise RuntimeError("OCR must run on the worker thread")

    read_single = read


class ScanController(QObject):
    pending_changed = Signal(object)        # DetailScan | None (first in queue)
    collection_read = Signal(int, int)
    message = Signal(str)                   # status-bar text
    auto_changed = Signal(bool)
    _scan_image = Signal(object)            # -> worker.scan_once
    _start_auto = Signal(int)               # -> worker.start
    _stop_auto = Signal()                   # -> worker.stop
    _set_masks = Signal(object)             # -> worker.set_masks
    _set_field = Signal(object)             # -> worker.set_field
    mode_changed = Signal(str)              # "pets" | "field"
    pet_scanned = Signal(str)               # pet id saved from the Pets window

    def __init__(self, store: Store, settings: dict, overlay, hotkeys):
        super().__init__()
        self.store = store
        self.settings = settings
        self.overlay = overlay
        self.hotkeys = hotkeys
        self.profiles = ProfileStore()
        self.sounds = Sounds(settings.get("sound", {}).get("enabled", True))
        self.busy = False
        self.auto = False
        self.saved_this_session: set[str] = set()
        self.queue: list[DetailScan] = []
        self.writer = Scanner(store, _NoEngine(), self.profiles, settings)

        self.nearby: dict[str, tuple] = {}         # monster -> (FieldHit, last seen)
        self.souls_this_session = 0
        self._unknown_noted: set[str] = set()
        self._alerted: dict[str, float] = {}       # pet_id -> last alert time
        self.mode = "pets"

        from app.ocr.engine import make_engine
        threads = settings.get("ocr_threads", 4)
        make = lambda: Scanner(store, make_engine(settings.get("ocr_engine", "rapidocr"), threads),
                               self.profiles, settings)
        self._thread = QThread()
        self._thread.setObjectName("ocr-worker")
        self._worker = AutoScanWorker(make, settings["ocr"].get("auto_interval_ms", 250), settings.get("field"))
        self._worker.moveToThread(self._thread)
        self._scan_image.connect(self._worker.scan_once)
        self._start_auto.connect(self._worker.start)
        self._stop_auto.connect(self._worker.stop)
        self._worker.result.connect(self._on_result)
        self._worker.status.connect(self._on_status)
        self._worker.stopped.connect(self._on_stopped)
        self._worker.error.connect(self._on_error)
        self._worker.field_hits.connect(self._on_field)
        self._worker.souls.connect(self._on_souls)
        self._worker.mode_changed.connect(self._on_mode)
        self._set_masks.connect(self._worker.set_masks)
        self._set_field.connect(self._worker.set_field)
        overlay.geometry_changed.connect(self._send_masks)
        self._expire = QTimer(self, interval=1000, timeout=self._expire_nearby)
        self._thread.started.connect(self._worker.warm_up)
        self._thread.start(QThread.LowestPriority)
        hotkeys.triggered.connect(self._on_hotkey)

    @property
    def pending(self) -> Optional[DetailScan]:
        return self.queue[0] if self.queue else None

    def reload_monsters(self):
        """Atlas data changed: the field matcher rebuilds its monster list on the next read."""
        self._worker._index = None

    def shutdown(self):
        self._unregister_confirm()
        self._stop_auto.emit()
        QTimer.singleShot(0, self._worker.shutdown)
        self._thread.quit()
        self._thread.wait(3000)

    # ------------------------------------------------------------------ auto-scan
    def toggle_auto(self):
        self.stop_auto() if self.auto else self.start_auto()

    def start_auto(self):
        if self.auto:
            return
        self.auto = True
        self.saved_this_session.clear()
        self.souls_this_session = 0
        self._unknown_noted: set[str] = set()
        self.sounds.play("start")
        self._send_masks()
        self._set_field.emit(self.settings.get("field", {}))
        self._start_auto.emit(self.settings.get("monitor_index", 1))
        self._expire.start()
        self._unknown_noted: set[str] = set()
        self.overlay.set_scan_state("field" if self.settings.get("field", {}).get("enabled", True) else "pets")
        self.auto_changed.emit(True)

    def stop_auto(self):
        if self.auto:
            self._stop_auto.emit()

    def _on_stopped(self, reason: str):
        self.auto = False
        self._expire.stop()
        self.nearby.clear()
        self.overlay.set_nearby_rows([])
        self.overlay.set_scan_state("")
        self.overlay.hide_map()
        self.sounds.play("stop")
        n = len(self.saved_this_session)
        souls = f" · {self.souls_this_session} souls tracked" if self.souls_this_session else ""
        self.overlay.show_toast(f"Auto-scan off · {n} pet{'s' if n != 1 else ''} saved{souls}", 3000)
        self.message.emit(f"Auto-scan off ({reason}). {n} pets saved this session{souls}.")
        self.auto_changed.emit(False)

    # ------------------------------------------------------------------ field mode
    def _on_mode(self, mode: str):
        self.mode = mode
        self.mode_changed.emit(mode)
        self.overlay.set_scan_state(mode)
        if mode == "pets":
            self.nearby.clear()
            self.overlay.set_nearby_rows([])
        else:
            self.overlay.hide_map()   # no live map while fighting

    def _send_masks(self):
        """Tell the worker where our overlay is so field reads never see its monster names."""
        o = self.overlay
        if not o.isVisible():
            self._set_masks.emit([])
            return
        r = o.frameGeometry()
        dpr = o.devicePixelRatioF()
        self._set_masks.emit([(int(r.left() * dpr), int(r.top() * dpr),
                               int((r.right() + 1) * dpr), int((r.bottom() + 1) * dpr))])

    def _on_field(self, hits):
        now = time.monotonic()
        alerts = []
        for h in hits:
            self.nearby[h.monster] = (h, now)
            self._learn_genus(h)
            alerts += self._alerts_for(h, now)
        self._render_nearby()
        if alerts:
            self.sounds.play("alert")   # one sound per read, however many pets
            body = "<br>".join(f"{self.overlay.pill(g)} <b>{pet.name}</b> nearby · {self._short_left(pet.id)}"
                               for g, _, pet in alerts)
            if not self.queue:
                self.overlay.show_toast(body, 5000, accent="#9d49df")
            for g, h, pet in alerts:
                self.message.emit(f"{g} pet nearby: {h.monster} → {pet.name} ({self.store.field_text(pet.id)})")

    def _on_souls(self, gains):
        """Souls read from chat ("Obtained 1 X Soul Points.")."""
        lines, big = [], None
        for g in gains:
            r = self.store.add_souls(g.pet_id, g.amount, g.text)
            name, left = g.pet_name, self.store.field_text(g.pet_id)
            res = r["result"]
            if res == "added":
                self.souls_this_session += g.amount   # shown by the numbers in the nearby list, no toast
            elif res == "unlocked":
                self.souls_this_session += g.amount
                lines.append(f"New pet: <b>{name}</b> · {left}")
            elif res == "levelup":
                self.souls_this_session += g.amount
                stm = self.store.souls_to_max(g.pet_id)
                big = big or ("saved", f"⬆ <b>{name}</b> reached Lv {r['level']}"
                              + (f" · {stm} to max" if stm is not None else ""), None)
            elif res == "maxed":
                self.souls_this_session += g.amount
                big = ("saved", f"★ <b>{name}</b> is MAX!", "#ffdf85")
            elif res == "unknown_level" and g.pet_id not in self._unknown_noted:
                self._unknown_noted.add(g.pet_id)  # say it once per session, not on every soul
                lines.append(f"<b>{name}</b>: scan it once in the Pets window to track souls")
            self.message.emit(f"Soul: +{g.amount} {name} → {res} · {left}")
        if self.nearby:
            self._render_nearby()
        if self.queue:
            return  # a scan is waiting for an answer; keep that toast up
        if big:
            sound, text, accent = big
            self.sounds.play(sound)
            self.overlay.show_toast(text + ("<br>" + "<br>".join(lines) if lines else ""), 5000, accent=accent)
        elif lines:
            self.overlay.show_toast("<br>".join(lines), 3000)

    def _expire_nearby(self):
        keep = self.settings.get("field", {}).get("keep_s", 10)
        now = time.monotonic()
        old = [m for m, (_, t) in self.nearby.items() if now - t > keep]
        for m in old:
            del self.nearby[m]
        if old:
            self._render_nearby()

    def _render_nearby(self):
        """One line per pet: genus, name, souls to max. Alert genera first, maxed pets last."""
        genera = set(self.settings.get("field", {}).get("notify_genera", ["Cogni"]))
        rows: dict[str, dict] = {}
        for h, _ in self.nearby.values():
            for pid in h.pet_ids:
                pet = self.store.pets[pid]
                pr = self.store.progress(pid)
                genus = pet.genus or h.game_genus
                row = rows.get(pid)
                if row is None:
                    rows[pid] = {"name": pet.name, "genus": genus, "maxed": pr.maxed,
                                 "text": self._short_left(pid), "targeted": h.targeted,
                                 "alert": genus in genera and not pr.maxed, "new": not pr.unlocked}
                elif h.targeted:
                    row["targeted"] = True
        order = sorted(rows.values(), key=lambda r: (r["maxed"], not r["alert"], not r["targeted"], r["name"]))
        self.overlay.set_nearby_rows(order)

    def _short_left(self, pid: str) -> str:
        pr = self.store.progress(pid)
        if pr.maxed:
            return "MAX"
        left = self.store.souls_to_max(pid)
        if left is None:
            return "not owned" if not pr.unlocked else "Lv ?"
        return f"{left} to max"

    def _alerts_for(self, h, now: float) -> list:
        """[(genus, hit, pet)] for pets in the alert genera that aren't maxed and weren't alerted recently."""
        f = self.settings.get("field", {})
        genera = set(f.get("notify_genera", ["Cogni"]))
        cooldown = f.get("alert_cooldown_s", 90)
        out = []
        for pid in h.pet_ids:
            pet = self.store.pets[pid]
            genus = pet.genus or h.game_genus
            if genus not in genera or self.store.progress(pid).maxed:
                continue
            if now - self._alerted.get(pid, -1e9) < cooldown:
                continue
            self._alerted[pid] = now
            out.append((genus, h, pet))
        return out

    def _learn_genus(self, h):
        """The game shows the target's genus under the target frame; use it to fill unknown / guessed genus."""
        if not h.game_genus or len(h.pet_ids) != 1:
            return
        pet = self.store.pets[h.pet_ids[0]]
        if pet.genus == h.game_genus and pet.genus_confidence in ("high", "override"):
            return
        if pet.genus_confidence in (None, "low") or pet.genus is None:
            old = pet.genus
            self.store.set_genus_override(pet.id, h.game_genus)
            self.message.emit(f"Genus learned from the game: {pet.name} is {h.game_genus}"
                              + (f" (was guessed {old})" if old and old != h.game_genus else ""))
        elif pet.genus != h.game_genus:
            self.message.emit(f"Note: the game shows {pet.name} as {h.game_genus}, the guide says {pet.genus}.")

    def _on_status(self, text: str):
        pass  # the overlay's status pill already shows what auto-scan is doing

    def _on_error(self, text: str):
        self.busy = False
        self.overlay.show_toast(f"Scan error: {text}", 6000)
        self.message.emit(f"Scan error: {text}")

    # ------------------------------------------------------------------ single scans
    def scan_screen(self, delay_ms: int = 0):
        if self.auto:
            self.message.emit("Auto-scan is already running.")
            return
        if self.busy:
            self.overlay.show_toast("Still reading the last scan…", 1500)
            return
        if delay_ms:
            self.message.emit(f"Scanning the screen in {delay_ms // 1000} s — switch to the game.")
            QTimer.singleShot(delay_ms, lambda: self.scan_screen(0))
            return
        hide = self.overlay.isVisible() and not self.overlay.capture_excluded
        if hide:
            self.overlay.hide()
            QApplication.processEvents()
        try:
            img = grab_monitor(self.settings.get("monitor_index", 1))
        except Exception as e:
            self.overlay.show_toast(f"Screen capture failed: {e}")
            return
        finally:
            if hide:
                self.overlay.show()
        self.busy = True
        self.overlay.show_toast("Scanning…", 0)
        self._scan_image.emit(img)

    def scan_file(self, path: str):
        if self.busy:
            return
        try:
            img = load_image(path)
        except Exception as e:
            self.message.emit(f"Could not open {path}: {e}")
            return
        self.busy = True
        self.overlay.show_toast("Scanning image…", 0)
        self._scan_image.emit(img)

    # ------------------------------------------------------------------ results
    def _on_result(self, scan: DetailScan):
        self.busy = False
        if scan.collection:
            self.collection_read.emit(*scan.collection)
        if scan.error and not scan.match:
            if not self.auto:
                self.writer.apply(scan, None, accepted=False)
                hint = "" if scan.calibrated or scan.resolution == "1920x1080" else \
                    f" ({scan.resolution} isn't calibrated yet — try Scan ▸ Calibrate)"
                self.overlay.show_toast(f"{scan.error}{hint}", 6000)
                self.message.emit(scan.error + hint)
            return
        if scan.auto_accept:
            self._finish(scan, scan.match.pet_id)
            return
        if any(q.match and scan.match and q.match.pet_id == scan.match.pet_id and q.name == scan.name
               for q in self.queue):
            return  # already waiting for an answer on this one
        self.queue.append(scan)
        self.sounds.play("confirm")
        if len(self.queue) == 1:
            self._register_confirm()
        self._show_pending()

    def _show_pending(self):
        scan = self.pending
        self.pending_changed.emit(scan)
        if scan is None:
            return
        hk = self.settings["confirm_hotkeys"]
        more = f" <span style='color:#9eafc8'>(+{len(self.queue) - 1} more waiting)</span>" if len(self.queue) > 1 else ""
        lines = [f"<b>Check this scan:</b> {scan.summary()}{more}",
                 f"<span style='color:#9eafc8'>Read “{scan.name}” — {scan.match.reason if scan.match else scan.error}</span>"]
        for i, c in enumerate((scan.match.candidates if scan.match else [])[:3], 1):
            lines.append(f"{hk[f'pick_{i}'].upper()}: {c.name} <span style='color:#9eafc8'>({c.score:.0f})</span>")
        lines.append(f"{hk['confirm_yes'].upper()} = first choice · {hk['confirm_no'].upper()} = discard"
                     " · or use the buttons in the tracker")
        self.overlay.show_toast("<br>".join(lines), 0)

    def confirm(self, pet_id: Optional[str]):
        if not self.queue:
            return
        scan = self.queue.pop(0)
        if pet_id is None:
            self.writer.apply(scan, None, accepted=False)
            self.overlay.show_toast("Scan discarded.", 1500)
        else:
            self._finish(scan, pet_id)
        if self.queue:
            self._show_pending()
        else:
            self._unregister_confirm()
            self.pending_changed.emit(None)

    def _finish(self, scan: DetailScan, pet_id: str):
        status = self.writer.apply(scan, pet_id, accepted=True)
        name = self.store.pets[pet_id].name
        pet = self.store.pets[pet_id]
        self.overlay.show_pet_map(pet.name, pet.genus, pet.links.get("atlas", ""))
        self.pet_scanned.emit(pet_id)
        if status == "saved":
            self.saved_this_session.add(pet_id)
            self.sounds.play("saved")
            n = len(self.saved_this_session)
            count = f" · {n} this session" if self.auto else ""
            left = self.store.souls_to_max(pet_id)
            lvl = "MAX" if scan.maxed else f"Lv {scan.level}" if scan.level else ""
            tail = f" · {left} to max" if left else ""
            text = f"✓ <b>{name}</b> {lvl}{tail}"
        else:
            self.sounds.play("confirm")
            text = f"{name}: {status}"
        if not self.queue:
            self.overlay.show_toast(text, 4000)
        self.message.emit(text)

    # ------------------------------------------------------------------ hotkeys
    def _on_hotkey(self, action: str):
        if action == "scan":
            self.toggle_auto()
        elif self.pending and action in CONFIRM_ACTIONS:
            cands = self.pending.match.candidates if self.pending.match else []
            if action == "confirm_no":
                self.confirm(None)
            elif action == "confirm_yes":
                self.confirm(self.pending.match.pet_id if self.pending.match else None)
            else:
                i = int(action[-1]) - 1
                if i < len(cands):
                    self.confirm(cands[i].pet_id)

    def _register_confirm(self):
        for a in CONFIRM_ACTIONS:
            if a not in self.hotkeys.bindings:
                self.hotkeys.register(a, self.settings["confirm_hotkeys"][a])

    def _unregister_confirm(self):
        for a in CONFIRM_ACTIONS:
            if a in self.hotkeys.bindings:
                self.hotkeys.unregister(a)
