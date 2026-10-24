from pathlib import Path

import pytest

from tools.parse_pdf import DEFAULT_PDF, EXPECTED, GuideParser

pytestmark = pytest.mark.skipif(not DEFAULT_PDF.exists(), reason="guide PDF not in data/source/")


@pytest.fixture(scope="module")
def parsed():
    gp = GuideParser(DEFAULT_PDF)
    pets = gp.parse()
    return gp, {p.id: p for p in pets}, {p.name: p for p in pets}


def test_validation_counts(parsed):
    gp, _, _ = parsed
    assert gp.validate() == []
    for key, exp in EXPECTED.items():
        assert gp.counts[key] == exp, key


def test_names_unique_per_field(parsed):
    gp, by_id, by_name = parsed
    assert gp.name_conflicts == {}
    assert len(by_name) == len(by_id) == 200


def test_pdf_ticks_imported(parsed):
    _, by_id, _ = parsed
    expected = {f"pet_{n}" for n in (1005, 1013, 1027, 1033, 1046, 1054, 1062, 1074, 1075,
                                      1089, 1117, 1137, 1147, 1186, 1209)}
    assert {pid for pid, p in by_id.items() if p.pdf_checked} == expected


@pytest.mark.parametrize("monster,pet", [
    ("Mumu Watcher", "Mumu Warrior"),
    ("Red Shell Mole", "Armadon"),
    ("Krall Armed Soldier", "Krall Laborer"),
    ("Black Claw Manduri Scout", "Manduri Trebuchet Worker"),
])
def test_monster_name_differs_from_pet(parsed, monster, pet):
    _, _, by_name = parsed
    assert monster in {s.monster for s in by_name[pet].sources}
    assert monster not in by_name  # monster is not itself a pet of that name (except where noted)


@pytest.mark.parametrize("group", [
    ["Tamed Karnif", "Karnif", "Modified Karnif", "Elite Karnif"],
    ["Dratona", "Dratona Tinkerer"],
    ["Spider", "Unstable Spider", "Baby Odyle Spider"],
    ["Agrint", "Thin Agrint", "Withered Agrint", "Ashen Agrint", "Dry Leaf Agrint"],
])
def test_similar_names_are_distinct(parsed, group):
    _, _, by_name = parsed
    ids = [by_name[n].id for n in group]
    assert len(set(ids)) == len(group)


def test_swarm_shared_across_pages(parsed):
    _, by_id, by_name = parsed
    swarm = by_name["Swarm"]
    assert swarm.id == "pet_1013"
    assert len(swarm.sources) >= 4
    assert {s.page for s in swarm.sources} >= {3, 13, 14}
    assert swarm.genus == "Varian"


def test_kailin_genus_from_dot(parsed):
    _, _, by_name = parsed
    k = by_name["Kailin"]
    assert k.genus == "Fera" and k.genus_confidence == "high"


def test_elite_and_priority_flags(parsed):
    _, _, by_name = parsed
    brute = [s for s in by_name["Drana Mutant Brute"].sources if s.zone == "Immortal Isle"][0]
    assert brute.monster == "Drana Mutant" and brute.elite and brute.priority_addition
    rotan = by_name["Silver Blade Rotan"].sources
    assert all(s.elite for s in rotan if s.zone == "Abyss")
    nag = [s for s in by_name["Nagarant Guardian Warrior"].sources if s.zone == "Abyss"]
    assert {s.monster for s in nag} == {"Abyss Nagarant Warrior", "Abyss Nagarant Brawler"}
    assert all(s.elite for s in nag)


def test_wrapped_names_joined(parsed):
    gp, _, _ = parsed
    names = {st.pet_name for c in gp.circuits for st in c.stops}
    assert "Manduri Trebuchet Worker" in names
    assert "Duduka Trebuchet Worker" in names
    assert "Enhanced Krall Combatant" in names


def test_chest_genus_counts(parsed):
    _, by_id, _ = parsed
    chest = [p for p in by_id.values() if any(s.source_type == "chest_merchant" for s in p.sources)]
    assert len(chest) == 35
    assert all(p.genus_confidence == "high" for p in chest)


def test_held_and_unconfirmed(parsed):
    _, _, by_name = parsed
    for n in ("Dratona", "Klaw", "Modified Karnif"):
        assert by_name[n].held
    for n in ("Furious Feruk", "Gatekeeper Pinopi", "Kernon", "Sentinel K'nash"):
        assert by_name[n].unconfirmed_note and "unconfirmed" in by_name[n].unconfirmed_note


def test_boss_sources(parsed):
    _, _, by_name = parsed
    ek = by_name["Elite Karnif"].sources[0]
    assert ek.source_type == "boss" and ek.monster == "Crimson Blizzard Renulf" and ek.level == 80
    bsm = by_name["Black Smoke Murute"].sources[0]
    assert bsm.source_type == "dungeon" and bsm.area == "Fire Temple"


def test_abyss_area_numbering(parsed):
    _, _, by_name = parsed
    s = [s for s in by_name["Swarm"].sources if s.page == 13][0]
    assert s.area == "Black Fragments Area" and s.area_no == 1 and s.pin == "A" and s.level == 45
    assert s.sub_location == "Kration Conflict Zone" and s.monster == "Abyss Aberrant Swarn"
