#!/usr/bin/env python3
"""Pre-parse replay JSONs into a sharded tensor cache for fast training startup.

Each shard is a self-contained .pt file with a flat list of encoded samples
plus the replay IDs they came from. A manifest tracks which replays are
covered, so re-running on an updated replay set only encodes the new ones.

Usage:
    # First time, full corpus
    python scripts/preparse_dataset.py --history sequence --min-rating 1200

    # After replay sync (only new replays get encoded)
    python scripts/preparse_dataset.py --history sequence --min-rating 1200

    # Override cache dir explicitly (otherwise auto-named from variant)
    python scripts/preparse_dataset.py --history sequence --min-rating 1200 \
        --cache-dir data/dataset_cache/v2_seq_1200

    # Quick smoke test
    python scripts/preparse_dataset.py --history sequence --min-rating 1200 --limit 500

    # Use 8 worker processes (default 4)
    python scripts/preparse_dataset.py --history sequence --min-rating 1200 --workers 8

The output is consumed by --cache <dir> in train_v2.py and train_winrate.py.
"""

from __future__ import annotations

import argparse
import gc
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CACHE_BASE = DATA_DIR / "dataset_cache"

REPLAY_SEARCH_DIRS = [
    DATA_DIR / "showdown_replays" / "spectated" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "downloaded" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma",
]


def find_replay_files(min_rating: int) -> list[tuple[Path, int]]:
    """Walk replay dirs + their indexes, return (path, rating) for replays >= min_rating."""
    seen: set[str] = set()
    out: list[tuple[Path, int]] = []

    for d in REPLAY_SEARCH_DIRS:
        if not d.exists():
            continue
        ratings: dict[str, int] = {}
        for idx_path in [d / "index.json", d.parent / "index.json"]:
            if idx_path.exists():
                try:
                    idx = json.loads(idx_path.read_text(encoding="utf-8"))
                    for rid, meta in idx.items():
                        r = meta.get("rating") or 0
                        if r:
                            ratings[rid] = r
                except Exception:
                    pass
                break
        for f in d.glob("*.json"):
            if f.name == "index.json" or f.name in seen:
                continue
            seen.add(f.name)
            rating = ratings.get(f.stem, 0)
            if rating >= min_rating:
                out.append((f, rating))
    return out


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

# Worker globals — populated once per process by _worker_init, then reused
# across batches. Avoids re-loading vocabularies + feature tables for each
# batch.
_W_VOCABS = None
_W_FEATURE_TABLES = None
_W_USAGE_STATS = None
_W_PLAYER_PROFILES = None


def _worker_init():
    global _W_VOCABS, _W_FEATURE_TABLES, _W_USAGE_STATS, _W_PLAYER_PROFILES
    from vgc_model.data.vocab import Vocabs
    from vgc_model.data.feature_tables import FeatureTables
    from vgc_model.data.usage_stats import UsageStats
    from vgc_model.data.player_profiles import PlayerProfiles

    _W_VOCABS = Vocabs.load(VOCAB_DIR)
    _W_FEATURE_TABLES = FeatureTables()
    try:
        _W_USAGE_STATS = UsageStats()
    except Exception:
        _W_USAGE_STATS = None
    try:
        _W_PLAYER_PROFILES = PlayerProfiles()
    except Exception:
        _W_PLAYER_PROFILES = None


