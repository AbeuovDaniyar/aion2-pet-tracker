# AION 2 Pet Tracker (Asmodian)

Desktop tracker for farming every pet to max level, built on Th3Ruthless's
*Pet Farming Guide: Asmodian Player Edition* (sources 08 Oct 2026, reviewed 12 Oct 2026).

The app only reads the screen. It never clicks, sends keys to the game, or reads game memory.

## Download

Get the latest **AION2-Pet-Tracker-…-win64.zip** from the
[Releases page](https://github.com/AbeuovDaniyar/aion2-pet-tracker/releases), unzip it anywhere, and run
`AION2 Pet Tracker.exe`. It's Windows 10/11, 64-bit, and needs no install. Run the game in **borderless windowed** mode
so the overlay can draw on top.

Windows SmartScreen may warn because the exe isn't code-signed: click *More info ▸ Run anyway*.

## Build from source



```bash
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Put the guide PDF at `data/source/pet_farming_guide_asmodian.pdf`, then:

```bash
.venv\Scripts\python tools\parse_pdf.py   # writes data/pets.json + data/parse_report.md
.venv\Scripts\python -m app.main          # start the tracker + overlay
.venv\Scripts\python -m pytest            # tests
```

The parser stops with an error if any count from the guide doesn't match (rows per page, 25 Abyss pets,
35 chest pets, 200 pet fields). `data/parse_report.md` lists pets whose genus is guessed or unknown.

On first run, the pets already ticked in the PDF are imported as **owned**.

## Desktop app

`build_exe.bat` builds `dist\AION2 Pet Tracker\AION2 Pet Tracker.exe`. The desktop shortcut
**AION2 Pet Tracker** points there. Rebuild after changing the code; close the app first.

Your progress, settings, genus overrides and calibration live in `%LOCALAPPDATA%\AION2 Pet Tracker`
(Scan ▸ *Open my data folder*), so rebuilding or deleting `dist` never loses anything. The app and
`python -m app.main` share that folder. Only one copy of the tracker runs at a time.

To make the hotkeys work while the game has focus, right-click the shortcut ▸ Properties ▸ Advanced ▸
*Run as administrator*. AION 2 runs as admin and blocks hotkeys from normal apps.

## Using it

**Tracker tab**
- Filters on the left: genus chips, status (default *Not maxed*), zone, source type, priority additions (`*`),
  hide elite, text search (matches pet **or** monster name).
- Group by *Pet* or *Zone → Area* (guide order, like the PDF).
- Detail panel: every source for the pet, owned/maxed, level and souls, "Lock from OCR", and a genus picker.
  Changing genus writes `data/genus_overrides.json`, which always wins over the PDF.
- Keys: `/` search, `Space` toggle maxed, `1`–`4` toggle Cogni / Fera / Natura / Varian.
- A hollow genus dot means the genus is only guessed from the checkbox colour on pages 3/8.

**Route tab**: pick a zone or one of the guide's short loops. Shows unfinished stops in pocket order with the exact
monster name large, plus a copy button.

**Map tab**: double-click a pet, or press **Show on map** in the detail panel. It shows the guide's own map
with a pulsing marker on the exact area or pin and the monster to kill. The left list has every place the
pet drops. Click one to switch maps, e.g. the island pin, then where the island sits on the mainland.
Wheel to zoom, drag to move. *Live spawn map ↗* opens the pet on the Pet Soul Atlas in your browser.
Chest/merchant pets and dungeon bosses have no map in the guide.

**Overlay**: a small always-on-top box that ignores the mouse. It shows only what matters:
- a status line (*auto-scan off* / *watching for pets* / *scanning Pets window*)
- the pets whose monsters are on screen, one line each: genus tag (COGNI, FERA, …), pet name, souls to max.
  Pets in your alert genera come first; maxed pets are dimmed; "new" means you don't own it yet.
- short popups only for important events: genus alert, pet saved, level-up / max, a scan waiting for your answer.

The box grows and shrinks with its content. Use the **Overlay ▾** button in the tracker header (no hotkey
needed, so it works while the game is running as admin):
- **Show overlay** turns it on or off.
- **Move / resize** lets you drag it anywhere and drag its left or right edge (orange bars) to set the width.
  Ctrl+wheel changes the text size, and the picker can show the tracker list or route under the pets. Click
  **Done moving / resizing** when finished; position, width and size are saved.
- **Text size** (Small, Normal, Large, Extra large) makes the whole box smaller or bigger.

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+O` | show / hide overlay |
| `Ctrl+Shift+I` | interactive mode: drag to move, corner to resize, pick filter vs route. Press again to lock. |
| `Ctrl+Shift+P` | auto-scan on / off (see below) |

Hotkeys use Windows' `RegisterHotKey`, so there's no keyboard hook. Change them in `config/settings.json`.

> **Run the game in borderless windowed mode.** Exclusive fullscreen hides every overlay, this one included.

## Scanning (OCR)

**Auto-scan (recommended)**
1. Click **▶ Auto-scan** in the tracker header (or press `Ctrl+Shift+P`).
2. Switch to the game, open the **Pets** window, and click pets one by one.
3. Each new pet is read within about a second of the panel settling. A rising **ding-ding** means it was
   saved, so move on to the next pet. A lower **two-note** sound means it needs your confirmation (see below).
4. Click **■ Stop auto-scan** when done. It also stops by itself after 10 minutes without a Pets window.

**Field mode (out in the world)**

While auto-scan is on and the Pets window is closed, the app reads the middle of the screen every 2.5 s and
looks for monster names from the guide: nameplates, and the target frame at the top (even when the name there
is cut off). The overlay's **NEARBY** box lists each one with the pet it drops and how far that pet is from max:

    🎯 Black Claw Manduri Scout
       → Manduri Trebuchet Worker · Cogni · 93 to max  (Lv 1)

- Souls to max use what scans have seen: 25 souls for Lv 1→2 and 75 for Lv 2→3. A pet you don't own
  shows "not owned · 100 to max".
- **Cogni alert:** a distinct four-note chirp and a purple toast when a Cogni pet you haven't maxed is on
  screen. Each pet alerts at most once every 90 s. Pick other genera under Scan ▸ *Alert me for genus*.
- The game shows the target's genus under the target frame. When the guide's genus for that pet is unknown
  or only guessed, the app saves the game's value as an override automatically.
- Opening the Pets window switches straight to pet scanning; closing it switches back.
- Turn field mode off under Scan ▸ *Watch for monsters while auto-scanning*. In `config/settings.json`
  (`field`): `interval_ms`, `region` (part of the screen to read), `notify_genera`, `alert_cooldown_s`.
  `ocr_threads` limits CPU use (default 4).
- Only names the guide lists are matched, so other mobs, players and chat are ignored.

**Live soul tracking (chat)**

The same read also covers the chat box (bottom left). Every new `Obtained N <pet> Soul Points.` line adds
souls to that pet, so the to-max numbers count down while you farm:

- `+1 Manduri Fighter · 92 to max` is shown briefly in the overlay, with no sound.
- Reaching the next level gives a ding and `⬆ Manduri Fighter reached Lv 2 · 75 to max`; reaching max gives
  a gold `★ … is MAX!`.
- Each read is lined up against the previous one, and only lines that appeared below the overlap count.
  Lines that differ only in a number ("Acquired 589 Kina" vs "524") never count as the same line. If a read
  can't be lined up (a huge pull scrolled the whole chat, or the chat was hidden), nothing is counted. So the
  tracker may miss a soul but never counts one twice. Your next Pets-window scan sets the exact numbers again.
- A pet you didn't own starts at Lv 1 with its first soul. A pet that's owned but was never scanned can't be
  placed: the overlay asks you to scan it once. Pets with **Lock from OCR** are never changed.
- Every soul is logged in `progress.db` (`soul_log`). Changes show as "updated by chat" in the detail panel.
- If you move the chat box, set `field.chat_region` in `config/settings.json`. Turn tracking off under
  Scan ▸ *Track souls from chat*.

Auto-scan takes about 4 screenshots per second, but only runs OCR when the name or level panel actually
changes and has stopped changing. It never clicks or presses anything in the game.

**AION 2 runs as administrator.** Windows may then block hotkeys from reaching this app while the game is
focused. Either start auto-scan with the button before switching to the game, or run the tracker as
administrator too if you want the hotkeys to work in game.

Scan ▸ *Scan once in 3 s* and *Scan an image file…* still do a single scan. Scan ▸ *Game monitor* picks
which screen to read (default: primary). Scan ▸ *Sounds* turns the sounds on or off.

Name matching is strict on purpose. An exact name saves right away. A close-but-not-exact read saves only if
it's clearly one pet. Anything in a look-alike family (Karnif / Tamed Karnif, Spider / Unstable Spider)
always asks first. Scans waiting for an answer queue up while you keep clicking:

| Hotkey (only while a scan is waiting) | Action |
|---|---|
| `Ctrl+Shift+Y` | accept the first choice |
| `Ctrl+Shift+1` / `2` / `3` | pick choice 1–3 |
| `Ctrl+Shift+N` | discard the scan |

The same choices appear as buttons in a banner at the top of the tracker window.

- Pets with **Lock from OCR** ticked are never changed by a scan.
- Every saved scan is logged in `progress.db` (`ocr_log`). The last 50 crops are kept in `data/ocr_debug/`.
- Each observed `(level, souls needed)` pair is remembered. Once a Lv 2 pet has been scanned, the remaining
  count includes the total to max.
- The header compares the in-game collection count with the app's owned count and warns when they differ.
- The overlay hides itself from the app's own screenshots, so it never covers what is being read.

**Other resolutions:** the default regions are measured at 1920×1080 and scaled to other sizes.
If scans miss, use **Scan ▸ Calibrate OCR regions…**:
1. Capture the screen with the Pets window open.
2. Drag the boxes into place.
3. Press **Test OCR**.
4. Press **Save**. It's stored per resolution in `config/ocr_profiles.json`.

The calibration test also reads level and MAX / x/y from each visible grid card. Cards carry no pet names,
so tying them to pets (grid scan) comes in the next milestone.

## Files

| Path | What |
|---|---|
| `data/pets.json` | generated pet + source data + map pins (hand-editable, committed) |
| `data/maps/` | map images rendered from the PDF by `tools/parse_pdf.py` (not committed) |
| `data/genus_overrides.json` | your genus corrections, by pet name |
| `data/progress.db` | your progress (SQLite) |
| `config/settings.json` | hotkeys, overlay position/opacity, max level (default 3) |
| `data/sample_screens/` | reference screenshots for OCR tests |

## Status

Done: parser (milestone 1), tracker (2), route mode (3), overlay shell + hotkeys (4), OCR detail scan,
calibration, strict matching (5).
Next (6): grid scan via learned card thumbnails, PyInstaller build.

## Credits

- Pet routes, monster → pet pairs and maps: **Th3Ruthless**, *AION 2 Pet Farming Routes, Asmodian Player
  Edition* (sources 08 Oct 2026, reviewed 12 Oct 2026). Go support the guide and the community links in it.
- Spawn data and map terrain via **Pet Soul Atlas** (petsouls.dev). Game terrain and assets © **NCSOFT**.
- Unofficial fan tool, not affiliated with NCSOFT. It only reads pixels from your screen and never sends
  input to the game or reads its memory.

The source code is MIT licensed (see `LICENSE`). The guide-derived data and maps belong to their owners.
