"""Global hotkeys.

On Windows this uses the RegisterHotKey API: no keyboard hook, no input is
read from or sent to the game, Windows just tells us when the combo is pressed.
Elsewhere it falls back to pynput's listener.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

MOD = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
VK_SPECIAL = {f"f{i}": 0x6F + i for i in range(1, 13)} | {
    "space": 0x20, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E,
    "pageup": 0x21, "pagedown": 0x22,
}


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+shift+p' -> (modifiers, virtual key)."""
    mods, vk = 0, None
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MOD:
            mods |= MOD[part]
        elif part in VK_SPECIAL:
            vk = VK_SPECIAL[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"unsupported key {part!r} in hotkey {combo!r}")
    if vk is None:
        raise ValueError(f"hotkey {combo!r} has no main key")
    return mods, vk


class HotkeyManager(QObject):
    triggered = Signal(str)  # action name
    failed = Signal(str)     # human-readable message

    def __init__(self, bindings: dict[str, str], parent=None):
        super().__init__(parent)
        self.bindings = bindings
        self._filter = None
        self._ids: dict[int, str] = {}
        self._listener = None

    def start(self, app):
        self._app = app
        if sys.platform == "win32":
            self._start_windows(app)
        else:
            self._start_pynput()

    def register(self, action: str, combo: str) -> bool:
        """Add a binding at runtime (e.g. confirm keys while a scan waits for an answer)."""
        self.bindings[action] = combo
        if sys.platform == "win32":
            return self._register_win(action, combo)
        self._start_pynput()
        return True

    def unregister(self, action: str) -> None:
        self.bindings.pop(action, None)
        if sys.platform == "win32":
            for i, a in list(self._ids.items()):
                if a == action:
                    self._user32.UnregisterHotKey(None, i)
                    del self._ids[i]
        else:
            self._start_pynput()

    # -- Windows
    def _start_windows(self, app):
        import ctypes
        from ctypes import wintypes

        self._user32 = ctypes.windll.user32
        self._next_id = 0xB000
        mgr = self

        class Filter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_HOTKEY and msg.wParam in mgr._ids:
                        mgr.triggered.emit(mgr._ids[msg.wParam])
                        return True, 0
                return False, 0

        self._filter = Filter()
        app.installNativeEventFilter(self._filter)
        for action, combo in list(self.bindings.items()):
            self._register_win(action, combo)

    def _register_win(self, action: str, combo: str) -> bool:
        try:
            mods, vk = parse_combo(combo)
        except ValueError as e:
            self.failed.emit(str(e))
            return False
        i = self._next_id
        self._next_id += 1
        # hwnd=None: WM_HOTKEY goes to this (GUI) thread's message queue.
        if self._user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
            self._ids[i] = action
            return True
        self.failed.emit(f"Could not register {combo} for {action} (already used by another app?)")
        return False

    # -- fallback
    def _start_pynput(self):
        try:
            from pynput import keyboard
        except ImportError:
            self.failed.emit("pynput not installed; global hotkeys disabled")
            return
        if self._listener:
            self._listener.stop()

        def fmt(c):
            return "+".join(f"<{p}>" if p in MOD or p in VK_SPECIAL else p for p in c.lower().split("+"))

        hk = {fmt(c): (lambda a=a: self.triggered.emit(a)) for a, c in self.bindings.items()}
        self._listener = keyboard.GlobalHotKeys(hk)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        for i in list(self._ids):
            self._user32.UnregisterHotKey(None, i)
        self._ids.clear()
        if self._listener:
            self._listener.stop()
