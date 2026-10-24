"""Strict pet-name matching.

The guide's whole point is that near-identical names are different pets
(Karnif vs Tamed Karnif, Spider vs Unstable Spider), so fuzzy matches only
auto-accept when they are very close AND clearly better than the runner-up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("`", "'").replace("‘", "'").lower()
    s = re.sub(r"[^a-z0-9' \-]", " ", s)
    return " ".join(s.split())


def differs_by_edge_words(a: str, b: str) -> bool:
    """True if one name is the other plus extra leading/trailing words (Karnif / Tamed Karnif)."""
    ta, tb = norm(a).split(), norm(b).split()
    if ta == tb or not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) < len(tb) else (tb, ta)
    n = len(short)
    return long_[-n:] == short or long_[:n] == short


@dataclass
class Candidate:
    pet_id: str
    name: str
    score: float


@dataclass
class MatchResult:
    query: str
    pet_id: Optional[str]
    name: Optional[str]
    score: float
    auto: bool
    reason: str
    candidates: list[Candidate] = field(default_factory=list)


def match_name(query: str, names: dict[str, str], min_ratio: float = 92, min_margin: float = 6,
               top: int = 3) -> MatchResult:
    """names: {pet_id: pet_name}. Returns the best guess and whether it is safe to auto-accept."""
    q = norm(query)
    if not q:
        return MatchResult(query, None, None, 0, False, "no text")
    scored = sorted(
        (Candidate(pid, n, 100.0 if norm(n) == q else float(fuzz.ratio(q, norm(n)))) for pid, n in names.items()),
        key=lambda c: -c.score,
    )
    cands = scored[:top]
    best = cands[0]
    second = cands[1] if len(cands) > 1 else None

    # Long names don't fit the panel and get cut off ("Spirit King's Bodygua"). A long enough read that
    # starts exactly one pet name is that pet.
    if best.score < 100.0 and len(q) >= 14:
        sq = q.replace(" ", "")
        starts = [(pid, n) for pid, n in names.items() if norm(n).replace(" ", "").startswith(sq)]
        if len(starts) == 1:
            pid, n = starts[0]
            return MatchResult(query, pid, n, 95.0, True, "prefix (long name cut off)",
                               [Candidate(pid, n, 95.0)] + [c for c in cands if c.pet_id != pid][:2])

    if best.score == 100.0:
        # Exact. Still note look-alikes that only add a word (OCR may have dropped one).
        longer = [n for n in names.values() if norm(n) != q and differs_by_edge_words(n, best.name)
                  and len(norm(n)) > len(q)]
        reason = "exact" + (f" (look-alike: {', '.join(sorted(longer))})" if longer else "")
        return MatchResult(query, best.pet_id, best.name, 100.0, True, reason, cands)

    if best.score < min_ratio:
        return MatchResult(query, best.pet_id, best.name, best.score, False,
                           f"best match {best.score:.0f} < {min_ratio:.0f}", cands)
    if second and best.score - second.score < min_margin:
        return MatchResult(query, best.pet_id, best.name, best.score, False,
                           f"too close to {second.name} ({best.score:.0f} vs {second.score:.0f})", cands)
    if second and differs_by_edge_words(best.name, second.name):
        return MatchResult(query, best.pet_id, best.name, best.score, False,
                           f"look-alike name: {second.name}", cands)
    # A fuzzy match in a look-alike family (Karnif / Tamed Karnif / Elite Karnif ...) always asks.
    lookalikes = sorted(n for pid, n in names.items() if pid != best.pet_id and differs_by_edge_words(n, best.name))
    if lookalikes:
        return MatchResult(query, best.pet_id, best.name, best.score, False,
                           f"fuzzy match with look-alikes: {', '.join(lookalikes[:3])}", cands)
    return MatchResult(query, best.pet_id, best.name, best.score, True, "fuzzy", cands)
