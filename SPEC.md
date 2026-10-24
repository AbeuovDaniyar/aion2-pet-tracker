# AION 2 Pet Tracker — Spec for Claude Code

## 1. Goal

A Windows desktop app that helps Danny (Asmodian) farm AION 2 pets to **max level** using Th3Ruthless's *Pet Farming Guide — Asmodian Player Edition* (PDF, 19 pages, sources 08 Oct 2026, reviewed 12 Oct 2026).

The app must:

1. **Show every pet** from the guide with where to farm it (zone → area → monster to kill → level).
2. **Check off pets** and track progress toward max level, not just "unlocked".
3. **Filter** by genus (Cogni / Fera / Natura / Varian), zone, status, and source type — e.g. "only unfinished Cogni pets in Altgard".
4. **Overlay**: an always-on-top, click-through window over the game. On a hotkey it screenshots the game, OCRs the pet collection screen, and updates how much each pet is still missing.
5. **Import the existing ticks** already saved in the PDF's form fields.

Out of scope: any input automation (no clicking, no keypresses sent to the game, no memory reading). The overlay only reads pixels from the screen. Keep it that way.

---

## 2. Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | |
| UI + overlay | PySide6 (Qt) | One app, two windows: main tracker + overlay |
| PDF parsing | PyMuPDF (`fitz`) | Need text spans with positions, vector colors, and form widgets |
| Screenshot | `mss` | Capture the game monitor or window rect |
| OCR | RapidOCR (onnxruntime) first; Tesseract as fallback | Pluggable `OcrEngine` interface |
| Fuzzy matching | `rapidfuzz` | **Strict** — see §6.3 |
| Global hotkey | `pynput` or `keyboard` | Default `Ctrl+Shift+P` |
| Storage | SQLite (`progress.db`) + `pets.json` seed | |
| Packaging | PyInstaller (one-folder) | Later |
| Tests | pytest | |

---

## 3. Source PDF structure (what the parser has to handle)

Input file: `data/source/pet_farming_guide_asmodian.pdf` (Danny will drop it in).

| Page | Content | Parse as |
|---|---|---|
| 1 | Cover / contents | skip |
| 2 | Altgard mainland map, 13 numbered areas | area order + area names |
| 3 | **Altgard "What to kill"** — 3 columns, 13 areas, monster → pet | `source` rows, zone=Altgard |
| 4 | Altgard short loops (4 circuits, A–E pockets, level ranges) | `circuit` rows |
| 5 | Spirit Isle — table w/ PIN, monster, pet, LV, genus dot | `source` rows, zone=Spirit Isle |
| 6 | Immortal Isle — same table format | zone=Immortal Isle |
| 7 | Verteron mainland map, 13 areas | area order |
| 8 | **Verteron "What to kill"** — 2 columns, 13 areas | zone=Verteron |
| 9 | Verteron short loops | `circuit` rows |
| 10 | Crimson Isle table | zone=Crimson Isle |
| 11 | Eternal Isle table | zone=Eternal Isle |
| 12 | Abyss overview (Chaotic Lower Reshanta), tour order 1–4 | area order |
| 13 | Black Fragments / Devastated Remnants / Reshanta's Root (A–D cards) | zone=Abyss |
| 14 | Sulfur Tree Island table | zone=Abyss |
| 15 | Siel's Wings table | zone=Abyss |
| 16 | Chests & merchants — 35 pets grouped by genus, no monster | `source_type=chest_merchant` |
| 17 | Bosses / dungeons + Abyss index | `source_type=boss` or `dungeon` |
| 18 | Held entries + unconfirmed alternate rewards | flags on pets |
| 19 | Community links | skip |

### 3.1 Genus colors (map legend, pages 2/7/12)
- **Cogni** = purple
- **Fera** = orange
- **Natura** = green
- **Varian** = blue

Island tables (pp. 5, 6, 10, 11) and Abyss maps draw a colored dot next to each pet row — that is the most reliable genus signal. Page 16 groups pets by genus explicitly.

