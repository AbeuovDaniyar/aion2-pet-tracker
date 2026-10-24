"""Pluggable OCR engines. RapidOCR (onnxruntime) first, Tesseract as fallback."""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np
from PIL import Image


@dataclass
class OcrLine:
    text: str
    score: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in the image passed in


class OcrEngine(Protocol):
    name: str

    def read(self, img: Image.Image) -> list[OcrLine]:
        """Detect + recognise every text line."""

    def read_single(self, img: Image.Image) -> Optional[OcrLine]:
        """Recognise the whole image as one line (no detection). For tiny crops like a level digit."""


def _as_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"))


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self, threads: int = -1):
        self._engine = None
        self._lock = threading.Lock()
        self.threads = threads

    def _get(self):
        if self._engine is None:
            from rapidocr import RapidOCR  # slow import; do it on first use
            # Default caps images at 2000 px and shrinks the enlarged field reads; small nameplates need more.
            # Detection would otherwise enlarge every image to >= 736 px on its short side, which made
            # small crops (target frame, pet panel) as slow as a whole screenshot.
            params = {"Global.max_side_len": 3000, "Det.limit_type": "max", "Det.limit_side_len": 2560}
            if self.threads and self.threads > 0:
                params["EngineConfig.onnxruntime.intra_op_num_threads"] = self.threads
            self._engine = RapidOCR(params=params)
        return self._engine

    def read(self, img: Image.Image) -> list[OcrLine]:
        with self._lock:
            r = self._get()(_as_array(img))
        out = []
        if r.txts is None:
            return out
        for box, txt, sc in zip(r.boxes, r.txts, r.scores):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append(OcrLine(str(txt), float(sc), (min(xs), min(ys), max(xs), max(ys))))
        return out

    def read_single(self, img: Image.Image) -> Optional[OcrLine]:
        with self._lock:
            r = self._get()(_as_array(img), use_det=False, use_cls=False, use_rec=True)
        if not r.txts:
            return None
        return OcrLine(str(r.txts[0]), float(r.scores[0]), (0, 0, img.width, img.height))


class TesseractEngine:
    name = "tesseract"

    def __init__(self):
        import pytesseract  # noqa: F401  (raises ImportError if missing)
        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract.exe not on PATH")

    def read(self, img: Image.Image) -> list[OcrLine]:
        import pytesseract
        d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 6")
        lines: dict[tuple, list[int]] = {}
        for i, t in enumerate(d["text"]):
            if t.strip() and float(d["conf"][i]) >= 0:
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        out = []
        for idx in lines.values():
            txt = " ".join(d["text"][i] for i in idx)
            conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100
            x0 = min(d["left"][i] for i in idx)
            y0 = min(d["top"][i] for i in idx)
            x1 = max(d["left"][i] + d["width"][i] for i in idx)
            y1 = max(d["top"][i] + d["height"][i] for i in idx)
            out.append(OcrLine(txt, conf, (x0, y0, x1, y1)))
        return out

    def read_single(self, img: Image.Image) -> Optional[OcrLine]:
        import pytesseract
        txt = pytesseract.image_to_string(img, config="--psm 7").strip()
        return OcrLine(txt, 0.5, (0, 0, img.width, img.height)) if txt else None


def make_engine(preferred: str = "rapidocr", threads: int = -1) -> OcrEngine:
    """Return the preferred engine, falling back to the other one."""
    order = [preferred] + [e for e in ("rapidocr", "tesseract") if e != preferred]
    errors = []
    for name in order:
        try:
            if name == "rapidocr":
                import rapidocr  # noqa: F401
                return RapidOcrEngine(threads)
            if name == "tesseract":
                return TesseractEngine()
        except Exception as e:  # pragma: no cover - depends on install
            errors.append(f"{name}: {e}")
    raise RuntimeError("No OCR engine available. " + "; ".join(errors))
