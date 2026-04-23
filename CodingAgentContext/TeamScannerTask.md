# Task: In-Game Team Scanner — COMPLETE

**Status:** ✅ All phases functional. Opp sprite slot 2 (Drampa) is the only known limitation; see "Known limits."

## What this solves

The AI auto-battler (`AutoLadder` with `MoveStrategy::AI`) needs full team data on both sides before turn 1. Previously this was done via a manual Showdown paste. Now it's read directly from the game UI across two screens, with the battle HUD as a runtime fallback.

## Final architecture

### Three screens cooperate

| Screen | Detector | Reader | Fields produced |
|---|---|---|---|
| **View Details → Moves & More** | `MovesMoreDetector` | `TeamSummaryReader::read_team()` | Own: species, ability, 4 moves for all 6 Pokémon |
| **Pre-battle Team Preview** | `TeamPreviewDetector` | `TeamPreviewReader::read()` | Own: species + items (cross-check). Opp: species (sprite-matched, 5/6 typical) |
| **Battle HUD** (existing) | `BattleModeDetector` etc. | `BattleHUDReader` | Per-turn: active species, HP, status — fills any opp slots the preview couldn't sprite-match |

### Data flow

```
User picks team in game menu
    │
    ▼
MovesMoreDetector fires in View Details
    ├─ read_team() → species, ability, 4 moves x 6
    └─ BattleStateTracker::set_own_team()

User returns to matchmaking, presses Start
    │
    ▼
AutoLadder::enter_matchmaking → Team Preview shows
    │
    ▼
TeamPreviewDetector fires (OCR: "Select")
    ├─ read() own-side: species + items x 6 (OCR)
    │   └─ BattleStateTracker::set_own_item(slot, item)
    └─ read() opp-side: sprite-match x 6 vs 272-species atlas
        └─ BattleStateTracker::set_opp_species_preview(slot, species)

Battle starts
    │
    ▼
Per-turn: BattleHUDReader fills in any opp slots missing from preview
    │
    └─ BattleStateTracker::update_from_hud() learns species as they enter play
```

## Files created

### C++ inference classes
```
SerialPrograms/Source/PokemonChampions/Inference/
  PokemonChampions_AbilityNameReader.h/.cpp     # SmallDictionaryMatcher, 135 abilities
  PokemonChampions_ItemNameReader.h/.cpp        # SmallDictionaryMatcher, 106 items
  PokemonChampions_MovesMoreDetector* (in TeamSummaryReader.cpp)
  PokemonChampions_TeamSummaryReader.h/.cpp     # 2x3 grid OCR of full team details
  PokemonChampions_TeamSelectDetector.h/.cpp    # Team Registration screen (yellow pill gate)
  PokemonChampions_TeamSelectReader.h/.cpp      # Species list on left of Team Registration
  PokemonChampions_TeamPreviewDetector.h/.cpp   # "Select 4" pre-battle screen (OCR gate)
  PokemonChampions_TeamPreviewReader.h/.cpp     # own OCR + opp sprite match
  PokemonChampions_SpriteMatcher.h/.cpp         # CroppedImageDictionaryMatcher, 272 species
```

### Resources
```
Resources/PokemonChampions/
  PokemonItemsOCR.json         # Generated from data/vocab/items.json
  PokemonAbilitiesOCR.json     # Generated from data/vocab/abilities.json
  PokemonSprites.png           # 2176x2048 atlas, 272 species at 128x128
  PokemonSprites.json          # Spritelocations map
```

### Python tooling
```
tools/
  pixel_inspector.py                     # --measure / --remeasure / --measure-status modes
  box_definitions.json                   # Pending/confirmed boxes (27 anchors)
  download_bulbapedia_sprites.py         # MediaWiki API + cloudscraper for 320 reference sprites
  map_sprites_to_slugs.py                # PokeAPI + custom form map → slug table
  build_sprite_atlas.py                  # Packs 272 sprites into PokemonSprites.{png,json}
  extract_movesmore_sprites.py           # Optional helper to extract sprites from gameplay
```

### Test fixtures
```
CommandLineTests/PokemonChampions/
  TeamSelectDetector/  teamreg_True.png, movesmore_False.png
  MovesMoreDetector/   movesmore_True.png, teamreg_False.png
  TeamSelectReader/    teamreg_garchomp_venusaur_charizard_sneasler_kingambit_incineroar.png
  TeamSummaryReader/   movesmore_garchomp_venusaur_charizard_sneasler_kingambit_incineroar.png
  TeamPreviewDetector/ preview_True.png, movesmore_False.png
  OCRDump/             movesmore_card.png, teamreg.png, team_preview.png
```

## Measured anchor points (1920x1080 normalized)

