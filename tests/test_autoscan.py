from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_screens" / "pets_konutin_worker_1080p.png"
PETS = ROOT / "data" / "pets.json"
FONT = Path("C:/Windows/Fonts/segoeui.ttf")

pytestmark = pytest.mark.skipif(not (SAMPLE.exists() and PETS.exists() and FONT.exists()),
                                reason="needs sample screenshot, pets.json and Segoe UI")


def other_pet_frame(base: Image.Image) -> Image.Image:
    """The sample screen with a different pet painted into the detail panel."""
    img = base.copy()
    d = ImageDraw.Draw(img)
    d.rectangle((1530, 205, 1835, 252), fill=(8, 12, 22))
    d.text((1537, 210), "Swarm", font=ImageFont.truetype(str(FONT), 30), fill=(240, 240, 240))
    d.rectangle((1725, 268, 1820, 296), fill=(8, 12, 22))
    d.text((1730, 271), "Lv. 2 (3/40)", font=ImageFont.truetype(str(FONT), 16), fill=(240, 240, 240))
    return img


def blank_frame(base: Image.Image) -> Image.Image:
    img = base.copy()
    ImageDraw.Draw(img).rectangle((1480, 180, 1910, 310), fill=(30, 50, 90))
    return img


@pytest.fixture(scope="module")
def worker(tmp_path_factory):
    from PySide6.QtCore import QCoreApplication

    from app.core.store import Store
    from app.ocr.capture import ProfileStore
    from app.ocr.engine import make_engine
    from app.ocr.scanner import Scanner
    from app.ui.autoscan import AutoScanWorker

    QCoreApplication.instance() or QCoreApplication([])
    tmp = tmp_path_factory.mktemp("auto")
    store = Store(pets_json=PETS, db_path=tmp / "p.db", overrides_path=tmp / "o.json")
    engine = make_engine()
    w = AutoScanWorker(lambda: Scanner(store, engine, ProfileStore(tmp / "prof.json")), field={"enabled": False})
    w._scanner = w._factory()
    yield w
    store.close()


def run_frames(worker, frames):
    got = []
    worker.result.connect(got.append)
    worker._reset()
    for frame in frames:          # one screen per tick (a tick may grab it more than once)
        worker._grab = lambda f=frame: f
        worker._backoff_until = 0  # tests don't wait out the back-off
        worker._tick()
    worker.result.disconnect()
    return got


def test_registers_each_pet_once_after_it_settles(worker):
    base = Image.open(SAMPLE).convert("RGB")
    swarm = other_pet_frame(base)
    frames = [base, base, base, base, swarm, swarm, swarm, base, base]
    got = run_frames(worker, frames)
    names = [(s.name, s.level, s.have, s.need) for s in got]
    assert names == [("Konutin Worker", 1, 7, 25), ("Swarm", 2, 3, 40), ("Konutin Worker", 1, 7, 25)]
    assert got[1].match.pet_id == "pet_1013" and got[1].auto_accept


def test_no_result_without_pets_window(worker):
    base = Image.open(SAMPLE).convert("RGB")
    got = run_frames(worker, [blank_frame(base)] * 4)
    assert got == []


def test_unsettled_frame_is_not_read(worker):
    base = Image.open(SAMPLE).convert("RGB")
    swarm = other_pet_frame(base)
    # Alternating frames never hold still for a tick, so nothing is read.
    got = run_frames(worker, [base, swarm, base, swarm, base, swarm])
    assert got == []
