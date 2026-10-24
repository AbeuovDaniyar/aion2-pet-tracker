"""Map panels from the guide PDF: render each map to an image, record pin label positions,
and link every source to the panel + pin that shows where to farm it."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

PAGE_TITLES = {
    2: "Altgard · mainland areas",
    7: "Verteron · mainland areas",
    5: "Spirit Isle",
    6: "Immortal Isle",
    10: "Crimson Isle",
    11: "Eternal Isle",
    12: "Abyss · Lower Reshanta overview",
    14: "Abyss · Sulfur Tree Island",
    15: "Abyss · Siel's Wings",
}
FULL_IMAGE_PAGES = (2, 7, 12)       # map is the page's big image
LINKED_PANEL_PAGES = (4, 5, 6, 9, 10, 11, 13, 14, 15)  # map panels are covered by a petsouls.dev link
LABEL_RE = re.compile(r"^(\d{1,2}|[A-MO-Z](/[A-Z])*|ALT)$")  # 'N' is the north arrow
TARGET_PX = 1800
ISLAND_ON_MAINLAND = {5: ("p2", "A"), 6: ("p2", "B"), 10: ("p7", "A"), 11: ("p7", "B")}
ABYSS_OVERVIEW = {"Black Fragments Area": "1", "Devastated Remnants": "ALT", "Reshanta's Root": "3",
                  "Sulfur Tree Island": "4", "Siel's Wings": "2"}


def _panels(doc) -> list[tuple[str, int, pymupdf.Rect]]:
    out = []
    for pn in FULL_IMAGE_PAGES:
        page = doc[pn - 1]
        big = max(page.get_image_info(), key=lambda i: (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]))
        out.append((f"p{pn}", pn, pymupdf.Rect(big["bbox"]) & page.rect))
    for pn in LINKED_PANEL_PAGES:
        page = doc[pn - 1]
        rects = sorted({tuple(round(v) for v in l["from"]) for l in page.get_links()
                        if "petsouls.dev" in l.get("uri", "") and l["from"].width > 200 and l["from"].height > 200},
                       key=lambda r: (r[1], r[0]))
        for i, r in enumerate(rects):
            pid = f"p{pn}" if len(rects) == 1 else f"p{pn}_{i}"
            out.append((pid, pn, pymupdf.Rect(r)))
    return out


def _labels(page, rect: pymupdf.Rect) -> list[tuple[str, float, float]]:
    out = []
    for b in page.get_text("dict", clip=rect)["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            bb = pymupdf.Rect(ln["bbox"])
            if t and rect.contains(bb) and LABEL_RE.match(t):
                out.append((t, (bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2))
    return out


def build_maps(gp, out_dir: Path) -> dict:
    doc = gp.doc
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    maps = {}
    card_titles = {}
    p13 = doc[12]
    for b in p13.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            s = ln["spans"][0]
            if round(s["size"]) == 17:
                card_titles[ln["bbox"][0]] = "".join(x["text"] for x in ln["spans"]).strip()
    for pid, pn, rect in _panels(doc):
        page = doc[pn - 1]
        zoom = TARGET_PX / max(rect.width, rect.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, alpha=False)
        fname = f"{pid}.jpg"
        pix.save(str(out_dir / fname), jpg_quality=90)
        labels: dict[str, list[float]] = {}
        for text, x, y in _labels(page, rect):
            pt = [round((x - rect.x0) * zoom, 1), round((y - rect.y0) * zoom, 1)]
            for part in text.split("/"):
                labels.setdefault(part, pt)
        title = PAGE_TITLES.get(pn)
        if pn == 13:
            near = min(card_titles, key=lambda x0: abs(x0 - rect.x0), default=None)
            title = f"Abyss · {card_titles.get(near, 'fragment area')}"
        maps[pid] = {"page": pn, "title": title or f"Page {pn}", "image": f"maps/{fname}",
                     "size": [pix.width, pix.height], "labels": labels}
    # Loop panels take their circuit's name.
    for c, (tx, ty) in zip(gp.circuits, gp.circuit_titles):
        for pid, m in maps.items():
            if m["page"] != c.page:
                continue
            r = [p for p in _panels(doc) if p[0] == pid][0][2]
            if abs(r.x0 - tx) < 12 and 0 < r.y0 - ty < 90:
                c.panel = pid
                m["title"] = f"{c.zone} loop · {c.name}"
    return maps


def _panel_for_area_p13(maps, area):
    for pid, m in maps.items():
        if m["page"] == 13 and m["title"].endswith(area):
            return pid
    return None


def attach_maps(gp) -> None:
    maps = gp.maps
    verteron_areas = {}
    for p in gp.pets:
        for s in p.sources:
            if s.page == 8 and s.area_no:
                verteron_areas[s.area] = s.area_no

    def ok(pid, label):
        if pid in maps and label in maps[pid]["labels"]:
            return [pid, label]
        gp.warnings.append(f"map: no pin '{label}' on panel {pid}")
        return None

    for p in gp.pets:
        for s in p.sources:
            views = []
            if s.page == 3:
                views = [ok("p2", str(s.area_no))]
            elif s.page == 8:
                views = [ok("p7", str(s.area_no))]
            elif s.page in ISLAND_ON_MAINLAND:
                views = [ok(f"p{s.page}", s.pin), ok(*ISLAND_ON_MAINLAND[s.page])]
            elif s.page == 13:
                pid = _panel_for_area_p13(maps, s.area)
                views = [ok(pid, s.pin) if pid else None, ok("p12", ABYSS_OVERVIEW[s.area])]
            elif s.page in (14, 15):
                views = [ok(f"p{s.page}", s.pin), ok("p12", ABYSS_OVERVIEW[s.area])]
            elif s.page == 17 and s.zone == "Verteron" and s.area in verteron_areas:
                views = [ok("p7", str(verteron_areas[s.area]))]
            s.map = [v for v in views if v]


def attach_links(gp) -> None:
    uris = [l["uri"] for page in gp.doc for l in page.get_links() if l.get("uri")]
    for p in gp.pets:
        num = p.id.split("_")[1]
        atlas = [u for u in uris if "petsouls.dev" in u and u.rstrip("/").endswith("/" + num)]
        db = [u for u in uris if "gaming.tools/pets/" in u and u.rstrip("/").endswith("/" + num)]
        order = {"altgard": 0, "verteron": 1, "reshanta": 2}
        atlas.sort(key=lambda u: next((v for k, v in order.items() if f"/{k}/" in u), 9))
        p.links = {k: v for k, v in (("atlas", atlas[0] if atlas else None), ("database", db[0] if db else None)) if v}
