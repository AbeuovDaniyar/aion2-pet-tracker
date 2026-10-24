from pathlib import Path

import pytest

from app.ocr.capture import DEFAULT_PROFILE, ProfileStore, card_boxes, scale_profile
from app.ocr.match import differs_by_edge_words, match_name
from app.ocr.parse import (clean_name, parse_card_progress, parse_collection, parse_insight,
                           parse_level_digit)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_screens" / "pets_konutin_worker_1080p.png"
PETS = ROOT / "data" / "pets.json"


# ------------------------------------------------------------------ parsing (pure)

@pytest.mark.parametrize("text,exp", [
    ("Pet Insight Lv. 1 (7/25)", (1, 7, 25)),
    ("Pet Insight Lv.1 (7/25)", (1, 7, 25)),
    ("Lv 2 ( 13 / 50 )", (2, 13, 50)),
    ("Lv. 1 (7|25)", (1, 7, 25)),
    ("Ｌｖ. 1 (７/２５)", (1, 7, 25)),
])
def test_parse_insight(text, exp):
    d = parse_insight(text)
    assert (d["level"], d["have"], d["need"]) == exp


def test_parse_insight_max_and_garbage():
    assert parse_insight("Lv. 3 (MAX)")["max"] is True
    assert parse_insight("Pet Insight") == {}
    assert parse_insight("Lv. 1 (30/25)")["have"] is None  # have > need is rejected


def test_parse_misc():
    assert parse_collection("Collection Status 173/200") == (173, 200)
    assert parse_card_progress("MAX") == {"max": True, "have": None, "need": None}
    assert parse_card_progress("7/25")["have"] == 7
    assert parse_level_digit("③") == 3 and parse_level_digit("1") == 1 and parse_level_digit("x") is None
    assert clean_name("★Konutin Worker") == "Konutin Worker"
    assert clean_name("Sentinel K’nash") == "Sentinel K'nash"


# ------------------------------------------------------------------ matching (strict)

NAMES = {"a": "Karnif", "b": "Tamed Karnif", "c": "Modified Karnif", "d": "Elite Karnif",
         "e": "Spider", "f": "Unstable Spider", "g": "Baby Odyle Spider", "h": "Konutin Worker",
         "i": "Dratona", "j": "Dratona Tinkerer", "k": "Sentinel K'nash"}


def test_exact_match_auto():
    m = match_name("Konutin Worker", NAMES)
    assert m.auto and m.pet_id == "h" and m.score == 100


def test_small_ocr_error_auto():
    m = match_name("Konutin Workerr", NAMES)
    assert m.auto and m.pet_id == "h"


@pytest.mark.parametrize("query", ["Tamed Karnf", "Unstable Spidr", "Dratona Tinkere", "Elite Karnlf"])
def test_lookalikes_never_auto(query):
    m = match_name(query, NAMES)
    assert not m.auto, m.reason
    assert len(m.candidates) == 3


def test_exact_lookalike_flagged_but_exact():
    m = match_name("Karnif", NAMES)
    assert m.auto and m.pet_id == "a" and "look-alike" in m.reason


def test_differs_by_edge_words():
    assert differs_by_edge_words("Karnif", "Tamed Karnif")
    assert differs_by_edge_words("Dratona", "Dratona Tinkerer")
    assert not differs_by_edge_words("Karnif", "Konutin Worker")


def test_apostrophes_normalised():
    assert match_name("Sentinel K`nash", NAMES).pet_id == "k"


def test_garbage_not_matched():
    m = match_name("Usage Time Left", NAMES)
    assert not m.auto


# ------------------------------------------------------------------ profiles

def test_profile_scaling_and_cards(tmp_path):
    ps = ProfileStore(tmp_path / "p.json")
    p, cal = ps.get(1920, 1080)
    assert not cal and p["name"] == DEFAULT_PROFILE["name"]
    q, _ = ps.get(2560, 1440)
    assert q["name"][0] == round(DEFAULT_PROFILE["name"][0] * 2560 / 1920)
    boxes = card_boxes(p)
    assert len(boxes) == 15 and boxes[0].card == (90, 147, 197, 297)
    ps.save(1920, 1080, scale_profile(p, 1, 1))
    assert ProfileStore(tmp_path / "p.json").get(1920, 1080)[1] is True


# ------------------------------------------------------------------ end to end on the reference screenshot

needs_sample = pytest.mark.skipif(not (SAMPLE.exists() and PETS.exists()), reason="sample screenshot / pets.json missing")


@pytest.fixture(scope="module")
def scanner(tmp_path_factory):
    from app.core.store import Store
    from app.ocr.capture import ProfileStore
    from app.ocr.engine import make_engine
    from app.ocr.scanner import Scanner

    tmp = tmp_path_factory.mktemp("ocr")
    store = Store(pets_json=PETS, db_path=tmp / "p.db", overrides_path=tmp / "ov.json")
    sc = Scanner(store, make_engine(), ProfileStore(tmp / "profiles.json"),
                 {"ocr": {"debug_keep": 0}})
    yield sc
    store.close()


@pytest.fixture(scope="module")
def sample():
    from app.ocr.capture import load_image
    return load_image(SAMPLE)


@needs_sample
def test_detail_scan_konutin_worker(scanner, sample, monkeypatch, tmp_path):
    import app.ocr.scanner as scmod
    monkeypatch.setattr(scmod, "DEBUG_DIR", tmp_path / "dbg")
    s = scanner.detail_scan(sample)
    assert s.error is None
    assert s.name == "Konutin Worker"
    assert s.match.pet_id == "pet_1031" and s.match.auto
    assert (s.level, s.have, s.need) == (1, 7, 25)
    assert s.collection == (173, 200)
    assert s.auto_accept and not s.maxed
    assert s.summary() == "Konutin Worker — 7/25 souls (Lv 1)"

    assert scanner.apply(s, "pet_1031", accepted=True) == "saved"
    pr = scanner.store.progress("pet_1031")
    assert (pr.level, pr.souls_have, pr.souls_need, pr.unlocked, pr.updated_by) == (1, 7, 25, True, "ocr")
    assert scanner.store.remaining_text("pet_1031") == "18 to Lv 2"
    assert scanner.store.level_requirements() == {1: 25}
    row = scanner.store.db.execute("SELECT pet_id, accepted, screenshot_path FROM ocr_log").fetchone()
    assert row[0] == "pet_1031" and row[1] == 1 and Path(row[2]).exists()


@needs_sample
def test_detail_scan_respects_lock(scanner, sample, monkeypatch, tmp_path):
    import app.ocr.scanner as scmod
    monkeypatch.setattr(scmod, "DEBUG_DIR", tmp_path / "dbg")
    pr = scanner.store.progress("pet_1031")
    pr.manual_lock, pr.level, pr.souls_have = True, 2, 3
    scanner.store.save_progress(pr)
    s = scanner.detail_scan(sample)
    assert scanner.apply(s, "pet_1031", accepted=True).startswith("locked")
    assert scanner.store.progress("pet_1031").level == 2


@needs_sample
def test_grid_read(scanner, sample):
    cards = scanner.grid_read(sample)
    assert len(cards) == 15
    first = cards[0]
    assert (first.row, first.col, first.level, first.have, first.need, first.maxed) == (0, 0, 1, 7, 25, False)
    for c in cards[1:]:
        assert c.level == 3 and c.maxed, c
