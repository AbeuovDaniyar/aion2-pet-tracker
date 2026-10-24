from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ocr.chat import ChatTracker, chat_lines, parse_soul, same_line, soul_gains
from app.ocr.engine import OcrLine

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "data" / "sample_screens" / "field_black_claw_1080p.png"
PETS = ROOT / "data" / "pets.json"
FONT = Path("C:/Windows/Fonts/segoeuib.ttf")

K1, K2, K3 = "Acquired 589 Kina.", "Acquired 524 Kina.", "Acquired 608 Kina."
MF = "Obtained 1 Manduri Fighter Soul Points."
VB = "Obtained 1 Varg Berserker Soul Points."


# ------------------------------------------------------------------ line matching / new-line detection

def test_same_line_numbers_must_match():
    assert same_line(K1, "Acquired 589 Kina")
    assert same_line(MF, "Obtained 1 Manduri Fightr Soul Points.")   # small OCR slip in letters
    assert not same_line(K1, K2)                                       # different amount
    assert not same_line(MF, "Obtained 2 Manduri Fighter Soul Points.")


def test_tracker_counts_only_new_lines():
    t = ChatTracker()
    assert t.feed([K1, MF, K2, VB]) is None              # first read is the baseline
    assert t.feed([K1, MF, K2, VB]) == []                # nothing new
    assert t.feed([K2, VB, K3, MF]) == [K3, MF]          # scrolled by two
    assert t.feed([K3, MF, "Acquired 7 Kina.", MF]) == ["Acquired 7 Kina.", MF]


def test_tracker_repeated_lines():
    t = ChatTracker()
    t.feed([MF, K1, MF, K2, MF])
    assert t.feed([MF, K2, MF, K3, MF]) == [K3, MF]


def test_tracker_gives_up_without_overlap():
    t = ChatTracker()
    t.feed([K1, MF, K2])
    assert t.feed(["Acquired 1 Kina.", "Acquired 2 Kina.", VB]) is None   # can't tell: count nothing
    assert t.feed(["Acquired 2 Kina.", VB, MF]) == [MF]                  # back on track


def test_chat_lines_join_wrapped_soul_message():
    lines = [OcrLine("Obtained 1 Mutated Aberrant Odyle", 0.99, (0, 0, 200, 15)),
             OcrLine("Spider Soul Points.", 0.99, (0, 17, 100, 32)),
             OcrLine("Acquired 5 Kina.", 0.99, (0, 34, 100, 49))]
    assert chat_lines(lines) == ["Obtained 1 Mutated Aberrant Odyle Spider Soul Points.", "Acquired 5 Kina."]


def test_parse_soul():
    assert parse_soul(MF) == (1, "Manduri Fighter")
    assert parse_soul("Obtained 3 Sentinel K’nash Soul Point") == (3, "Sentinel K'nash")
    assert parse_soul("[Pan] Obtained 1 thing") is None


# ------------------------------------------------------------------ applying souls

pytestmark_store = pytest.mark.skipif(not PETS.exists(), reason="run tools/parse_pdf.py first")


@pytest.fixture
def store(tmp_path):
    from app.core.store import Store
    s = Store(pets_json=PETS, db_path=tmp_path / "p.db", overrides_path=tmp_path / "o.json")
    s.record_level_requirement(1, 25)
    s.record_level_requirement(2, 75)
    yield s
    s.close()


def pid(store, name):
    return next(p.id for p in store.pets.values() if p.name == name)


@pytestmark_store
def test_soul_gains_match_pet_names(store):
    names = {p.id: p.name for p in store.pets.values()}
    g = soul_gains([K1, MF, VB, "Obtained 1 Not A Real Pet Soul Points."], names)
    assert [(x.pet_name, x.amount) for x in g] == [("Manduri Fighter", 1), ("Varg Berserker", 1)]


