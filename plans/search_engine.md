# Search/Inference Engine — Implementation Plan

## Overview

Expand the Python FastAPI inference server with a `POST /search` endpoint that does MCTS-style 1-ply search using the action model (v2_seq) + winrate model + a minimal battle simulator. C++ SerialPrograms changes one URL from `/predict` to `/search`.

## Design Decisions

- **Runs in Python inference server** — C++ side just calls a different endpoint
- **MCTS-style sampling** — sample move pairs proportional to action model probabilities
- **1-ply depth** — winrate model captures multi-turn implications already
- **Minimal Python battle sim** — reference Showdown source, covers ~90% of turns
- **Prune to top-3 per slot** — 81 combos max, sampled by probability
- **N=100 rollouts** — ~100ms total latency
- **Opponent unknowns from usage stats** — consistent with how models were trained
- **New `/search` endpoint** — old `/predict` stays as fallback

## Search Flow

1. Run action model (your POV) → probability distributions for your 2 slots
2. Run action model (swapped inputs) → opponent's probability distributions  
3. Sample N=100 rollouts — (your_a, your_b, their_a, their_b) weighted by probs
4. Simulate each turn with battle sim → new board state
5. Batch-evaluate all resulting states with winrate model → win probabilities
6. Aggregate by (your_a, your_b) pair, return pair with highest avg win%

## Files to Create

### 1. `src/vgc_model/sim/__init__.py` (empty)
### 2. `src/vgc_model/sim/type_chart.py`
- Hardcoded 18×18 type effectiveness matrix
- `type_effectiveness(atk_type, def_type1, def_type2) -> float`

### 3. `src/vgc_model/sim/battle_sim.py` (~1500-2500 lines)
Core of the sim. SimPokemon, SimField, SimState dataclasses.

**BattleSim class:**
- `simulate_turn(state, own_actions, opp_actions) -> SimState`
- `_decode_action(idx, pokemon, bench) -> ActionSpec`
- `_resolve_order(state, actions) -> ordered list` (switches first → priority → speed, Trick Room reverses)
- `_execute_move(state, user, move, target)` → apply damage/effects
- `_calc_damage(user, target, move_data, field, is_spread) -> hp_fraction`
- `_execute_switch(state, side, slot_idx, bench_idx)` → swap + reset boosts
- `from_predict_request(req, ft, usage_stats) -> SimState` — convert server format

**v1 scope (essentials):**
- Speed/priority resolution
- Damage calc (base power × level × atk/def × STAB × type effectiveness × weather × terrain × screens × spread × boosts × burn)
- Protect blocking
- Move targeting (single/spread/self/ally)
- Fainting + removal
- Switching (reset boosts)
- Expected damage roll (0.925 average instead of random)

**v2 scope (later):**
- Intimidate, weather-setting abilities
- Life Orb, Focus Sash, berries
- Status damage ticks (burn/poison)
- Stat boost moves (Swords Dance, etc.)
- Secondary effects (flinch, stat drops)
- Recoil/drain

### 4. `src/vgc_model/inference/search.py`
**SearchEngine class:**
- Holds action model (v2_seq), winrate model, vocabs, feature tables, usage stats, BattleSim
- `search(req, n_rollouts=100) -> SearchResult`
- `_build_v2_batch(req, perspective)` — encode game state for v2_seq model, swap own/opp when perspective="opp"
- `_states_to_winrate_batch(states)` — batch-encode N post-sim states for winrate model (one forward pass, not N)

### 5. `src/vgc_model/inference/server.py` (modify existing)
- Load v2_seq + winrate models alongside existing v1
- New `POST /search` endpoint accepting same PredictRequest JSON
- Returns: best actions + win% + opponent predictions + rollout count
- CLI args: `--v2-checkpoint`, `--winrate-checkpoint`

## Latency Budget (~100ms total)
- Action model forward (own): ~10ms
- Action model forward (opp): ~10ms  
- Sampling 100 tuples: <1ms
- Simulating 100 turns: ~50ms
- Winrate model batch forward (100 states): ~30ms
- Aggregation: <1ms

## Implementation Order
1. type_chart.py (zero dependencies)
2. battle_sim.py (depends on type_chart + feature_tables)
3. search.py (depends on battle_sim + models)
4. server.py modifications (ties it all together)
5. C++ client update (optional, for later)

## Data Dependencies
- `data/feature_tables/` — species base stats, move data, type info (must exist)
- `data/checkpoints_v2/best.pt` — trained v2_seq action model
- `data/checkpoints_winrate/best.pt` — trained winrate model
- `data/vocab/` — token vocabularies
- `data/usage_stats/` — opponent set inference

## Key Risks
- **V2 tensor encoding**: `_build_v2_batch()` must match training format exactly (enriched_dataset.py lines 242-496)
- **Perspective swap**: all 8 slots + field sides must be rearranged correctly
- **Sim accuracy**: damage calc must be close enough that winrate model evaluations are meaningful
- **Feature tables**: `data/feature_tables/` may need regenerating via `scripts/build_feature_tables.py`
