"""Live soul tracking from the chat box: 'Obtained 1 Manduri Fighter Soul Points.'

The chat keeps old lines on screen, so each read is lined up against the previous one and only
lines that appeared below the overlap are counted. When a read can't be lined up (huge pull that
scrolled everything away, chat hidden), nothing is counted: missing a soul is fixed by the next
Pets-window scan, counting one twice is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

from .engine import OcrLine
from .match import match_name, norm
from .parse import normalize_text

SOUL_RE = re.compile(r"\bobtained\s+(\d+)\s+(.+?)\s+soul\s*points?\b", re.I)
_LINE_STARTS = ("obtained", "acquired", "[", "you ", "received", "gained")


@dataclass
class SoulGain:
    pet_id: str
    pet_name: str
    amount: int
    text: str


def chat_lines(lines: list[OcrLine], min_len: int = 4) -> list[str]:
    """OCR lines in chat order (top to bottom). Wrapped soul messages are joined back together."""
    rows = sorted((l for l in lines if len(norm(l.text)) >= min_len), key=lambda l: (l.box[1], l.box[0]))
    out: list[str] = []
    for ln in rows:
        t = normalize_text(ln.text).strip()
        if out and out[-1].lower().startswith("obtained") and "soul" not in out[-1].lower() \
                and not t.lower().startswith(_LINE_STARTS):
            out[-1] = f"{out[-1]} {t}"   # "Obtained 1 Mutated Aberrant Odyle" + "Spider Soul Points."
        else:
            out.append(t)
    return out


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def same_line(a: str, b: str) -> bool:
    """Equal chat lines, allowing small OCR slips in letters but never in numbers."""
    if _digits(a) != _digits(b):
        return False
    na, nb = norm(a), norm(b)
    return na == nb or fuzz.ratio(na, nb) >= 90


class ChatTracker:
    def __init__(self):
        self.prev: Optional[list[str]] = None

    def reset(self):
        self.prev = None

    def feed(self, cur: list[str]) -> Optional[list[str]]:
        """Returns the lines that are new since the last read, or None for 'can't tell'
        (first read, or no overlap with the previous read)."""
        prev, self.prev = self.prev, cur
        if prev is None:
            return None
        if not cur:
            return []
        if not prev:
            return None
        for o in range(min(len(prev), len(cur)), 0, -1):
            pairs = list(zip(prev[len(prev) - o:], cur[:o]))
            hits = sum(same_line(a, b) for a, b in pairs)
            # Most of the overlap must agree; a single shared line is only trusted when it's all we have.
            if hits >= max(1, round(0.8 * o)) and (o >= 2 or len(prev) == 1 or len(cur) == 1):
                return cur[o:]
        return None


def parse_soul(line: str) -> Optional[tuple[int, str]]:
    m = SOUL_RE.search(normalize_text(line))
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip(" .")


def soul_gains(new_lines: list[str], pet_names: dict[str, str]) -> list[SoulGain]:
    out = []
    for line in new_lines:
        p = parse_soul(line)
        if not p:
            continue
        amount, name = p
        m = match_name(name, pet_names)
        if m.auto and m.pet_id:
            out.append(SoulGain(m.pet_id, m.name, amount, line))
    return out
