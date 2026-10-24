"""Detail scan / grid read / collection check, plus writing results to the store."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from app.core.store import Store
from app.paths import USER_DATA

from .capture import ProfileStore, card_boxes, crop, preprocess
from .engine import OcrEngine
from .match import MatchResult, match_name
from .parse import (clean_name, join_lines, parse_card_progress, parse_collection, parse_insight,
                    parse_level_digit)

DEBUG_DIR = USER_DATA / "ocr_debug"


@dataclass
class DetailScan:
    raw_name: str = ""
    raw_insight: str = ""
    raw_collection: str = ""
    name: str = ""
    name_score: float = 0.0
    level: Optional[int] = None
    have: Optional[int] = None
    need: Optional[int] = None
    maxed: bool = False
    collection: Optional[tuple[int, int]] = None
    match: Optional[MatchResult] = None
    auto_accept: bool = False
    resolution: str = ""
    calibrated: bool = False
    crop: Optional[Image.Image] = field(default=None, repr=False)
    error: Optional[str] = None

    @property
    def confidence(self) -> float:
        """0..1 combining OCR certainty and name-match score."""
        m = (self.match.score / 100) if self.match else 0.0
        return round(min(self.name_score, 1.0) * m, 3)

    def summary(self, pet_name: Optional[str] = None) -> str:
        nm = pet_name or (self.match.name if self.match else None) or self.name or "?"
        if self.maxed:
            return f"{nm} — MAX (Lv {self.level or '?'})"
        if self.have is not None and self.need:
            return f"{nm} — {self.have}/{self.need} souls (Lv {self.level})"
        if self.level is not None:
            return f"{nm} — Lv {self.level}"
        return f"{nm} — progress not read"

    def parsed_json(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k not in ("crop", "match")}
        if self.match:
            d["match"] = {"pet_id": self.match.pet_id, "name": self.match.name, "score": self.match.score,
                          "auto": self.match.auto, "reason": self.match.reason,
                          "candidates": [asdict(c) for c in self.match.candidates]}
        return json.dumps(d, ensure_ascii=False)


@dataclass
class CardRead:
    row: int
    col: int
    level: Optional[int]
    have: Optional[int]
    need: Optional[int]
    maxed: bool
    raw: str


def panel_signature(img: Image.Image, profile: dict):
    """Tiny greyscale thumbnails of the name + insight rows; cheap to compare every frame."""
    import numpy as np

    parts = []
    for key, size in (("name", (64, 10)), ("insight", (64, 6))):
        parts.append(np.asarray(crop(img, profile[key]).convert("L").resize(size, Image.BILINEAR), dtype=np.int16))
    return np.concatenate([p.ravel() for p in parts])


def signature_diff(a, b) -> float:
    """Mean absolute difference, 0..255. None counts as completely different."""
    if a is None or b is None or a.shape != b.shape:
        return 255.0
    return float(abs(a - b).mean())


class Scanner:
    def __init__(self, store: Store, engine: OcrEngine, profiles: Optional[ProfileStore] = None,
                 settings: Optional[dict] = None):
        self.store = store
        self.engine = engine
        self.profiles = profiles or ProfileStore()
        conf = (settings or {}).get("confidence", {})
        self.min_ratio = conf.get("fuzzy_ratio", 92)
        self.min_margin = conf.get("fuzzy_margin", 6)
        self.auto_threshold = conf.get("auto_accept", 0.90)
        ocr = (settings or {}).get("ocr", {})
        self.debug_keep = ocr.get("debug_keep", 50)
        self.scale = ocr.get("scale", 2)

    # ------------------------------------------------------------------ reading
    def _read(self, img: Image.Image, box, scale=None) -> tuple[str, float]:
        lines = self.engine.read(preprocess(crop(img, box), scale or self.scale))
        if not lines:
            return "", 0.0
        return join_lines(lines), min(l.score for l in lines)

    def _read_panel(self, img: Image.Image, profile: dict) -> tuple[str, float, str]:
        """One OCR pass over the detail panel; lines are assigned to the name / insight regions
        by where their centre lands (in screen pixels)."""
        px1, py1, _, _ = (int(v) for v in profile["detail_panel"])
        px1, py1 = max(0, px1), max(0, py1)
        pad, sc = 8, self.scale
        lines = self.engine.read(preprocess(crop(img, profile["detail_panel"]), sc, pad=pad))

        def inside(ln, box):
            cx = px1 + ((ln.box[0] + ln.box[2]) / 2 - pad) / sc
            cy = py1 + ((ln.box[1] + ln.box[3]) / 2 - pad) / sc
            return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]

        name = [l for l in lines if inside(l, profile["name"])]
        ins = [l for l in lines if inside(l, profile["insight"])]
        score = min((l.score for l in name), default=0.0)
        return join_lines(name), score, join_lines(ins)

    def read_collection(self, img: Image.Image, profile: Optional[dict] = None) -> tuple[str, Optional[tuple[int, int]]]:
        profile = profile or self.profiles.get(img.width, img.height)[0]
        raw, _ = self._read(img, profile["collection"])
        return raw, parse_collection(raw)

    def detail_scan(self, img: Image.Image, with_collection: bool = True, fast: bool = False) -> DetailScan:
        """fast=True (auto-scan): skip the slower per-region retry when no pet name is visible at all."""
        profile, calibrated = self.profiles.get(img.width, img.height)
        s = DetailScan(resolution=f"{img.width}x{img.height}", calibrated=calibrated)
        s.crop = crop(img, profile["detail_panel"])
        s.raw_name, s.name_score, s.raw_insight = self._read_panel(img, profile)
        if (s.raw_name or not fast) and (not s.raw_name or not parse_insight(s.raw_insight)):
            # Fallback: read the two regions separately.
            s.raw_name, s.name_score = self._read(img, profile["name"])
            s.raw_insight, _ = self._read(img, profile["insight"])
        if with_collection:
            s.raw_collection, s.collection = self.read_collection(img, profile)
        s.name = clean_name(s.raw_name)
        ins = parse_insight(s.raw_insight)
        s.level, s.have, s.need = ins.get("level"), ins.get("have"), ins.get("need")
        max_level = self.store.default_max
        s.maxed = bool(ins.get("max")) or (s.level is not None and s.level >= max_level)
        if not s.name:
            s.error = "No pet name found. Is the Pets window open with a pet selected?"
            return s
        names = {pid: p.name for pid, p in self.store.pets.items()}
        s.match = match_name(s.name, names, self.min_ratio, self.min_margin)
        if not ins:
            s.error = "Pet name read, but not the 'Pet Insight Lv. x (a/b)' line."
        s.auto_accept = bool(s.match.auto and not s.error and s.confidence >= self.auto_threshold)
        return s

    def grid_read(self, img: Image.Image) -> list[CardRead]:
        """Level + MAX / x/y from each visible card. Cards carry no names, so these
        can't be tied to pets until card thumbnails are learned (milestone 6)."""
        profile, _ = self.profiles.get(img.width, img.height)
        out = []
        for cb in card_boxes(profile):
            raw_l, _ = self._read(img, cb.level, scale=4)
            lvl = parse_level_digit(raw_l)
            if lvl is None:
                single = self.engine.read_single(preprocess(crop(img, cb.level), 3, pad=0))
                lvl = parse_level_digit(single.text) if single else None
            raw_p, _ = self._read(img, cb.progress, scale=3)
            prog = parse_card_progress(raw_p)
            if not raw_p and lvl is None:
                continue  # empty slot
            out.append(CardRead(cb.row, cb.col, lvl, prog.get("have"), prog.get("need"),
                                bool(prog.get("max")), f"{raw_l} | {raw_p}"))
        return out

    # ------------------------------------------------------------------ writing
    def apply(self, scan: DetailScan, pet_id: Optional[str], accepted: bool) -> str:
        """Log the scan; if accepted, write progress (unless the pet is locked). Returns a status line."""
        shot = self._save_debug(scan, pet_id)
        msg = "rejected"
        if accepted and pet_id:
            pr = self.store.progress(pet_id)
            if pr.manual_lock:
                msg = "locked — not changed"
            else:
                pr.unlocked = True
                if scan.level is not None:
                    pr.level = scan.level
                if scan.maxed:
                    pr.maxed = True
                    pr.souls_have = pr.souls_need = None
                elif scan.have is not None and scan.need:
                    pr.souls_have, pr.souls_need = scan.have, scan.need
                    if scan.level is not None:
                        self.store.record_level_requirement(scan.level, scan.need)
                ok = self.store.save_progress(pr, by="ocr")
                msg = "saved" if ok else "locked — not changed"
        self.store.db.execute(
            "INSERT INTO ocr_log(ts, pet_id, raw_text, parsed_json, confidence, screenshot_path, accepted)"
            " VALUES (?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), pet_id,
             f"{scan.raw_name} || {scan.raw_insight} || {scan.raw_collection}", scan.parsed_json(),
             scan.confidence, str(shot) if shot else None, int(bool(accepted and msg == "saved"))),
        )
        self.store.db.commit()
        return msg

    def _save_debug(self, scan: DetailScan, pet_id: Optional[str]) -> Optional[Path]:
        if scan.crop is None:
            return None
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = DEBUG_DIR / f"{ts}_{pet_id or 'unmatched'}.png"
        scan.crop.save(path)
        files = sorted(DEBUG_DIR.glob("*.png"))
        for old in files[:-self.debug_keep] if self.debug_keep else []:
            try:
                old.unlink()
            except OSError:
                pass
        return path
