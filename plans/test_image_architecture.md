# PRD: Test Image & Detection Architecture Overhaul

## Problem Statement

The current detector/reader testing system encodes labels in filenames and stores one copy of each image per detector directory. This creates three critical problems:

1. **No reuse** — the same screenshot can't serve as a test case for multiple detectors/readers without duplication
2. **Can't encode complex labels** — filenames can't represent multi-dimensional ground truth (species names + detector bools + sprite data on one image)
3. **No comprehensive screen model** — detectors are added ad-hoc with no shared understanding of all game screens and transitions, making it hard to plan coverage or build a state machine for auto-ladder

## Solution Overview

Replace the filename-based, per-detector directory structure with:

1. **A canonical screen graph** (`screens.yaml`) defining every game screen, valid transitions, and registered detectors/readers with typed field schemas
2. **Per-screen image directories** with `manifest.json` files storing all labels
3. **Implicit negative testing** — any image not in a detector's registered screen is a negative case
4. **A web-based labeler** on the ash dashboard with OCR pre-population via ColePC job runner API

## Screen Inventory

### Screens (13 directories)

| Directory | Description | Singles/Doubles Split |
|-----------|-------------|-----------------------|
| `team_select` | Registering team of 6 before queueing | No |
| `searching_for_battle` | Animation/transition after matchmaking | No |
| `team_preview_selecting` | Choosing 4 to bring, opponent team visible | No |
| `team_preview_locked_in` | Selections made, "Standing By" pills | No |
| `action_menu_singles` | FIGHT / POKEMON buttons (singles) | Yes |
| `action_menu_doubles` | FIGHT / POKEMON buttons (doubles) | Yes |
| `move_select_singles` | 4-move panel, PP, mega evo toggle (singles) | Yes |
| `move_select_doubles` | 4-move panel, PP, mega evo toggle (doubles) | Yes |
| `pokemon_switch_singles` | Choosing mon to switch to (singles) | Yes |
| `pokemon_switch_doubles` | Choosing mon to switch to (doubles) | Yes |
| `communicating` | "Communicating..." waiting for opponent | No |
| `result_screen` | WON! / LOST | No |
| `post_match` | Quit / Edit Team / Continue buttons | No |

### Overlays (1 directory)

| Directory | Description |
|-----------|-------------|
| `_overlays/battle_log` | Text bar overlay during battle, can appear over any in-battle screen |

### Transitions (state machine)

```
team_select -> searching_for_battle
searching_for_battle -> team_preview_selecting
team_preview_selecting -> team_preview_locked_in, communicating
team_preview_locked_in -> communicating
communicating -> action_menu_singles, action_menu_doubles, pokemon_switch_singles, pokemon_switch_doubles, result_screen
action_menu_singles -> move_select_singles, pokemon_switch_singles, communicating
action_menu_doubles -> move_select_doubles, pokemon_switch_doubles, communicating
move_select_singles -> communicating
move_select_doubles -> communicating
pokemon_switch_singles -> communicating
pokemon_switch_doubles -> communicating
result_screen -> post_match
post_match -> team_select, searching_for_battle
```

Note: forfeit can transition any in-battle screen to `result_screen` at any time.

## Directory Structure

```
test_images/
├── screens.yaml                         # Canonical screen graph
├── _overlays/
│   └── battle_log/
│       ├── manifest.json
│       └── *.png
├── team_select/
│   ├── manifest.json
│   └── *.png
├── searching_for_battle/
│   ├── manifest.json
│   └── *.png
├── team_preview_selecting/
│   ├── manifest.json
│   └── *.png
├── team_preview_locked_in/
│   ├── manifest.json
│   └── *.png
├── action_menu_singles/
│   ├── manifest.json
│   └── *.png
├── action_menu_doubles/
│   ├── manifest.json
│   └── *.png
├── move_select_singles/
│   ├── manifest.json
│   └── *.png
├── move_select_doubles/
│   ├── manifest.json
│   └── *.png
├── pokemon_switch_singles/
│   ├── manifest.json
│   └── *.png
├── pokemon_switch_doubles/
│   ├── manifest.json
│   └── *.png
├── communicating/
│   ├── manifest.json
│   └── *.png
├── result_screen/
│   ├── manifest.json
│   └── *.png
└── post_match/
    ├── manifest.json
    └── *.png
```

## screens.yaml Schema

