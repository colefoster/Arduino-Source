# What's Next

Living doc. Keep it short. When in doubt, move things up or delete, don't expand.

Update protocol: edit in place, no dates on items in Now/Next/Backlog. Add to **Recently shipped** when something lands.

---

## Now
*Actively touching this week.*

- **OCR quality pass on BattleHUDReader.** HP digit massaging started (`088b961c9`: 7→1, 0-699, cur≤max). PP surfaced in OcrSuggest + manifest. Still open: HP-bar-color sanity check on max HP, decide whether to keep PP visual or DB-tracked.
- **Mismatches workflow.** Streaming + per-row crop + bulk Accept + j/k/a/s/i landed. Use it to grind down the remaining detector failures (see Backlog).

## Next
*Picked, not started.*

- **Pokeball detector live integration.** Detector + visual confirm shipped. Still need: wire into the inference engine / spectator pipeline so it runs per turn. (Runtime carries forward "was alive at start" so fainted-vs-empty ambiguity resolves itself; no ground-truth labeling needed.)
- **Game time + turn time parsing.** Niche, but useful for troubleshooting and replay annotation.
- **(Removed)** BattleHUD own-active sprite match -- shipped as a sanity-check signal at ~5/6 on team mons; not the primary identity path. Active mon is determined by user selection order, not visual.
- **Result screen box widths.** Gold/silver detection works; if the L/R win/loss assumption (us=left, opp=right) is ever wrong, adjust boxes.

## Backlog
*Ideas, not committed.*

- **Break up `BattleHUDReader`?** It's drifting toward 8+ sub-readers (HP, PP, status, Tera, item, ability, sprite, pokeballs). Open design Q -- when does fan-out beat a single fat reader?
- **Detector tuning grind** (current state, 2026-05-02 evening):
  - PostMatchScreenDetector: 211/213 (99.1%) -- 2 fails (action_menu attack animation + 1 communicating overlay both have bright green at the Continue position)
  - BattleHUDReader.opponent_species: 138/138 (100%) -- all 41 prior fails were mislabels; OCR was correct (canonical species, language-agnostic)
  - BattleHUDReader.own_hp_current: 66/66 (100%)
  - BattleHUDReader.own_hp_max: 66/66 (100%)
  - TeamPreviewDetector: 213/213 (100%) -- locked-in screen dropped from registry; PreparingForBattleDetector covers that screen
  - MovesMoreDetector / BattleLogReader: 2 fails each
  - MoveSelectDetector / TeamSelectDetector / BattleHUDReader.own_hp_current: 1 fail each
- **Search engine sequence-history encoding.** MCTS 1-ply gave -0.4% lift; bottleneck is missing sequence history in encoding (per `memory/project_search_engine.md`).
- **Pipeline redesign.** Two-layer hour-bucketed pipeline; sharded_cache + lead/winrate/v2_window slated for deletion. Phased plan in `plans/two-layer-pipeline-and-model-cuts.md`.

## Recently shipped
*Last ~2 weeks. Trim aggressively -- this is for context, not history.*

