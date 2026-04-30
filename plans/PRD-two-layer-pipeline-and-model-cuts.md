## Problem Statement

The current VGC battle data pipeline has accreted into a maze of ad-hoc patches:

- **Adding new replay data triggers a 2-hour preparse**, blocking experiments.
- The latest cache layer (sharded, lazy-loading) was the third rebuild in a month and **brought training to a standstill** (~58 min/epoch, GPU 0–15% utilization) after a stack of bandaids.
- **Slot-swap augmentation** runs per-sample on CPU with ~40 `tensor.clone()` calls, starving the GPU. The model is small (962K params) so the GPU finishes its work in microseconds and waits.
- **Three datasets (`EnrichedDataset`, `LeadDataset`, `WinrateDataset`)**, **six models**, and **four training loops** with 80% duplication.
- The same `_swap_slots` augmentation logic is **duplicated in three files**.
- ash spectator dumps **525k JSON files into a single flat directory**, which broke `_find_replay_dir` and slowed sync.
- Hidden-info inference relies on a `player_history` cheat (aggregating prior battles by player name) that doesn't reflect how a real player thinks, was added because Pikalytics has long-tail gaps, and adds complexity.

We don't have a coherent design for either the parsing pipeline or the model lineup. Ad-hoc adjustments meant to speed things up have made training slower and the codebase harder to reason about.

## Solution

Redesign the data pipeline as **two clean cache layers aligned with hour-bucketed replay storage**, cut unused models, and move augmentation off the per-sample CPU hot path.

**Pipeline shape:**

```
ash:    replays/<format>/YYYY-MM-DD/HH/*.json    (hour-bucketed, ash stays dumb)
        ↓ rsync hourly to unraid
unraid: replays/...
        ↓ parse  → parsed/<format>/YYYY-MM-DD/HH.parquet      (Layer 1 — schema-stable)
        ↓ encode → encoded/<format>/v<N>/<mode>/YYYY-MM-DD/HH.pt  (Layer 2 — versioned)
        ↓ train action model (GPU-side slot-swap augmentation)
```

**Key properties:**

- **Adding new replays = parsing + encoding only the new buckets.** No 2-hour preparse.
- **Encoding-version bumps re-run Layer 2 only** (Layer 1 stays).
- **Encoder mode** (`meta-on` vs `meta-off`) is part of the path: enables training two model variants on the same Layer 1 data — one informed by usage stats, one purely observation-based.
- **Pluggable `UsageStatsSource` interface** lets us swap stats sources without touching the parsing or encoding code; same interface used by the live-inference encoder for deployment.
- **Augmentation moves to a single vectorized GPU op** post-collate. ~1000× faster than per-sample CPU clones.
- **Replay end timestamp** (`|t:|`) determines which hour bucket a replay lands in — temporally honest, supports out-of-order arrivals.

**Cuts:**

- Delete lead model (`lead_model.py`, `train_lead.py`, `lead_dataset.py`).
- Delete winrate models (`winrate_model.py`, `winrate_model_seq.py`, `train_winrate.py`, `winrate_dataset.py`).
- Delete `vgc_model_v2_window.py` (3-turn fixed window — superseded by full LSTM).
- Delete the parse-on-fly path in `EnrichedDataset`. Training only reads from `encoded/`.
- Delete `player_profiles.py` and the `player_history` confidence source.
- Consolidate from **3 datasets → 1**, **6 models → 3** (v2 baseline, v2_seq, plus a small action head), **4 training loops → 1**.

## User Stories

