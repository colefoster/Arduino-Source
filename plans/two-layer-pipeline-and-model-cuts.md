# Plan: Two-layer hour-bucketed data pipeline + model lineup cuts

> Source PRD: `plans/PRD-two-layer-pipeline-and-model-cuts.md`

## Architectural decisions

Durable decisions that apply across all phases. Reference these from any phase.

- **Hour-bucketed dirs at every layer**, keyed off the replay's `|t:|` end timestamp.
  - `replays/<format>/YYYY-MM-DD/HH/<replay_id>.json` (ash + unraid mirror)
  - `parsed/<format>/YYYY-MM-DD/HH.parquet` (unraid)
  - `encoded/<format>/v<N>/<mode>/YYYY-MM-DD/HH.pt` (unraid)
- **Encoding-version + mode in path**: a new model encoding bumps the `v<N>` segment; meta-aware vs meta-blind training are sibling `<mode>` subdirs (`meta-on`, `meta-off`). Old version dirs stay until manually pruned.
- **Layer 1 schema**: parquet, **one row per replay**, nested arrays of turns. Hidden-info fields stored as `{value, source_type, prob, stats_source_id}` where `source_type ∈ {"revealed", "meta"}` (no `"unknown"` source). Schema-stable across encoding bumps.
- **Layer 2 schema**: `.pt` per hour bucket, list of flattened `(replay, turn, player)` samples. No augmentation baked in.
- **`UsageStatsSource` interface** is the load-bearing abstraction:
  - `lookup_item(species) -> {value, prob}`
  - `lookup_ability(species) -> {value, prob}`
  - `lookup_moves(species, n=4) -> [{value, prob}]`
  - `coverage_score(species) -> float`
  - Same interface used by Layer 1 parsing AND eventual live-inference encoder.
- **Pipeline locality**: ash is a dumb writer. Parse + encode + train all on unraid.
- **Idempotency at every runner**: re-running a parse or encode on the same bucket is a no-op if outputs are newer than inputs. Failed replays go to `failed/<HH>.errors.jsonl`, parsing of the rest of the bucket continues.
- **Cron timing**: parse + encode at `:15` past every hour. Pikalytics scrape every ~3 days.
- **Single training entry point**: new `train.py` replaces `train_v2.py`, `train_winrate.py`, `train_lead.py`, `train.py(v1)`. Reads encoded shards via `--encoded`, filters via `--min-rating` and `--since`.
- **Augmentation**: single vectorized GPU op post-collate. Lives in exactly one place.

---

## Phase 1: Replay storage migration

**User stories**: 6, 8, 10, 11

### What to build

A vertical slice that gets the new bucketed layout into reality, end to end:

- ash writes new spectated replays into hour-bucketed dirs (instead of the flat dir).
- A one-shot CLI on unraid backfills all 525k existing replays into the new layout, bucketed by their `|t:|` end timestamp. Treats ash as the source of truth; ColePC's archive is not consulted.
- A small rsync wrapper pulls new buckets from ash to unraid, idempotently.
- After migration, ash's flat replay dir is cleared; ash retains only ~24 hours of replays going forward.

The dashboard's existing replay-sync trigger is updated to use the new bucketed rsync path.

### Acceptance criteria

- [ ] ash writes today's new replays into `replays/<format>/YYYY-MM-DD/HH/<replay_id>.json`
- [ ] Migration CLI on unraid completes in one shot, bucketing all ~525k existing replays
- [ ] A spot-check confirms: a replay with `|t:|<unix>` lands in the bucket whose hour matches that timestamp (UTC)
- [ ] `replays/` total size and file counts match expectations (per-bucket counts roughly proportional to ELO-sliced spectator coverage)
- [ ] rsync pulls a freshly-spectated replay from ash to unraid in <60 seconds end-to-end
- [ ] ash's old flat replay dir is empty after migration
- [ ] Existing training still works (still using legacy data path; nothing reads from `replays/` yet — Phase 1 only changes storage layout)

---

## Phase 2: `UsageStatsSource` interface + fresh Pikalytics scrape + cron

**User stories**: 12, 14, 18

### What to build

The pluggable stats abstraction, plus a fresh data snapshot:

- Define the `UsageStatsSource` interface (lookup_item/ability/moves, coverage_score).
- Refactor the existing `usage_stats.py` to expose a `PikalyticsStatsSource` implementation behind the interface. No change to its underlying data.
- Add a Pikalytics scraper that produces the JSON file the implementation reads. Run it once today to replace the Apr 24 snapshot with fresh data.
- Wire a cron (every ~3 days) on unraid to re-scrape Pikalytics.
- Each lookup result includes a `stats_source_id` (e.g. `"pikalytics-2026-04-30"`) that downstream callers can record.