⚠️ The checkbox border colors on pp. 3 and 8 are **not** confirmed to mean genus (e.g. Kailin has a blue box on p3 but an orange/Fera dot on p5). Do not trust them blindly.

**Genus resolution order:**
1. Page 16 genus heading (chest/merchant pets)
2. Dot color next to the pet on any island/Abyss table
3. Checkbox border color on pp. 3/8 — only as a *suggestion*, marked `genus_confidence="low"`
4. Unknown → `genus=null`, show in a "needs review" list in the UI

Also support `data/genus_overrides.json` (`{"Kailin": "Fera", ...}`) that always wins. The UI should let Danny set genus on a pet and write to this file.

### 3.2 Form fields = stable pet IDs
The PDF is a fillable form. Each pet checkbox has a field name like `pet_1013`. **Repeated pets share one field across pages** (the guide says so, and e.g. `pet_1013` appears checked on pp. 3, 4, 13 and 14 — that's Swarm). So:

- Use the form field name as the pet's primary key (`pdf_field_id`).
- Map field → pet name by locating the widget rect and taking the nearest pet-name text span on the same line.
- Read each widget's checked state → import as `unlocked=True` on first run.

Fields seen checked in Danny's copy (for test fixtures): `pet_1005, 1013, 1027, 1033, 1046, 1054, 1062, 1074, 1075, 1089, 1117, 1137, 1147, 1186, 1209`.

### 3.3 Validation counts (fail the parse loudly if these don't match)
- Altgard key: 90 monster→pet rows across 13 areas
- Verteron key: 37 rows across 13 areas
- Spirit Isle 16, Immortal Isle 23, Crimson Isle 10, Eternal Isle 22 rows
- Sulfur Tree Island 10 monster variants / 9 pets; Siel's Wings 11 / 11
- Abyss total: 25 distinct pets
- Chests & merchants: 35 pets (Cogni 6, Fera 12, Natura 9, Varian 8)

### 3.4 Gotchas the parser and data model must respect
- **Monster name ≠ pet name.** Always store both. Examples: Mumu Watcher → *Mumu Warrior*; Red Shell Mole → *Armadon*; Krall Armed Soldier → *Krall Laborer*; Black Claw Manduri Scout → *Manduri Trebuchet Worker*.
- **Similar names are different pets**: Tamed Karnif ≠ Karnif ≠ Modified Karnif ≠ Elite Karnif; Dratona ≠ Dratona Tinkerer; Spider ≠ Unstable Spider ≠ Baby Odyle Spider; Agrint / Thin / Withered / Ashen / Dry Leaf Agrint are all distinct.
- **`*` gold marker** on island/Abyss tables = pet missing from the home mainland checklist → store `priority_addition=True` for that source row.
- **`[ELITE]`** after a monster name → `elite=True`, strip from the name.
- Wrapped names in loop cards (e.g. "Manduri Trebuchet\nWorker") must be joined.
- Two Abyss fragment areas give the same 4 pets; Nagarant Warrior and Brawler share one pet.
- Page 18: Dratona, Klaw, Modified Karnif are "held" entries; Furious Feruk, Gatekeeper Pinopi, Kernon, Sentinel K'nash have **unconfirmed** alternate kill rewards → `unconfirmed_note` text.

---

## 4. Data model

`pets.json` (generated, committed, hand-editable):

```json
{
  "guide_version": "2026-10-12",
  "faction": "Asmodian",
  "pets": [
    {
      "id": "pet_1013",
      "name": "Swarm",
      "genus": "Varian",
      "genus_confidence": "high",
      "flags": { "held": false, "unconfirmed_note": null },
      "sources": [
        {
          "zone": "Altgard",
          "area_no": 10,
          "area": "Fafnite Deposit",
          "monster": "Giant Ore Insectoid",
          "level": null,
          "pin": null,
          "elite": false,
          "priority_addition": false,
          "source_type": "monster",
          "page": 3
        },
        {
          "zone": "Abyss",
          "area": "Black Fragments Area",
          "sub_location": "Kration Conflict Zone",
          "monster": "Abyss Aberrant Swarn",
          "level": 45,
          "pin": "A",
          "elite": false,
          "source_type": "monster",
          "page": 13
        }
      ]
    }
  ],
  "circuits": [
    {
      "zone": "Altgard",
      "name": "Fafnite Deposit",
      "level_range": "35-36",
      "note": "Varian-focused repeatable pockets.",
      "stops": [ { "pocket": "A", "pet_id": "pet_1013", "monster": "Giant Ore Insectoid" } ],
      "page": 4
    }
  ]
}
```

`source_type` ∈ `monster | chest_merchant | boss | dungeon`.
`zone` ∈ `Altgard | Spirit Isle | Immortal Isle | Verteron | Crimson Isle | Eternal Isle | Abyss | Other`.

SQLite `progress.db`:

```sql
CREATE TABLE progress (
  pet_id        TEXT PRIMARY KEY,
  unlocked      INTEGER NOT NULL DEFAULT 0,
  level         INTEGER,          -- current pet level, if known
  max_level     INTEGER,          -- from OCR or config
  souls_have    INTEGER,          -- current progress numerator (see §6)
  souls_need    INTEGER,          -- denominator to next level / max
  maxed         INTEGER NOT NULL DEFAULT 0,
  manual_lock   INTEGER NOT NULL DEFAULT 0, -- if 1, OCR never overwrites
  updated_at    TEXT,
  updated_by    TEXT              -- 'manual' | 'ocr' | 'pdf_import'
);
CREATE TABLE level_requirements (   -- learned from OCR: souls needed per level
  level INTEGER PRIMARY KEY, need INTEGER NOT NULL, seen_count INTEGER DEFAULT 1
);
CREATE TABLE card_hashes (          -- for grid scan (§6.5)
  pet_id TEXT, phash TEXT, resolution TEXT, PRIMARY KEY (pet_id, resolution)
);
CREATE TABLE ocr_log (
  id INTEGER PRIMARY KEY, ts TEXT, pet_id TEXT, raw_text TEXT,
  parsed_json TEXT, confidence REAL, screenshot_path TEXT, accepted INTEGER
);
```

---

## 5. Main tracker window

- **Left sidebar filters**: Genus (4 toggle chips, colored to match the guide), Zone, Status (Missing / Unlocked / In progress / Maxed), Source type, "Priority additions only", "Hide elite sources", text search (matches pet *or* monster name).
- **Center list**: one row per pet — checkbox (maxed), genus color dot, pet name, progress bar (`souls_have / souls_need` or `level / max_level`), best source summary (`Altgard · Fafnite Deposit · kill Giant Ore Insectoid`).
- **Group-by** toggle: by Pet (default) or by Zone → Area (route view, ordered by the guide's area numbers so it reads like the PDF).
- **Detail panel**: all sources for the selected pet, flags, page reference, manual edit of level/progress, "lock from OCR" toggle.
- **Route mode**: pick a zone/circuit → show only unfinished stops in pocket order (A, B, C…) with the exact monster names large and copy-able.
- Header stats: `Cogni 14/38 maxed` etc. per genus, plus overall.
- Keyboard: `/` focus search, `Space` toggle maxed, `1–4` toggle genus chips.

---

## 6. Overlay

### 6.1 Window
- Frameless, translucent, always-on-top, **click-through by default** (`Qt.WindowTransparentForInput`); toggle interactive mode with a hotkey to drag/resize.
- Compact panel showing the current filter's top N unfinished pets with remaining counts, plus a "current zone" picker so it can show just the active circuit.
- Works with the game in **borderless windowed** mode (exclusive fullscreen will hide it — document this in the README).

### 6.2 Scan flow (hotkey `Ctrl+Shift+P`)
1. `mss` grabs the game monitor.
2. Crop to a **calibrated ROI** (see 6.4).
3. Preprocess: upscale 2×, grayscale, contrast/threshold.
4. OCR → list of text lines with boxes.
5. Parse: pet name line + progress pattern(s) (`(\d+)\s*/\s*(\d+)`, `Lv\.?\s*(\d+)`).
6. Match name to a known pet (§6.3).
7. Show a toast on the overlay: `Swarm — 12/40 souls (Lv 3)`. Auto-accept if confidence ≥ threshold, else ask (✓ / ✗ / pick from top 3).
8. Write to `progress` (unless `manual_lock`), log to `ocr_log`, save the screenshot crop to `data/ocr_debug/` (keep last 50).

Also support "scan the whole list page" mode: OCR every visible row in the collection grid and batch-update.

### 6.3 Name matching — must be strict
Because the guide's whole point is that near-identical names are different pets:
- Normalize (case, whitespace, apostrophes).
- Exact match first.
- Fuzzy only with `rapidfuzz.fuzz.ratio` ≥ 92 **and** a margin of ≥ 6 over the second-best candidate; otherwise require confirmation.
- Never auto-accept when the top two candidates differ only by a prefix word (Karnif vs Tamed Karnif, Spider vs Unstable Spider).

### 6.4 The in-game Pets window (from a real 1920×1080 screenshot)

Reference image: `data/sample_screens/pets_konutin_worker_1080p.png`.

**Layout**
- Title "Pets", top tabs **Pets** / **Genus Insight**.
- Far-left vertical icon column: **ALL** plus 5 category icons. These are probably genus filters, but there are 5 icons for 4 genera, so confirm what each one is before relying on them.
- **Pet card grid**: 3 columns, scrollable. Each card shows:
  - bottom-left: a circled **level number** (`1`, `3`, …)
  - bottom-right: either **`MAX`** or a **progress fraction** like `7/25`
  - the equipped pet has an "Equipped" text overlay (OCR noise; ignore it)
  - ⚠️ **Cards show no pet name.** The grid alone cannot identify a pet.
- **Right detail panel** (for the selected card), with tabs Pet Info / Source / All Owned Effects:
  - **Pet name** (large), e.g. `Konutin Worker`
  - circular badge top-right with a genus icon (tree here; Konutin Worker is Natura). It also shows "MAX", whose meaning is unclear (the pet itself is Lv 1), so don't parse it as level.
  - **`Pet Insight  Lv. 1 (7/25)`** plus a progress bar → `level`, `have`, `need`
  - 3 stage icons under the bar → **max level is 3** (MAX cards all show level 3)
  - Owned Effect (e.g. Stamina 3) — optional to capture
  - `<` `>` arrows step through pets
- Bottom-left: **`Collection Status 173/200`** → total pets owned / total pets.

**Default ROIs** (store as fractions of the game client area so other resolutions scale; values below are pixels at 1920×1080):

| ROI | x1, y1 → x2, y2 | Parse |
|---|---|---|
| `name` | 1530, 205 → 1840, 255 | pet name |
| `insight` | 1500, 270 → 1820, 296 | `Lv\.?\s*(\d+)\s*\((\d+)\s*/\s*(\d+)\)` |
| `genus_badge` | 1843, 200 → 1893, 250 | icon template match (optional) |
| `collection` | 250, 1012 → 445, 1037 | `(\d+)\s*/\s*(\d+)` |
| `grid` | 85, 140 → 440, 990 | per-card crops (pitch ≈ 118 × 163 px) |
| per card `level` | bottom-left circle of card | digit |
| per card `progress` | bottom-right of card | `MAX` or `(\d+)/(\d+)` |

**What "missing" means**
- `maxed` = level == 3 (or card shows `MAX`).
- Otherwise missing at this level = `need - have` (e.g. 25 − 7 = 18 for Konutin Worker at Lv 1).
- The requirement for later levels isn't known yet. Record every observed `(level, need)` pair in a `level_requirements` table. Once a Lv 2 pet has been seen, total-to-max = (need − have at current level) + sum of the known later requirements. Until then, show "18 to Lv 2" rather than inventing a total.
- Also store `max_level=3` as a config default (`config/settings.json`) in case it changes.

### 6.5 Scan modes for this UI
1. **Detail scan (primary)** — hotkey OCRs `name` + `insight` for the selected pet → exact update. Danny clicks `>` in game himself and presses the hotkey again. The app never clicks for him.
2. **Grid scan (fast, after learning)** — since cards have no names, the first time a pet is detail-scanned, save its card thumbnail (perceptual hash, e.g. `imagehash.phash`) next to its pet_id. Later, a grid scan crops each visible card, matches the hash to a known pet, and reads level + `MAX`/`x/y` from the card corners. Unmatched cards → "unknown card, select it and detail-scan once."
3. **Collection check** — read `Collection Status x/y` on every scan and show it in the tracker header. If the app's unlocked count differs from `x`, flag "out of sync."

Keep a **calibration wizard** as a fallback: show the screenshot with the default ROIs drawn and let Danny drag them if the layout or resolution differs. Save to `config/ocr_profiles.json` keyed by resolution.

OCR tests: use the reference screenshot as a fixture. Expected values: name `Konutin Worker`, level 1, have 7, need 25, collection 173/200; first grid card shows level 1 and `7/25`; the other visible cards show level 3 and `MAX`.

**TODO for Danny:** add more screenshots to `data/sample_screens/`: a pet at Lv 2 (to learn the next requirement), the **Source** tab, the **Genus Insight** tab, and one with each left-column category icon selected.

### 6.6 Config
`config/settings.json`: hotkeys, monitor index, OCR engine, confidence thresholds, overlay opacity/position, `max_level` (default 3).

---

## 7. Project layout

```
aion2-pet-tracker/
  app/
    main.py              # entry: tracker window + overlay + hotkey thread
    ui/tracker_window.py
    ui/overlay.py
    ui/calibration.py
    ui/widgets/          # genus chips, progress rows
    core/models.py       # dataclasses: Pet, Source, Circuit, Progress
    core/store.py        # SQLite + pets.json loading
    core/filters.py      # pure filter/sort functions (unit-tested)
    ocr/engine.py        # OcrEngine protocol, RapidOcr/Tesseract impls
    ocr/capture.py       # mss + ROI crop + preprocess
    ocr/parse.py         # text → {name, level, have, need}
    ocr/match.py         # strict name matching
    hotkeys.py
  tools/
    parse_pdf.py         # PDF → data/pets.json + parse_report.md
  data/
    source/              # the guide PDF (gitignored)
    pets.json
    genus_overrides.json
    sample_screens/
    ocr_debug/
  config/
  tests/
  README.md
```

---

## 8. Build order (milestones)

1. **Parser** — `tools/parse_pdf.py` produces `pets.json`, `parse_report.md` (counts vs §3.3, pets with unknown/low-confidence genus, any unmatched form fields), and imports checked form fields. Tests: count assertions + fixtures for the §3.4 gotchas (e.g. Mumu Watcher → Mumu Warrior, Tamed Karnif ≠ Karnif, Swarm has ≥ 4 sources).
2. **Tracker window** — list, filters (genus filter is the headline feature), detail panel, manual progress editing, persistence.
3. **Route mode** — zone/circuit view with unfinished stops only.
4. **Overlay shell** — click-through window showing the filtered missing list, hotkey toggle.
5. **OCR pipeline** — capture, calibration wizard, parse, strict match, confirm toast, logging. Tests run against `data/sample_screens/`.
6. **Polish** — grid scan via card hashes (§6.5), per-genus stats header, PyInstaller build, README (borderless mode, hotkeys, calibration).

Ask Danny before milestone 5 if sample screenshots aren't in the repo yet.

---

## 9. Acceptance checks

- Filtering to Cogni + Missing shows only Cogni pets that aren't maxed, across all zones, and the counts in the header match the list.
- Ticking a pet anywhere updates every place that pet appears (shared ID, same as the PDF).
- First run imports the 15 pre-checked PDF fields as unlocked.
- OCR on a sample screenshot fills `souls_have/souls_need` (or level) for the right pet and never auto-matches a look-alike name.
- Overlay never steals focus or clicks from the game.
- Nothing is sent to the game process; the app only reads the screen.
