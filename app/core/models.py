"""Plain data classes shared by the parser, store, filters and UI."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

GENERA = ("Cogni", "Fera", "Natura", "Varian")
ZONES = (
    "Altgard", "Spirit Isle", "Immortal Isle",
    "Verteron", "Crimson Isle", "Eternal Isle",
    "Abyss", "Other",
)
SOURCE_TYPES = ("monster", "chest_merchant", "boss", "dungeon")

# Guide colours (also used by the UI chips / dots).
GENUS_COLORS = {
    "Cogni": "#9d49df",
    "Fera": "#df6a25",
    "Natura": "#258443",
    "Varian": "#187cb7",
}


@dataclass
class Source:
    zone: str
    source_type: str = "monster"
    area: Optional[str] = None
    area_no: Optional[int] = None
    sub_location: Optional[str] = None
    monster: Optional[str] = None
    level: Optional[int] = None
    pin: Optional[str] = None
    elite: bool = False
    priority_addition: bool = False
    page: Optional[int] = None
    map: list = field(default_factory=list)  # [[panel_id, pin_label], ...] most specific first
    origin: Optional[str] = None             # None = the guide, "atlas" = Pet Soul Atlas
    spawns: Optional[int] = None             # spawn points on the atlas map

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != []}

    @classmethod
    def from_json(cls, d: dict) -> "Source":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})

    def summary(self) -> str:
        bits = [self.zone]
        if self.area:
            bits.append(self.area)
        if self.sub_location and self.sub_location != self.area:
            bits.append(self.sub_location)
        if self.monster:
            verb = "boss" if self.source_type in ("boss", "dungeon") else "kill"
            bits.append(f"{verb} {self.monster}" + (" [ELITE]" if self.elite else ""))
        elif self.source_type == "chest_merchant":
            bits.append("chest / merchant")
        return " · ".join(bits)


@dataclass
class Pet:
    id: str
    name: str
    genus: Optional[str] = None
    genus_confidence: Optional[str] = None  # high | low | override | None
    held: bool = False
    unconfirmed_note: Optional[str] = None
    pdf_checked: bool = False
    sources: list[Source] = field(default_factory=list)
    links: dict = field(default_factory=dict)  # {"atlas": url, "database": url}

    @property
    def zones(self) -> set[str]:
        return {s.zone for s in self.sources}

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "genus": self.genus,
            "genus_confidence": self.genus_confidence,
            "flags": {"held": self.held, "unconfirmed_note": self.unconfirmed_note},
            "pdf_checked": self.pdf_checked,
            "links": self.links,
            "sources": [s.to_json() for s in self.sources],
        }

    @classmethod
    def from_json(cls, d: dict) -> "Pet":
        flags = d.get("flags") or {}
        return cls(
            id=d["id"],
            name=d["name"],
            genus=d.get("genus"),
            genus_confidence=d.get("genus_confidence"),
            held=bool(flags.get("held")),
            unconfirmed_note=flags.get("unconfirmed_note"),
            pdf_checked=bool(d.get("pdf_checked")),
            sources=[Source.from_json(s) for s in d.get("sources", [])],
            links=d.get("links") or {},
        )


@dataclass
class CircuitStop:
    pocket: str
    pet_id: str
    pet_name: str
    monster: str

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Circuit:
    zone: str
    name: str
    level_range: Optional[str]
    note: Optional[str]
    stops: list[CircuitStop]
    page: int
    panel: Optional[str] = None  # map panel id for this loop

    def to_json(self) -> dict:
        return {
            "zone": self.zone, "name": self.name, "level_range": self.level_range,
            "note": self.note, "stops": [s.to_json() for s in self.stops], "page": self.page,
            "panel": self.panel,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Circuit":
        return cls(
            zone=d["zone"], name=d["name"], level_range=d.get("level_range"),
            note=d.get("note"), page=d.get("page", 0), panel=d.get("panel"),
            stops=[CircuitStop(**s) for s in d.get("stops", [])],
        )


@dataclass
class Progress:
    pet_id: str
    unlocked: bool = False
    level: Optional[int] = None
    max_level: Optional[int] = None
    souls_have: Optional[int] = None
    souls_need: Optional[int] = None
    maxed: bool = False
    manual_lock: bool = False
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    @property
    def status(self) -> str:
        """One of: maxed, in_progress, unlocked, missing."""
        if self.maxed:
            return "maxed"
        if not self.unlocked:
            return "missing"
        if self.level is not None or self.souls_have is not None:
            return "in_progress"
        return "unlocked"

    def fraction(self, default_max: int = 3) -> Optional[float]:
        """0..1 progress toward max level, or None when nothing is known."""
        if self.maxed:
            return 1.0
        mx = self.max_level or default_max
        if self.level is not None and mx:
            base = (self.level - 1) / max(mx - 1, 1) if mx > 1 else 0.0
            if self.souls_have is not None and self.souls_need:
                step = 1 / max(mx - 1, 1)
                base += step * min(self.souls_have / self.souls_need, 1.0)
            return max(0.0, min(base, 1.0))
        if self.souls_have is not None and self.souls_need:
            return min(self.souls_have / self.souls_need, 1.0)
        return None
