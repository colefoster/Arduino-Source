# Encoding Tier 1: Move features + species features + action masking

## Why

Last training experiment (`scale_probe_d320_l8`) showed scaling the
transformer (d 192→320, layers 6→8) bought only **−0.03 val_loss / +1.85pp
full-action**, vs the LSTM-history lever which bought **−1.0 val_loss / +20.6pp**.
Conclusion: model capacity isn't the bottleneck — encoding is.

The current `ActionModel` represents each move and species as a single
embedding indexed by ID. The model has to memorize that "Earthquake is a
ground-type 100-BP physical move that hits both adjacent foes" from raw
win/loss signal alone — for ~700 moves and ~1000 species. `FeatureTables`
already exists in `src/vgc_model/data/feature_tables.py` (built for the
older `vgc_model_v2.py`) but is **not wired into the new pipeline**.

## What ships in Phase 1 (this session)

Three changes to `ActionModel`, all gated behind a new `--use-features` flag
so we can ablate cleanly. **No re-encoding of shards required** — features are
indexed by IDs that already live in the encoded `.pt` files.

1. **Species features** (45-D from `_species_to_tensor`): 6 base stats
   normalized, type1 + type2 one-hot, weight, BST, fully-evolved/mega flags.
   Projected to `d_model` and added to the species embedding.

2. **Move features** (48-D from `_move_to_tensor`): base power, accuracy,
   priority, type one-hot, category, target type, contact/sound flags,
   secondary chance/flinch/status, drain/recoil, side-effect tags. Projected
   to `d_model` and added to the move embedding.

3. **Action masking** at logits: `head_move_a/b` outputs over the full
   ~700-move vocab, but only 4 moves are legal for the active slot. Same
   problem on `head_switch_a/b` — only alive bench species are legal switch
   targets. We mask non-legal logits to `-inf` at train + val. Free
   correctness — removes label noise on the move-pick task.

## Run plan

| field | value |
|---|---|
| run_id | `tier1_features_d192_l6` |
| model | d=192, layers=6 (same as `overnight_meta_off_history`) |
| flags | `--version v4 --mode meta-off --min-rating 1200 --use-history --use-features` |
| epochs | 60 |
| host | unraid GPU container |

The d=192/l=6 size matches the prior baseline so the comparison is clean: any
delta vs `overnight_meta_off_history` is attributable to the encoding changes.

## Success criteria

- **Stretch:** −0.1+ val_loss, +5pp on `val_full_a_acc` vs `overnight_meta_off_history`.
- **Pass:** any positive delta. Confirms encoding is the lever, justifies Phase 2.
- **Fail (revisit thesis):** flat or worse. Suggests the move/species embeddings
  had already learned what the features encode, and the bottleneck is elsewhere
  (data, history representation, or genuinely capacity).

## Phases 2+ (not this session)

- **Phase 2:** Item & ability features (already in `FeatureTables`). Cheap follow-up.
- **Phase 3:** Stat boosts + volatile statuses (Encore, Substitute HP,
  Choice-locked move, Taunt counter). **Requires parser changes** —
  `enriched_parser.py` doesn't track these today. Probably the biggest single
  remaining lever after Phase 1.
- **Phase 4:** Field state beyond bool — Tailwind / Trick Room / screen / hazard
  turn counters. Parser changes needed.
- **Phase 5:** Damage matrix per turn — precompute expected damage % for every
  (attacker, move, defender) pair using the existing `BattleSim`. Concatenate as
  64 floats per sample. Likely the biggest lift on `move_a` / `target_a` heads.
- **Phase 6:** Replace LSTM history with attention over per-turn tokens.

Each phase gets one isolated run vs the prior best so the lever is measurable.