Team preview reader uses these and linearly interpolates between slot 0 and slot 5:

| Box | Slot 0 | Slot 2 (midpoint verify) | Slot 5 |
|---|---|---|---|
| own_species | (0.0760, 0.1565, 0.0969, 0.0389) | (0.0729, 0.3898, 0.0844, 0.0352) | (0.0724, 0.7389, 0.0922, 0.0361) |
| own_item    | (0.0964, 0.1981, 0.0786, 0.0333) | (0.0974, 0.4343, 0.0802, 0.0296) | (0.0995, 0.7852, 0.0823, 0.0306) |
| opp_sprite  | (0.8380, 0.1509, 0.0578, 0.0917) | —                                | (0.8411, 0.7407, 0.0583, 0.0880) |

Moves & More reader anchors: `moves_more/species_0`, `species_1`, `species_2`, `ability_0`, `move_0_{0..3}` — all measured and committed in `tools/box_definitions.json`.

## Text-filter gotchas learned

- **Team Registration screen:** dark navy text (`RGB ~5,45,124`) on pale lavender pill. Standard `BLACK_TEXT_FILTERS` fails because B channel too high; use custom range up to `0xa0b0c0`.
- **Team Preview screen, unhighlighted slots:** WHITE text on purple pill. Use `WHITE_TEXT_FILTERS` ranges.
- **Team Preview screen, highlighted (lime) slot:** DARK text on lime pill. Reuse the dark-navy filter.
- **Moves & More screen:** WHITE text on purple pill. Standard `WHITE_TEXT_FILTERS` works.

OCR framework accepts multiple text-color ranges per call and tries each — we use combined white+dark lists where a screen has both states.

## Results on test screenshot (team_preview_3804.png)

Ground truth enemy team: Gardevoir, Heracross, Drampa, Azumarill, Corviknight, Abomasnow.

```
  own 0: species="glimmora"   item="focus-sash"     ✓
  own 1: species="sinistcha"  item="sitrus-berry"   ✓
  own 2: species="rotom"      item="choice-scarf"   ✓
  own 3: species="sylveon"    item="leftovers"      ✓
  own 4: species="dragapult"  item="lum-berry"      ✓
  own 5: species="kingambit"  item="bright-powder"  ✓
  opp 0: species="gardevoir"     (alpha=0.18)  ✓
  opp 1: species="heracross"     (alpha=0.13)  ✓
  opp 2: species=""              (rejected 0.35 > 0.30 threshold, was going to be "wyrdeer")
  opp 3: species="azumarill"     (alpha=0.13)  ✓
  opp 4: species="corviknight"   (alpha=0.13)  ✓
  opp 5: species="abomasnow"     (alpha=0.23)  ✓
```

Own: 12/12. Opp: 5/6 correctly identified, 1/6 correctly abstained (better than a wrong answer).

## Known limits

### Drampa / Wyrdeer confusion

Both are brown quadrupeds with similar silhouettes. RMSD at 0.35 is the boundary between confident and ambiguous. The 0.30 threshold chooses "unknown" over "likely wrong," which is correct for downstream decision-making. The HUD reader fills this in the moment Drampa hits the field.

### Visually similar species cluster

Any two Pokémon with very similar silhouettes (e.g. Salamence vs Goodra, Noivern vs Dragonite from some angles) will produce marginal alphas and may be rejected. If this becomes a problem:

- Option A: widen alpha threshold back up (accept more risk of wrong matches).
- Option B: use `SilhouetteDictionaryMatcher` with alpha-masked RMSD for higher discriminative power.
- Option C: for top-N candidates within a 0.05 alpha spread, emit them all and let the AI treat as "likely one of these."

Not a priority until it affects win rate.

### Items for opponents

Team preview shows opponent items as **small circular icons**, not text. Not implemented — would require a separate item-sprite matcher (~106 classes). Low priority because opponents reveal items via item-activation log events during battle.

### Doubles-only verification

Everything tested against a Doubles team preview (bring-6-pick-4). Singles format (bring-6-pick-3) likely has the same UI structure but hasn't been verified. Coordinates and thresholds are expected to carry over — if not, same pixel_inspector measurement workflow applies.

## How to regenerate the atlas

If Pokémon Champions updates add new species:

```bash
python3 tools/download_bulbapedia_sprites.py          # downloads new Menu_CP_*.png files
python3 tools/map_sprites_to_slugs.py                  # maps filenames → slugs (check for unmapped)
python3 tools/build_sprite_atlas.py                    # rebuilds PokemonSprites.{png,json}
```

If any unmapped files appear, update `FORM_SUFFIX_MAP` or `OCR_SLUG_FIXUPS` in `map_sprites_to_slugs.py`, and add missing slugs to `PokemonSpeciesOCR.json`.
