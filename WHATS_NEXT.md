# What's Next

Living doc. Keep it short. When in doubt, move things up or delete, don't expand.

Update protocol: edit in place, no dates on items in Now/Next/Backlog. Add to **Recently shipped** when something lands.

**Theme: close the auto-laddering loop.** All readers/detectors are at 100% on the manifest. The remaining work is plumbing those signals into `BattleStateTracker` and closing action-execution gaps in `AutoLadder`. See gap analysis: AutoLadder ~40% end-to-end; biggest single win is wiring BattleLogReader.

---

## Now
*Actively touching this week.*

- **Wire BattleLogReader → BattleStateTracker.update_from_log()** in the per-turn loop. `LiveDetectorTrace.cpp:172` notes it's built but not wired. Unlocks boosts, status, weather, terrain, trick room, tailwind, screens, switch events, mega flag, item/ability reveals — everything `/predict` currently receives as zeros.
- **Pokeball detector live integration.** Detector + visual confirm shipped; still need to call it per turn from AutoLadder and feed `alive[]` into the tracker. Runtime carries forward "was alive at start" so fainted-vs-empty resolves itself.

## Next
*Picked, not started.*

- **Target-select detection + execution for doubles.** `AutoLadder.cpp:721` TODO. Need TargetSelectDetector wired to the loop, and execute_action to navigate to the chosen target instead of mashing A.
- **Plumb `/team-select` into AutoLadder.** Endpoint exists server-side; AutoLadder still uses hardcoded `TEAM_STRATEGY` (first-three / random / last-three). Also: AutoLadder hardcodes 3-of-6, but Champions format is 4-of-6.
- **TeamSelectScreenDetector.** Replace the hardcoded 60s wait at `AutoLadder.cpp:333`.
- **Legal-actions mask** computed client-side from HP / PP / choice-lock / disable, passed in `PredictRequest`. Today the model picks blind and can recommend illegal moves.
- **Mega Evo execution + confirmation.** R-toggle is sent but `is_mega` is never set post-execution; no detector confirms it landed.
- **Switch action space beyond bench slots 0–1.** Actions 12–13 hardcoded; doesn't cover all viable benches.

## Backlog
*Ideas, not committed.*

- **Overlay-based readers as backup for log misses:** StatusOverlayReader (HUD status icons), BoostsReader (stat arrows), WeatherReader, TerrainReader, TrickRoom/Tailwind/Screens detectors. Battle log is primary; these are belt-and-suspenders for OCR-miss frames.
- **Edge-case handling in AutoLadder:** struggle (out of PP), forced switch on faint, opponent forfeit / disconnect, our forfeit, taunt / disable / protect cooldown tracked in `PokemonState`.
- **Inference server schema gaps:** choice-locked move, disable turns, taunt turns, protect-cooldown, opponent move history not in `PokemonState`. Server can't see them; client can't send them.
- **AbilityRevealReader / ItemRevealReader.** Today reveals come only via battle log; an overlay reader would catch the "Garchomp's Sand Veil!" bubble directly.
- **Game time + turn time parsing.** Niche; useful for replay annotation and timeout debugging.
- **HP-bar-color sanity check on max HP** (BattleHUDReader). Cross-check OCR'd max against pixel-level bar-color reading.
- **PP: visual OCR vs DB-tracked.** Currently OCR'd; could be subtracted from move DB on each MOVE_USED event.
- **Break up `BattleHUDReader`?** Drifting toward 8+ sub-readers. Open design Q — when does fan-out beat a single fat reader?
- **Search engine sequence-history encoding.** MCTS 1-ply gave -0.4% lift; bottleneck is missing sequence history per `memory/project_search_engine.md`.
- **Pipeline redesign.** Two-layer hour-bucketed pipeline; sharded_cache + lead/winrate/v2_window slated for deletion. Phased plan in `plans/two-layer-pipeline-and-model-cuts.md`.

## Recently shipped
*Last ~2 weeks. Trim aggressively -- this is for context, not history.*

- 2026-05-06 -- HUD Pill Atlas (in-domain sprite atlas, ~95% top-1 vs canonical 22%); audit + Accept-relabel flow at /#/pillatlas; box normalization; uses own_species_icon boxes (not name-text).
- 2026-05-05 -- PokeballAliveDetector 4th state ALIVE_STATUSED (orange ball).
- 2026-05-05 -- Inbox: Accept All button in the Partial section header.
- 2026-05-04 -- TeamSelectDetector to 100% (brightness floor `r+g >= 400` to kill green-flash mid-animation FP).
- 2026-05-04 -- BattleLogReader 100% + full PS-derived event taxonomy (220 patterns / 41 event types from `data/text/default.ts` via `tools/generate_battle_log_patterns.py`). `regex_search` over length-sorted patterns; picks up withdrew, drowsy, confusion, crit, miss, immune, mega, cant, item-transfer, field-effect.
- 2026-05-04 -- PostMatchScreenDetector + MovesMoreDetector + MainMenuDetector to 100% via co-evidence + brightness-floor pattern (same shape as TeamSelect fix). All readers + detectors now at 100%; manifest regression 2543/2543.
- 2026-05-04 -- BattleHUDReader.own_hp_current/max to 100% via combined "X/Y" crop + digit-confusable pre-pass with sandwich-drop rule for segmentation noise.
- 2026-05-03 -- TeamPreviewDetector + BattleHUDReader.opponent_species to 100% (mostly mislabel cleanup; opp species cards confirmed canonical English, language-agnostic).
- 2026-05-02 -- ResultScreenDetector to 100% (blue/red nameplate, not gold/silver emblem).
- 2026-05-02 -- PokeballAliveDetector base implementation: 3-state (alive/fainted/empty) on mean green; box anchors via Inspector.
- 2026-05-02 -- BattleHUD own-sprite sanity check (Shiny atlas, team-atlas filter, 5/6 top-1). Sprites tab + Team Preview tab split.
- 2026-05-01 -- Mismatches view: stream rows, per-row crop, bulk Accept, j/k/a/s/i nav.
