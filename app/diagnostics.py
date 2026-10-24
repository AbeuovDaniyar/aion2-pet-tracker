"""Diagnostic report: one zip a user can send when auto-scan doesn't work for them.

Contains a screenshot of every monitor, the text OCR finds on each, whether the Pets window
labels were found and the regions calibration would use, the settings and OCR profiles, the
last scans, the crash log, and basic system info. Nothing is sent anywhere; the user decides.
"""
from __future__ import annotations

import io
import json
import platform
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from app import __version__
from app.paths import USER, USER_CONFIG, USER_DATA


def _system_info() -> dict:
    info = {"app_version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
            "frozen": bool(getattr(sys, "frozen", False))}
    try:
        import ctypes
        info["dpi_scale_percent"] = ctypes.windll.shcore.GetScaleFactorForDevice(0)
    except Exception:
        pass
    return info


def build_report(store, settings: dict, engine, profiles, out_dir: Path = USER / "diagnostics") -> Path:
    import mss
    from PIL import Image

    from app.ocr.calibrate import derive_profile, find_anchors

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"aion2-tracker-report-{datetime.now():%Y%m%d-%H%M%S}.zip"
    summary = {"created": datetime.now().isoformat(timespec="seconds"), "system": _system_info(),
               "monitor_index_setting": settings.get("monitor_index"), "monitors": []}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        factory = getattr(mss, "MSS", None) or mss.mss
        with factory() as sct:
            for idx, mon in enumerate(sct.monitors[1:], start=1):
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.rgb)
                buf = io.BytesIO()
                img.save(buf, "PNG", optimize=True)
                z.writestr(f"monitor{idx}.png", buf.getvalue())
                lines = engine.read(img)
                z.writestr(f"monitor{idx}_ocr.txt", "\n".join(
                    f"{l.score:.2f}  {[round(v) for v in l.box]}  {l.text}" for l in lines))
                anchors = find_anchors(lines)
                prof, calibrated = profiles.get(img.width, img.height)
                derived = derive_profile(anchors, img.width, img.height)
                brightness = max(img.resize((32, 18)).convert("L").getdata())
                summary["monitors"].append({
                    "index": idx, "size": [img.width, img.height], "position": [mon["left"], mon["top"]],
                    "looks_black": brightness < 12, "text_lines_found": len(lines),
                    "pets_window_labels": {k: v for k, v in anchors.__dict__.items()},
                    "saved_profile_for_this_size": calibrated, "profile_in_use": prof,
                    "profile_from_labels": derived,
                })
        z.writestr("summary.json", json.dumps(summary, indent=2, default=str))
        z.writestr("settings.json", json.dumps(settings, indent=2))
        for name in ("ocr_profiles.json",):
            p = USER_CONFIG / name
            if p.exists():
                z.write(p, name)
        crash = USER / "crash.log"
        if crash.exists():
            z.writestr("crash.log", crash.read_text(encoding="utf-8", errors="replace")[-200_000:])
        try:
            db = sqlite3.connect(str(USER_DATA / "progress.db"))
            rows = db.execute("SELECT ts, pet_id, raw_text, confidence, accepted FROM ocr_log "
                              "ORDER BY id DESC LIMIT 40").fetchall()
            z.writestr("recent_scans.json", json.dumps(rows, indent=1))
            db.close()
        except sqlite3.Error:
            pass
        z.writestr("atlas.json", json.dumps(getattr(store, "atlas_meta", {}), indent=2))
    return out
