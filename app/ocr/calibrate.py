"""Self-calibration: find the Pets window on screen by its labels and work out every OCR region.

The default regions are measured on a 1920x1080 screen. Other resolutions, ultrawide screens
(the detail panel hugs the right edge) and a changed in-game UI scale all move things around.
Instead of guessing, read the whole screen once, find labels that are always there, and place
the regions relative to them:

* "Pet Info" + "Source" tabs: their distance gives the UI scale, their position the detail panel
* "Pet Insight": backup anchor for the detail panel
* "Collection Status": anchors the card grid and collection counter on the left
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from .capture import DEFAULT_PROFILE
from .engine import OcrLine
from .match import norm

# Label positions (x0, y0) on the 1920x1080 reference screenshot.
REF = {
    "pet_info": (1535, 147),
    "source": (1671, 147),
    "pet_insight": (1495, 268),
    "collection": (250, 1015),
}
RIGHT_KEYS = ("name", "insight", "genus_badge", "detail_panel")


@dataclass
class Anchors:
    pet_info: Optional[tuple] = None
    source: Optional[tuple] = None
    pet_insight: Optional[tuple] = None
    collection: Optional[tuple] = None

    @property
    def found_panel(self) -> bool:
        return bool(self.pet_info or self.pet_insight)


def find_anchors(lines: list[OcrLine]) -> Anchors:
    a = Anchors()
    for ln in lines:
        t = norm(ln.text)
        box = tuple(float(v) for v in ln.box)
        if t.startswith("pet info") and a.pet_info is None:
            a.pet_info = box
        elif t == "source" or t.startswith("source "):
            if a.source is None:
                a.source = box
        elif t.startswith("pet insight") and a.pet_insight is None:
            a.pet_insight = box
        elif t.startswith("collection status") and a.collection is None:
            a.collection = box
    # "Source" must sit on the same row as "Pet Info", to its right
    if a.pet_info and a.source:
        if not (a.source[0] > a.pet_info[0] and abs(a.source[1] - a.pet_info[1]) < 20):
            a.source = None
    return a


def ui_scale(a: Anchors, screen_h: int) -> float:
    if a.pet_info and a.source:
        s = (a.source[0] - a.pet_info[0]) / (REF["source"][0] - REF["pet_info"][0])
        if 0.4 < s < 3.0:
            return s
    return screen_h / 1080


def derive_profile(a: Anchors, screen_w: int, screen_h: int, base: dict = DEFAULT_PROFILE) -> Optional[dict]:
    """Regions for this screen, placed relative to the labels found. None if the panel wasn't found."""
    if not a.found_panel:
        return None
    s = ui_scale(a, screen_h)
    if a.pet_info:
        (ax, ay), (rx, ry) = a.pet_info[:2], REF["pet_info"]
    else:
        (ax, ay), (rx, ry) = a.pet_insight[:2], REF["pet_insight"]

    def right(box):
        x1, y1, x2, y2 = box
        return [round(ax + (x1 - rx) * s), round(ay + (y1 - ry) * s),
                round(ax + (x2 - rx) * s), round(ay + (y2 - ry) * s)]

    if a.collection:
        (cx, cy), (rcx, rcy) = a.collection[:2], REF["collection"]
    else:
        (cx, cy), (rcx, rcy) = (0, 0), (0, 0)  # left/top anchored, scaled

    def left(box):
        x1, y1, x2, y2 = box
        return [round(cx + (x1 - rcx) * s), round(cy + (y1 - rcy) * s),
                round(cx + (x2 - rcx) * s), round(cy + (y2 - rcy) * s)]

    p = copy.deepcopy(base)
    for k in RIGHT_KEYS:
        p[k] = right(base[k])
    p["collection"] = left(base["collection"])
    g = base["grid"]
    p["grid"]["area"] = left(g["area"])
    p["grid"]["first_card"] = left(g["first_card"])
    p["grid"]["pitch"] = [round(g["pitch"][0] * s), round(g["pitch"][1] * s)]
    for k in ("level", "progress"):
        p["grid"][k] = [round(v * s) for v in g[k]]
    p["auto"] = {"scale": round(s, 3), "screen": [screen_w, screen_h]}
    return p


def calibrate(img, engine, scanner) -> tuple[Optional[dict], Optional[object], str]:
    """Full-screen read -> (profile, DetailScan, message). The profile is only returned when a
    detail read with it actually finds a pet, so a wrong guess is never saved."""
    lines = engine.read(img)
    a = find_anchors(lines)
    if not a.found_panel:
        return None, None, "Pets window not found on screen"
    prof = derive_profile(a, img.width, img.height)

    class _One:
        profiles: dict = {}

        def get(self, w, h):
            return copy.deepcopy(prof), True

    real = scanner.profiles
    scanner.profiles = _One()
    try:
        scan = scanner.detail_scan(img, with_collection=True)
    finally:
        scanner.profiles = real
    if not scan.name or scan.level is None:
        return None, scan, "found the Pets window but couldn't read the pet panel"
    return prof, scan, f"calibrated for {img.width}x{img.height} (UI scale {prof['auto']['scale']})"