- 2026-05-04 -- MainMenuDetector 95.3% -> 100%. Remaining 10 FPs were action_menu / move_select / battle_log / battle_mode_menu frames where genuine yellow pixels (move tiles, status icons) happened to land on the 3x3 button-glow sample regions. Tightened `is_solid` ratio tolerance 0.15 -> 0.05 (kills 6 off-color FPs) and added a third "menu chrome" sample at (0.30, 0.45) — the TV/character backdrop reads bright cyan-blue (b≈254) on the menu and warm/dim (b<150) on every battle FP. Also added detectors to the dashboard Mismatches view (new `Detectors` optgroup) and switched mac_dev_runner from single-threaded `HTTPServer` to `ThreadingHTTPServer` so 200+ parallel scans don't queue head-of-line and trigger Cloudflare 524.
- 2026-05-04 -- BattleHUDReader.own_hp_current/max 90.9%/95.5% -> 100%/100%. Switched from two per-side crops (cur, max) to one combined "X/Y" crop per slot — Tesseract sees the slash in proper digit context. Added a digit-confusable pre-pass mapping common Tesseract misreads (`>` → `2`, `B`/`E` → `8`, `O` → `0`, etc.) before parse_fraction; the pre-pass drops confusables that are sandwiched between two digits (segmentation noise like "8E4") instead of mapping them. Mismatches view now shows `(raw: X)` next to `got` so you can see pre/post fixup at a glance.
- 2026-05-03 -- TeamPreviewDetector 98.1% -> 100%. All 4 fails were on `team_preview_locked_in` frames; the detector OCRs "Select 4 Pokemon..." which only appears on the selecting screen. Fixed by dropping `team_preview_locked_in` from the detector's registry entry (PreparingForBattleDetector already covers that screen).
- 2026-05-03 -- BattleHUDReader.opponent_species 70.3% -> 100%. All 41 fails were mislabels; OCR had been right. Mismatches view now supports `field=` filter + URL prepopulation (`#/mismatches?reader=...&field=...&auto=1`) for fast triage. Confirmed live that opp species cards are canonical (not nicknames) and language-agnostic -- saved to memory.
- 2026-05-02 -- MainMenuDetector 81.9% -> 95.3% and PostMatchScreenDetector 82.8% -> 99.1%. Both detectors were matching dim-but-correctly-rationed pixels (RGB ~(80, 60, 5) ratios identically to bright menu yellow ~(240, 250, 20)). Added brightness floors (`r+g >= 400` for MainMenu yellow, `>= 280` for PostMatch green). 2 mislabeled "Win Streak Bonus" interlude frames moved from `post_match/` to `_other/` -- they have no visible buttons.
- 2026-05-02 -- ResultScreenDetector to 100%. Switched winner/loser color from gold/silver to **blue/red nameplate** (the gold "WON!" emblem the user mentioned earlier sits above the nameplate, not on it). Tolerance widened to absorb white-text-on-color stddev. 4 mislabeled frames moved: 3 from `post_match/` to `result_screen/` (visually identical to result frames), 2 transition frames to `_other/`.
- 2026-05-02 -- PokeballAliveDetector. C++ class + OcrSuggest dispatch + dashboard reader entry + Pokeballs tab visual-confirm view (`/api/pokeballs/scan` + `views/pokeballs.html`). Three-state classifier (alive / fainted / empty) on mean green: thresholds 150 / 67. Greens read cleanly across 110 frames; runtime context disambiguates fainted vs empty (greens-then-grey = fainted; never-green = empty), so no ground-truth labeling needed. Box anchors saved by user via Inspector; rest linearly extrapolated.
- 2026-05-02 -- BattleHUD own-sprite sanity check. Shiny atlas (Bulbapedia "Champions Shiny menu sprites" -> `PokemonSpritesShiny.{png,json}`, 272 entries, loaded with `-shiny` slug suffix). `--sprite-match` / `--sprite-match-debug` CLI modes (`Tests/SpriteMatch.{h,cpp}`) with bg-paint pre-pass (pill purple + active-turn lime green). Manifests carry `own_species_shiny: [bool, bool]` via `tools/mark_shiny_species.py`. Dashboard Sprites tab "BattleHUD own-species icons" section runs aggregated per-species debug (crop -> auto-crop -> top-3 matches). Team-atlas filter caps candidates to current team's normal/shiny/mega slugs -> 5/6 top-1 on team mons.
- 2026-05-02 -- Team Preview tab split out from Sprites tab into its own lightweight view.
- 2026-05-02 -- Sprites tab: drop "All references" grid, drop My-side panel on locked-in (no own text there), 7x faster examples endpoint. Gate own-side OCR off in `TeamPreviewReader::read` for locked-in.
- 2026-05-01 -- HP digit fixups (7→1, 0-699 clamp, cur≤max), gold/silver result colors, PP in OcrSuggest+manifest (`088b961c9`).
- 2026-05-01 -- Mismatches view: stream rows + progress bar (`4c4c32951`); per-row crop, bulk Accept, j/k/a/s/i nav (`ec26afd65`).
- 2026-04-30 -- TeamPreviewReader dispatches opp boxes by PreparingForBattleDetector (selecting vs locked-in) (`5d9c48b4f`).
- 2026-04-30 -- Sprites tab: My-side species OCR alongside opp matches (`673f382f2`); all labeled team-preview frames (`f175208f5`).
- 2026-04-29 -- Locked-in opp coords re-anchored at slot 0/1/5 (`647e16fb8`); inspector exposes TeamPreviewReader_selecting overlay for tuning (`7459d7d2d`).
- 2026-04-28 -- BattleLogReader tightened x/width (`3295c4181`).
