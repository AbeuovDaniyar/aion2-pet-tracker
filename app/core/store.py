"""pets.json + genus overrides + SQLite progress."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .models import GENERA, Circuit, Pet, Progress

from app.paths import RES_DATA, USER_CONFIG, USER_DATA

DATA = RES_DATA          # shipped, read-only: pets.json, maps/
CONFIG = USER_CONFIG     # user settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
  pet_id        TEXT PRIMARY KEY,
  unlocked      INTEGER NOT NULL DEFAULT 0,
  level         INTEGER,
  max_level     INTEGER,
  souls_have    INTEGER,
  souls_need    INTEGER,
  maxed         INTEGER NOT NULL DEFAULT 0,
  manual_lock   INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT,
  updated_by    TEXT
);
CREATE TABLE IF NOT EXISTS level_requirements (
  level INTEGER PRIMARY KEY, need INTEGER NOT NULL, seen_count INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS card_hashes (
  pet_id TEXT, phash TEXT, resolution TEXT, PRIMARY KEY (pet_id, resolution)
);
CREATE TABLE IF NOT EXISTS ocr_log (
  id INTEGER PRIMARY KEY, ts TEXT, pet_id TEXT, raw_text TEXT,
  parsed_json TEXT, confidence REAL, screenshot_path TEXT, accepted INTEGER
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS level_need_counts (
  level INTEGER, need INTEGER, n INTEGER DEFAULT 1, PRIMARY KEY (level, need)
);
CREATE TABLE IF NOT EXISTS soul_log (
  id INTEGER PRIMARY KEY, ts TEXT, pet_id TEXT, amount INTEGER, text TEXT, result TEXT
);
"""

