# AION 2 Pet Tracker (Asmodian)

Desktop tracker and in-game overlay for farming every AION 2 pet to max level. It's built on Th3Ruthless's
*Pet Farming Guide: Asmodian Player Edition* and the **Pet Soul Atlas** Global data (all 200 pets and
400+ monsters).

The app only reads pixels from your screen. It never clicks, sends keys to the game, or reads game memory.

## Download

Get the latest **AION2-Pet-Tracker-…-win64.zip** from the
[Releases page](https://github.com/AbeuovDaniyar/aion2-pet-tracker/releases). Unzip it anywhere and run
`AION2 Pet Tracker.exe`. It runs on Windows 10/11 (64-bit) with no install.

- Run the game in **borderless windowed** mode so the overlay can draw on top.
- Windows SmartScreen may warn because the exe isn't code-signed: click *More info ▸ Run anyway*.
- Your progress is stored in `%LOCALAPPDATA%\AION2 Pet Tracker`, so updating means unzipping the new version
  over the old one (or anywhere else). Nothing is lost.

## What it does

**Tracker tab**: every pet with genus, progress and where to get it.
- Filters: genus chips, status (default *Not maxed*), zone, source type, priority additions (`*`), hide elite,
  and search by pet **or** monster name.
- Group by *Pet* or *Zone → Area*.
- Detail panel: every source (guide + atlas, with levels and spawn counts), owned/maxed, level and souls,
  "Lock from OCR", and a genus picker (saved as an override that always wins).
- Keys: `/` search, `Space` toggle maxed, `1`–`4` toggle Cogni / Fera / Natura / Varian.

**Route tab**: a zone or one of the guide's short loops, with only unfinished stops, in pocket order. Monster
names are shown large, with a copy button.

**Map tab**: double-click a pet, or press **Show on map** in the detail panel.
- **Live map** (default) is the interactive Pet Soul Atlas, focused on that pet's spawns, with the atlas's pet
  card (where, which monsters, other sources).
- **Guide map** is the guide's own maps with a pulsing marker on the numbered area or pin.
- When auto-scan reads a pet in the in-game Pets window, the Map tab follows it. Handy on a second monitor.

**Overlay**: a small always-on-top box that ignores the mouse.
- A status line: *auto-scan off*, *watching for pets*, or *scanning Pets window*.
- **Nearby pets**: one line each for monsters on screen, with genus tag, pet name and souls to max. Pets in your
  alert genera come first, maxed pets are dimmed, and "new" means you don't own it yet.
- **Live map**: when you click a pet in the in-game Pets window, a compact map of where its monsters spawn. It
  hides again when you go back to the world.
- Short popups only for important events: genus alert, pet saved, level-up / max, a scan waiting for your answer.

Use the **Overlay ▾** button in the tracker header. No hotkey is needed, so it works while the game runs as admin.
- *Show overlay* turns it on or off.
- *Move / resize* lets you drag it, and drag its left or right edge (orange bars) to set the width. Ctrl+wheel
  changes the text size. Click *Done moving / resizing* when finished.
- *Text size*: Small, Normal, Large or Extra large.
- *Show live map when a pet is selected* turns the overlay map on or off. The **Overlay map: on/off** button in
  the header (or `Ctrl+Shift+M`) does the same.
- *Hide overlay from screenshots / streams*: off by default, so Discord, OBS and screenshots show the overlay.
  Turn it on to keep it private. Discord **window** capture of the game never includes overlays; share the
  screen instead.

## Auto-scan

1. Click **▶ Auto-scan** in the tracker header (or press `Ctrl+Shift+P`).
2. **In the Pets window**, click pets one by one. Each new pet is read about a second after the panel
   settles. A rising **ding-ding** means it was saved, so move on. A lower **two-note** sound means it needs
   your confirmation (see below).
3. **Out in the world** (field mode), the app reads the **target frame** at the top of the screen, which shows the
   name and the game's genus tag. Nearby pets then shows which pet that monster drops and how many souls are
   left. A **Cogni alert** (four-note chirp and purple popup) fires when a Cogni pet you haven't maxed shows up,
   at most once per pet every 90 s. Pick other genera under Scan ▸ *Alert me for genus*.
4. **Live soul tracking:** every new `Obtained N <pet> Soul Points.` chat line adds souls to that pet, levels it
   up at 25 / 75 souls, and plays a ding on level-up and max. It may miss a soul when a huge pull scrolls the
   whole chat, but it never counts one twice. The next Pets-window scan sets the exact numbers again.
5. Click **■ Stop auto-scan** when done.

Opening the Pets window switches to pet scanning automatically; closing it switches back to field mode.

**Name matching.** Each read is saved as the best-matching pet straight away. Reads that aren't clearly any pet
(menu text, half-drawn frames) are skipped, never guessed. Special pets that aren't part of the 200-pet
collection (Twitch drops, cash shop, founder's pack, …) are skipped too, including variants of a known name
like "Shiny Konutin Worker". If you'd rather confirm look-alike names (Karnif /
Tamed Karnif) yourself, turn on Scan ▸ *Ask before saving look-alike names*. Then a banner and the hotkeys
`Ctrl+Shift+Y` (first choice), `Ctrl+Shift+1/2/3` (pick) and `Ctrl+Shift+N` (discard) let you answer.

**Field mode options** (Scan menu and `config/settings.json`, `field` section):
- `mode`: `"target"` (default, cheap) reads the target frame; `"full"` scans the whole middle of the screen for
  every nameplate (more CPU).
- `interval_ms` (default 1500), `notify_genera`, `alert_cooldown_s`, `chat_region` (if you move the chat box).
- Scan ▸ *Watch for monsters while auto-scanning* and *Track souls from chat* turn the features off.

**Performance.** The tracker is built to stay out of the game's way:
- It grabs only small screen regions (the pet panel, target frame, chat) and runs OCR only when one of them
  changes.
- It runs below normal priority, with 2 OCR threads (`ocr_threads` in settings).
- Standing still costs about 3% of one CPU core; the Pets window idle costs nearly nothing.

**Pet Soul Atlas data** is downloaded from petsouls.dev on first start and refreshed every few days
(Scan ▸ *Update from Pet Soul Atlas*). It adds every monster, level, area and spawn count the guide doesn't
list, and the genus for all 200 pets. The guide's routes, pins and maps stay the base.

**Any resolution or UI scale:** the first time auto-scan runs on a screen, open the in-game Pets window once.
The tracker finds it by its labels ("Pet Info", "Source", "Pet Insight", "Collection Status"), works out where
everything is, and remembers it for that resolution. This covers ultrawide screens, 1440p/4K and a changed
in-game UI scale, and it finds the game on another monitor. Scan ▸ *Calibrate OCR regions…* is still there
for manual fine-tuning.

**Hotkeys** use Windows' `RegisterHotKey` (no keyboard hook): `Ctrl+Shift+P` auto-scan, `Ctrl+Shift+O` show /
hide overlay, `Ctrl+Shift+I` move overlay. **AION 2 runs as administrator**, which can block hotkeys from normal
apps while the game has focus. Use the buttons, or run the tracker as administrator (shortcut ▸ Properties ▸
Advanced).

## Troubleshooting

**Auto-scan doesn't recognize pets**
1. Run AION 2 in **borderless windowed** mode. Exclusive fullscreen can't be captured, and the tracker warns
   when the capture is black.
2. Start auto-scan, then open the in-game **Pets** window and select a pet. A popup "Found the Pets window" means
   it calibrated. Keep the overlay off the right-hand pet panel.
3. The tracker reads the **English** game client. Other client languages show other pet names.
4. Still nothing? Use Scan ▸ **Save diagnostic report…** with the Pets window open. It saves a zip (monitor
   screenshots, what OCR read, settings, crash log) and opens its folder. Send that zip to the developer.

**The souls-to-max countdown stops going down**
- If the chat shows the **same soul message over and over** (only "Obtained 1 Pino Soul Points.", nothing in
  between), each new line looks identical to the one before and can't be counted. The tracker warns when it
  sees this. Show Kina / loot messages in that chat tab, or turn on chat timestamps, so each line differs.
- Keep the chat box where it is by default (bottom left), or set `field.chat_region` in the settings.
- Scanning the pet in the Pets window always sets the exact numbers again.

**The app crashed**: details are written to `%LOCALAPPDATA%\AION2 Pet Tracker\crash.log`, which is also included
in the diagnostic report.

## Build from source

```bash
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app.main          # run from source
.venv\Scripts\python -m pytest            # tests (screenshot tests skip without local sample screens)
build_exe.bat                             # build dist\AION2 Pet Tracker\AION2 Pet Tracker.exe
```

`data/pets.json` and `data/maps/` are generated from the guide PDF. To regenerate them, put the PDF at
`data/source/pet_farming_guide_asmodian.pdf` and run `.venv\Scripts\python tools\parse_pdf.py`. The parser
stops with an error if any count from the guide doesn't match.

| Path | What |
|---|---|
| `app/` | the application (tracker, overlay, OCR, atlas import) |
| `tools/parse_pdf.py`, `tools/maps.py` | guide PDF → pets.json + map images and pins |
| `data/pets.json`, `data/maps/` | guide data shipped with the app |
| `%LOCALAPPDATA%\AION2 Pet Tracker` | your progress, settings, overrides, calibration, atlas cache |

## Credits

- Pet routes, monster → pet pairs and maps: **Th3Ruthless**, *AION 2 Pet Farming Routes, Asmodian Player
  Edition* (sources 08 Oct 2026, reviewed 12 Oct 2026). Go support the guide and the community links in it.
- Global pet, monster and spawn data and the live map: **Pet Soul Atlas** (petsouls.dev). The data is
  downloaded from the site at runtime and not redistributed here.
- Game terrain and assets © **NCSOFT**. This is an unofficial fan tool, not affiliated with NCSOFT.

The source code is MIT licensed (see `LICENSE`). The guide-derived data and maps belong to their owners.
