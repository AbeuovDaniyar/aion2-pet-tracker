"""Scans save the best match without asking, but never turn special / unknown pets into collection pets."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PETS = ROOT / "data" / "pets.json"
pytestmark = pytest.mark.skipif(not PETS.exists(), reason="run tools/parse_pdf.py first")


@pytest.fixture(scope="module")
def ctl():
    from app.ocr.match import match_name
    from app.ocr.scanner import DetailScan
    from app.ui.scan_controller import ScanController

    names = {p["id"]: p["name"] for p in json.loads(PETS.read_text(encoding="utf-8"))["pets"]}

    class C:  # just enough of ScanController for _trust_first
        settings = {"confirm_lookalikes": False}
        _trust_first = ScanController._trust_first

    def scan(text):
        return DetailScan(name=text, name_score=0.97, level=1, have=3, need=25, match=match_name(text, names))
    return C(), scan


@pytest.mark.parametrize("text", ["Konutin Worker", "Konutin Workerr", "Tamed Karnf", "Manduri Fightr"])
def test_known_pets_and_ocr_slips_are_saved(ctl, text):
    c, scan = ctl
    assert c._trust_first(scan(text))


@pytest.mark.parametrize("text", ["Golden Karnif", "Founder's Karnif", "Shiny Konutin Worker", "Twitch Fluffy Lion",
                                  "Celestial Pino", "Daeva Panda"])
def test_special_and_unknown_pets_are_skipped(ctl, text):
    c, scan = ctl
    assert not c._trust_first(scan(text))


@pytest.mark.parametrize("read,pet", [
    ("Spirit King's Bodygua", "Spirit King's Bodyguard Warrior"),
    ("Mutated Aberrant Od", "Mutated Aberrant Odyle Spider"),
    ("Elite Poisonous Spore", "Elite Poisonous Spore Fungen"),
    ("Flame Stone Guardian", "Flame Stone Guardian Statue"),
    ("Addicted Shulak Cart", "Addicted Shulak Cart Worker"),
])
def test_long_names_cut_off_are_saved_without_asking(ctl, read, pet):
    c, scan = ctl
    s = scan(read)
    assert s.match.name == pet and c._trust_first(s)


def test_short_cut_off_still_skipped(ctl):
    c, scan = ctl
    assert not c._trust_first(scan("Konutin"))   # too short to be sure (could be a special pet)