1. As a model developer, I want adding 1000 new replays to take seconds, so that I can iterate on data quality without waiting 2 hours.
2. As a model developer, I want changing a model feature (e.g. adding a new state input) to re-run only the encoding step, so that I don't re-pay the parsing cost.
3. As a model developer, I want a single training entry point with a clear `--encoded` flag, so that I don't have to remember which of four scripts handles which model.
4. As a model developer, I want my GPU to be ≥60% utilized during training, so that compute time isn't wasted on CPU-bound augmentation.
5. As a model developer, I want to train two variants of the action model (meta-aware and meta-blind) on the same parsed data, so that I can compare how much usage-stats knowledge helps.
6. As an operator, I want ash to stay a "dumb" replay writer with no Python ML stack on it, so that ash is robust and decoupled from training-side code changes.
7. As an operator, I want unraid to run parse + encode + train in one container, so that there's a single canonical training rig.
8. As an operator, I want hourly buckets parsed by a cron at :15, so that data flows from spectator to encoded shards without manual intervention.
9. As an operator, I want a corrupt replay to log to a sidecar file and not block the rest of the bucket, so that one bad input doesn't taint a whole hour.
10. As an operator, I want a one-time CLI to migrate the existing 525k replays into the new bucketed layout, so that the rollover is a single command.
11. As an operator, I want ash's storage cleaned up to ~24 hours of replays after migration, so that ash isn't holding the whole archive.
12. As an analyst, I want Pikalytics stats re-scraped every ~3 days, so that the meta signal stays fresh in a brand-new format.
13. As an analyst, I want a fallback to replay-corpus-derived stats for species Pikalytics misses, so that long-tail species still get a reasonable guess.
14. As a future deployer, I want the same encoder code path used in training and in live inference (with a different `UsageStatsSource` plugged in), so that the deployment-time encoder is exercised by the training pipeline.
15. As a developer, I want to filter encoded shards by `--min-rating` and `--since <date>`, so that training runs can target a slice of the data without rebuilding the cache.
16. As a developer, I want the `_swap_slots` augmentation logic to live in exactly one place, so that there are no "remember to update three files" bugs.
17. As a developer, I want failed replays to be logged with their replay_id and error message, so that I can investigate parser regressions.
18. As a developer, I want each Layer 1 row to record which `stats_source_id` produced its meta guesses, so that I can audit and selectively re-parse if a stats source changes.
19. As a developer, I want old encoding-version directories to remain on disk until I manually delete them, so that an in-progress training run can resume safely after a version bump.
20. As a developer, I want the parsed parquet schema to be stable and human-readable (one row per replay, nested arrays of turns), so that I can inspect data with pandas or parquet-tools without writing code.
21. As a developer, I want the training loop, encoder, and parser each to be testable in isolation against fixture inputs, so that regressions are caught at the unit level.
22. As a developer, I want all model-tuning floats (confidence weights, etc.) to live in Layer 2, so that re-tuning never requires re-parsing.

## Implementation Decisions

### Architecture

- **Two-layer cache**: Layer 1 (`parsed/`) is schema-stable and survives encoding-version bumps. Layer 2 (`encoded/`) is regeneration-cheap and depends on the current model code.
- **Encoding version + mode in path**: `encoded/<format>/v<N>/<mode>/<YYYY-MM-DD>/<HH>.pt`. Old versions stay on disk until manually pruned.
- **Hour-bucketed dirs at every layer**, keyed off the replay's `|t:|` end timestamp. Out-of-order arrivals (e.g. a downloaded backlog from a week ago) land in old buckets; the parse cron picks them up next run.

### Modules

**Deep (encapsulate complexity, stable interfaces):**

- **`UsageStatsSource`**: interface with methods like `lookup_item(species) -> {value, prob}`, `lookup_ability(species) -> {value, prob}`, `lookup_moves(species, n) -> [{value, prob}]`, `coverage_score(species) -> float`. Pikalytics implementation built first; replay-corpus implementation deferred until measured gaps justify it. Multi-source chain (try Pikalytics first, fall back to replay-corpus) is a thin composite wrapper conforming to the same interface.
- **`ReplayParser`**: pure function. `parse(replay_json, stats_source) -> ParsedReplay`. Encapsulates the existing two-pass enriched parser logic. No I/O. No globals.
- **`Encoder`**: `encode(parsed_replay, mode) -> tensors`. `mode` is `"meta-on"` or `"meta-off"` (zeros out non-revealed slots). No state across calls.
- **`GpuSlotSwap`**: post-collate vectorized augmentation. `swap(batch_dict, swap_mask) -> batch_dict`. Single GPU op set; replaces the per-sample CPU clone-spam in three files.

**Shallow (orchestration, change-y):**