```yaml
screens:
  team_select:
    description: "Registering team of 6 before queueing for ranked"
    transitions_to: [searching_for_battle]
    detectors: [TeamSelectDetector]
    readers:
      TeamSelectReader:
        fields:
          species:
            type: array
            items: string
            length: 6

  team_preview_selecting:
    description: "Choosing which 4 mons to bring. Opponent team visible. No Standing By pills."
    transitions_to: [team_preview_locked_in, communicating]
    detectors: [TeamPreviewDetector]
    readers:
      TeamPreviewReader:
        fields:
          own_species:
            type: array
            items: string
            length: 6
          opponent_species:
            type: array
            items: string
            length: 6
      OpponentSpriteReader:
        fields:
          sprites:
            type: array
            items: string
            length: 6

  move_select_doubles:
    description: "4-move panel active in doubles. PP visible. Mega evo toggle possible."
    transitions_to: [communicating]
    detectors: [MoveSelectDetector]
    readers:
      MoveNameReader:
        fields:
          moves:
            type: array
            items: string
            length: 4
      MoveSelectCursorSlot:
        fields:
          slot:
            type: int
            min: 0
            max: 3
      BattleHUDReader:
        fields:
          opponent_species:
            type: array
            items: string
            length: 2
          opponent_hp_pct:
            type: array
            items: int
            length: 2
          own_hp:
            type: array
            items: string
            length: 2

overlays:
  battle_log:
    description: "Text bar overlay during battle. Can appear over any in-battle screen."
    readers:
      BattleLogReader:
        fields:
          events:
            type: array
            items: string
```

- Field types: `string`, `int`, `bool`, `array`, `object`
- Use `null` for unreadable/missing values (not "NONE")
- New readers are added by updating screens.yaml and labeling images

## manifest.json Schema

Per-directory JSON file. Keys are filenames, values are reader labels.

```json
{
  "20260428-085740607506.png": {
    "TeamPreviewReader": {
      "own_species": ["garchomp", "incineroar", "tornadus", "rillaboom", "flutter-mane", "urshifu"],
      "opponent_species": ["kyogre", "calyrex-shadow", "incineroar", "rillaboom", "tornadus", "flutter-mane"]
    },
    "OpponentSpriteReader": {
      "sprites": ["kyogre", "calyrex-shadow", "incineroar", "rillaboom", "tornadus", "flutter-mane"]
    }
  }
}
```

- Images not present in a manifest but in the directory are unlabeled (flagged by validation)
- Detectors are NOT in manifests — positive/negative is determined by directory membership + screens.yaml registration

## Negative Test Model

- A detector registered against `team_preview_selecting` and `team_preview_locked_in` returns **true** on all images in those directories
- It returns **false** on all images in every other screen directory
- No explicit false entries needed anywhere
- Adding a new screen with 50 images automatically gives every other detector 50 new negative test cases

## C++ Test Runner Changes

- Add **yaml-cpp** and **nlohmann/json** as dependencies
- Replace `CommandLineTests/PokemonChampions/` directory scanning with `test_images/` structure
- Parse `screens.yaml` for detector/reader registration
- Parse `manifest.json` per directory for expected reader values
- For each detector: run positive tests (registered screen images) + negative tests (all other screen images)
- For each reader: run against registered screen images, compare output to manifest values
- Delete old `CommandLineTests/PokemonChampions/` directory

## Web Labeler (ash dashboard)

### Inbox View
- Shows unsorted images dumped from DetectorTest or manual screenshots
- Assign each image to a screen directory (click or keyboard shortcut)
- Bulk selection supported

### Screen View
- Pick a screen directory, see all images
- Each image shows: full screenshot + crop region previews
- Label fields auto-generated from screens.yaml schema
- Pre-populated with OCR suggestions from ColePC job runner API

### Validation View
- Shows images with incomplete or missing labels across all screens
- Flags manifest entries that don't match screens.yaml schema

## OCR Suggestion API (ColePC job runner)

Extend the existing job runner (port 8422) with:

```
POST /ocr-suggest
Body: { image: <base64 or multipart>, reader: "MoveNameReader", screen: "move_select_doubles" }
Response: { "moves": ["fake-out", "close-combat", "dire-claw", "protect"] }
```

- Runs the actual C++ reader against the image
- Returns suggested labels for human confirmation in the web labeler
- Optional — labeler works without it, just requires manual entry

## Image Naming

- Timestamps: `20260428-085740607506.png`
- Filenames carry zero semantic meaning
- All labels in manifest.json
- No renaming during ingest

## Migration Plan

- Rip and replace: delete `CommandLineTests/PokemonChampions/`
- Migrate existing labeled images into new directory structure
- Build migration script that parses old filenames into manifest entries
- One-time operation, no incremental migration needed