@pytestmark_store
def test_add_souls_levels_up_and_maxes(store):
    p = pid(store, "Manduri Fighter")
    pr = store.progress(p)
    pr.level, pr.souls_have, pr.souls_need = 1, 23, 25
    store.save_progress(pr)
    assert store.add_souls(p, 1)["result"] == "added"
    assert store.progress(p).souls_have == 24 and store.souls_to_max(p) == 76
    r = store.add_souls(p, 2)
    assert r["result"] == "levelup" and r["level"] == 2
    pr = store.progress(p)
    assert (pr.level, pr.souls_have, pr.souls_need) == (2, 1, 75)
    assert store.add_souls(p, 74)["result"] == "maxed" and store.progress(p).maxed
    assert store.add_souls(p, 1)["result"] == "already_max"
    rows = store.db.execute("SELECT result FROM soul_log WHERE pet_id=? ORDER BY id", (p,)).fetchall()
    assert [r[0] for r in rows] == ["added", "levelup", "maxed", "already_max"]


@pytestmark_store
def test_add_souls_new_pet_unknown_and_locked(store):
    new = pid(store, "Varg Berserker")
    assert store.add_souls(new, 1)["result"] == "unlocked"
    pr = store.progress(new)
    assert (pr.unlocked, pr.level, pr.souls_have, pr.souls_need) == (True, 1, 1, 25)

    owned = pid(store, "Swarm")                        # imported from the PDF: owned, level never scanned
    store.set_unlocked(owned, True)
    assert store.add_souls(owned, 1)["result"] == "unknown_level"

    locked = pid(store, "Konutin Worker")
    pr = store.progress(locked)
    pr.level, pr.souls_have, pr.souls_need, pr.manual_lock = 1, 7, 25, True
    store.save_progress(pr)
    assert store.add_souls(locked, 1)["result"] == "locked"
    assert store.progress(locked).souls_have == 7


# ------------------------------------------------------------------ real screenshot, end to end in the worker

def scrolled_chat(base: Image.Image, new_lines: list[str]) -> Image.Image:
    """The sample screen with the chat scrolled up by len(new_lines) and those lines painted at the bottom."""
    img = base.copy()
    step = 17.5
    n = len(new_lines)
    top, bottom, x0, x1 = 812, 1005, 9, 382
    shift = int(round(step * n))
    img.paste(base.crop((x0, top + shift, x1, bottom)), (x0, top))
    d = ImageDraw.Draw(img)
    strip_top = bottom - shift
    d.rectangle((x0, strip_top, x1, bottom), fill=(96, 86, 74))
    font = ImageFont.truetype(str(FONT), 13)
    for i, text in enumerate(new_lines):
        y = strip_top + 2 + i * step
        d.text((45, y + 1), text, font=font, fill=(0, 0, 0))
        d.text((44, y), text, font=font, fill=(236, 232, 214))
    return img


needs_shot = pytest.mark.skipif(not (FIELD.exists() and PETS.exists() and FONT.exists()),
                                reason="needs field screenshot, pets.json and Segoe UI Bold")


@needs_shot
def test_worker_counts_one_new_soul(tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app.core.store import Store
    from app.ocr.capture import ProfileStore
    from app.ocr.engine import make_engine
    from app.ocr.scanner import Scanner
    from app.ui.autoscan import AutoScanWorker

    QCoreApplication.instance() or QCoreApplication([])
    store = Store(pets_json=PETS, db_path=tmp_path / "p.db", overrides_path=tmp_path / "o.json")
    w = AutoScanWorker(lambda: Scanner(store, make_engine(threads=4), ProfileStore(tmp_path / "x.json")),
                       field={"enabled": True, "interval_ms": 0, "track_souls": True})
    w._scanner = w._factory()
    w._reset()
    got = []
    w.souls.connect(got.extend)
    base = Image.open(FIELD).convert("RGB")
    frame2 = scrolled_chat(base, ["Acquired 611 Kina.", MF])
    for frame in (base, frame2, frame2):      # baseline, one new soul, same screen again
        w._grab = lambda f=frame: f
        w._tick()
    store.close()
    assert [(g.pet_name, g.amount) for g in got] == [("Manduri Fighter", 1)]
