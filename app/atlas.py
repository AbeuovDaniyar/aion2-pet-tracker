"""Pet Soul Atlas (petsouls.dev) data: every Global pet, the monsters that drop it, and where they spawn.

The atlas ships its dataset as a JavaScript module (assets/data-<hash>.js). We download it,
evaluate it with Qt's JavaScript engine, keep a compact summary in the user data folder
(atlas.json), and merge that into the guide data when the store loads:

* monsters the guide doesn't list become extra sources (zone, area, level, elite, spawn count)
* guide sources that the atlas also has get the spawn count added
* pets whose genus the guide doesn't give (or only guesses) take the atlas genus

The guide stays the base: its pins, maps and routes are untouched.
"""
from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.paths import USER_DATA

BASE = "https://petsouls.dev/"
CACHE = USER_DATA / "atlas.json"
UA = {"User-Agent": "AION2-Pet-Tracker (personal fan tool; caches the atlas data locally)"}

# atlas world key -> (tracker zone, url slug)
WORLDS = {
    "World_D_A": ("Altgard", "altgard"),
    "World_L_A": ("Verteron", "verteron"),
    "Abyss_Reshanta_A": ("Abyss", "reshanta"),
}
ISLANDS = {"Spirit Isle", "Immortal Isle", "Crimson Isle", "Eternal Isle"}


# ---------------------------------------------------------------------------- download + decode

def _get(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def find_data_url() -> str:
    """The data file name carries a content hash that changes with every atlas deploy."""
    html = _get(BASE)
    m = re.search(r'src="/?(assets/index-[\w-]+\.js)"', html)
    if not m:
        raise RuntimeError("Pet Soul Atlas page layout changed (no index script)")
    js = _get(BASE + m.group(1))
    d = re.search(r'(assets/)?(data-[\w-]+\.js)', js)
    if not d:
        raise RuntimeError("Pet Soul Atlas page layout changed (no data module)")
    return BASE + "assets/" + d.group(2)


def evaluate_module(src: str) -> dict:
    """Run the ES module text and return its exports as plain Python data."""
    from PySide6.QtQml import QJSEngine

    m = re.search(r"export\s*\{([^}]*)\}\s*;?\s*$", src.strip())
    if not m:
        raise RuntimeError("unexpected atlas data format (no export)")
    items = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        local, _, exported = part.partition(" as ")
        items.append(f"{(exported or local).strip()}:{local.strip()}")
    body = src.strip()[:m.start()] + ";({" + ",".join(items) + "})"
    eng = QJSEngine()
    val = eng.evaluate(body)
    if val.isError():
        raise RuntimeError(f"atlas data failed to load: {val.toString()}")
    exports = val.toVariant()
    for v in exports.values():
        if isinstance(v, dict) and "pets" in v and "npcs" in v:
            return v
    raise RuntimeError("atlas data has no pets/npcs")


def decode_spawns(packed: list) -> dict[int, Counter]:
    """Packed per-world spawn list -> {npc index: Counter(subzone index -> spawns)}.
    Layout (from the atlas): npc, groups, then per group: subzone, count, count x (dx, dz)."""
    out: dict[int, Counter] = defaultdict(Counter)
    t = 0
    n = len(packed)
    while t < n:
        npc, groups = int(packed[t]), int(packed[t + 1])
        t += 2
        for _ in range(groups):
            zone, count = int(packed[t]), int(packed[t + 1])
            t += 2 + 2 * count
            out[npc][zone] += count
    return out


def summarize(data: dict) -> dict:
    """The parts the tracker uses, small enough to cache as JSON."""
    worlds = []
    for w in data["worlds"]:
        worlds.append({"key": w["key"], "slug": w["slug"], "name": w["name"], "faction": w.get("faction"),
                       "subzones": [s["n"] for s in w["subzones"]]})
    spawns = {}
    for key, packed in data.get("spawns", {}).items():
        spawns[key] = {str(npc): {str(z): c for z, c in zones.items()}
                       for npc, zones in decode_spawns(packed).items()}
    return {
        "fetched": datetime.now().isoformat(timespec="seconds"),
        "meta": data.get("meta", {}),
        "worlds": worlds,
        "pets": [{"id": int(p["id"]), "name": p["n"], "genus": p["c"], "npcs": [int(i) for i in p["npcs"]]}
                 for p in data["pets"]],
        "no_drop": [{"name": p["n"], "genus": p["c"]} for p in data.get("noDrop", [])],
        "npcs": [{"name": n["n"], "lv": n.get("lv"), "rank": n.get("r") or "Normal", "pet": int(n["pet"])}
                 for n in data["npcs"]],
        "spawns": spawns,
    }


def fetch(cache: Path = CACHE) -> dict:
    """Download the current atlas data and cache it. Raises on network or format problems."""
    url = find_data_url()
    summary = summarize(evaluate_module(_get(url, timeout=40)))
    summary["source_url"] = url
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return summary


def load_cache(cache: Path = CACHE) -> Optional[dict]:
    if not cache.exists():
        return None
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_age_days(atlas: Optional[dict]) -> Optional[float]:
    if not atlas or "fetched" not in atlas:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(atlas["fetched"])).total_seconds() / 86400
    except ValueError:
        return None


