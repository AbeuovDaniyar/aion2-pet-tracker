"""Every module must compile and import: catches broken files the feature tests don't load."""
import importlib
import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(p for d in ("app", "tools") for p in (ROOT / d).rglob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_compiles(path):
    py_compile.compile(str(path), doraise=True)


@pytest.mark.parametrize("module", ["app.main", "app.diagnostics", "app.atlas", "app.ui.atlas_view",
                                    "app.ui.scan_controller", "app.ocr.calibrate", "run_tracker"])
def test_imports(module):
    importlib.import_module(module)
