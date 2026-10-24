"""Pure filter / sort helpers. No Qt here so they are easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .models import ZONES, Pet, Progress, Source

# Guide advice: Altgard first, check Abyss before a Verteron rift visit.
ZONE_PREFERENCE = {z: i for i, z in enumerate(
    ("Altgard", "Spirit Isle", "Immortal Isle", "Abyss", "Verteron", "Crimson Isle", "Eternal Isle", "Other"))}
TYPE_PREFERENCE = {"monster": 0, "boss": 1, "dungeon": 2, "chest_merchant": 3}

STATUS_CHOICES = {
    "all": "All",
    "not_maxed": "Not maxed",
    "missing": "Not owned",
    "unlocked": "Owned, no progress yet",
    "in_progress": "In progress",
    "maxed": "Maxed",
}


@dataclass
class FilterSpec:
    genera: set[str] = field(default_factory=set)       # empty = all; "Unknown" matches genus None
    zones: set[str] = field(default_factory=set)        # empty = all
    status: str = "all"
    source_types: set[str] = field(default_factory=set)  # empty = all
    priority_only: bool = False
    hide_elite: bool = False
    needs_review: bool = False                           # genus unknown or low confidence
    text: str = ""

    @property
    def narrows_sources(self) -> bool:
        return bool(self.zones or self.source_types or self.priority_only)


def norm(s: str) -> str:
    return " ".join(s.lower().replace("’", "'").split())


def matching_sources(pet: Pet, spec: FilterSpec) -> list[Source]:
    out = []
    for s in pet.sources:
        if spec.zones and s.zone not in spec.zones:
            continue
        if spec.source_types and s.source_type not in spec.source_types:
            continue
        if spec.priority_only and not s.priority_addition:
            continue
        if spec.hide_elite and s.elite:
            continue
        out.append(s)
    return out


def status_matches(pr: Progress, status: str) -> bool:
    if status == "all":
        return True
    if status == "not_maxed":
        return not pr.maxed
    return pr.status == status


def pet_matches(pet: Pet, pr: Progress, spec: FilterSpec) -> bool:
    if spec.genera:
        g = pet.genus or "Unknown"
        if g not in spec.genera:
            return False
    if spec.needs_review and pet.genus and pet.genus_confidence != "low":
        return False
    if not status_matches(pr, spec.status):
        return False
    srcs = matching_sources(pet, spec)
    if spec.narrows_sources and not srcs:
        return False
    if spec.hide_elite and pet.sources and not srcs:
        return False  # only elite sources left
    if spec.text:
        q = norm(spec.text)
        hay = [pet.name] + [s.monster or "" for s in pet.sources]
        if not any(q in norm(h) for h in hay):
            return False
    return True


def source_sort_key(s: Source):
    return (
        ZONE_PREFERENCE.get(s.zone, 99),
        TYPE_PREFERENCE.get(s.source_type, 9),
        s.elite,
        s.area_no if s.area_no is not None else 99,
        s.pin or "",
        s.page or 0,
    )


def best_source(pet: Pet, spec: Optional[FilterSpec] = None) -> Optional[Source]:
    srcs = matching_sources(pet, spec) if spec else list(pet.sources)
    if not srcs and spec and not spec.narrows_sources:
        srcs = list(pet.sources)
    return min(srcs, key=source_sort_key) if srcs else None


def filter_pets(pets: Iterable[Pet], progress: Callable[[str], Progress], spec: FilterSpec) -> list[Pet]:
    out = [p for p in pets if pet_matches(p, progress(p.id), spec)]
    out.sort(key=lambda p: norm(p.name))
    return out


def group_by_area(pets: Iterable[Pet], spec: FilterSpec) -> list[tuple[str, str, list[tuple[Pet, Source]]]]:
    """Route-style grouping: [(zone, area_label, [(pet, source), ...]), ...] in guide order."""
    buckets: dict[tuple, list[tuple[Pet, Source]]] = {}
    for p in pets:
        srcs = matching_sources(p, spec) if spec.narrows_sources or spec.hide_elite else list(p.sources)
        for s in srcs:
            label = area_label(s)
            key = (ZONE_PREFERENCE.get(s.zone, 99), s.zone,
                   s.area_no if s.area_no is not None else 99, label)
            buckets.setdefault(key, []).append((p, s))
    out = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda ps: (ps[1].pin or "", ps[1].sub_location or "", norm(ps[0].name)))
        out.append((key[1], key[3], rows))
    return out


def area_label(s: Source) -> str:
    if s.zone in ("Altgard", "Verteron") and s.area_no is not None and s.source_type == "monster":
        return f"{s.area_no:02d} {s.area}"
    if s.zone == "Abyss" and s.area_no is not None:
        return f"{s.area_no} {s.area}" + (f" · {s.sub_location}" if s.sub_location and s.page in (14, 15) else "")
    return s.area or s.source_type.replace("_", " / ")


__all__ = ["FilterSpec", "STATUS_CHOICES", "ZONES", "filter_pets", "best_source", "group_by_area",
           "matching_sources", "pet_matches", "area_label", "norm"]