- **`ReplayBucketWriter`** (on ash): writes finished spectated replays into `replays/<format>/YYYY-MM-DD/HH/<id>.json` based on `|t:|`.
- **`ReplaySync`**: rsync wrapper (ash → unraid), idempotent, logs new buckets.
- **`ParseRunner`**: per-bucket orchestration. Reads a bucket's JSON files, runs `ReplayParser`, writes `<HH>.parquet`. Logs failures to `failed/<HH>.errors.jsonl`. Idempotent (skip if `<HH>.parquet` exists and is newer than all inputs).
- **`EncodeRunner`**: per-bucket orchestration. Reads parsed parquet, runs `Encoder` for the configured mode, writes encoded shard. Idempotent.
- **`TrainingDataset`**: reads encoded shards under `encoded/<format>/<version>/<mode>/`, applies `--min-rating` / `--since` filters at row level, yields tensors. Lazy if needed (one shard at a time), but single-process if it fits in RAM.
- **`PikalyticsScraper`**: cron-driven refresh, every ~3 days initially, configurable.
- **`MigrationCLI`**: one-time backfill. Reads all 525k replays from ash + ColePC (treat ash as truth, ignore ColePC overlap), buckets by `|t:|`, writes to unraid's `replays/<format>/YYYY-MM-DD/HH/`.
- **`train.py`** (new, consolidated): single entry point replacing `train_v2.py`, `train_winrate.py`, `train_lead.py`, `train.py`.

### Layer 1 Schema (parsed parquet)

**One row per replay, nested arrays of turns.** Approximate columns (final names TBD during implementation):