def _worker_process_batch(args):
    """Encode one batch of replays. Runs in a worker process.

    Args:
        replay_files: list of (Path, int) -- replays + ratings
        history_mode: "single" | "window" | "sequence"
        winner_only: bool

    Returns: (samples, replay_ids) where samples is a list of tensor-dicts.
    """
    replay_files, history_mode, winner_only = args

    from vgc_model.data.enriched_dataset import EnrichedDataset

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Symlink (or copy) replay files into a temp directory and write a minimal
        # index so EnrichedDataset can rate-filter properly.
        for f, _ in replay_files:
            dst = tmpdir / f.name
            try:
                dst.symlink_to(f.resolve())
            except (OSError, NotImplementedError):
                shutil.copy2(f, dst)
        index = {f.stem: {"rating": rating} for f, rating in replay_files if rating}
        (tmpdir / "index.json").write_text(json.dumps(index))

        dataset = EnrichedDataset(
            replay_dir=tmpdir,
            vocabs=_W_VOCABS,
            feature_tables=_W_FEATURE_TABLES,
            usage_stats=_W_USAGE_STATS,
            player_profiles=_W_PLAYER_PROFILES,
            min_rating=0,  # already filtered by caller
            winner_only=winner_only,
            min_turns=3,
            augment=False,  # cache un-augmented; aug happens at training __getitem__
            history_mode=history_mode,
        )

        encoded: list[dict] = []
        n_battle = len(dataset.samples)  # first N indices are battle samples; rest are team_previews
        for i in range(len(dataset)):
            try:
                d = dataset[i]
            except Exception:
                continue
            # win_label: real value for battle samples, 0.0 for team_preview samples
            # (which winrate training filters out via turn > 0).
            if i < n_battle:
                is_winner = dataset.samples[i][0].is_winner
                d["win_label"] = torch.tensor(1.0 if is_winner else 0.0, dtype=torch.float)
            else:
                d["win_label"] = torch.tensor(0.0, dtype=torch.float)
            encoded.append(d)

    replay_ids = [f.stem for f, _ in replay_files]
    return encoded, replay_ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pre-parse replays into sharded tensor cache")
    parser.add_argument("--history", type=str, default="sequence",
                        choices=["single", "window", "sequence"])
    parser.add_argument("--min-rating", type=int, default=1200)
    parser.add_argument("--winner-only", action="store_true",
                        help="Encode only winning-side actions (default: include both players)")
    parser.add_argument("--shard-size", type=int, default=5000,
                        help="Replays per shard (smaller = more shards, more granular incremental updates)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Worker processes for parallel parse+encode (default 4; 0 = serial)")
    parser.add_argument("--limit", type=int, default=0,
                        help="If >0, only process up to N replays (smoke test)")
    parser.add_argument("--cache-dir", type=str, default="",
                        help="Override cache directory (default: data/dataset_cache/<variant_key>)")
    args = parser.parse_args()

    from vgc_model.data.sharded_cache import (
        ShardedCacheManifest, write_shard, find_uncovered_replays, variant_key,
    )

    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
    else:
        cache_dir = CACHE_BASE / variant_key(args.history, args.min_rating, args.winner_only)
    cache_dir.mkdir(parents=True, exist_ok=True)

    manifest = ShardedCacheManifest(cache_dir)
    if not manifest.shards:
        manifest.init_variant(args.history, args.min_rating, args.winner_only)
    else:
        manifest.validate_variant(args.history, args.min_rating, args.winner_only)

    print(f"Cache dir:   {cache_dir}")
    print(f"Variant:     history={args.history} min_rating={args.min_rating} winner_only={args.winner_only}")
    print(f"Existing:    {len(manifest.shards)} shards, {manifest.total_samples()} samples, "
          f"{len(manifest.covered_replay_ids())} replays covered")

    print(f"\nFinding replay files (min_rating={args.min_rating})...")
    all_files = find_replay_files(args.min_rating)
    print(f"Found {len(all_files)} candidate replays")

    # Skip already-encoded
    todo = find_uncovered_replays(all_files, manifest)
    print(f"To encode:   {len(todo)} new replays")

    if args.limit and len(todo) > args.limit:
        todo = todo[:args.limit]
        print(f"--limit:     truncated to {len(todo)} replays")

    if not todo:
        print("\nNothing to do — cache is up to date.")
        return

    # Split into batches
    batches = [todo[i:i + args.shard_size] for i in range(0, len(todo), args.shard_size)]
    print(f"Split into {len(batches)} batches of up to {args.shard_size} replays\n")

    t_total = time.time()
    new_samples = 0

    if args.workers > 0:
        # Parallel: each worker handles one batch at a time. Workers init their
        # own resources once; main writes shards as results come back so the cache
        # is usable mid-flight if the run is interrupted.
        with mp.Pool(processes=args.workers, initializer=_worker_init) as pool:
            tasks = [(batch, args.history, args.winner_only) for batch in batches]
            for i, (samples, replay_ids) in enumerate(
                pool.imap_unordered(_worker_process_batch, tasks)
            ):
                t0 = time.time()
                fname = write_shard(cache_dir, samples, replay_ids, args.history)
                manifest.add_shard(fname, replay_ids, len(samples))
                new_samples += len(samples)
                wallclock_pct = 100 * (i + 1) / len(batches)
                elapsed = time.time() - t_total
                rate = new_samples / max(elapsed, 1)
                print(
                    f"[{i + 1:>3}/{len(batches)}  {wallclock_pct:5.1f}%]  "
                    f"shard={fname}  samples={len(samples):>5}  "
                    f"replays={len(replay_ids):>5}  "
                    f"total={new_samples:>7}  "
                    f"rate={rate:>5.0f} samples/s  "
                    f"write={time.time() - t0:.1f}s"
                )
    else:
        # Serial fallback (no multiprocessing) — useful for debugging
        _worker_init()
        for i, batch in enumerate(batches):
            t0 = time.time()
            samples, replay_ids = _worker_process_batch((batch, args.history, args.winner_only))
            fname = write_shard(cache_dir, samples, replay_ids, args.history)
            manifest.add_shard(fname, replay_ids, len(samples))
            new_samples += len(samples)
            print(
                f"[{i + 1:>3}/{len(batches)}]  shard={fname}  "
                f"samples={len(samples):>5}  replays={len(replay_ids):>5}  "
                f"elapsed={time.time() - t0:.1f}s"
            )
            gc.collect()

    elapsed_total = time.time() - t_total
    print(f"\nDone. Encoded {new_samples} new samples in {elapsed_total / 60:.1f} min.")
    print(f"Cache now: {len(manifest.shards)} shards, {manifest.total_samples()} samples.")
    print(f"\nUse with: --cache {cache_dir}")


if __name__ == "__main__":
    main()
