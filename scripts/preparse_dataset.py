#!/usr/bin/env python3
"""Pre-parse replay JSONs into cached tensor datasets for fast training startup.

Processes replays in batches to stay within memory limits (safe for 4GB VPS).
Saves encoded tensor dicts to a single .pt file that CachedDataset loads instantly.

Usage:
    python scripts/preparse_dataset.py                              # default
    python scripts/preparse_dataset.py --history sequence            # for v2_seq
    python scripts/preparse_dataset.py --min-rating 1200
    python scripts/preparse_dataset.py --batch-size 500              # smaller batches for low RAM
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CACHE_DIR = DATA_DIR / "dataset_cache"

REPLAY_SEARCH_DIRS = [
    DATA_DIR / "showdown_replays" / "spectated" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "downloaded" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma",
]


def find_replay_files(min_rating: int) -> list[tuple[Path, int]]:
    """Find all replay files across search directories with ratings."""
    seen = set()
    result = []

    for d in REPLAY_SEARCH_DIRS:
        if not d.exists():
            continue

        # Load ratings index if available
        ratings = {}
        for idx_path in [d / "index.json", d.parent / "index.json"]:
            if idx_path.exists():
                try:
                    idx = json.loads(idx_path.read_text())
                    for rid, meta in idx.items():
                        r = meta.get("rating", 0)
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
                result.append((f, rating))

    return result


def process_batch(
    replay_files: list[tuple[Path, int]],
    vocabs, feature_tables, usage_stats, player_profiles,
    history_mode: str,
) -> list[dict[str, torch.Tensor]]:
    """Parse and encode a batch of replays. Returns list of tensor dicts."""
    from vgc_model.data.enriched_dataset import EnrichedDataset

    # Create a temporary directory-like structure for EnrichedDataset
    # We'll write the batch files to a temp dir
    import tempfile
    import shutil

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Symlink or copy replay files into temp dir
        for f, rating in replay_files:
            dst = tmpdir / f.name
            try:
                dst.symlink_to(f)
            except (OSError, NotImplementedError):
                shutil.copy2(f, dst)

        # Create a minimal index.json with ratings
        index = {}
        for f, rating in replay_files:
            if rating:
                index[f.stem] = {"rating": rating}
        (tmpdir / "index.json").write_text(json.dumps(index))

        # Parse this batch
        dataset = EnrichedDataset(
            replay_dir=tmpdir,
            vocabs=vocabs,
            feature_tables=feature_tables,
            usage_stats=usage_stats,
            player_profiles=player_profiles,
            min_rating=0,  # already filtered
            winner_only=True,
            min_turns=3,
            augment=False,
            history_mode=history_mode,
        )

        # Encode all samples
        encoded = []
        for i in range(len(dataset)):
            try:
                encoded.append(dataset[i])
            except Exception:
                continue

    return encoded


def main():
    parser = argparse.ArgumentParser(description="Pre-parse replays into cached tensor dataset")
    parser.add_argument("--history", type=str, default="sequence",
                        choices=["single", "window", "sequence"])
    parser.add_argument("--min-rating", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Replays per batch (lower = less RAM)")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"dataset_{args.history}_r{args.min_rating}.pt"

    # Load resources (these stay in memory — they're small)
    print("Loading vocabularies...")
    from vgc_model.data.vocab import Vocabs
    from vgc_model.data.feature_tables import FeatureTables
    from vgc_model.data.usage_stats import UsageStats
    from vgc_model.data.player_profiles import PlayerProfiles

    vocabs = Vocabs.load(VOCAB_DIR)

    print("Loading feature tables...")
    feature_tables = FeatureTables()

    usage_stats = None
    try:
        usage_stats = UsageStats()
        print(f"Loaded usage stats: {len(usage_stats.species_list)} species")
    except Exception as e:
        print(f"Usage stats not available: {e}")

    player_profiles = None
    try:
        player_profiles = PlayerProfiles()
        print(f"Loaded player profiles: {player_profiles}")
    except Exception as e:
        print(f"Player profiles not available: {e}")

    # Find replay files
    print(f"Finding replay files (min_rating={args.min_rating})...")
    replay_files = find_replay_files(args.min_rating)
    print(f"Found {len(replay_files)} replay files")

    if not replay_files:
        print("No replay files found.")
        return

    # Process in batches
    all_encoded = []
    total_batches = (len(replay_files) + args.batch_size - 1) // args.batch_size
    t0 = time.time()

    for batch_idx in range(total_batches):
        start = batch_idx * args.batch_size
        end = min(start + args.batch_size, len(replay_files))
        batch = replay_files[start:end]

        print(f"\nBatch {batch_idx + 1}/{total_batches}: "
              f"replays {start + 1}-{end} ({len(batch)} files)...")

        try:
            encoded = process_batch(
                batch, vocabs, feature_tables, usage_stats, player_profiles,
                args.history,
            )
            all_encoded.extend(encoded)
            print(f"  → {len(encoded)} samples ({len(all_encoded)} total)")
        except Exception as e:
            print(f"  → Error: {e}")

        # Force garbage collection between batches
        gc.collect()

    parse_time = time.time() - t0
    print(f"\nParsed {len(all_encoded)} samples from {len(replay_files)} replays "
          f"in {parse_time:.1f}s")

    if not all_encoded:
        print("No samples encoded. Check replay data.")
        return

    # Save cache
    print(f"Saving cache to {cache_file}...")
    t0 = time.time()
    torch.save({
        "samples": all_encoded,
        "history_mode": args.history,
        "min_rating": args.min_rating,
        "num_replays": len(replay_files),
        "num_samples": len(all_encoded),
        "created": time.time(),
    }, cache_file)

    # Save manifest
    manifest_file = CACHE_DIR / f"{cache_file.stem}_manifest.json"
    manifest = {
        "parsed_files": [f.name for f, _ in replay_files],
        "history_mode": args.history,
        "min_rating": args.min_rating,
        "num_samples": len(all_encoded),
        "num_replays": len(replay_files),
        "created": time.time(),
        "parse_time_sec": parse_time,
        "batch_size": args.batch_size,
    }
    manifest_file.write_text(json.dumps(manifest, indent=2))

    save_time = time.time() - t0
    file_size_mb = cache_file.stat().st_size / 1024 / 1024
    print(f"Saved in {save_time:.1f}s ({file_size_mb:.1f} MB)")
    print(f"\nDone! Use with: --cache {cache_file}")


if __name__ == "__main__":
    main()
