# Task: In-Game Team Scanner — OCR team data from Pokemon Champions UI

## Goal

Build a "Scan Team" feature that reads the player's 6 Pokemon team from the in-game UI, extracting species, moves, item, and ability for each. This populates the `BattleStateTracker` automatically instead of requiring a manual Showdown paste.

## Context

The AI auto-battler (`AutoLadder` with `MoveStrategy::AI`) needs to know the player's own team. Currently this is done via a Showdown paste text box. This task adds the ability to read it directly from the game's screens.

### What already exists

- **`BattleStateTracker`** (`PokemonChampions_BattleStateTracker.h/.cpp`) — has `set_own_team()` and `load_team_from_showdown_paste()`. The scanner should populate the same `ConfiguredPokemon` struct:
  ```cpp
  struct ConfiguredPokemon {
      std::string species;              // slug: "kingambit"
      std::array<std::string, 4> moves; // slugs: "sucker-punch"
      std::string item;                 // slug: "bright-powder"
      std::string ability;              // slug: "defiant"
  };
  ```

- **OCR infrastructure** — all building blocks are in place:
  - `SpeciesNameOCR` singleton (`BattleHUDReader.h`) — `SmallDictionaryMatcher` with 315 species, tested and working on live frames
  - `MoveNameOCR` singleton (`MoveNameReader.h`) — `SmallDictionaryMatcher` with 473 moves
  - `OCR::WHITE_TEXT_FILTERS()` and `match_substring_from_image_multifiltered()` — the standard OCR pipeline
  - `ImageFloatBox` crop regions + `extract_box_reference()` — normalized coordinate system
  - `raw_ocr_line()` / `raw_ocr_numbers()` — with upscaling for small text

- **OCR dictionaries** in `Resources/PokemonChampions/`:
  - `PokemonMovesOCR.json` — 473 moves
  - `PokemonSpeciesOCR.json` — 315 species
  - **No item dictionary yet** — needs to be created from `data/vocab/items.json`
  - **No ability dictionary yet** — needs to be created from `data/vocab/abilities.json`

- **C++ CLI test framework** — `SerialProgramsCommandLine.exe --test <path>` runs OCR against static images. Tests go in `CommandLineTests/PokemonChampions/<TestName>/`. Use `OCRDump` for dev iteration.

- **Pixel inspector tool** — `tools/pixel_inspector.py` for measuring crop box coordinates from screenshots

- **Auto-screenshot** — `DetectorTest` program captures classified frames from live gameplay to `Screenshots/detector_test/`

### Screens available for reading team data

**1. Team Select Screen (pre-battle)**
- Appears after matchmaking finds an opponent
- Shows all 6 own Pokemon on the left side as a vertical list
- Each slot shows: sprite, nickname, item name, gender icon
- Header: "Ranked Battles   Double Battle" (or Single Battle)
- Bottom: "0/4 Done" counter
- **Captured frames**: `MOVE_SELECT/61_*.png` (misclassified as MOVE_SELECT), `UNKNOWN/131_*.png`
- **Best for**: Reading all 6 species + items in one screen

**2. Team Summary Screen (from Box / "Show Summary" button)**
- Accessible from team select via Y button ("Show Summary")
- Shows one Pokemon at a time with full details
- Left panel: species name (actual, not nickname), stats, nature, IVs/EVs
- Right panel: 4 moves with PP, ability, held item
- Navigation: L/R buttons cycle through team members
- **Captured frames**: `ACTION_MENU/2_*.png` (the Victreebel summary from earlier session, was from video not live)
- **Best for**: Complete data per Pokemon (species, moves, ability, item, stats)

**3. Moves & More Screen (in-battle, X button → "Moves & More" tab)**
- Only available during battle when it's your turn
- Shows one Pokemon's moves, PP, ability, held item
- Left panel: own team HP bars
- Right panel: opponent team sprites
- **Captured frames**: `POST_MATCH/76_*.png`, `POST_MATCH/131_*.png`
- **Best for**: Move/ability/item data during a battle (already accessible)

