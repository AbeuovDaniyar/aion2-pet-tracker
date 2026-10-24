"""Parse Th3Ruthless's Asmodian pet farming guide into data/pets.json.

Usage:
    python tools/parse_pdf.py [path/to/guide.pdf]

Every pet checkbox in the PDF is a form field named pet_NNNN. That name is the
pet's ID. Repeated pets share one field across pages, so each widget is one
"row" and all rows with the same field belong to the same pet.

Writes data/pets.json and data/parse_report.md. Exits with code 1 if any
validation count (spec §3.3) does not match.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Circuit, CircuitStop, Pet, Source  # noqa: E402

DEFAULT_PDF = ROOT / "data" / "source" / "pet_farming_guide_asmodian.pdf"
OUT_JSON = ROOT / "data" / "pets.json"
OUT_REPORT = ROOT / "data" / "parse_report.md"

GUIDE_VERSION = "2026-10-12"

# Fill colours of the genus dots / legend in the guide.
GENUS_RGB = {
    (0.616, 0.286, 0.875): "Cogni",
    (0.875, 0.416, 0.145): "Fera",
    (0.145, 0.518, 0.263): "Natura",
    (0.094, 0.486, 0.718): "Varian",
}

KEY_PAGES = {3: "Altgard", 8: "Verteron"}
CIRCUIT_PAGES = {4: "Altgard", 9: "Verteron"}
ISLAND_PAGES = {5: "Spirit Isle", 6: "Immortal Isle", 10: "Crimson Isle", 11: "Eternal Isle"}
ABYSS_CARD_PAGE = 13
ABYSS_TABLE_PAGES = {14: "Sulfur Tree Island", 15: "Siel's Wings"}
CHEST_PAGE = 16
BOSS_PAGE = 17
NOTES_PAGE = 18

# Collection tour order from page 12 (Devastated Remnants is the alternative to area 1).
ABYSS_AREA_ORDER = {
    "Black Fragments Area": 1,
    "Devastated Remnants": 1,
    "Siel's Wings": 2,
    "Reshanta's Root": 3,
    "Sulfur Tree Island": 4,
}

EXPECTED = {
    "Altgard key rows": 90,
    "Altgard key areas": 13,
    "Verteron key rows": 37,
    "Verteron key areas": 13,
    "Spirit Isle rows": 16,
    "Immortal Isle rows": 23,
    "Crimson Isle rows": 10,
    "Eternal Isle rows": 22,
    "Sulfur Tree Island monster variants": 10,
    "Sulfur Tree Island pets": 9,
    "Siel's Wings monster variants": 11,
    "Siel's Wings pets": 11,
    "Abyss distinct pets": 25,
    "Chest/merchant pets": 35,
    "Chest/merchant Cogni": 6,
    "Chest/merchant Fera": 12,
    "Chest/merchant Natura": 9,
    "Chest/merchant Varian": 8,
    "Distinct pet fields": 200,
}


class ParseError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    color: int
    size: float
    bold: bool

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Widget:
    field: str
    x0: float
    y0: float
    x1: float
    y1: float
    checked: bool
    border: tuple | None

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def rgb3(c):
    return tuple(round(v, 3) for v in c) if c else None


def page_lines(page) -> list[Line]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for ln in block.get("lines", []):
            spans = ln["spans"]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            s0 = spans[0]
            x0, y0, x1, y1 = ln["bbox"]
            out.append(Line(x0, y0, x1, y1, text, s0["color"], round(s0["size"], 1), "Bold" in s0["font"]))
    return out


def page_widgets(doc, page) -> list[Widget]:
    """Checkbox widgets. A box counts as ticked if either its own appearance
    state or the shared parent field value is /Yes (some viewers only update one)."""
    out = []
    for w in page.widgets():
        x = w.xref
        state = doc.xref_get_key(x, "AS")[1]
        parent = doc.xref_get_key(x, "Parent")
        pval = None
        if parent[0] == "xref":
            pval = doc.xref_get_key(int(parent[1].split()[0]), "V")[1]
        own = doc.xref_get_key(x, "V")[1]
        checked = "/Yes" in (state, own, pval) or w.field_value == "Yes"
        r = w.rect
        out.append(Widget(w.field_name, r.x0, r.y0, r.x1, r.y1, checked, rgb3(w.border_color)))
    return out


def same_row(lines, w, tol=5.0):
    return [l for l in lines if abs(l.cy - w.cy) <= tol]


def clean_pet(text: str) -> tuple[str, bool]:
    """Strip 'Pet:' prefix and the gold '*' marker. Returns (name, starred)."""
    t = re.sub(r"^Pet:\s*", "", text.strip())
    starred = t.endswith("*")
    t = t.rstrip("*").strip()
    return re.sub(r"\s+", " ", t), starred


def clean_monster(text: str) -> tuple[str, bool]:
    elite = "[ELITE]" in text
    t = text.replace("[ELITE]", "").strip()
    return re.sub(r"\s+", " ", t), elite


def pet_name_lines(lines, w, max_dx=30):
    """Pet name to the right of the checkbox, plus wrapped continuation lines."""
    first = [l for l in same_row(lines, w) if w.x1 - 2 <= l.x0 <= w.x1 + max_dx]
    if not first:
        raise ParseError(f"no pet name next to {w.field} at {w.x0:.0f},{w.y0:.0f}")
    first.sort(key=lambda l: l.x0)
    head = first[0]
    parts = [head]
    y = head.y1
    while True:
        nxt = [
            l for l in lines
            if abs(l.x0 - head.x0) < 1.5 and 0 <= l.y0 - y < 6
            and l.color == head.color and l.bold == head.bold
            and not l.text.startswith("Kill:")
        ]
        if not nxt:
            break
        parts.append(nxt[0])
        y = nxt[0].y1
    return parts


def pet_name(lines, w, max_dx=30) -> tuple[str, bool]:
    parts = pet_name_lines(lines, w, max_dx)
    return clean_pet(" ".join(p.text for p in parts))


def nearest_above(cands, y):
    above = [c for c in cands if c.y0 < y]
    return max(above, key=lambda c: c.y0) if above else None


def genus_dots(page):
    dots = []
    for d in page.get_drawings():
        g = GENUS_RGB.get(rgb3(d.get("fill")))
        if g and d["rect"].width < 10 and d["rect"].height < 10:
            dots.append((d["rect"], g))
    return dots


# --------------------------------------------------------------------------- row record


@dataclass
class Row:
    page: int
    field: str
    name: str
    checked: bool
    source: Source | None = None
    genus: str | None = None
    genus_conf: str | None = None


class GuideParser:
    def __init__(self, pdf_path: Path):
        self.doc = pymupdf.open(str(pdf_path))
        if self.doc.page_count != 19:
            raise ParseError(f"expected 19 pages, got {self.doc.page_count}")
        self.rows: list[Row] = []
        self.circuits: list[Circuit] = []
        self.counts: dict[str, int] = {}
        self.notes: dict[str, dict] = {}  # field -> {"held":..., "note":...}
        self.warnings: list[str] = []
        self.circuit_titles: list[tuple[float, float]] = []
        self.maps: dict[str, dict] = {}

    # -- page helpers
    def _page(self, pn):
        p = self.doc[pn - 1]
        return p, page_lines(p), page_widgets(self.doc, p)

    # -- pages 3 / 8: monster -> pet key
    def parse_key(self, pn, zone):
        page, lines, widgets = self._page(pn)
        heads = [l for l in lines if l.bold and l.size >= 11 and re.match(r"^\d\d\s", l.text)]
        col_starts = sorted(l.x0 for l in lines if l.text == "MONSTER TO KILL")
        areas = set()
        for w in widgets:
            name, star = pet_name(lines, w)
            col_x = max(x for x in col_starts if x < w.x0) - 2
            col_heads = [h for h in heads if col_x <= h.x0 < w.x0]
            head = nearest_above(col_heads, w.y0)
            if not head:
                raise ParseError(f"p{pn}: no area header for {w.field}")
            m = re.match(r"^(\d\d)\s+(.+)$", head.text)
            area_no, area = int(m.group(1)), m.group(2).strip()
            areas.add(area_no)
            left = [l for l in same_row(lines, w) if col_x <= l.x0 and l.x1 <= w.x0]
            if len(left) != 1:
                raise ParseError(f"p{pn}: expected one monster left of {w.field}, got {[l.text for l in left]}")
            monster, elite = clean_monster(left[0].text)
            g = GENUS_RGB.get(w.border)
            self.rows.append(Row(
                pn, w.field, name, w.checked,
                Source(zone=zone, area_no=area_no, area=area, monster=monster, elite=elite,
                       priority_addition=star, source_type="monster", page=pn),
                genus=g, genus_conf="low" if g else None,
            ))
        self.counts[f"{zone} key rows"] = len(widgets)
        self.counts[f"{zone} key areas"] = len(areas)

    # -- pages 4 / 9: short loops
    def parse_circuits(self, pn, zone):
        page, lines, widgets = self._page(pn)
        titles = [l for l in lines if l.bold and l.size == 16.0]
        by_title: dict[int, list] = defaultdict(list)
        for w in widgets:
            cands = [t for t in titles if t.x0 < w.x0 and w.x0 - t.x0 < 700]
            title = nearest_above(cands, w.y0)
            if not title:
                raise ParseError(f"p{pn}: no circuit title for {w.field}")
            name, _ = pet_name(lines, w)
            pocket = [l for l in same_row(lines, w) if w.x0 - 25 <= l.x0 < w.x0 and re.fullmatch(r"[A-Z]", l.text)]
            kill = [l for l in lines if abs(l.x0 - w.x0) < 2 and l.y0 > w.y0 and l.text.startswith("Kill:")]
            if not pocket or not kill:
                raise ParseError(f"p{pn}: incomplete circuit stop {w.field}")
            kill = min(kill, key=lambda l: l.y0)
            monster = kill.text.split(":", 1)[1].strip()
            by_title[id(title)].append((title, CircuitStop(pocket[0].text, w.field, name, monster), w))
        for stops in by_title.values():
            title = stops[0][0]
            sub = [l for l in lines if abs(l.x0 - title.x0) < 2 and 0 < l.y0 - title.y1 < 20]
            lv, note = None, None
            if sub:
                m = re.match(r"^Lv\s*([\d\-–]+)\s*\|\s*(.*)$", sub[0].text)
                if m:
                    lv, note = m.group(1).replace("–", "-"), m.group(2).strip()
            self.circuits.append(Circuit(
                zone=zone, name=title.text, level_range=lv, note=note, page=pn,
                stops=sorted((s for _, s, _ in stops), key=lambda s: s.pocket),
            ))
            self.circuit_titles.append((title.x0, title.y0))
            for _, stop, w in stops:
                self.rows.append(Row(pn, w.field, stop.pet_name, w.checked))

    # -- pages 5 / 6 / 10 / 11: island tables
    def parse_island(self, pn, zone):
        page, lines, widgets = self._page(pn)
        dots = genus_dots(page)
        for w in widgets:
            name, star = pet_name(lines, w)
            row = same_row(lines, w)
            pin = [l for l in row if l.x1 < w.x0 and re.fullmatch(r"\d+", l.text)]
            mon = [l for l in row if l.x1 < w.x0 - 5 and not re.fullmatch(r"\d+", l.text) and l.x0 > 700]
            lv = [l for l in row if l.x0 > 1380 and re.fullmatch(r"\d+", l.text)]
            if len(mon) != 1 or not pin or not lv:
                raise ParseError(f"p{pn}: bad island row {w.field}: {[l.text for l in row]}")
            monster, elite = clean_monster(mon[0].text)
            g = [gn for r, gn in dots if w.x0 - 20 < r.x0 < w.x0 and abs((r.y0 + r.y1) / 2 - w.cy) < 6]
            p = pin[0].text
            self.rows.append(Row(
                pn, w.field, name, w.checked,
                Source(zone=zone, area=f"Pocket {p}", area_no=int(p), pin=p, monster=monster,
                       level=int(lv[0].text), elite=elite, priority_addition=star,
                       source_type="monster", page=pn),
                genus=g[0] if g else None, genus_conf="high" if g else None,
            ))
            if not g:
                self.warnings.append(f"p{pn}: no genus dot for {name} ({w.field})")
        self.counts[f"{zone} rows"] = len(widgets)

    # -- page 13: fragment / root cards
    def parse_abyss_cards(self):
        pn = ABYSS_CARD_PAGE
        page, lines, widgets = self._page(pn)
        titles = [l for l in lines if l.color == 0xC2A5FF and l.size == 17.0]
        for w in widgets:
            name, star = pet_name(lines, w, max_dx=12)
            title = nearest_above([t for t in titles if t.x0 <= w.x0 and w.x0 - t.x0 < 60], w.y0)
            pocket = [l for l in same_row(lines, w) if l.x1 <= w.x0 and re.fullmatch(r"[A-Z]", l.text)]
            below = sorted([l for l in lines if abs(l.x0 - w.x0) < 2 and 0 < l.y0 - w.y1 < 45], key=lambda l: l.y0)
            if not title or not pocket or len(below) < 2:
                raise ParseError(f"p{pn}: incomplete card row {w.field}")
            m = re.match(r"^(.*?)\s*/\s*Lv\s*(\d+)\s*(\[ELITE\])?\s*$", below[0].text)
            if not m:
                raise ParseError(f"p{pn}: cannot read monster line {below[0].text!r}")
            area = title.text
            self.rows.append(Row(
                pn, w.field, name, w.checked,
                Source(zone="Abyss", area=area, area_no=ABYSS_AREA_ORDER.get(area),
                       sub_location=below[1].text, monster=m.group(1).strip(), level=int(m.group(2)),
                       pin=pocket[0].text, elite=bool(m.group(3)), priority_addition=star,
                       source_type="monster", page=pn),
            ))

    # -- pages 14 / 15: Abyss island tables
    def parse_abyss_table(self, pn, area):
        page, lines, widgets = self._page(pn)
        heads = [l for l in lines if l.color == 0xC2A5FF and l.size == 12.1 and 750 < l.x0 < 800]
        pins = [l for l in lines if l.color == 0xC2A5FF and re.fullmatch(r"\d", l.text) and 730 < l.x0 < 750]
        for w in widgets:
            name, star = pet_name(lines, w)
            head = nearest_above(heads, w.y0)
            pin = nearest_above(pins, w.y0)
            row = same_row(lines, w)
            mon = [l for l in row if 700 < l.x0 and l.x1 < w.x0]
            lv = [l for l in row if l.x0 > 1380 and re.fullmatch(r"\d+", l.text)]
            if not head or len(mon) != 1 or not lv:
                raise ParseError(f"p{pn}: bad Abyss row {w.field}: {[l.text for l in row]}")
            elite_line = [l for l in lines if l.text == "[ELITE]" and abs(l.x0 - mon[0].x0) < 2 and 0 < l.y0 - mon[0].y1 < 10]
            monster, elite = clean_monster(mon[0].text)
            self.rows.append(Row(
                pn, w.field, name, w.checked,
                Source(zone="Abyss", area=area, area_no=ABYSS_AREA_ORDER.get(area),
                       sub_location=head.text, pin=pin.text if pin else None, monster=monster,
                       level=int(lv[0].text), elite=elite or bool(elite_line), priority_addition=star,
                       source_type="monster", page=pn),
            ))
        self.counts[f"{area} monster variants"] = len(widgets)
        self.counts[f"{area} pets"] = len({w.field for w in widgets})

    # -- page 16: chests & merchants
    def parse_chests(self):
        pn = CHEST_PAGE
        page, lines, widgets = self._page(pn)
        heads = [l for l in lines if l.size == 20.0 and l.text.capitalize() in ("Cogni", "Fera", "Natura", "Varian")]
        per = Counter()
        for w in widgets:
            name, _ = pet_name(lines, w)
            head = nearest_above([h for h in heads if abs(h.x0 - w.x0) < 15], w.y0)
            if not head:
                raise ParseError(f"p{pn}: no genus heading for {w.field}")
            genus = head.text.capitalize()
            per[genus] += 1
            self.rows.append(Row(
                pn, w.field, name, w.checked,
                Source(zone="Other", area="Chests & merchants", sub_location=f"{genus} chests + merchants",
                       source_type="chest_merchant", page=pn),
                genus=genus, genus_conf="high",
            ))
        self.counts["Chest/merchant pets"] = len(widgets)
        for g in ("Cogni", "Fera", "Natura", "Varian"):
            self.counts[f"Chest/merchant {g}"] = per[g]

    # -- page 17: bosses, dungeons, Abyss index
    def parse_bosses(self):
        pn = BOSS_PAGE
        page, lines, widgets = self._page(pn)
        sections = [l for l in lines if l.color == 0xFFDF85 and l.size == 16.0]
        for w in widgets:
            name, _ = pet_name(lines, w)
            sec = nearest_above(sections, w.y0)
            info = [l for l in same_row(lines, w) if l.x0 > 400]
            if not sec or not info:
                raise ParseError(f"p{pn}: bad boss row {w.field}")
            monster, _, where = info[0].text.partition("|")
            monster, where = monster.strip(), where.strip()
            if sec.text.startswith("ABYSS INDEX"):
                # Index of pets already covered on pages 13-15; no new source.
                self.rows.append(Row(pn, w.field, name, w.checked))
                continue
            if sec.text.startswith("VERTERON FIELD BOSSES"):
                src = Source(zone="Verteron", area=where, monster=monster, source_type="boss", page=pn)
            else:
                lv = re.search(r"\(Lv\s*(\d+)\s*field boss\)", where)
                place = re.sub(r"\s*\(.*\)\s*$", "", where)
                src = Source(zone="Other", area=place, monster=monster,
                             level=int(lv.group(1)) if lv else None,
                             source_type="boss" if lv else "dungeon", page=pn)
            self.rows.append(Row(pn, w.field, name, w.checked, src))

    # -- page 18: held + unconfirmed
    def parse_notes(self):
        pn = NOTES_PAGE
        page, lines, widgets = self._page(pn)
        sections = [l for l in lines if l.color == 0xFFDF85 and l.size == 16.0]
        for w in widgets:
            name, _ = pet_name(lines, w)
            sec = nearest_above(sections, w.y0)
            info = [l for l in same_row(lines, w) if l.x0 > 400]
            text = info[0].text if info else ""
            entry = self.notes.setdefault(w.field, {"held": False, "note": None})
            if sec and sec.text.startswith("HELD"):
                entry["held"] = True
                entry["held_text"] = text
            elif sec and sec.text.startswith("UNCONFIRMED"):
                entry["note"] = text
            self.rows.append(Row(pn, w.field, name, w.checked))

    # -- everything
    def parse(self):
        for pn, zone in KEY_PAGES.items():
            self.parse_key(pn, zone)
        for pn, zone in CIRCUIT_PAGES.items():
            self.parse_circuits(pn, zone)
        for pn, zone in ISLAND_PAGES.items():
            self.parse_island(pn, zone)
        self.parse_abyss_cards()
        for pn, area in ABYSS_TABLE_PAGES.items():
            self.parse_abyss_table(pn, area)
        self.parse_chests()
        self.parse_bosses()
        self.parse_notes()
        # Every widget in the document must have been consumed.
        total = sum(len(list(p.widgets())) for p in self.doc)
        if total != len(self.rows):
            raise ParseError(f"consumed {len(self.rows)} of {total} checkbox widgets")
        abyss = {r.field for r in self.rows if r.page in (13, 14, 15)}
        self.counts["Abyss distinct pets"] = len(abyss)
        self.counts["Distinct pet fields"] = len({r.field for r in self.rows})
        return self.build()

    def build(self):
        by_field: dict[str, list[Row]] = defaultdict(list)
        for r in self.rows:
            by_field[r.field].append(r)
        pets = []
        self.name_conflicts = {}
        self.genus_conflicts = {}
        for fid in sorted(by_field):
            rows = by_field[fid]
            names = Counter(r.name for r in rows)
            name = names.most_common(1)[0][0]
            if len(names) > 1:
                self.name_conflicts[fid] = dict(names)
            # Genus: high-confidence votes win over low.
            high = Counter(r.genus for r in rows if r.genus and r.genus_conf == "high")
            low = Counter(r.genus for r in rows if r.genus and r.genus_conf == "low")
            genus, conf = None, None
            if high:
                genus, conf = high.most_common(1)[0][0], "high"
                if len(high) > 1:
                    self.genus_conflicts[fid] = {"high": dict(high), "low": dict(low)}
            elif low:
                genus, conf = low.most_common(1)[0][0], "low"
                if len(low) > 1:
                    self.genus_conflicts[fid] = {"low": dict(low)}
            if high and low and set(low) - set(high):
                self.genus_conflicts.setdefault(fid, {"high": dict(high), "low": dict(low)})
            note = self.notes.get(fid, {})
            sources = [r.source for r in sorted(rows, key=lambda r: r.page) if r.source]
            pets.append(Pet(
                id=fid, name=name, genus=genus, genus_confidence=conf,
                held=note.get("held", False), unconfirmed_note=note.get("note"),
                pdf_checked=any(r.checked for r in rows), sources=sources,
            ))
        self.pets = pets
        return pets

    # -- validation + report
    def validate(self) -> list[str]:
        fails = []
        for k, exp in EXPECTED.items():
            got = self.counts.get(k)
            if got != exp:
                fails.append(f"{k}: expected {exp}, got {got}")
        return fails

    def border_agreement(self):
        """How often the p3/p8 checkbox colour matches a high-confidence genus."""
        high = {}
        for r in self.rows:
            if r.genus_conf == "high":
                high[r.field] = r.genus
        agree = disagree = 0
        mism = []
        for r in self.rows:
            if r.genus_conf == "low" and r.field in high:
                if r.genus == high[r.field]:
                    agree += 1
                else:
                    disagree += 1
                    mism.append(f"{r.name} ({r.field}): box {r.genus}, dot/heading {high[r.field]}")
        return agree, disagree, mism

    def circuit_mismatches(self):
        """Circuit 'Kill:' names that differ from the zone key for the same pet."""
        key = defaultdict(set)
        for p in self.pets:
            for s in p.sources:
                if s.page in (3, 8) and s.monster:
                    key[(s.zone, p.id)].add(s.monster)
        out = []
        for c in self.circuits:
            for st in c.stops:
                known = key.get((c.zone, st.pet_id), set())
                if st.monster not in known:
                    out.append(f"{c.zone} / {c.name} / {st.pocket}: kill '{st.monster}' for {st.pet_name}; key says {sorted(known) or 'nothing'}")
        return out

    def report(self, fails) -> str:
        agree, disagree, mism = self.border_agreement()
        L = ["# Parse report", "", f"Guide version {GUIDE_VERSION}. {len(self.pets)} pets, "
             f"{sum(len(p.sources) for p in self.pets)} sources, {len(self.circuits)} circuits.", ""]
        L += ["## Validation counts (spec §3.3)", "", "| Check | Expected | Got | |", "|---|---|---|---|"]
        for k, exp in EXPECTED.items():
            got = self.counts.get(k)
            L.append(f"| {k} | {exp} | {got} | {'OK' if got == exp else '**FAIL**'} |")
        L += ["", f"**{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' CHECK(S) FAILED'}**", ""]

        checked = sorted(p.id for p in self.pets if p.pdf_checked)
        L += ["## Ticked in the PDF", "", f"{len(checked)} pets: " + ", ".join(
            f"{p.name} (`{p.id}`)" for p in self.pets if p.pdf_checked), ""]

        gc = Counter(p.genus_confidence for p in self.pets)
        L += ["## Genus", "",
              f"- high confidence (island dot or chest heading): {gc['high']}",
              f"- low confidence (p3/p8 checkbox colour only): {gc['low']}",
              f"- unknown: {gc[None]}", "",
              f"Checkbox colour vs dot/heading, where both exist: {agree} agree, {disagree} disagree.", ""]
        if mism:
            L += [f"- {m}" for m in mism] + [""]
        if self.genus_conflicts:
            L += ["Conflicting genus votes:", ""] + [f"- `{k}` {v}" for k, v in self.genus_conflicts.items()] + [""]
        L += ["### Low confidence", ""] + [f"- {p.name} (`{p.id}`): {p.genus}" for p in self.pets if p.genus_confidence == "low"] + [""]
        L += ["### Unknown genus (needs review)", ""] + [f"- {p.name} (`{p.id}`)" for p in self.pets if not p.genus] + [""]

        L += ["## Name consistency", ""]
        if self.name_conflicts:
            L += [f"- `{k}`: {v}" for k, v in self.name_conflicts.items()]
        else:
            L += ["Every field has the same pet name on every page."]
        L += [""]

        mm = self.circuit_mismatches()
        L += ["## Circuit kill names that differ from the zone key", ""]
        L += [f"- {m}" for m in mm] if mm else ["None."]
        L += [""]

        nosrc = [p for p in self.pets if not p.sources]
        L += ["## Pets with no farmable source", ""] + [
            f"- {p.name} (`{p.id}`)" + (" — held" if p.held else "") for p in nosrc] + [""]
        if self.warnings:
            L += ["## Warnings", ""] + [f"- {w}" for w in self.warnings] + [""]
        return "\n".join(L)


def to_json(pets, circuits, maps=None) -> dict:
    return {
        "guide_version": GUIDE_VERSION,
        "faction": "Asmodian",
        "pets": [p.to_json() for p in pets],
        "circuits": [c.to_json() for c in circuits],
        "maps": maps or {},
    }


def run(pdf: Path, out_json: Path = OUT_JSON, out_report: Path = OUT_REPORT) -> int:
    gp = GuideParser(pdf)
    pets = gp.parse()
    fails = gp.validate()
    from tools.maps import attach_links, attach_maps, build_maps
    gp.maps = build_maps(gp, out_json.parent / "maps")
    attach_maps(gp)
    attach_links(gp)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(to_json(pets, gp.circuits, gp.maps), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out_report.write_text(gp.report(fails), encoding="utf-8")
    print(f"Wrote {out_json.relative_to(ROOT)} ({len(pets)} pets) and {out_report.relative_to(ROOT)}")
    if fails:
        print("VALIDATION FAILED:", *fails, sep="\n  ", file=sys.stderr)
        return 1
    print("All validation counts match.")
    return 0


if __name__ == "__main__":
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    sys.exit(run(pdf))
