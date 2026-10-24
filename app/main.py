"""Entry point: tracker window + overlay + global hotkeys.

    python -m app.main
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QLockFile, QObject, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from app.core.store import DATA, Store, load_settings, save_settings  # noqa: E402
from app.paths import USER, USER_DATA, ensure_dirs, migrate_from  # noqa: E402
from app.hotkeys import HotkeyManager  # noqa: E402
from app.ui.overlay import Overlay  # noqa: E402
from app.ui.scan_controller import ScanController  # noqa: E402
from app.ui.theme import STYLESHEET, StoreSignals  # noqa: E402
from app.ui.tracker_window import MainWindow  # noqa: E402


def _pick_and_scan(win, scans):
    path, _ = QFileDialog.getOpenFileName(win, "Scan a screenshot", str(DATA / "sample_screens"),
                                          "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
    if path:
        scans.scan_file(path)


def _calibrate(win, scans, settings):
    from app.ui.calibration import CalibrationDialog

    dlg = CalibrationDialog(scans.profiles, settings, win)
    dlg.exec()


def _monitor_menu(sub, settings):
    from PySide6.QtGui import QActionGroup
    from app.ocr.capture import monitor_count

    group = QActionGroup(sub)
    try:
        n = monitor_count()
    except Exception:
        n = 1
    for i in range(1, n + 1):
        a = sub.addAction(f"Monitor {i}" + ("  (primary)" if i == 1 else ""))
        a.setCheckable(True)
        a.setChecked(settings.get("monitor_index", 1) == i)
        group.addAction(a)

        def pick(_=False, i=i):
            settings["monitor_index"] = i
            save_settings(settings)

        a.triggered.connect(pick)


def _field_menu(menu, settings, scans):
    from app.core.models import GENERA

    field = settings.setdefault("field", {})
    watch = menu.addAction("Watch for monsters while auto-scanning")
    watch.setCheckable(True)
    watch.setChecked(field.get("enabled", True))

    def set_watch(on):
        field["enabled"] = on
        save_settings(settings)
        scans._set_field.emit(field)

    watch.toggled.connect(set_watch)
    souls = menu.addAction("Track souls from chat (live to-max counts)")
    souls.setCheckable(True)
    souls.setChecked(field.get("track_souls", True))

    def set_souls(on):
        field["track_souls"] = on
        save_settings(settings)
        scans._set_field.emit(field)

    souls.toggled.connect(set_souls)
    sub = menu.addMenu("Alert me for genus")
    for g in GENERA:
        a = sub.addAction(g)
        a.setCheckable(True)
        a.setChecked(g in field.get("notify_genera", ["Cogni"]))

        def toggle(on, g=g):
            cur = set(field.get("notify_genera", ["Cogni"]))
            cur.add(g) if on else cur.discard(g)
            field["notify_genera"] = sorted(cur)
            save_settings(settings)

        a.toggled.connect(toggle)


def _open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _install_crash_log():
    """Write unexpected errors (and hard crashes) to crash.log in the data folder."""
    import faulthandler
    import traceback
    from datetime import datetime

    log = USER / "crash.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(log, "a", encoding="utf-8")
        fh.write(f"\n=== start {datetime.now().isoformat(timespec='seconds')} ===\n")
        fh.flush()
        faulthandler.enable(fh)  # native crashes (access violations) with the Python stack
        _install_crash_log.fh = fh
    except OSError:
        return

    def hook(etype, value, tb):
        fh.write(f"--- {datetime.now().isoformat(timespec='seconds')} unhandled error\n")
        fh.write("".join(traceback.format_exception(etype, value, tb)))
        fh.flush()
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = hook


def main() -> int:
    _install_crash_log()
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)  # required by the embedded live map
    app = QApplication(sys.argv)
    app.setApplicationName("AION 2 Pet Tracker")
    from PySide6.QtGui import QIcon
    from app.paths import ASSETS
    app.setWindowIcon(QIcon(str(ASSETS / "icon.png")))
    if sys.platform == "win32":  # own taskbar icon instead of python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Th3Ruthless.AION2PetTracker")
        # The game always gets the CPU first: run the whole tracker below normal priority.
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                BELOW_NORMAL_PRIORITY_CLASS)
    app.setStyleSheet(STYLESHEET)

    ensure_dirs()
    migrated = migrate_from()
    lock = QLockFile(str(USER / "tracker.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "AION 2 Pet Tracker", "The tracker is already running.")
        return 0
    app._single_instance_lock = lock  # keep it alive while the app runs

    if not (DATA / "pets.json").exists():
        QMessageBox.critical(None, "Pet Tracker",
                             "data/pets.json is missing.\nRun:  python tools/parse_pdf.py")
        return 1

    settings = load_settings()
    from app.atlas import load_cache
    store = Store(max_level=settings["max_level"], atlas=load_cache())
    parts = build(app, store, settings)
    if migrated:
        parts.win.statusBar().showMessage(f"Moved your progress to {USER}", 10000)
    if store.pdf_import_count:
        parts.win.statusBar().showMessage(f"Imported {store.pdf_import_count} ticked pets from the PDF as owned.", 10000)
    if os.environ.get("AION2_SELFTEST"):
        _self_test(app, parts, Path(os.environ["AION2_SELFTEST"]))
    return app.exec()


def _self_test(app, parts, report: Path):
    """Packaging check: OCR an image, load the live map, write what happened, quit.
    Run with AION2_TRACKER_HOME pointing at a scratch folder so real progress is untouched.
    Uses the sample screenshots when present (development), otherwise a generated image."""
    from PIL import Image, ImageDraw, ImageFont
    from PySide6.QtCore import QTimer

    out = []
    sample = DATA / "sample_screens" / "pets_konutin_worker_1080p.png"

    def run():
        parts.scans.message.connect(lambda m: out.append(f"scan: {m}"))
        if sample.exists():
            parts.scans.scan_file(str(sample))
        else:
            img = Image.new("RGB", (900, 120), (10, 14, 24))
            d = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 40)
            except OSError:
                font = ImageFont.load_default()
            d.text((20, 30), "Konutin Worker Lv. 1 (7/25)", font=font, fill=(240, 240, 240))
            lines = parts.scans._worker._scanner.engine.read(img) if parts.scans._worker._scanner else []
            out.append("ocr: " + " ".join(l.text for l in lines))
        # live map: open the Map tab on a pet and wait for the page
        pid = next((p.id for p in parts.store.pets.values() if p.name == "Manduri Trebuchet Worker"), None)
        parts.win.open_map(pid)
        view = parts.win.map.live_view
        if view is None:
            out.append("live map: not created")
        else:
            view.loadFinished.connect(lambda ok: out.append(f"live map loaded: {ok} {view.url().toString()}"))
        QTimer.singleShot(12000, finish)

    def finish():
        out.append(f"maps: {len(parts.store.maps)} | sounds: {parts.scans.sounds.enabled} | "
                   f"atlas: {parts.store.atlas_meta or 'not yet'}")
        report.write_text(" | ".join(out), encoding="utf-8")
        app.quit()

    QTimer.singleShot(3000, run)


class DiagnosticsRunner(QObject):
    """Builds the diagnostic zip on a background thread, then opens its folder."""
    finished = Signal(str, str)

    def __init__(self, store, settings, scans, win):
        super().__init__(win)
        self.store, self.settings, self.scans, self.win = store, settings, scans, win
        self.finished.connect(self._done)
        self._busy = False

    def run(self):
        import threading
        if self._busy:
            return
        self._busy = True
        self.win.statusBar().showMessage("Building diagnostic report (takes a few seconds)…")

        def work():
            try:
                from app.diagnostics import build_report
                from app.ocr.engine import make_engine
                path = build_report(self.store, self.settings, make_engine(threads=2), self.scans.profiles)
                self.finished.emit("ok", str(path))
            except Exception as e:
                self.finished.emit("err", f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _done(self, kind, val):
        self._busy = False
        if kind == "ok":
            self.win.statusBar().showMessage(f"Diagnostic report saved: {val}", 15000)
            _open_folder(Path(val).parent)
        else:
            self.win.statusBar().showMessage(f"Diagnostic report failed: {val}", 15000)


class AtlasUpdater(QObject):
    """Downloads the Pet Soul Atlas data in the background and merges it into the store."""
    finished = Signal(str, object)   # emitted from the download thread, handled on the GUI thread

    def __init__(self, store, scans, win):
        super().__init__(win)
        self.store, self.scans, self.win = store, scans, win
        self._thread = None
        self._quiet = False
        self.finished.connect(self._done)

    def update_if_stale(self, max_age_days: float = 3):
        from app.atlas import cache_age_days, load_cache
        age = cache_age_days(load_cache())
        if age is None or age > max_age_days:
            self.update(quiet=True)

    def update(self, quiet: bool = False):
        import threading

        if self._thread and self._thread.is_alive():
            return
        bar = self.win.statusBar()
        if not quiet:
            bar.showMessage("Updating from Pet Soul Atlas…")

        def work():
            from app.atlas import fetch
            try:
                result = ("ok", fetch())
            except Exception as e:  # network down, site changed, ...
                result = ("err", f"{type(e).__name__}: {e}")
            self.finished.emit(*result)

        self._quiet = quiet
        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def _done(self, kind: str, val):
        bar = self.win.statusBar()
        if kind == "err":
            if not self._quiet:
                bar.showMessage(f"Pet Soul Atlas update failed: {val}", 10000)
            return
        stats = self.store.apply_atlas(val)
        self.scans.reload_monsters()
        bar.showMessage(f"Pet Soul Atlas data ({val.get('meta', {}).get('builtAt', '?')}): "
                        f"{stats.get('added', 0)} extra monsters, {stats.get('genus_filled', 0)} genus filled.", 10000)


class Parts:
    """The running app's main objects (handy for tests)."""


