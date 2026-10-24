"""Short UI sounds, generated once as WAV files and played without blocking."""
from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

from app.paths import ASSETS as _ASSETS

ASSETS = _ASSETS / "sounds"
RATE = 44100

# name -> list of (frequency Hz, duration s)
TONES = {
    "saved": [(988, 0.07), (1319, 0.12)],             # quick rising "ding-ding": registered, move on
    "confirm": [(660, 0.12), (494, 0.18)],            # falling: needs your answer
    "start": [(523, 0.06), (659, 0.06), (784, 0.10)],
    "stop": [(784, 0.06), (523, 0.12)],
    "alert": [(1175, 0.07), (1568, 0.07), (1175, 0.07), (1568, 0.16)],  # genus alert: pet you want is nearby
}


def _write(path: Path, notes, volume: float = 0.35):
    frames = bytearray()
    for freq, dur in notes:
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            env = min(1.0, i / (RATE * 0.005)) * math.exp(-4.0 * t / dur)  # click-free attack, soft decay
            v = volume * env * (math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t))
            frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


def ensure_sounds() -> None:
    for name, notes in TONES.items():
        p = ASSETS / f"{name}.wav"
        if not p.exists():
            _write(p, notes)


class Sounds:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        try:
            ensure_sounds()
        except OSError:
            self.enabled = False

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        path = ASSETS / f"{name}.wav"
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:  # pragma: no cover
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
