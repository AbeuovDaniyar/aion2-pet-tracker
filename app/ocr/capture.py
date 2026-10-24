"""Screen capture, OCR regions (ROIs) per resolution, crop + preprocess."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from app.paths import USER_CONFIG

PROFILES_PATH = USER_CONFIG / "ocr_profiles.json"

REF_W, REF_H = 1920, 1080

# Pixel boxes at 1920x1080, measured on data/sample_screens/pets_konutin_worker_1080p.png.
DEFAULT_PROFILE = {
    "name": [1525, 203, 1842, 255],
    "insight": [1495, 266, 1822, 298],
    "genus_badge": [1843, 200, 1893, 250],
    "collection": [245, 1010, 450, 1039],
    "detail_panel": [1490, 190, 1905, 305],  # saved as the debug crop
    "grid": {
        "area": [80, 135, 445, 990],
        "first_card": [90, 147, 197, 297],
        "pitch": [119, 164],
        "cols": 3,
        "rows": 5,
        # offsets from the card's bottom-left / bottom-right corners
        "level": [-8, -22, 22, 8],
        "progress": [-52, -25, 2, -3],
    },
}

BOX_KEYS = ("name", "insight", "genus_badge", "collection", "detail_panel")


def res_key(w: int, h: int) -> str:
    return f"{w}x{h}"


def scale_profile(p: dict, sx: float, sy: float) -> dict:
    q = copy.deepcopy(p)
    for k in BOX_KEYS:
        x1, y1, x2, y2 = p[k]
        q[k] = [round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy)]
    g = p["grid"]
    qg = q["grid"]
    for k in ("area", "first_card"):
        x1, y1, x2, y2 = g[k]
        qg[k] = [round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy)]
    qg["pitch"] = [round(g["pitch"][0] * sx), round(g["pitch"][1] * sy)]
    for k in ("level", "progress"):
        a, b, c, d = g[k]
        qg[k] = [round(a * sx), round(b * sy), round(c * sx), round(d * sy)]
    return q


class ProfileStore:
    """config/ocr_profiles.json: {"1920x1080": {...}, ...}. Unknown sizes are scaled from 1920x1080."""

    def __init__(self, path: Path = PROFILES_PATH):
        self.path = Path(path)
        self.profiles: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.profiles = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.profiles = {}

    def get(self, w: int, h: int) -> tuple[dict, bool]:
        """Returns (profile, calibrated?)."""
        k = res_key(w, h)
        if k in self.profiles:
            return copy.deepcopy(self.profiles[k]), True
        base = self.profiles.get(res_key(REF_W, REF_H), DEFAULT_PROFILE)
        return scale_profile(base, w / REF_W, h / REF_H), False

    def save(self, w: int, h: int, profile: dict) -> None:
        self.profiles[res_key(w, h)] = profile
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.profiles, indent=2) + "\n", encoding="utf-8")


@dataclass
class CardBox:
    row: int
    col: int
    card: tuple[int, int, int, int]
    level: tuple[int, int, int, int]
    progress: tuple[int, int, int, int]


def card_boxes(profile: dict) -> list[CardBox]:
    g = profile["grid"]
    x0, y0, x1, y1 = g["first_card"]
    w, h = x1 - x0, y1 - y0
    px, py = g["pitch"]
    area = g["area"]
    out = []
    for r in range(g["rows"]):
        for c in range(g["cols"]):
            cx, cy = x0 + c * px, y0 + r * py
            if cy + h > area[3] + 2:
                continue  # card cut off at the bottom of the scroll area
            l = g["level"]
            p = g["progress"]
            out.append(CardBox(
                r, c, (cx, cy, cx + w, cy + h),
                (cx + l[0], cy + h + l[1], cx + l[2], cy + h + l[3]),
                (cx + w + p[0], cy + h + p[1], cx + w + p[2], cy + h + p[3]),
            ))
    return out


def crop(img: Image.Image, box) -> Image.Image:
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    return img.crop((x1, y1, x2, y2))


def preprocess(img: Image.Image, scale: int = 2, pad: int = 8, contrast: bool = True) -> Image.Image:
    """Upscale, greyscale, stretch contrast, pad with black. Kept mild: RapidOCR prefers soft edges
    over a hard threshold on this game's anti-aliased text."""
    im = img.convert("RGB")
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    if contrast:
        g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=1)
        im = Image.merge("RGB", (g, g, g))
    if pad:
        im = ImageOps.expand(im, pad, fill=(0, 0, 0))
    return im


def grab_monitor(index: int = 1) -> Image.Image:
    """Screenshot of one monitor (1 = primary in mss numbering)."""
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    with factory() as sct:
        mons = sct.monitors
        mon = mons[index] if 0 < index < len(mons) else mons[1]
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def monitor_count() -> int:
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    with factory() as sct:
        return len(sct.monitors) - 1


def load_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def best_profile_for(img: Image.Image, store: Optional[ProfileStore] = None) -> tuple[dict, bool]:
    return (store or ProfileStore()).get(img.width, img.height)
