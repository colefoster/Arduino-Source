# What's Next

Living doc. Keep it short. When in doubt, move things up or delete, don't expand.

Update protocol: edit in place, no dates on items in Now/Next/Backlog. Add to **Recently shipped** when something lands.

**Theme: close the auto-laddering loop.** All readers/detectors are at 100% on the manifest. LiveDetectorTrace now wires every available signal into `BattleStateTracker`; the remaining work is propagating the same wiring into `AutoLadder`'s per-turn loop and closing action-execution gaps.

---

## Now
*Actively touching this week.*

- **Pull the LiveDetectorTrace wiring into AutoLadder's per-turn loop.** Trace now feeds BattleLogReader, AbilityItemReader, CommunicatingDetector, TeamSelectDetector, TargetSelectDetector + Reader (with dedup on the log/overlay readers). AutoLadder still calls a stripped-down subset; should reuse the same path so `BattleStateTracker.update_from_log()` and ability/item reveals fire mid-match.
- **AbilityItemReader → tracker.** Dashboard surfaces the readout; tracker fields aren't yet written. Need a slug-match against own/opp species to set `m_*_team[i].ability/item`.
- **Pokeball detector → AutoLadder.** Detector + visual confirm shipped, live trace runs it. AutoLadder still doesn't call it per turn / feed `alive[]` into the tracker.
- **opponent_species hybrid dispatch (OCR → sprite-match).** Two failure modes confirmed: JP-language renders JP chars; nicknamed opponents show the nickname, not the species. Manifest is at 100% but only because nicknames aren't represented. Wire dispatch: OCR if ASCII species slug, else fall back to HUD pill atlas sprite-match narrowed to opp_team from Team Preview.

## Next
*Picked, not started.*

- **Doubles target-select execution.** Detector + reader now both wired in the live trace. AutoLadder's `execute_action` (`AutoLadder.cpp:721`) still mashes A; needs to navigate to the chosen target using `TargetSelectDetector::selected_index()`.
- **Plumb `/team-select` into AutoLadder.** Endpoint exists server-side; AutoLadder still uses hardcoded `TEAM_STRATEGY` (first-three / random / last-three). Also: AutoLadder hardcodes 3-of-6, but Champions format is 4-of-6.
- **AutoLadder team-select wait → TeamSelectDetector.** Replace the hardcoded 60s wait at `AutoLadder.cpp:333` (live trace already recognizes `team_select` as a screen).
- **Legal-actions mask** computed client-side from HP / PP / choice-lock / disable, passed in `PredictRequest`. Today the model picks blind and can recommend illegal moves.
- **Mega Evo execution + confirmation.** R-toggle is sent but `is_mega` is never set post-execution; no detector confirms it landed.
- **Switch action space beyond bench slots 0–1.** Actions 12–13 hardcoded; doesn't cover all viable benches.

## Backlog
*Ideas, not committed.*

- **Overlay-based readers as backup for log misses:** StatusOverlayReader (HUD status icons), BoostsReader (stat arrows), WeatherReader, TerrainReader, TrickRoom/Tailwind/Screens detectors. Battle log is primary; these are belt-and-suspenders for OCR-miss frames.
- **Edge-case handling in AutoLadder:** struggle (out of PP), forced switch on faint, opponent forfeit / disconnect, our forfeit, taunt / disable / protect cooldown tracked in `PokemonState`.
- **Inference server schema gaps:** choice-locked move, disable turns, taunt turns, protect-cooldown, opponent move history not in `PokemonState`. Server can't see them; client can't send them.
- **Game time + turn time parsing.** Niche; useful for replay annotation and timeout debugging.
- **HP-bar-color sanity check on max HP** (BattleHUDReader). Cross-check OCR'd max against pixel-level bar-color reading.
- **PP: visual OCR vs DB-tracked.** Currently OCR'd; could be subtracted from move DB on each MOVE_USED event.
- **Break up `BattleHUDReader`?** Drifting toward 8+ sub-readers. Open design Q — when does fan-out beat a single fat reader?
- **Search engine sequence-history encoding.** MCTS 1-ply gave -0.4% lift; bottleneck is missing sequence history per `memory/project_search_engine.md`.
- **Pipeline redesign.** Two-layer hour-bucketed pipeline; sharded_cache + winrate + v2_window slated for deletion (lead model retained). Phased plan in `plans/two-layer-pipeline-and-model-cuts.md`.
- **Lead model: sequence-history token.** Action model got +11.7pt type-acc from `--use-history`; lead is overfit (train 67% / val 50%) and input-side feature engineering is tapped out per `plans/lead_archetype_experiment.md`. History conditioning is the bigger lever.

