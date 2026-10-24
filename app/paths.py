"""Where files live.

* RES_DATA - read-only files shipped with the app (pets.json, maps, sample screenshots).
             In the .exe these are unpacked next to it; in development it's the project's data/ folder.
* USER_DATA / USER_CONFIG - your progress, settings, genus overrides, calibration and debug crops.
             Always %LOCALAPPDATA%\\AION2 Pet Tracker, so rebuilding or moving the app never loses progress.
             Set AION2_TRACKER_HOME to use a different folder.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
PROJECT = Path(__file__).resolve().parents[1]
RESOURCES = Path(getattr(sys, "_MEIPASS", PROJECT)) if FROZEN else PROJECT
RES_DATA = RESOURCES / "data"
# Icons and sounds. Bundled as a top-level "assets" folder: a folder named "app" in the
# package would hide the app's own code from Python.
ASSETS = RESOURCES / "assets" if FROZEN else PROJECT / "app" / "ui" / "assets"

_home = os.environ.get("AION2_TRACKER_HOME")
USER = Path(_home) if _home else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AION2 Pet Tracker"
USER_DATA = USER / "data"
USER_CONFIG = USER / "config"

# Files that belong to the user, relative to the old project layout.
_USER_FILES = [
    ("data/progress.db", USER_DATA / "progress.db"),
    ("data/genus_overrides.json", USER_DATA / "genus_overrides.json"),
    ("config/settings.json", USER_CONFIG / "settings.json"),
    ("config/ocr_profiles.json", USER_CONFIG / "ocr_profiles.json"),
]


def migrate_from(project: Path = PROJECT) -> list[str]:
    """Copy progress and settings from the old in-project location the first time. Never overwrites."""
    if (USER_DATA / "progress.db").exists():
        return []
    copied = []
    for rel, dest in _USER_FILES:
        src = project / rel
        if src.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(rel)
    return copied


def ensure_dirs() -> None:
    for d in (USER_DATA, USER_CONFIG, USER_DATA / "ocr_debug"):
        d.mkdir(parents=True, exist_ok=True)