- Header: `replay_id`, `format`, `bucket_hour`, `replay_end_ts`, `p1_player`, `p2_player`, `p1_rating`, `p2_rating`, `winner`.
- `p1_team`, `p2_team`: list of 6 Pokémon as nested structs (species, gender, level, tera_type, plus revealed item/ability/moves observed during the game — NOT post-game ground truth, which doesn't exist in Showdown replays).
- `turns`: list of Turn structs. Each Turn has:
  - `turn_num`, `weather`, `terrain`, `megas_used`, `hazards`.
  - `p1_state`, `p2_state`: per-player view (active, bench, opponent_revealed). For each Pokémon in `opponent_revealed`, item/ability/moves are stored as `{value, source_type, prob, stats_source_id}` where `source_type ∈ {"revealed", "meta"}`. No `"unknown"` source — meta always provides a guess (real players always have an opinion).
  - `p1_action`, `p2_action`: structured action `{type, slot, move, target, switch_to, team_order}`.
- The "final revealed state" is implicitly the last turn's state — not stored separately. Compute on demand if needed.

### Layer 2 Schema (encoded .pt)

- Same tensor structure as today's `EnrichedDataset.__getitem__` output, except:
  - No augmentation baked in (augmentation is GPU-side at training time).
  - Confidence floats produced from Layer 1's `prob` field via the encoder's mapping.
- One `.pt` per hour bucket. Each contains the list of (replay, turn, player) samples flattened.

### `UsageStatsSource` interface

- `lookup_item(species) -> {value, prob}` — most-common item and its frequency.
- `lookup_ability(species) -> {value, prob}`.
- `lookup_moves(species, n=4) -> list[{value, prob}]` — top-n moves.
- `coverage_score(species) -> float` — how confident we are in this species' stats. Used for fallback chaining.
- Implementations: `PikalyticsStatsSource` (now), `ReplayCorpusStatsSource` (deferred), `MultiSourceStatsSource` (chain).
- `stats_source_id` is recorded per-row in Layer 1 for auditability.

### Training entry point

- Single `train.py`.
- Flags: `--encoded <path>`, `--mode <meta-on|meta-off>` (or implicit from path), `--model <v2|v2_seq>`, `--min-rating <int>`, `--since <YYYY-MM-DD>` (defaults to all), standard hyperparameter flags.
- Reads encoded shards, builds `TrainingDataset`, creates `DataLoader` with `num_workers > 0` and `GpuSlotSwap` applied post-collate.
- Action model heads: action policy (the centerpiece). Lead/team selection and winrate heads are removed; can be re-added as additional heads when needed.

### Operational

- **Cron**: parse + encode runs every hour at :15 on unraid, idempotent.
- **Pikalytics scrape**: every 3 days initially. Configurable.
- **Failure isolation**: corrupt JSON → `failed/<HH>.errors.jsonl`, parse continues.
- **Encoding-version cutover**: new version is a new directory; old version stays for resumes; manual deletion when no resumes pending.
- **Migration**: CLI on unraid, one-shot, run today (after this PRD lands).
- **ash cleanup**: post-migration, ash retains only ~24 hours of replays.

### Scope of Cuts (consolidated)

Files to delete:
- `src/vgc_model/model/lead_model.py`, `winrate_model.py`, `winrate_model_seq.py`, `vgc_model_v2_window.py`, `vgc_model.py` (v1).
- `src/vgc_model/training/train.py` (v1, dead), `train_lead.py`, `train_winrate.py`.
- `src/vgc_model/data/lead_dataset.py`, `winrate_dataset.py`, `dataset.py` (v1), `player_profiles.py`.
- `src/vgc_model/data/sharded_cache.py` (replaced by encoded-shard reader).
- `src/vgc_model/lead_advisor.py`.
- The parse-on-fly path inside `EnrichedDataset` (the file may stay temporarily but its CachedDataset path goes away).

## Testing Decisions

**Test the deep modules; skip the orchestration layer.**

A good test in this codebase: takes a small frozen input fixture, calls a single deep-module function, asserts on the shape and key values of the output. No mocking of external services; no testing of glue.

| Module | Test approach | Prior art |
|---|---|---|
| `PikalyticsStatsSource` | Frozen JSON fixture from a known scrape; assert lookups return expected `(value, prob)` pairs. | `data/usage_stats/gen9championsvgc2026regma.json` is already a fixture-shaped file. |
| `ReplayParser` | A few hand-picked replay JSONs as fixtures; assert the parsed parquet row matches a golden expected struct (round-trip via pandas). Cover: known-good battle, battle with mega evolution, battle with switch + move on same turn, battle with no rating. | Existing parsing tests in `enriched_parser` if any; otherwise this is new. |
| `Encoder` | Take a known parsed replay, encode in `meta-on` and `meta-off` modes, assert tensor shapes and a few specific cell values (e.g. that `meta-off` produces zeros where revealed-only mode should). | None directly — new. |
| `GpuSlotSwap` | Construct a tiny known batch, apply the swap with all-True mask, assert slot[0] and slot[1] are exchanged for every relevant tensor; apply again and assert idempotent (back to original). | None directly — new. |

Skipped:
- Orchestration runners (`ParseRunner`, `EncodeRunner`, `ReplaySync`): too much I/O wiring; tested by E2E smoke runs.
- `train.py`: covered by a smoke run that trains for one batch and asserts the loss is a finite scalar.
- `MigrationCLI`: one-shot, test by running it with a small subset of replays and inspecting the output dir.

## Out of Scope

- **Lead model and winrate model rebuilds**: deleted in this PRD; if/when needed later, they come back as additional heads on the consolidated training pipeline. Not blocking action-model improvements.
- **Auxiliary task: predicting hidden info**: depended on having ground truth, which Showdown replays don't provide. Not feasible.
- **Calibration metrics ("how often is our meta guess right?")**: same — depends on ground truth we don't have. Could be done via "how often does our turn-N guess match what's revealed by turn-end," but that's a Phase-2 nice-to-have.
- **Replay-corpus-derived `UsageStatsSource`**: deferred unless we measure that Pikalytics gaps are hurting model accuracy.
- **Champions-game `UsageStatsSource`**: doesn't exist yet; the interface is in place for when it does.
- **Deeper retention policy** (auto-pruning old encoding versions, archiving replays after N days): manual for now.
- **Multi-format support for non-VGC formats**: the directory layout supports it (`replays/<format>/...`), but we're only training on `gen9championsvgc2026regma`.
- **Smogon monthly snapshots**: doesn't exist yet for this format. Will be added when Smogon publishes.

## Further Notes

- **Migration to run today**: the user has approved running the one-time backfill on unraid as soon as the modules are ready.
- **ash storage cleanup**: post-migration, ash should retain only ~24 hours of replays. Older ones live on unraid only.
- **`encoding_version` numbering starts at v3** (since v1 = original `EnrichedDataset` parse-on-fly path, v2 = sharded cache; both being retired).
- **Pikalytics current snapshot is from Apr 24**; first task in implementation is to re-scrape and verify the scraper works as a one-shot before wiring up the cron.
- **The `UsageStatsSource` interface is the load-bearing abstraction**: it's shared between Layer 1 parsing and the eventual live-inference encoder. Getting it right pays back forever.
- **Parquet was chosen over JSONL** for Layer 1: ~5–10× compression, columnar filter pushdown for `min_rating`, stable schema as a feature.
- **One row per replay** (rather than per training-example) was chosen for compactness and to make replay-level filters cheap.
- **Phased rollout suggested via `/mp-prd-to-plan`**: tracer-bullet slices likely look like (1) ash hour-bucketed writer + migration CLI, (2) `UsageStatsSource` interface + Pikalytics re-scrape, (3) `ReplayParser` + `ParseRunner` + Layer 1 cron, (4) `Encoder` + `EncodeRunner` + Layer 2 cron, (5) consolidated `train.py` + `GpuSlotSwap`, (6) cuts (delete dead model/dataset/training files).