DEFAULT_SETTINGS = {
    "settings_version": 2,
    "ocr_threads": 2,  # CPU threads for OCR; lower = smoother game, slower scans
    "hotkeys": {
        "scan": "ctrl+shift+p",
        "toggle_overlay": "ctrl+shift+o",
        "overlay_interactive": "ctrl+shift+i",
        "toggle_overlay_map": "ctrl+shift+m",
    },
    "confirm_lookalikes": False,   # True = ask before saving a look-alike name (Karnif / Tamed Karnif)
    "confirm_hotkeys": {
        "confirm_yes": "ctrl+shift+y",
        "confirm_no": "ctrl+shift+n",
        "pick_1": "ctrl+shift+1",
        "pick_2": "ctrl+shift+2",
        "pick_3": "ctrl+shift+3",
    },
    "monitor_index": 1,
    "ocr_engine": "rapidocr",
    "ocr": {"scale": 2, "debug_keep": 50, "scan_delay_ms": 3000, "auto_interval_ms": 250},
    "sound": {"enabled": True},
    "field": {
        "enabled": True,
        "interval_ms": 1500,
        # "target" reads only the target frame (cheap); "full" scans the whole middle for nameplates
        "mode": "target",
        "target_region": [0.36, 0.01, 0.64, 0.09],
        # part of the screen to read, as fractions (x1, y1, x2, y2): skips chat, skill bar, quest list
        "region": [0.02, 0.02, 0.86, 0.76],
        "scale": 1.5,
        "notify_genera": ["Cogni"],
        "alert_cooldown_s": 90,
        "keep_s": 10,
        "track_souls": True,
        # chat box, as screen fractions; souls are read from "Obtained N <pet> Soul Points."
        "chat_region": [0.005, 0.80, 0.2, 0.95],   # newest ~9 lines; new messages appear at the bottom
    },
    "confidence": {"auto_accept": 0.90, "fuzzy_ratio": 92, "fuzzy_margin": 6},
    "overlay": {"opacity": 0.88, "x": 40, "y": 160, "width": 340, "height": 440, "top_n": 12,
                "visible": True, "hide_from_capture": False},
    "max_level": 3,
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _upgrade(s: dict) -> dict:
    """Older settings files carry the old, heavier defaults; move them to the lighter ones once."""
    if s.get("settings_version", 1) < 2:
        if s.get("ocr_threads", 4) == 4:
            s["ocr_threads"] = 2
        f = s.setdefault("field", {})
        f["mode"] = "target"
        if f.get("chat_region") == [0.005, 0.75, 0.2, 0.95]:
            f["chat_region"] = [0.005, 0.80, 0.2, 0.95]
        if f.get("interval_ms", 2000) in (2000, 2500, 3000):
            f["interval_ms"] = 1500
        s["settings_version"] = 2
    return s


def load_settings(path: Path = CONFIG / "settings.json") -> dict:
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            old = raw.get("settings_version", 1)
            s = _upgrade(_merge(DEFAULT_SETTINGS, {**raw, "settings_version": old}))
            if old < 2:
                save_settings(s, path)
            return s
        except (json.JSONDecodeError, OSError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_SETTINGS, indent=2) + "\n", encoding="utf-8")
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(settings: dict, path: Path = CONFIG / "settings.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, pets_json: Path = DATA / "pets.json", db_path: Path = USER_DATA / "progress.db",
                 overrides_path: Path = USER_DATA / "genus_overrides.json", max_level: int = 3,
                 atlas: Optional[dict] = None):
        self.pets_json = Path(pets_json)
        self.overrides_path = Path(overrides_path)
        self.default_max = max_level
        self._listeners: list[Callable[[set[str]], None]] = []

        raw = json.loads(self.pets_json.read_text(encoding="utf-8"))
        self._raw_pets = {d["id"]: d for d in raw["pets"]}
        self.guide_version = raw.get("guide_version")
        self.pets: dict[str, Pet] = {d["id"]: Pet.from_json(d) for d in raw["pets"]}
        self.circuits = [Circuit.from_json(c) for c in raw.get("circuits", [])]
        self.maps: dict[str, dict] = raw.get("maps", {})
        self.maps_dir = self.pets_json.parent
        self.atlas_stats: dict = {}
        self.atlas_meta: dict = {}
        self._build(atlas)

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.executescript(SCHEMA)
        self._progress: dict[str, Progress] = {}
        for row in self.db.execute(
            "SELECT pet_id, unlocked, level, max_level, souls_have, souls_need, maxed, manual_lock,"
            " updated_at, updated_by FROM progress"
        ):
            pid, unl, lvl, mx, have, need, maxed, lock, at, by = row
            self._progress[pid] = Progress(pid, bool(unl), lvl, mx, have, need, bool(maxed), bool(lock), at, by)
        self.pdf_import_count = self._import_pdf_ticks()

    # ------------------------------------------------------------------ guide + atlas
    def _build(self, atlas: Optional[dict]) -> None:
        """Guide data, plus the Pet Soul Atlas data when given, then genus overrides on top.
        Rebuilds in place so views holding Pet objects keep working."""
        for pid, pet in self.pets.items():
            fresh = Pet.from_json(self._raw_pets[pid])
            pet.sources, pet.links = fresh.sources, fresh.links
            pet.genus, pet.genus_confidence = fresh.genus, fresh.genus_confidence
        if atlas:
            from app.atlas import merge
            self.atlas_stats = merge(self.pets, atlas)
            self.atlas_meta = {"built": atlas.get("meta", {}).get("builtAt"), "fetched": atlas.get("fetched"),
                               "client": atlas.get("meta", {}).get("client")}
        for p in self.pets.values():
            p.parsed_genus = p.genus  # type: ignore[attr-defined]
            p.parsed_confidence = p.genus_confidence  # type: ignore[attr-defined]
        self._apply_overrides()

    def apply_atlas(self, atlas: Optional[dict]) -> dict:
        self._build(atlas)
        self._emit(set(self.pets))
        return self.atlas_stats

    # ------------------------------------------------------------------ events
    def subscribe(self, fn: Callable[[set[str]], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, ids: set[str]) -> None:
        for fn in list(self._listeners):
            fn(ids)

    # ------------------------------------------------------------------ genus
    def _load_overrides(self) -> dict[str, str]:
        if not self.overrides_path.exists():
            return {}
        try:
            return json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _apply_overrides(self) -> None:
        ov = self._load_overrides()
        by_name = {p.name: p for p in self.pets.values()}
        for p in self.pets.values():
            p.genus, p.genus_confidence = p.parsed_genus, p.parsed_confidence  # type: ignore[attr-defined]
        for key, genus in ov.items():
            p = self.pets.get(key) or by_name.get(key)
            if p and genus in GENERA:
                p.genus, p.genus_confidence = genus, "override"

    def set_genus_override(self, pet_id: str, genus: Optional[str]) -> None:
        """Write (or clear, with None) an override. Keyed by pet name like the spec example."""
        pet = self.pets[pet_id]
        ov = self._load_overrides()
        ov.pop(pet_id, None)
        if genus:
            ov[pet.name] = genus
        else:
            ov.pop(pet.name, None)
        self.overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self.overrides_path.write_text(json.dumps(dict(sorted(ov.items())), indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
        self._apply_overrides()
        self._emit({pet_id})

    # ------------------------------------------------------------------ progress
    def _import_pdf_ticks(self) -> int:
        done = self.db.execute("SELECT value FROM meta WHERE key='pdf_imported'").fetchone()
        if done:
            return 0
        n = 0
        for p in self.pets.values():
            if p.pdf_checked and not self.progress(p.id).unlocked:
                pr = self.progress(p.id)
                pr.unlocked = True
                self._write(pr, "pdf_import")
                n += 1
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('pdf_imported', ?)", (_now(),))
        self.db.commit()
        return n

    def progress(self, pet_id: str) -> Progress:
        pr = self._progress.get(pet_id)
        if pr is None:
            pr = Progress(pet_id)
        # hand out a copy so callers must go through save_progress
        return Progress(**pr.__dict__)

    def _write(self, pr: Progress, by: str) -> None:
        pr.updated_at, pr.updated_by = _now(), by
        self.db.execute(
            "INSERT OR REPLACE INTO progress VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pr.pet_id, int(pr.unlocked), pr.level, pr.max_level, pr.souls_have, pr.souls_need,
             int(pr.maxed), int(pr.manual_lock), pr.updated_at, pr.updated_by),
        )
        self._progress[pr.pet_id] = Progress(**pr.__dict__)

    def save_progress(self, pr: Progress, by: str = "manual") -> bool:
        """Persist progress. OCR writes are refused for locked pets."""
        current = self._progress.get(pr.pet_id)
        if by == "ocr" and current and current.manual_lock:
            return False
        if pr.maxed:
            pr.unlocked = True
        if pr.level is not None and pr.level >= 1:
            pr.unlocked = True
        mx = pr.max_level or self.default_max
        if pr.level is not None and pr.level >= mx:
            pr.maxed = True
        self._write(pr, by)
        self.db.commit()
        self._emit({pr.pet_id})
        return True

    def set_maxed(self, pet_id: str, maxed: bool) -> None:
        pr = self.progress(pet_id)
        pr.maxed = maxed
        if maxed:
            pr.level = pr.max_level or self.default_max
            pr.souls_have = pr.souls_need = None
        elif pr.level is not None and pr.level >= (pr.max_level or self.default_max):
            pr.level = None
        self.save_progress(pr)

    def set_unlocked(self, pet_id: str, unlocked: bool) -> None:
        pr = self.progress(pet_id)
        pr.unlocked = unlocked
        if not unlocked:
            pr.maxed, pr.level, pr.souls_have, pr.souls_need = False, None, None, None
        self.save_progress(pr)

    # ------------------------------------------------------------------ level requirements
    def record_level_requirement(self, level: int, need: int) -> None:
        """Remember how many souls a level took. Pets can differ, so count every value seen and use
        the most common one as the default for pets that haven't been scanned at that level."""
        self.db.execute("INSERT INTO level_need_counts(level, need) VALUES (?, ?) "
                        "ON CONFLICT(level, need) DO UPDATE SET n = n + 1", (level, need))
        best = self.db.execute("SELECT need FROM level_need_counts WHERE level=? ORDER BY n DESC, need DESC "
                               "LIMIT 1", (level,)).fetchone()[0]
        self.db.execute(
            "INSERT INTO level_requirements(level, need) VALUES (?, ?) "
            "ON CONFLICT(level) DO UPDATE SET need=excluded.need, seen_count=seen_count+1",
            (level, best),
        )
        self.db.commit()

    def level_requirements(self) -> dict[int, int]:
        return dict(self.db.execute("SELECT level, need FROM level_requirements"))

    def remaining_text(self, pet_id: str) -> str:
        """Short human summary of what is still missing for this pet."""
        pr = self.progress(pet_id)
        mx = pr.max_level or self.default_max
        if pr.maxed:
            return "MAX"
        if not pr.unlocked:
            return "not owned"
        if pr.souls_have is not None and pr.souls_need:
            left = max(pr.souls_need - pr.souls_have, 0)
            if pr.level is None:
                return f"{left} souls to next Lv"
            reqs = self.level_requirements()
            later = [reqs.get(l) for l in range(pr.level + 1, mx)]
            if all(v is not None for v in later):
                total = left + sum(later)  # type: ignore[arg-type]
                if total != left:
                    return f"{left} to Lv {pr.level + 1} · {total} to max"
            return f"{left} to Lv {pr.level + 1}"
        if pr.level is not None:
            return f"Lv {pr.level}/{mx}"
        return "owned"

    def add_souls(self, pet_id: str, amount: int, text: str = "", by: str = "chat") -> dict:
        """Add souls seen in chat. Levels up using the learned per-level requirements.
        Returns {"result": ..., "level": ..., "from_level": ...}; result is one of
        added | levelup | maxed | unlocked | unknown_level | locked | already_max."""
        pr = self.progress(pet_id)
        mx = pr.max_level or self.default_max
        reqs = self.level_requirements()
        out = {"result": "added", "level": pr.level, "from_level": pr.level}

        def log(result):
            self.db.execute("INSERT INTO soul_log(ts, pet_id, amount, text, result) VALUES (?,?,?,?,?)",
                            (_now(), pet_id, amount, text, result))
            self.db.commit()
            out["result"] = result
            return out

        if pr.manual_lock:
            return log("locked")
        if pr.maxed:
            return log("already_max")
        unlocked_now = False
        if not pr.unlocked:
            # First soul for a pet we didn't own: start it at Lv 1. A Pets-window scan corrects this if needed.
            pr.unlocked, pr.level, pr.souls_have, pr.souls_need = True, 1, 0, reqs.get(1)
            unlocked_now = True
        if pr.level is None or pr.souls_have is None:
            return log("unknown_level")  # owned but never scanned: can't place the souls yet
        have = pr.souls_have + amount
        need = pr.souls_need or reqs.get(pr.level)
        level = pr.level
        while need and have >= need and level < mx:
            have -= need
            level += 1
            need = reqs.get(level) if level < mx else None
        pr.level = level
        if level >= mx:
            pr.maxed, pr.souls_have, pr.souls_need = True, None, None
        else:
            pr.souls_have, pr.souls_need = have, need
        self.save_progress(pr, by=by)
        out["level"] = level
        if pr.maxed:
            return log("maxed")
        if level != out["from_level"] and not unlocked_now:
            return log("levelup")
        return log("unlocked" if unlocked_now else "added")

    def souls_to_max(self, pet_id: str) -> Optional[int]:
        """Souls still needed to reach max level, or None while a level's requirement is unknown.
        A pet you don't own counts from Lv 1 at 0 souls."""
        pr = self.progress(pet_id)
        mx = pr.max_level or self.default_max
        if pr.maxed:
            return 0
        reqs = self.level_requirements()
        if not pr.unlocked or pr.level is None:
            start, done = 1, 0
        else:
            start, done = pr.level, (pr.souls_have or 0)
        need = [reqs.get(l) for l in range(start, mx)]
        if need and pr.unlocked and pr.level is not None and pr.souls_need:
            need[0] = pr.souls_need   # this pet's own requirement for its current level (from the scan)
        if any(v is None for v in need):
            return None
        return max(sum(need) - done, 0)

    def field_text(self, pet_id: str) -> str:
        """Short line for the overlay's 'nearby' list."""
        pr = self.progress(pet_id)
        if pr.maxed:
            return "MAX ✓"
        left = self.souls_to_max(pet_id)
        tail = f"{left} to max" if left is not None else self.remaining_text(pet_id)
        if not pr.unlocked:
            return f"not owned · {tail}" if left is not None else "not owned"
        return f"{tail}  (Lv {pr.level})" if pr.level else tail

    # ------------------------------------------------------------------ stats
    def genus_stats(self) -> dict[str, tuple[int, int]]:
        out = {}
        for g in (*GENERA, None):
            ps = [p for p in self.pets.values() if p.genus == g]
            out[g or "Unknown"] = (sum(self.progress(p.id).maxed for p in ps), len(ps))
        return out

    def unlocked_count(self) -> int:
        return sum(self.progress(p).unlocked for p in self.pets)

    def close(self) -> None:
        self.db.close()
