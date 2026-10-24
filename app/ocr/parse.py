"""OCR text -> numbers. Pure functions, no images."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .engine import OcrLine

# ①..⑳, ⓪, ❶.., ➀.. → plain digits
_CIRCLED = {}
for base, start in ((0x2460, 1), (0x2776, 1), (0x2780, 1), (0x278A, 1)):
    for i in range(10):
        _CIRCLED[chr(base + i)] = str(start + i)
_CIRCLED["⓪"] = "0"


def normalize_text(s: str) -> str:
    s = "".join(_CIRCLED.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKC", s)  # full-width digits/slashes
    s = s.replace("’", "'").replace("`", "'").replace("‘", "'")
    return s


def join_lines(lines: list[OcrLine]) -> str:
    """Lines in reading order (top-to-bottom, then left-to-right), joined by spaces."""
    if not lines:
        return ""
    rows: list[list[OcrLine]] = []
    for ln in sorted(lines, key=lambda l: (l.box[1] + l.box[3]) / 2):
        cy = (ln.box[1] + ln.box[3]) / 2
        h = ln.box[3] - ln.box[1]
        if rows and abs(cy - _row_cy(rows[-1])) < max(h, 8) * 0.6:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return " ".join(" ".join(l.text for l in sorted(r, key=lambda l: l.box[0])) for r in rows)


def _row_cy(row):
    return sum((l.box[1] + l.box[3]) / 2 for l in row) / len(row)


def clean_name(text: str) -> str:
    """Strip stars, icons and stray punctuation from an OCR'd pet name."""
    t = normalize_text(text)
    t = re.sub(r"[^A-Za-z0-9' \-]", " ", t)
    return " ".join(t.split()).strip(" -'")


_SLASH = r"[/|lI\\]"

INSIGHT_RE = re.compile(rf"Lv\.?\s*(\d+)\s*\(\s*(\d+)\s*{_SLASH}\s*(\d+)\s*\)", re.I)
INSIGHT_MAX_RE = re.compile(r"Lv\.?\s*(\d+)\s*\(?\s*MAX\s*\)?", re.I)
LEVEL_RE = re.compile(r"Lv\.?\s*(\d+)", re.I)
FRACTION_RE = re.compile(rf"(\d+)\s*{_SLASH}\s*(\d+)")


def parse_insight(text: str) -> dict:
    """'Pet Insight  Lv. 1 (7/25)' -> {'level': 1, 'have': 7, 'need': 25}."""
    t = normalize_text(text)
    m = INSIGHT_RE.search(t)
    if m:
        lvl, have, need = (int(g) for g in m.groups())
        if need > 0 and have <= need:
            return {"level": lvl, "have": have, "need": need, "max": False}
    m = INSIGHT_MAX_RE.search(t)
    if m:
        return {"level": int(m.group(1)), "have": None, "need": None, "max": True}
    m = LEVEL_RE.search(t)
    if m:
        return {"level": int(m.group(1)), "have": None, "need": None, "max": False}
    return {}


def parse_fraction(text: str) -> Optional[tuple[int, int]]:
    t = normalize_text(text)
    m = FRACTION_RE.search(t)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if b > 0 and a <= b else None


def parse_collection(text: str) -> Optional[tuple[int, int]]:
    """'Collection Status 173/200' -> (173, 200)."""
    t = normalize_text(text)
    i = t.lower().find("status")
    return parse_fraction(t[i:] if i >= 0 else t)


def parse_card_progress(text: str) -> dict:
    """Bottom-right of a grid card: 'MAX' or '7/25'."""
    t = normalize_text(text).upper()
    if "MAX" in t or "MAK" in t:
        return {"max": True, "have": None, "need": None}
    f = parse_fraction(t)
    if f:
        return {"max": False, "have": f[0], "need": f[1]}
    return {}


def parse_level_digit(text: str) -> Optional[int]:
    t = normalize_text(text)
    digits = re.findall(r"\d+", t)
    if len(digits) == 1 and 0 < int(digits[0]) <= 20:
        return int(digits[0])
    return None