## Recently shipped
*Last ~2 weeks. Trim aggressively -- this is for context, not history.*

- 2026-05-06 -- LiveDetectorTrace signal-plumbing pass. Wired BattleLogReader (feeds `BattleStateTracker.update_from_log()` for boosts/status/weather/terrain/trick room/switch/faint, with raw-text dedup so each line fires once), AbilityItemReader (overlay reveals, deduped), CommunicatingDetector (overlay co-fire), TeamSelectDetector (new screen slug `team_select`), TargetSelectDetector (new — see below) + TargetSelectReader (`target_select` screen branch).
- 2026-05-06 -- TargetSelectDetector. New detector for the doubles target-select modal; reuses TargetSelectReader's 4 strip boxes verbatim. Strict selected-strip rule (`g >= 220 AND b <= 80`) plus "≥2 saturated strip colors" — handles both 4-strip doubles and 2-strip self-target (Protect) cases. 406/406; 4899/4899 overall.
- 2026-05-06 -- screens.yaml registry corrections. Dropped MegaEvolveDetector from `move_select` (it's a state probe, not a screen classifier — only fires when active mon CAN mega-evolve) and TeamPreviewDetector from `team_preview_locked_in` (covered by PreparingForBattleDetector; locked-in screen lacks the "Select 4 Pokemon..." text the OCR keys on). Both regressions reintroduced when registry was regenerated; now documented inline so future regens don't reintroduce them.
- 2026-05-06 -- Lead model L3: archetype-aware features (per-mon cluster + team-archetype [TEAM] token + opp-conditioned pair bias). +0.30pt lead_top1, +0.38pt lead_top3, -0.018 NLL vs baseline (3 seeds × 10 epochs). Full writeup in `plans/lead_archetype_experiment.md`.
- 2026-05-06 -- HUD Pill Atlas (in-domain sprite atlas, ~95% top-1 vs canonical 22%); audit + Accept-relabel flow at /#/pillatlas; box normalization; uses own_species_icon boxes (not name-text).
- 2026-05-05 -- PokeballAliveDetector 4th state ALIVE_STATUSED (orange ball).
- 2026-05-05 -- Inbox: Accept All button in the Partial section header.
- 2026-05-04 -- TeamSelectDetector to 100% (brightness floor `r+g >= 400` to kill green-flash mid-animation FP).
- 2026-05-04 -- BattleLogReader 100% + full PS-derived event taxonomy (220 patterns / 41 event types from `data/text/default.ts` via `tools/generate_battle_log_patterns.py`). `regex_search` over length-sorted patterns; picks up withdrew, drowsy, confusion, crit, miss, immune, mega, cant, item-transfer, field-effect.
- 2026-05-04 -- PostMatchScreenDetector + MovesMoreDetector + MainMenuDetector to 100% via co-evidence + brightness-floor pattern. All readers + detectors at 100%.
- 2026-05-04 -- BattleHUDReader.own_hp_current/max to 100% via combined "X/Y" crop + digit-confusable pre-pass with sandwich-drop rule.
- 2026-05-03 -- TeamPreviewDetector + BattleHUDReader.opponent_species to 100%.
- 2026-05-02 -- ResultScreenDetector to 100% (blue/red nameplate, not gold/silver emblem).
- 2026-05-02 -- PokeballAliveDetector base implementation: 3-state on mean green.
- 2026-05-01 -- Mismatches view: stream rows, per-row crop, bulk Accept, j/k/a/s/i nav.
