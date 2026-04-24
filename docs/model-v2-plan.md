# Model V2: Enriched Features + Player-POV Training

**Status: DESIGN ONLY — nothing implemented yet.**

This is a ground-up rebuild of the training pipeline and model architecture.
The v1 model and weights are not reusable — the input representation is
fundamentally different. Train from scratch on the same replay corpus with
the new pipeline.

## Problem Statement

The current model trains on spectator-POV battle logs where:
- Each Pokemon is a single learned embedding (species=64d, moves=32d, items=24d, abilities=24d)
- No explicit knowledge of types, base stats, move properties, or matchups
- Own-team info is incomplete — moves/items/abilities only known as revealed during the game
- No distinction between own team and opponent team in terms of information availability
- From spectated logs: only 43% of moves, 37% of items, 16% of abilities are ever revealed

## Design Overview

### 1. Single-Player Perspective

Each training sample is from **one player's POV**, simulating a real battle:

- **Own team**: species always known (team preview), moves/items/abilities filled via progressive enrichment
- **Opponent team**: species known (team preview), moves/items/abilities start as `<UNK>`, revealed turn-by-turn
- **Experimental variant**: opponent also gets usage-stat inference, to compare performance

### 2. Progressive Information Revelation

Both sides update as the game progresses. Each move/item/ability slot carries a **confidence flag**:

| Tier | Source | Flag value |
|------|--------|------------|
| **Known** | Revealed in this game's log | 1.0 |
| **Player-inferred** | Same player's other recent games | 0.8 |
| **Population-inferred** | Usage stats for this species | 0.5 |
| **Unknown** | Not yet revealed, no inference | 0.0 (`<UNK>` token) |

**Own team at turn 0**: species known, moves/items/abilities filled from player profile → usage stats (confidence 0.5-0.8). As moves fire, flags flip to 1.0 and inferred values are replaced with ground truth.

**Opponent team at turn 0**: species from preview, everything else `<UNK>` (confidence 0.0). Updates as revealed in-game.

### 3. Explicit Feature Encoding

Replace pure learned embeddings with **learned embedding + explicit property vectors**.

#### Species (currently: 64d embedding only)

Add ~25 explicit features from PS pokedex data:

| Feature | Type | Dims |
|---------|------|------|
| Base stats (hp, atk, def, spa, spd, spe) | Normalized floats | 6 |
| Type 1 | One-hot (18 types) | 18 |
| Type 2 | One-hot (18 types, zeros if mono-type) | 18 |
| Weight (kg) | Normalized float | 1 |
| BST (base stat total) | Normalized float | 1 |
| Is fully evolved | Binary | 1 |

Total: **~45d explicit** + existing learned embedding

Source: `https://play.pokemonshowdown.com/data/pokedex.json`

#### Moves (currently: 32d embedding only)

Add ~25 explicit features from PS moves data:

| Feature | Type | Dims |
|---------|------|------|
| Base power | Normalized float | 1 |
| Accuracy | Normalized float (100=bypass) | 1 |
| Priority | Normalized int (-7 to +5) | 1 |
| Type | One-hot (18 types) | 18 |
| Category | One-hot (Physical/Special/Status) | 3 |
| Target | One-hot (single/spread/self/ally/allAdjFoes) | 5 |
| Contact flag | Binary | 1 |
| Sound flag | Binary | 1 |
| Has secondary effect | Binary | 1 |
| Secondary chance | Normalized float | 1 |
| Secondary flinch | Binary | 1 |
| Secondary status | One-hot (brn/par/slp/frz/psn/tox) | 6 |
| Drain fraction | Float | 1 |
| Recoil fraction | Float | 1 |
| Self-switch (pivot) | Binary | 1 |
| Force-switch (phaze) | Binary | 1 |
| Stalling move (Protect) | Binary | 1 |
| Sets weather | Binary | 1 |
| Sets terrain | Binary | 1 |
| Sets side condition | Binary | 1 |
| Confidence flag | Float (0.0-1.0) | 1 |

Total: **~48d explicit** + existing learned embedding

Source: `https://play.pokemonshowdown.com/data/moves.json`

#### Items (currently: 24d embedding only)

PS item data is sparse — hand-built categories needed:

| Feature | Type | Dims |
|---------|------|------|
| Category | One-hot (berry, choice, mega stone, focus sash, recovery, boost, misc) | 7 |
| Is berry | Binary | 1 |
| Is choice-locking | Binary | 1 |
| Is mega stone | Binary | 1 |
| Confidence flag | Float (0.0-1.0) | 1 |

Total: **~11d explicit** + existing learned embedding

Source: `https://play.pokemonshowdown.com/data/items.json` + hand-built taxonomy

#### Abilities (currently: 24d embedding only)

PS ability data has almost no structured fields — hand-built categories needed:

