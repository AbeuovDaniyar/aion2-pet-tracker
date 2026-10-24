from pathlib import Path

import pytest
from PIL import Image

from app.ocr.engine import OcrLine

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "data" / "sample_screens" / "field_black_claw_1080p.png"
PETS_SHOT = ROOT / "data" / "sample_screens" / "pets_konutin_worker_1080p.png"
PETS = ROOT / "data" / "pets.json"
pytestmark = pytest.mark.skipif(not PETS.exists(), reason="run tools/parse_pdf.py first")


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    from app.core.store import Store
    tmp = tmp_path_factory.mktemp("field")
    s = Store(pets_json=PETS, db_path=tmp / "p.db", overrides_path=tmp / "o.json")
    yield s
    s.close()


@pytest.fixture(scope="module")
def index(store):
    from app.ocr.field import MonsterIndex
    return MonsterIndex(store)


def L(text, box=(0, 0, 100, 20), score=0.99):
    return OcrLine(text, score, box)


@pytest.mark.parametrize("text,exp", [
    ("Black Claw Manduri Scout", "Black Claw Manduri Scout"),
    ("45 Black ClawManduri Sc...18m", "Black Claw Manduri Scout"),     # target frame, cut off
    ("Lv.41 Black Claw Manduri Combatant", "Black Claw Manduri Combatant"),
    ("Giant Ore Insectoid", "Giant Ore Insectoid"),
    ("Giant Ore Insectoid Adult", "Giant Ore Insectoid Adult"),        # look-alike stays distinct
    ("Mumu Watcher", "Mumu Watcher"),
])
def test_match_monsters(index, text, exp):
    assert index.match(text)[0] == exp


@pytest.mark.parametrize("text", ["Black Claw...", "Someplayer", "Obtained 1 Manduri Fighter Soul Points.",
                                  "Chief's Sentinel", "Tg", "Acquired 589 Kina."])
def test_ignores_non_monsters(index, text):
    assert index.match(text) is None


def test_target_frame_genus_tag(index):
    lines = [L("45 Black ClawManduri Sc...18m", (803, 4, 1068, 25)), L("Cogni", (859, 43, 894, 58)),
             L("Black Claw Manduri Scout", (843, 323, 1044, 346))]
    from app.ocr.field import find_monsters
    hits = find_monsters(lines, index)
    assert len(hits) == 1 and hits[0].targeted and hits[0].game_genus == "Cogni"


def test_pets_window_detected():
    from app.ocr.field import is_pets_window
    assert is_pets_window([L("Pet Insight"), L("Lv. 1 (7/25)")])
    assert not is_pets_window([L("Black Claw Manduri Scout")])


def test_souls_to_max(store):
    store.record_level_requirement(1, 25)
    store.record_level_requirement(2, 75)
    pr = store.progress("pet_1104")  # Manduri Trebuchet Worker
    assert store.souls_to_max("pet_1104") == 100 and store.field_text("pet_1104") == "not owned · 100 to max"
    pr.level, pr.souls_have, pr.souls_need = 1, 7, 25
    store.save_progress(pr)
    assert store.souls_to_max("pet_1104") == 93
    assert store.field_text("pet_1104") == "93 to max  (Lv 1)"
    store.set_maxed("pet_1104", True)
    assert store.field_text("pet_1104") == "MAX ✓"


# ------------------------------------------------------------------ real screenshots

needs_shots = pytest.mark.skipif(not (FIELD.exists() and PETS_SHOT.exists()), reason="sample screenshots missing")


@pytest.fixture(scope="module")
def worker(store):
    from PySide6.QtCore import QCoreApplication

    from app.ocr.capture import ProfileStore
    from app.ocr.engine import make_engine
    from app.ocr.scanner import Scanner
    from app.ui.autoscan import AutoScanWorker

    QCoreApplication.instance() or QCoreApplication([])
    engine = make_engine(threads=4)
    w = AutoScanWorker(lambda: Scanner(store, engine, ProfileStore(ROOT / "nonexistent.json")),
                       field={"enabled": True, "interval_ms": 0, "region": [0.02, 0.02, 0.86, 0.76], "scale": 1.5})
    w._scanner = w._factory()
    return w


def _field_read(worker, mode):
    hits, modes = [], []
    worker.set_field({**worker.field, "mode": mode})
    worker.field_hits.connect(hits.extend)
    worker.mode_changed.connect(modes.append)
    worker._reset()
    worker._grab = lambda: Image.open(FIELD).convert("RGB")
    worker._tick()
    worker.field_hits.disconnect()
    worker.mode_changed.disconnect()
    return {h.monster: h for h in hits}, modes


@needs_shots
def test_field_target_mode_reads_target_frame(worker):
    names, modes = _field_read(worker, "target")
    assert set(names) == {"Black Claw Manduri Scout"}       # default: only what you're targeting
    scout = names["Black Claw Manduri Scout"]
    assert scout.targeted and scout.game_genus == "Cogni" and scout.pet_ids == ["pet_1104"]
    assert modes == [] and worker.mode == "field"


@needs_shots
def test_field_full_mode_reads_nameplates(worker):
    names, _ = _field_read(worker, "full")
    assert set(names) == {"Black Claw Manduri Scout", "Black Claw Manduri Combatant"}
    assert names["Black Claw Manduri Scout"].game_genus == "Cogni"


@needs_shots
def test_field_skips_unchanged_screen(worker):
    worker.set_field({**worker.field, "mode": "target"})
    worker._reset()
    worker._grab = lambda: Image.open(FIELD).convert("RGB")
    before = dict(worker.stats)
    got = []
    worker.field_hits.connect(got.append)
    worker._tick()          # reads
    worker._tick()          # same screen: no OCR, but the target stays reported
    worker.field_hits.disconnect()
    assert worker.stats["ocr"] - before["ocr"] == 1
    assert worker.stats["skipped"] - before["skipped"] == 1
    assert [h.monster for h in got[1]] == ["Black Claw Manduri Scout"]


@needs_shots
def test_switches_to_pets_mode_and_back(worker):
    modes = []
    worker.mode_changed.connect(modes.append)
    worker._reset()
    worker._grab = lambda: Image.open(PETS_SHOT).convert("RGB")
    worker._tick()
    assert worker.mode == "pets"
    worker._grab = lambda: Image.open(FIELD).convert("RGB")
    for _ in range(3):  # panel changes, settles, OCR finds no pet -> back to field
        worker._tick()
    assert worker.mode == "field"
    assert modes == ["pets", "field"]
    worker.mode_changed.disconnect()


@needs_shots
def test_overlay_mask_hides_monster_names(worker):
    hits = []
    worker.field_hits.connect(hits.extend)
    worker._reset()
    worker._grab = lambda: Image.open(FIELD).convert("RGB")
    worker.set_field({**worker.field, "mode": "full"})
    worker.set_masks([(500, 250, 1700, 500)])  # cover all three nameplates
    worker._tick()
    worker.set_masks([])
    worker.field_hits.disconnect()
    assert {h.monster for h in hits} <= {"Black Claw Manduri Scout"}  # only the top target frame is left
