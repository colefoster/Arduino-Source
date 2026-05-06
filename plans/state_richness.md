# State Richness — closing the encoder gap

## Premise

Our action model currently sees ~3 field bits + species/HP/status/item/ability/moves
per slot. It is **blind to**: stat boost stages, side conditions (tailwind,
screens, hazards), volatile statuses (taunt, encore, helping hand, protect,
substitute, …), residual effects (wish, future sight), and last-used-move.

Reference design: [pmariglia/poke-engine](https://github.com/pmariglia/poke-engine)
encodes a comprehensive state including **108 volatile statuses**, 20
side-condition counters, 7 stat boosts, and a stack of residuals. Used by
foul-play (a competitive Showdown AI) for state-search.

Goal: close the gap by feeding the model a vector representation that
reflects the *actual* battle state, not just the visible Pokemon.

---

## Current state — three-layer survey

### Parser (log_parser.py / enriched_parser.py)

**Tracked:**
- Per-Pokemon: species, hp, max_hp, status (`brn/par/slp/frz/psn/tox`),
  **boosts (dict, all 7 stats)**, item, ability, moves_known, mega, fainted,
  gender, level
- Field: weather, terrain, trick_room
- Per-side: tailwind, light_screen, reflect, **aurora_veil** (boolean,
  no duration)

**Not tracked:**
- All entry hazards (Stealth Rock, Spikes, Toxic Spikes, Sticky Web)
- Per-side: Mist, Safeguard, Lucky Chant, Crafty Shield, Wide/Quick Guard,
  Mat Block, Healing Wish, Lunar Dance
- Toxic counter (turn count for Toxic damage scaling)
- All 108 volatile statuses
- Substitute health
- Last used move (per side)
- Wish, Future Sight pending hits
- Perish Song counter
- Side-condition durations (booleans only, can't tell "tailwind ends in 2 turns")

### Parsed parquets

Whatever the parser emits goes through to the parquet. Boost dict and
field booleans are present.

### Encoder (encoder.py)

**Encodes:** `species_ids, hp_values, status_ids, alive_flags, item_ids,
ability_ids, move_ids, weather_id, terrain_id, trick_room` + the action
labels.

**Drops on the floor (in parser but not in encoder):**
- The **boosts dict** for every Pokemon
- The **per-side tailwind/screens/aurora_veil** flags

This is the easiest immediate win: encoder change only, no parser work.

---

## Plan — three tiers, each ablatable

### Tier 1: encode what the parser already has (cheapest)

**Added inputs:**
- Per-slot 7-D stat-boost vector (atk, def, spa, spd, spe, acc, eva), each
  in [-6, +6] → normalize to [-1, +1] floats.
- Per-side 4-D side-condition vector (tailwind, light_screen, reflect,
  aurora_veil) → 0/1 for now (durations not parser-tracked).

**Encoder changes:**
- Add `stat_boosts: (8, 7) float32` shard column.
- Add `side_conditions: (2, 4) float32` shard column.

**Model wiring:**
- Per-slot: `slot = slot + boost_proj(boost_vec)` where `boost_proj` is
  `Linear(7, d_model)`. Folds into existing slot embedding.
- Per-side: project `(2, 4)` to 2 d-vectors and add to the field token (or
  to the slot tokens of the matching side).

**New CLI flag:** `--use-state-rich` (gated, off by default until validated).

**Decision matrix vs current champion (combo d=256/l=10, 1.5960):**
- < 1.55: huge — these were carrying real signal.
- 1.55–1.59: solid lever, ~half a combo.
- 1.59–1.60: marginal, but cheap so keep it on.
- > 1.60: regression, debug data flow first.

**Effort:** ~2h plumbing + ~5h training. New encoded shards needed (call
the version `v6_<date>` once we ship).

### Tier 2: extend the parser, add hazards + side condition durations

**Parser additions (log_parser + enriched_parser):**
- `-sidestart`/`-sideend` for **Stealth Rock, Spikes (1–3 stacks),
  Toxic Spikes (1–2 stacks), Sticky Web, Mist, Safeguard, Lucky Chant,
  Crafty Shield**
- Track **layers** for Spikes/Toxic Spikes (parser sees `spikes`,
  `spikes 2`, `spikes 3` over the same -sidestart command).
- Convert tailwind/screens/aurora_veil from bool to **i8 turn counter**
  (matches poke-engine). Decrement each turn end; reset when re-applied.

**Encoder additions:**
- Per-side hazard vector: `(2, 4)` for {SR present, Spike layers, Toxic
  Spike layers, Sticky Web present}. SR/Sticky Web are 0/1; Spikes is
  0/1/2/3; ToxSpikes is 0/1/2.
- Per-side condition durations: `(2, 7)` for {tailwind, lightscreen,
  reflect, aurora_veil, mist, safeguard, lucky_chant} as turn counters.

**Decision matrix vs Tier 1:**
- < combined Tier 1 by ≥0.01: hazards/durations carry independent signal.
- ~ Tier 1: redundant. Drop the addition, simpler is fine.

**Effort:** ~1 day parser work + tests, then re-encode + retrain.

### Tier 3: full volatile-status coverage

This is the big one — all 108 PokemonVolatileStatus values from poke-engine.

**Parser additions:**
- Capture every `-start`, `-end`, `-status`, `-curestatus`, `-volatile`,
  `-singleturn`, `-singlemove`, `-mustrecharge`, `-fieldstart`,
  `-activate` event that sets/clears a volatile.
- Map Showdown event names to the canonical 108-value enum (mirror
  poke-engine's `PokemonVolatileStatus`).
- Add `volatile_statuses: set[str]` to the per-Pokemon dataclass.
- Add `substitute_health: int = 0` — track from `-start ... Substitute`
  events plus damage events that hit the sub.
- Add `last_used_move: str = ""` per side.
- Add `volatile_status_durations: dict[str, int]` for statuses that have
  duration semantics (Encore, Disable, Taunt, Confusion, Yawn, Perish*,
  protect-failure-counter).

**Encoder additions:**
- Per-slot 108-D volatile-status bitmask (bool float32).
- Per-slot scalar: substitute_health (0 if no sub, else hp fraction).
- Per-side: last_used_move_id (already an ID in our move vocab).
- Per-slot 8-D durations vector (only the high-signal duration-bearing
  statuses; rest are 0/1 in the bitmask).

**Model wiring:**
- Per-slot: `slot = slot + volatiles_proj(bitmask) + sub_proj(sub_hp_scalar)`.
- Per-side: append `last_used_move_emb(...)` projection to field token.

**Decision matrix vs Tier 2:**
- < 1.50: home run, fully closes the encoder gap.
- 1.50–1.55: strong, real signal.
- 1.55–combo: marginal (108 features may be too sparse — most volatiles
  rare). Consider top-N most common only.
- > combo: regression — likely a parser bug or a mismatched index.

**Effort:** 2–3 days. Parser is the long pole — need to enumerate every
Showdown protocol event that maps to a volatile and verify against game
logs.

---

## Order of operations

1. **Tier 1 first.** Cheapest, encoder-only, validates the basic
   "richer state helps" hypothesis. If Tier 1 is flat, Tier 2/3 are
   probably also flat — pivot to a different lever (e.g. behavioral
   cloning targets, search-aware training, more data).
2. **Tier 2 second.** Adds hazards + durations once T1 lands.
3. **Tier 3 last.** Highest implementation cost; only do it if T1+T2
   together gave clear lift, justifying the parser overhaul.

Stack ablations: each tier should be ablatable independently (separate
CLI flags `--use-boosts`, `--use-side-cond`, `--use-volatile`) so we can
attribute gains.

---

## Compatibility / corpus snapshot

Each tier requires a **new encoded-shard schema** because the column
specs change. Cut a fresh corpus snapshot for each tier:
- `v6_TIER1_<date>` — boosts + side flags
- `v7_TIER2_<date>` — adds hazards + durations
- `v8_TIER3_<date>` — adds volatiles + sub_hp + last_used_move

Old shards stay around as stable baselines.

When training, the model's `--state-rich` knob must match the shard's
schema. Don't load a v6 shard with a v8-trained model (or vice versa).

---

## Open questions / risks

1. **Boosts at decision-time vs end-of-turn.** Showdown emits boosts
   mid-turn; we encode **at the start of each turn**. Need to confirm
   the parser dataclass holds the *pre-decision* state at sample time.
2. **108 volatiles is sparse.** Most statuses appear in <1% of decisions.
   Consider an embedding lookup per status (treat the bitmask as a
   multi-hot, project to d_model) instead of a 108→d_model linear (fewer
   dead weights).
3. **Showdown-side parsing fragility.** Many volatiles trigger via
   `-activate` or `-singleturn`/`-singlemove` with no explicit `-start`.
   Will need a comprehensive map of Showdown event → volatile.
4. **Parser regression risk.** Adding state to the parser changes
   parquet schema. Re-parse all 291k+ replays from scratch — that's the
   long pole on Tier 2/3.