| Feature | Type | Dims |
|---------|------|------|
| PS rating | Normalized float (0-5) | 1 |
| Category | One-hot (weather-setter, terrain-setter, intimidate-like, stat-boost-on-switch, contact-punish, immunity, mold-breaker-like, misc) | 8 |
| Breakable (by Mold Breaker) | Binary | 1 |
| Confidence flag | Float (0.0-1.0) | 1 |

Total: **~11d explicit** + existing learned embedding

Source: `https://play.pokemonshowdown.com/data/abilities.json` + hand-built taxonomy

### 4. Cross-Game Player Profiling

Build player-specific team profiles by linking replays from the same player:

- Index replays by player name
- For each player, accumulate species → {moves, items, abilities} across games
- Weight recent games higher than older ones
- Use player profile to backfill own-team unknowns (confidence 0.8) before falling back to population usage stats (confidence 0.5)

**Coverage improvement** (from analysis of 30k replays):

| Metric | Single game | Multi-game combined |
|--------|-------------|---------------------|
| Moves per Pokemon | 1.93/4 (48%) | 3.00/4 (75%) |
| Full moveset found | 5.4% | 45.6% |

**Limitations:**
- 50% of players appear only once (no multi-game benefit)
- ~48% of repeat players switch teams frequently (Jaccard < 0.5)
- Diminishing returns past ~10 games; 4th move often never used

### 5. Usage Stats

Build per-species move/item/ability frequency distributions from our own 75k+ replay dataset.

From 30k replay sample, we have 251 unique species with rich data:
- Top moves per species with frequency counts
- Top items per species with frequency counts
- Top abilities per species with frequency counts

Used as the **population-level fallback** (confidence 0.5) when player profile data isn't available.

## Data Flow

```
Raw replay JSON
    │
    ├─► Full-log scan (pass 1): extract all revealed moves/items/abilities per Pokemon
    │
    ├─► Player profile lookup: cross-reference with same player's other games
    │
    ├─► Usage stats lookup: fill remaining unknowns with population frequencies
    │
    ├─► Per-turn sample generation (pass 2):
    │       Own team: fully populated (known + inferred), confidence flags set
    │       Opponent: progressive revelation, <UNK> for unrevealed
    │
    ├─► Property encoding: species/move/item/ability → embedding + explicit features
    │
    └─► Training sample with confidence-annotated, property-rich features
```

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| PS data fetch (pokedex, moves, items, abilities) | Done | `scripts/fetch_ps_data.py` |
| Feature tables (property vectors) | Done | `scripts/build_feature_tables.py`, `src/vgc_model/data/feature_tables.py` |
| Item/ability hand-built taxonomies | Done | Built into `build_feature_tables.py` |
| Usage stats (Pikalytics + replays) | Done | `scripts/build_usage_stats.py`, `src/vgc_model/data/usage_stats.py` |
| Player profiles | Done | `scripts/build_player_profiles.py`, `src/vgc_model/data/player_profiles.py` |
| Enriched two-pass parser | Done | `src/vgc_model/data/enriched_parser.py` |
| Progressive revelation + confidence flags | Done | EnrichedPokemon dataclass with per-slot confidence |
| Dataset encoding (explicit features) | Done | `src/vgc_model/data/enriched_dataset.py` |
| Model architecture (expanded encoders) | Done | `src/vgc_model/model/vgc_model_v2.py` (822k params, +13% from v1) |
| Training script | Done | `src/vgc_model/training/train_v2.py` |
| Build data on ash (usage stats, player profiles, feature tables) | Not started | Run build scripts on ash |
| Train v2 model | Not started | Run train_v2.py on ColePC (GPU) |
| `reconstruct_teams.py` | Exists | Measures coverage only, superseded by enriched parser |

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `data/ps_data/pokedex.json` | Create | Fetched from PS, species properties |
| `data/ps_data/moves.json` | Create | Fetched from PS, move properties |
| `data/ps_data/items.json` | Create | Fetched from PS, item properties |
| `data/ps_data/abilities.json` | Create | Fetched from PS, ability properties |
| `data/usage_stats/*.json` | Create | Per-species distributions from our replays |
| `data/player_profiles/*.json` | Create | Per-player team history |
| `scripts/build_usage_stats.py` | Create | Generate usage stats from replay corpus |
| `scripts/build_player_profiles.py` | Create | Index replays by player, build profiles |
| `scripts/fetch_ps_data.py` | Create | Download + clean PS data files |
| `scripts/build_feature_tables.py` | Create | Convert PS JSON → model-ready lookup tables |
| `src/vgc_model/data/feature_tables.py` | Create | Load + lookup species/move/item/ability properties |
| `src/vgc_model/data/enriched_parser.py` | Create | Two-pass parser with player profiles + usage stats |
| `src/vgc_model/data/dataset.py` | Modify | New encoding with explicit features + confidence flags |
| `src/vgc_model/data/vocab.py` | Modify | Ensure `<UNK>` handling for unrevealed info |
| `src/vgc_model/model/vgc_model.py` | Modify | Expanded PokemonEncoder with property inputs |
