# PyInstaller recipe:  .venv\Scripts\pyinstaller packaging\tracker.spec --noconfirm
# One-folder build in dist\AION2 Pet Tracker\. Your progress is NOT in here; it lives in
# %LOCALAPPDATA%\AION2 Pet Tracker, so rebuilding is always safe.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "data" / "pets.json"), "data"),
    (str(ROOT / "data" / "maps"), "data/maps"),
    # never "app/...": a folder named app in the bundle would hide the app package itself
    (str(ROOT / "app" / "ui" / "assets"), "assets"),
]
datas += collect_data_files("rapidocr")          # OCR models + config.yaml
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    [str(ROOT / "run_tracker.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["winsound", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtQml"],
    # QtWebEngine (live map) and QtQml (reads the atlas data) are needed; the rest is unused.
    excludes=["pymupdf", "fitz", "pymupdf4llm", "pymupdf_layout", "pytest", "tkinter",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtGraphs"],
    noarchive=False,
)


# Qt ships translations for ~40 languages (about 54 MB); the app is English-only.
def _keep(dest: str) -> bool:
    d = dest.replace("\\", "/")
    if "/translations/" not in d:
        return True
    return "en-US" in d or d.endswith("_en.qm")


a.datas = [x for x in a.datas if _keep(x[0])]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AION2 Pet Tracker",
    icon=str(ROOT / "packaging" / "icon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AION2 Pet Tracker")
