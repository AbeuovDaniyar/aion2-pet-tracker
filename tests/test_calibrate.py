"""Self-calibration finds the Pets window on screens laid out differently from 1920x1080."""
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_screens" / "pets_konutin_worker_1080p.png"
PETS = ROOT / "data" / "pets.json"
pytestmark = pytest.mark.skipif(not (SAMPLE.exists() and PETS.exists()), reason="sample screenshot missing")


def anchored(base: Image.Image, scale: float, W: int, H: int) -> Image.Image:
    """The game UI drawn at `scale`: left half pinned to the left edge, right half to the right edge."""
    s = base.resize((round(1920 * scale), round(1080 * scale)), Image.LANCZOS)
    c = Image.new("RGB", (W, H))
    half = s.width // 2
    c.paste(s.crop((0, 0, half, s.height)), (0, H - s.height))
    c.paste(s.crop((half, 0, s.width, s.height)), (W - (s.width - half), H - s.height))
    return c


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    from app.core.store import Store
    from app.ocr.capture import ProfileStore
    from app.ocr.engine import make_engine
    from app.ocr.scanner import Scanner

    tmp = tmp_path_factory.mktemp("cal")
    store = Store(pets_json=PETS, db_path=tmp / "p.db", overrides_path=tmp / "o.json")
    engine = make_engine(threads=2)
    yield engine, Scanner(store, engine, ProfileStore(tmp / "prof.json"))
    store.close()


@pytest.mark.parametrize("label,scale,W,H", [
    ("1080p", 1.0, 1920, 1080),
    ("ultrawide 2560x1080", 1.0, 2560, 1080),
    ("1440p", 1440 / 1080, 2560, 1440),
    ("ultrawide 3440x1440", 1440 / 1080, 3440, 1440),
    ("1080p UI scale 80%", 0.8, 1920, 1080),
])
def test_calibrates_any_layout(tools, label, scale, W, H):
    from app.ocr.calibrate import calibrate

    engine, scanner = tools
    base = Image.open(SAMPLE).convert("RGB").resize((1920, 1080))
    prof, scan, msg = calibrate(anchored(base, scale, W, H), engine, scanner)
    assert prof is not None, msg
    assert (scan.name, scan.level, scan.have, scan.need) == ("Konutin Worker", 1, 7, 25)
    assert scan.collection == (173, 200)
    assert abs(prof["auto"]["scale"] - scale) < 0.06


def test_no_pets_window_no_profile(tools):
    from app.ocr.calibrate import calibrate

    engine, scanner = tools
    prof, scan, msg = calibrate(Image.new("RGB", (1920, 1080), (40, 60, 90)), engine, scanner)
    assert prof is None and "not found" in msg