This phase produces a tested, swappable stats provider but no other component uses it yet.

### Acceptance criteria

- [ ] `UsageStatsSource` interface defined with the four methods listed in architectural decisions
- [ ] `PikalyticsStatsSource` is a conforming implementation
- [ ] Unit tests pass against a frozen JSON fixture: known species return expected `(value, prob)` pairs for items, abilities, and moves
- [ ] A fresh Pikalytics scrape has run today; the file's modified-date is today and includes species not in the Apr 24 snapshot (or has higher sample sizes)
- [ ] Cron is scheduled and idempotent (running it twice in a row produces the same output, doesn't double-write)
- [ ] `lookup_item("Aegislash")` returns `{value: "<top item>", prob: <float in 0..1>, stats_source_id: "pikalytics-YYYY-MM-DD"}`

---

## Phase 3: Layer 1 — `ReplayParser` + `ParseRunner` + hourly cron + initial backfill

**User stories**: 1, 9, 17, 18, 20, 21, 22

### What to build

The first cache layer, end to end:

- `ReplayParser` is a pure function: replay JSON + `UsageStatsSource` → `ParsedReplay`. Encapsulates the existing two-pass enriched parse logic. No I/O, no globals.
- `ParsedReplay` serializes to one parquet row with the schema in the architectural decisions section.
- `ParseRunner` is the bucket-level orchestrator: reads `replays/<fmt>/YYYY-MM-DD/HH/`, runs `ReplayParser` on each, writes `parsed/<fmt>/YYYY-MM-DD/HH.parquet`. Failed replays log to `failed/<fmt>/YYYY-MM-DD/HH.errors.jsonl` with `replay_id` + error. Skipping is idempotent (parsed mtime newer than newest input → skip).
- A one-shot run of `ParseRunner` over every existing bucket builds the initial Layer 1.
- Cron at `:15` runs `ParseRunner` going forward.

After this phase, every replay is mirrored as a parquet row. Encoder is not yet built.

### Acceptance criteria

- [ ] `ReplayParser` unit tests pass against ≥3 fixture replays (golden parquet output): a clean battle, a battle with mega evolution, a battle with switch + move on the same turn
- [ ] `ParseRunner` is idempotent: running on the same bucket twice produces no new writes the second time
- [ ] Failed replays land in `failed/.../<HH>.errors.jsonl`, with `replay_id` and exception message; the parsed parquet is still produced for the rest of the bucket
- [ ] Initial backfill produces a parsed parquet for every populated hour bucket
- [ ] `pandas.read_parquet("parsed/.../HH.parquet")` loads a DataFrame with one row per replay; `df.explode("turns")` produces (replay, turn) rows
- [ ] Hourly cron is scheduled on unraid, runs at `:15`, idempotent
- [ ] `stats_source_id` is recorded on every meta-source row

---

## Phase 4: Layer 2 — `Encoder` (both modes) + `EncodeRunner` + versioned cutover

**User stories**: 2, 5, 19

### What to build

The second cache layer, with the encoding-mode split as a first-class feature:

- `Encoder` takes a `ParsedReplay` + `mode` → flat list of per-decision tensor dicts. `mode ∈ {"meta-on", "meta-off"}`. `meta-off` zeros out non-revealed slots; `meta-on` uses `prob` as the confidence for those slots.
- `EncodeRunner` is the bucket-level orchestrator: reads parsed parquet, runs `Encoder` for each configured mode, writes `encoded/<fmt>/v3/<mode>/YYYY-MM-DD/HH.pt`. Idempotent.
- `v3` is the first new encoding version (v1 = original on-the-fly, v2 = sharded cache, both retired).
- Initial backfill produces `v3/meta-on` and `v3/meta-off` shards for every parsed bucket.
- Cron extends to also run `EncodeRunner` after `ParseRunner` at `:15`.
- `train_v2.py` (still alive) gets a small adapter so it can read `encoded/<fmt>/v3/meta-on/` to validate the format. **No** training cutover yet.

After this phase, training shards exist in both modes. The new trainer is built in Phase 5.

### Acceptance criteria

- [ ] `Encoder` unit tests pass: a known parsed replay encoded with `meta-on` and `meta-off` produces tensors with expected shapes and key values (specifically: `meta-off` produces zero confidences where revealed-only mode should)
- [ ] `EncodeRunner` is idempotent (same as ParseRunner)
- [ ] Initial backfill produces both `meta-on` and `meta-off` shard sets for every parsed bucket
- [ ] Existing `train_v2.py` can load a `v3/meta-on` shard via a temporary adapter, produce a batch, run forward+backward without errors
- [ ] Hourly cron extension runs encode after parse, idempotent
- [ ] Versioned-path cutover policy documented: bumping to v4 is a new directory; v3 stays until manually pruned

---

## Phase 5: Consolidated `train.py` + `GpuSlotSwap` + first measured run

**User stories**: 3, 4, 5, 15, 16, 21

### What to build

The new training entry point that closes out the standstill:

- New `train.py` replaces `train_v2.py`, `train_winrate.py`, `train_lead.py`. Single entry point. Reads `encoded/<fmt>/<version>/<mode>/` shards, applies `--min-rating` and `--since <YYYY-MM-DD>` filters at row level.
- `GpuSlotSwap` is a single vectorized op that runs **post-collate, on-device**. Replaces all per-sample CPU `_swap_slots` logic. Lives in exactly one place.
- `TrainingDataset` reads encoded shards, exposes them via standard `DataLoader` with `num_workers > 0` and `persistent_workers=True`.
- A first end-to-end measured run on the new pipeline: train one epoch on `v3/meta-on` with ≥1200 min-rating, record GPU utilization and per-epoch wall time.
- A second measured run on `v3/meta-off` for comparison (no need to train fully — just one epoch to verify the path works).
- `train_v2.py`'s temporary adapter (from Phase 4) gets removed; legacy training paths are not deleted yet (Phase 6).

After this phase, the standstill is over and `train.py` is the only path being used.

### Acceptance criteria

- [ ] `GpuSlotSwap` unit test: a tiny known batch with all-True swap mask produces correctly-exchanged slot[0]/slot[1] tensors; double-swap is idempotent
- [ ] `train.py` runs end-to-end on `v3/meta-on` data, produces a checkpoint, dashboard records training progress
- [ ] Measured GPU utilization during steady-state training is ≥60% (vs. previous 0–15%)
- [ ] Measured per-epoch wall time is materially under 58 minutes — target ≤15 minutes per epoch on unraid for the meta-on full-data run, but the binding criterion is "GPU is no longer the bottleneck"
- [ ] `--since 2026-03-01` filter excludes earlier replays (verify by row count)
- [ ] `meta-off` mode: one-epoch run completes successfully on `v3/meta-off`, validating the second-model path
- [ ] No occurrence of `_swap_slots` outside the single `GpuSlotSwap` module

---

## Phase 6: Cleanup — delete dead model/dataset/training files + ash retention

**User stories**: 7, 11 (plus implicit collapse from "many things" to "one thing")

### What to build

The cuts. Everything has been replaced; now delete the predecessors.

- Delete: `lead_model.py`, `train_lead.py`, `lead_dataset.py`, `lead_advisor.py`.
- Delete: `winrate_model.py`, `winrate_model_seq.py`, `train_winrate.py`, `winrate_dataset.py`.
- Delete: `vgc_model_v2_window.py`, `vgc_model.py` (v1).
- Delete: `train.py` (v1, dead), `train_v2.py`.
- Delete: `dataset.py` (v1), `player_profiles.py`, the `player_history` confidence source, `sharded_cache.py`.
- Delete: parse-on-fly path inside `EnrichedDataset` (the file may shrink to nothing — remove if so).
- Update any straggler imports / dashboard references.
- ash retention: post-migration, ash retains only ~24 hours of replays. Add a small cleanup script (cron daily on ash) that prunes the bucketed dirs older than 24h.

### Acceptance criteria

- [ ] Listed files are deleted; `git grep` confirms no remaining imports
- [ ] Repository tree under `src/vgc_model/` is visibly smaller
- [ ] Existing tests pass; smoke training run on `train.py` still works
- [ ] ash daily cleanup cron prunes `replays/<format>/<date>/<HH>/` dirs older than 24h
- [ ] Dashboard's training tab still groups by model variant (v2 baseline, v2_seq) without referencing deleted models
- [ ] No test or runtime importer of `player_profiles`, `lead_*`, `winrate_*`, `*_v2_window`, `sharded_cache` remains

---

## Out-of-plan items (deferred from PRD)

These are explicitly **not** phases. Pull into a Phase 7+ later if needed:

- Replay-corpus-derived `UsageStatsSource` (only if measured Pikalytics gaps hurt accuracy)
- Calibration metrics ("how often does our turn-N meta guess match what's revealed by turn-end?")
- Auxiliary task: predicting hidden info from earlier turns (limited by lack of ground truth)
- Champions-game `UsageStatsSource` (waits on the data existing)
- Smogon monthly snapshot source (waits on Smogon publishing)
- Auto-pruning old encoding versions
- Multi-format support beyond `gen9championsvgc2026regma`