def build(app, store, settings, show: bool = True, hotkeys=None) -> Parts:
    signals = StoreSignals(store)

    win = MainWindow(store, signals)
    overlay = Overlay(store, settings, win.tracker, win.route)
    win.overlay_show.setChecked(settings["overlay"]["visible"])
    win.overlay_show.toggled.connect(lambda on: overlay.setVisible(on))

    def move_mode(on: bool):
        if on and not overlay.isVisible():
            overlay.show()
            win.overlay_show.setChecked(True)
        overlay.set_interactive(on)

    win.overlay_move.toggled.connect(move_mode)
    overlay.interactive_changed.connect(lambda on: (win.overlay_move.blockSignals(True),
                                                     win.overlay_move.setChecked(on),
                                                     win.overlay_move.setText("Done moving / resizing" if on else
                                                                              "Move / resize  (drag it; side edges set width)"),
                                                     win.overlay_move.blockSignals(False)))

    def sync_size(scale: float):
        for s, a in win.overlay_sizes.items():
            a.blockSignals(True)
            a.setChecked(abs(s - scale) < 0.01)
            a.blockSignals(False)

    for s, a in win.overlay_sizes.items():
        a.triggered.connect(lambda _=False, s=s: overlay.set_scale(s))
    overlay.scale_changed.connect(sync_size)
    sync_size(overlay.scale)
    signals.changed.connect(lambda _: overlay.refresh())

    hotkeys = hotkeys or HotkeyManager(dict(settings["hotkeys"]))
    scans = ScanController(store, settings, overlay, hotkeys)
    scans.collection_read.connect(win.set_ingame_collection)
    scans.message.connect(lambda m: win.statusBar().showMessage(m, 8000))
    scans.pending_changed.connect(win.show_pending)
    scans.pet_scanned.connect(win.map.show_pet)   # the Map tab follows the pet you click in game

    show_map = win.overlay_menu.addAction("Show live map when a pet is selected")
    show_map.setCheckable(True)
    show_map.setChecked(settings["overlay"].get("show_map", True))

    def set_show_map(on):
        settings["overlay"]["show_map"] = on
        save_settings(settings)
        if not on:
            overlay.hide_map()

    show_map.toggled.connect(set_show_map)

    def sync_map_controls(on):
        for w in (show_map, win.overlay_map_btn):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)
        win.overlay_map_btn.setText("Overlay map: on" if on else "Overlay map: off")

    def toggle_map(on):
        set_show_map(on)
        sync_map_controls(on)

    show_map.toggled.disconnect()
    show_map.toggled.connect(toggle_map)
    win.overlay_map_btn.toggled.connect(toggle_map)
    sync_map_controls(settings["overlay"].get("show_map", True))
    win._toggle_overlay_map = lambda: toggle_map(not settings["overlay"].get("show_map", True))

    confirm = win.scan_menu.addAction("Ask before saving look-alike names")
    confirm.setCheckable(True)
    confirm.setChecked(settings.get("confirm_lookalikes", False))

    def set_confirm(on):
        settings["confirm_lookalikes"] = on
        save_settings(settings)

    confirm.toggled.connect(set_confirm)

    hide_cap = win.overlay_menu.addAction("Hide overlay from screenshots / streams")
    hide_cap.setToolTip("Off: Discord, OBS and screenshots show the overlay. On: only you see it.")
    hide_cap.setCheckable(True)
    hide_cap.setChecked(settings["overlay"].get("hide_from_capture", False))
    hide_cap.toggled.connect(overlay.set_capture_hidden)
    win.on_confirm = scans.confirm

    def set_auto_btn(on: bool):
        win.auto_btn.blockSignals(True)
        win.auto_btn.setChecked(on)
        win.auto_btn.setText("■  Stop auto-scan" if on else "▶  Auto-scan")
        win.auto_btn.blockSignals(False)
        if on and not overlay.isVisible():
            overlay.show()
            win.overlay_show.setChecked(True)

    win.auto_btn.toggled.connect(lambda on: scans.start_auto() if on else scans.stop_auto())
    scans.auto_changed.connect(set_auto_btn)

    delay = settings["ocr"]["scan_delay_ms"]
    menu = win.scan_menu
    menu.addAction(f"Auto-scan on / off   ({settings['hotkeys']['scan']})", scans.toggle_auto)
    menu.addAction(f"Scan once in {delay // 1000} s (switch to the game)", lambda: scans.scan_screen(delay))
    menu.addAction("Scan an image file…", lambda: _pick_and_scan(win, scans))
    menu.addSeparator()
    _monitor_menu(menu.addMenu("Game monitor"), settings)
    snd = menu.addAction("Sounds")
    snd.setCheckable(True)
    snd.setChecked(scans.sounds.enabled)

    def toggle_sound(on):
        scans.sounds.enabled = on
        settings.setdefault("sound", {})["enabled"] = on
        save_settings(settings)
        if on:
            scans.sounds.play("saved")

    snd.toggled.connect(toggle_sound)
    _field_menu(menu, settings, scans)
    menu.addSeparator()
    atlas = AtlasUpdater(store, scans, win)
    menu.addAction("Update from Pet Soul Atlas", atlas.update)
    QTimer.singleShot(4000, atlas.update_if_stale)
    menu.addAction("Calibrate OCR regions…", lambda: _calibrate(win, scans, settings))
    menu.addAction("Open OCR debug folder", lambda: _open_folder(USER_DATA / "ocr_debug"))
    diag = DiagnosticsRunner(store, settings, scans, win)
    menu.addAction("Save diagnostic report… (send it if auto-scan doesn't work)", diag.run)
    menu.addAction("Open my data folder", lambda: _open_folder(USER_DATA.parent))

    def on_hotkey(action: str):
        if action == "toggle_overlay":
            overlay.toggle_visible()
            win.overlay_show.blockSignals(True)
            win.overlay_show.setChecked(overlay.isVisible())
            win.overlay_show.blockSignals(False)
        elif action == "toggle_overlay_map":
            win._toggle_overlay_map()
        elif action == "overlay_interactive":
            if not overlay.isVisible():
                overlay.show()
            overlay.toggle_interactive()
        elif action == "scan":
            if not overlay.isVisible():
                overlay.show()
                win.overlay_show.setChecked(True)

    hotkeys.triggered.connect(on_hotkey)
    hotkeys.failed.connect(lambda msg: win.statusBar().showMessage(msg, 10000))
    hotkeys.start(app)

    if show:
        win.show()
        if settings["overlay"]["visible"]:
            overlay.show()

    app.aboutToQuit.connect(scans.shutdown)
    app.aboutToQuit.connect(hotkeys.stop)
    app.aboutToQuit.connect(store.close)
    parts = Parts()
    parts.win, parts.overlay, parts.scans, parts.hotkeys, parts.store = win, overlay, scans, hotkeys, store
    return parts


if __name__ == "__main__":
    sys.exit(main())
