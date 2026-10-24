import json
import shutil
from pathlib import Path

import pytest

from app.core.filters import FilterSpec, best_source, filter_pets, group_by_area
from app.core.store import Store

ROOT = Path(__file__).resolve().parents[1]
PETS = ROOT / "data" / "pets.json"
pytestmark = pytest.mark.skipif(not PETS.exists(), reason="run tools/parse_pdf.py first")


@pytest.fixture
def store(tmp_path):
    s = Store(pets_json=PETS, db_path=tmp_path / "p.db", overrides_path=tmp_path / "ov.json")
    yield s
    s.close()


def names(pets):
    return {p.name for p in pets}


def test_first_run_imports_15_ticks(store, tmp_path):
    assert store.pdf_import_count == 15
    assert store.unlocked_count() == 15
    assert store.progress("pet_1013").updated_by == "pdf_import"
    store.close()
    again = Store(pets_json=PETS, db_path=tmp_path / "p.db", overrides_path=tmp_path / "ov.json")
    assert again.pdf_import_count == 0 and again.unlocked_count() == 15
    again.close()


def test_cogni_not_maxed(store):
    store.set_maxed("pet_1054", True)  # Mumu Warrior, Cogni
    spec = FilterSpec(genera={"Cogni"}, status="not_maxed")
    res = filter_pets(store.pets.values(), store.progress, spec)
    assert res and all(p.genus == "Cogni" for p in res)
    assert "Mumu Warrior" not in names(res)
    maxed, total = store.genus_stats()["Cogni"]
    assert len(res) == total - maxed
    # spans zones
    assert len({s.zone for p in res for s in p.sources}) > 2


def test_unfinished_cogni_in_altgard(store):
    spec = FilterSpec(genera={"Cogni"}, zones={"Altgard"}, status="not_maxed")
    res = filter_pets(store.pets.values(), store.progress, spec)
    assert "Mumu Warrior" in names(res)
    assert all(any(s.zone == "Altgard" for s in p.sources) for p in res)


def test_shared_id_updates_everywhere(store):
    seen = []
    store.subscribe(seen.append)
    store.set_maxed("pet_1013", True)
    assert seen == [{"pet_1013"}]
    groups = group_by_area([store.pets["pet_1013"]], FilterSpec())
    assert len(groups) >= 4  # Swarm shows up in several areas, all the same record
    assert store.progress("pet_1013").maxed and store.remaining_text("pet_1013") == "MAX"


def test_text_search_matches_monster(store):
    res = filter_pets(store.pets.values(), store.progress, FilterSpec(text="mumu watcher"))
    assert names(res) == {"Mumu Warrior"}


def test_hide_elite_and_priority(store):
    res = names(filter_pets(store.pets.values(), store.progress, FilterSpec(hide_elite=True)))
    assert "Silver Blade Rotan" not in res  # only elite sources
    assert "Swarm" in res
    pri = names(filter_pets(store.pets.values(), store.progress,
                            FilterSpec(zones={"Spirit Isle"}, priority_only=True)))
    assert pri == {"Dracuni Herbalist", "Intermediate Water Spirit", "Odyle Stone Spirit", "Ashen Agrint",
                   "Mutated Aberrant Odyle Spider", "Intermediate Fire Spirit"}


def test_best_source_prefers_altgard(store):
    s = best_source(store.pets["pet_1013"])
    assert s.zone == "Altgard" and s.monster == "Giant Ore Insectoid"


def test_genus_override_roundtrip(store, tmp_path):
    store.set_genus_override("pet_1005", "Fera")  # Klaw
    assert store.pets["pet_1005"].genus == "Fera"
    assert json.loads((tmp_path / "ov.json").read_text()) == {"Klaw": "Fera"}
    store.set_genus_override("pet_1005", None)
    assert store.pets["pet_1005"].genus is None


def test_ocr_respects_manual_lock(store):
    pr = store.progress("pet_1031")
    pr.manual_lock, pr.level = True, 1
    store.save_progress(pr)
    pr2 = store.progress("pet_1031")
    pr2.souls_have, pr2.souls_need = 7, 25
    assert store.save_progress(pr2, by="ocr") is False
    assert store.progress("pet_1031").souls_have is None


def test_remaining_text(store):
    pr = store.progress("pet_1031")  # Konutin Worker Lv 1 (7/25)
    pr.level, pr.souls_have, pr.souls_need = 1, 7, 25
    store.save_progress(pr)
    assert store.remaining_text("pet_1031") == "18 to Lv 2"
    store.record_level_requirement(2, 50)
    assert store.remaining_text("pet_1031") == "18 to Lv 2 · 68 to max"