### Recommended approach

**Phase 1: Team Select Screen Reader** (highest value, reads all 6 at once)
- Create `PokemonChampions_TeamSelectDetector.h/.cpp` — detect when team select is visible
- Create `PokemonChampions_TeamSelectReader.h/.cpp` — OCR species + item for all 6 slots
- Needs: 6 species name crop boxes, 6 item name crop boxes (measure with pixel inspector)
- Needs: `PokemonItemsOCR.json` dictionary (generate from `data/vocab/items.json`)

**Phase 2: Summary Screen Reader** (reads moves + ability per Pokemon)
- After reading species/items from team select, navigate to Show Summary (Y button)
- Read moves (4 boxes), ability (1 box), confirm species + item
- Press L/R to cycle through all 6 team members
- This gives complete team data without any manual input

**Phase 3: Wire into AutoLadder**
- Add a "Scan Team from Game" button in the Auto Ladder UI
- When clicked: navigate to team select, read all 6, optionally open summary for each
- Populate `BattleStateTracker` and update the Showdown paste text box to match

### Key files to reference

| File | What it does |
|------|-------------|
| `PokemonChampions_BattleHUDReader.h/.cpp` | Pattern for OCR readers — crop boxes, `read_opponent_species()`, etc. |
| `PokemonChampions_MoveNameReader.h/.cpp` | Pattern for move OCR with `SmallDictionaryMatcher` |
| `PokemonChampions_BattleModeDetector.h/.cpp` | Pattern for screen detection (color check + OCR) |
| `PokemonChampions_BattleStateTracker.h/.cpp` | Target: `set_own_team()` and `ConfiguredPokemon` struct |
| `PokemonChampions_AutoLadder.h/.cpp` | Integration point: `AI_TEAM_PASTE` option, program flow |
| `Tests/PokemonChampions_Tests.cpp` | Test framework pattern for adding new test functions |
| `data/vocab/items.json` | Source for building items OCR dictionary |
| `data/vocab/abilities.json` | Source for building abilities OCR dictionary |
| `Resources/PokemonChampions/PokemonMovesOCR.json` | Example dictionary format: `{"eng": {"slug": ["Display Name"]}}` |
| `scripts/test_ocr.py` | Python OCR testing — useful for quick coordinate iteration |
| `CodingAgentContext/AutomationProgramPatterns.md` | C++ program architecture patterns |

### Captured frame locations (on ColePC)

- `Screenshots/detector_test/MOVE_SELECT/` — 250 frames (some are team select)
- `Screenshots/detector_test/UNKNOWN/` — 233 frames
- `Screenshots/detector_test/ACTION_MENU/` — 31 frames (some are summary/info screens)
- `CommandLineTests/PokemonChampions/OCRDump/` — test frames for CLI testing

### Build & test workflow

1. Edit files locally on Mac
2. `git commit && git push`
3. SSH to ColePC: `ssh colepc 'cd C:\Dev\pokemon-champions && git pull'`
4. Build: `build_and_run.bat` or manual cmake build
5. OCR dictionaries must be copied: `xcopy /E /I /Y Resources\PokemonChampions build\Release\Resources\PokemonChampions`
6. CLI test: `build\Release\SerialProgramsCommandLine.exe --test CommandLineTests\PokemonChampions\OCRDump\`
7. Live test: Run DetectorTest with Auto-Screenshot on, capture frames while navigating menus

### Important notes

- The game uses **nicknames** on the team select screen, not species names. The species is revealed in the summary screen or can be inferred from the sprite.
- Item names on team select include Mega Stones (e.g., "Victreebelite", "Clefablite") which reveal the species even when nicknames are used.
- The resolution is always 1920x1080 from the capture card.
- All coordinates use normalized `ImageFloatBox(x, y, width, height)` where values are 0.0-1.0.
- MSVC treats warnings as errors (`/WX`), so no unused variables or implicit narrowing conversions.
