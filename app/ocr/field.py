"""Field mode: find guide monster names in on-screen text (nameplates, target frame)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.core.models import GENERA
from app.core.store import Store

from .engine import OcrLine
from .match import match_name, norm
from .parse import normalize_text

_LEVEL = re.compile(r"\b(lv|lvl|level)\s*\.?\s*\d+\b", re.I)
_LEAD_NUM = re.compile(r"^\s*\d+\s+")              # target frame starts with the level: "45 Black Claw…"
_DISTANCE = re.compile(r"\s*\d+(\.\d+)?\s*m\s*$")   # "...18m" distance at the end of the target frame
_JUNK = re.compile(r"[\[\]\(\)<>{}|*:;,_~=+#@!?]")
_NUM = re.compile(r"\b\d+[\d.,/%]*\b")
_TRUNC = re.compile(r"(\.{2,}|…)")
_PETS_WINDOW = ("pet insight", "collection status", "genus insight")


def squash(s: str) -> str:
    return norm(s).replace(" ", "").replace("-", "")


def clean_plate(text: str) -> tuple[str, bool]:
    """-> (name, truncated?)  e.g. '45 Black ClawManduri Sc...18m' -> ('Black ClawManduri Sc', True)."""
    t = normalize_text(text).replace("[ELITE]", " ").replace("[Elite]", " ")
    m = _TRUNC.search(t)
    truncated = bool(m)
    if m:
        t = t[:m.start()]
    t = _DISTANCE.sub("", t)
    t = _LEAD_NUM.sub("", t)
    t = _LEVEL.sub(" ", t)
    t = _JUNK.sub(" ", t)
    t = _NUM.sub(" ", t)
    return " ".join(t.split()).strip(" -'."), truncated


@dataclass
class FieldHit:
    monster: str
    pet_ids: list[str]
    score: float
    text: str
    box: tuple = (0, 0, 0, 0)
    targeted: bool = False          # from the target frame / selected nameplate
    game_genus: Optional[str] = None  # genus tag the game shows under the target frame


class MonsterIndex:
    """Every monster / boss name in the guide -> the pet(s) it drops."""

    def __init__(self, store: Store):
        self.by_monster: dict[str, list[str]] = {}
        for p in store.pets.values():
            for s in p.sources:
                if s.monster and s.source_type in ("monster", "boss"):
                    ids = self.by_monster.setdefault(s.monster, [])
                    if p.id not in ids:
                        ids.append(p.id)
        self.names = {m: m for m in self.by_monster}
        self._squashed = {squash(m): m for m in self.by_monster}

    def match(self, text: str, min_ratio: float = 92, min_margin: float = 6) -> Optional[tuple[str, float]]:
        t, truncated = clean_plate(text)
        q = squash(t)
        if len(q) < 3:
            return None
        if q in self._squashed:
            return self._squashed[q], 100.0
        if truncated:
            # Cut-off name: accept only if exactly one monster starts this way (and enough is visible).
            starts = [m for k, m in self._squashed.items() if k.startswith(q)]
            if len(q) >= 8 and len(starts) == 1:
                return starts[0], 95.0
            return None
        if len(q) < 6:
            return None  # short words must match exactly
        m = match_name(t, self.names, min_ratio, min_margin)
        return (m.pet_id, m.score) if m.auto and m.pet_id else None


def is_pets_window(lines: list[OcrLine]) -> bool:
    return any(any(k in norm(l.text) for k in _PETS_WINDOW) for l in lines)


def _genus_tag_below(line: OcrLine, lines: list[OcrLine]) -> Optional[str]:
    x0, y0, x1, y1 = line.box
    h = y1 - y0
    for other in lines:
        g = other.text.strip().capitalize()
        if g in GENERA:
            ox0, oy0, ox1, oy1 = other.box
            if 0 <= oy0 - y1 <= 3 * h and ox0 < x1 and ox1 > x0:
                return g
    return None


def find_monsters(lines: list[OcrLine], index: MonsterIndex, min_score: float = 0.6) -> list[FieldHit]:
    hits: dict[str, FieldHit] = {}
    for ln in lines:
        if ln.score < min_score:
            continue
        r = index.match(ln.text)
        if not r:
            continue
        name, score = r
        _, truncated = clean_plate(ln.text)
        target_frame = truncated or bool(_LEAD_NUM.match(normalize_text(ln.text)))
        hit = hits.get(name)
        if hit is None or score > hit.score:
            hit = FieldHit(name, index.by_monster[name], score, ln.text, ln.box,
                           targeted=hit.targeted if hit else False,
                           game_genus=hit.game_genus if hit else None)
            hits[name] = hit
        if target_frame:
            hit.targeted = True
            hit.game_genus = hit.game_genus or _genus_tag_below(ln, lines)
    return sorted(hits.values(), key=lambda h: (not h.targeted, h.monster))