# ---------------------------------------------------------------------------- merge

def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", s.lower().replace("’", "'")).split())


def _area_parts(world_zone: str, subzone: str) -> tuple[str, str, Optional[str]]:
    """-> (tracker zone, area, sub_location)."""
    if subzone in ISLANDS:
        return subzone, subzone, None
    area, _, sub = subzone.partition(" - ")
    return world_zone, area, (sub or None)


def merge(pets: dict, atlas: dict) -> dict:
    """Merge atlas data into the store's pets (in place). Returns counts for the status bar."""
    from app.core.models import Source

    stats = Counter()
    worlds = {w["key"]: w for w in atlas.get("worlds", [])}
    npcs = atlas.get("npcs", [])
    spawns = atlas.get("spawns", {})
    by_id = {int(pid.split("_")[1]): p for pid, p in pets.items()}

    for ap in atlas.get("pets", []):
        pet = by_id.get(ap["id"])
        if pet is None:
            stats["unknown_pet"] += 1
            continue
        _merge_genus(pet, ap["genus"], stats)
        known = {(_norm(s.monster), s.zone) for s in pet.sources if s.monster}
        per_world_total = Counter()
        for idx in ap["npcs"]:
            if idx >= len(npcs):
                continue
            npc = npcs[idx]
            elite = npc.get("rank", "Normal") != "Normal"
            placed = False
            for wkey, (zone, slug) in WORLDS.items():
                zones = spawns.get(wkey, {}).get(str(idx))
                if not zones:
                    continue
                placed = True
                names = worlds.get(wkey, {}).get("subzones", [])
                total = sum(zones.values())
                per_world_total[slug] += total
                top_zone = max(zones.items(), key=lambda kv: kv[1])[0]
                sub_name = names[int(top_zone)] if int(top_zone) < len(names) else ""
                tz, area, sub = _area_parts(zone, sub_name)
                key = (_norm(npc["name"]), tz)
                match = next((s for s in pet.sources if s.monster and (_norm(s.monster), s.zone) == key), None)
                if match is not None:
                    match.spawns = total
                    if match.level is None:
                        match.level = npc.get("lv")
                    stats["enriched"] += 1
                    continue
                if key in known:
                    continue
                pet.sources.append(Source(zone=tz, area=area or zone, sub_location=sub, monster=npc["name"],
                                          level=npc.get("lv"), elite=elite, source_type="monster",
                                          origin="atlas", spawns=total))
                known.add(key)
                stats["added"] += 1
            if not placed and (_norm(npc["name"]), "Other") not in known:
                # Drops from a monster with no mapped spawn (dungeon / field boss elsewhere).
                if not any(s.monster and _norm(s.monster) == _norm(npc["name"]) for s in pet.sources):
                    pet.sources.append(Source(zone="Other", area="Off-map (dungeon / boss)", monster=npc["name"],
                                              level=npc.get("lv"), elite=elite,
                                              source_type="boss" if elite else "dungeon", origin="atlas"))
                    stats["added_offmap"] += 1
        if per_world_total:
            slug = next((s for s in ("altgard", "reshanta", "verteron") if per_world_total.get(s)), "altgard")
            pet.links.setdefault("atlas", f"{BASE}#/{slug}/{ap['id']}")
            pet.atlas_slug = slug  # type: ignore[attr-defined]
        else:
            pet.links.setdefault("atlas", f"{BASE}#/altgard/{ap['id']}")
    for nd in atlas.get("no_drop", []):
        pet = next((p for p in pets.values() if _norm(p.name) == _norm(nd["name"])), None)
        if pet:
            _merge_genus(pet, nd["genus"], stats)
    return dict(stats)


def _merge_genus(pet, genus: str, stats: Counter) -> None:
    if not genus:
        return
    if pet.genus_confidence in (None, "low") or pet.genus is None:
        if pet.genus != genus:
            stats["genus_filled" if pet.genus is None else "genus_corrected"] += 1
        pet.genus, pet.genus_confidence = genus, "atlas"
    elif pet.genus != genus and pet.genus_confidence == "high":
        stats["genus_conflict"] += 1


def atlas_url(pet) -> Optional[str]:
    return pet.links.get("atlas")
