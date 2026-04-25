#!/usr/bin/env python3
"""Pre-parse replay JSONs into cached tensor datasets for fast training startup.

Runs the full enriched parsing pipeline (two-pass parser, player profiles,
usage stats, feature tables, history chains) and saves encoded tensor dicts
to a single .pt file. Subsequent training runs load the cache in seconds
instead of re-parsing 80k+ JSON files.

Supports incremental updates: tracks which replay files have been parsed,
only processes new ones on subsequent runs.

Usage:
    python scripts/preparse_dataset.py                              # default
    python scripts/preparse_dataset.py --history sequence            # for v2_seq
    python scripts/preparse_dataset.py --history window              # for v2_window
    python scripts/preparse_dataset.py --min-rating 1200
    python scripts/preparse_dataset.py --force                       # re-parse everything
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch
from vgc_model.data.enriched_dataset import EnrichedDataset
from vgc_model.data.feature_tables import FeatureTables
from vgc_model.data.usage_stats import UsageStats
from vgc_model.data.player_profiles import PlayerProfiles
from vgc_model.data.vocab import Vocabs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CACHE_DIR = DATA_DIR / "dataset_cache"

REPLAY_SEARCH_DIRS = [
    DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "spectated" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "downloaded" / "gen9championsvgc2026regma",
]


def find_replay_dir() -> Path:
    for d in REPLAY_SEARCH_DIRS:
        if d.exists() and any(d.glob("*.json")):
            return d
    return REPLAY_SEARCH_DIRS[0]


def cache_filename(history_mode: str, min_rating: int) -> str:
    return f"dataset_{history_mode}_r{min_rating}.pt"


def main():
    parser = argparse.ArgumentParser(description="Pre-parse replays into cached tensor dataset")
    parser.add_argument("--history", type=str, default="sequence",
                        choices=["single", "window", "sequence"])
    parser.add_argument("--min-rating", type=int, default=0)
    parser.add_argument("--replay-dir", type=str, default="")
    parser.add_argument("--force", action="store_true", help="Re-parse everything, ignore cache")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / cache_filename(args.history, args.min_rating)
    manifest_file = CACHE_DIR / f"{cache_file.stem}_manifest.json"

    # Load resources
    print("Loading vocabularies...")
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

    replay_dir = Path(args.replay_dir) if args.replay_dir else find_replay_dir()
    print(f"Replay directory: {replay_dir}")

    # Check existing cache
    existing_files = set()
    if not args.force and manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())
        existing_files = set(manifest.get("parsed_files", []))
        print(f"Existing cache: {len(existing_files)} files already parsed")

    # Count available replays
    all_replay_files = [f.name for f in replay_dir.glob("*.json") if f.name != "index.json"]
    new_files = [f for f in all_replay_files if f not in existing_files]

    if not new_files and not args.force:
        print(f"Cache is up to date ({len(existing_files)} files). Use --force to re-parse.")
        return

    print(f"Total replay files: {len(all_replay_files)}")
    print(f"New files to parse: {len(new_files)}" if not args.force else "Force re-parsing all")

    # Parse the full dataset
    print(f"\nParsing dataset (history_mode={args.history}, min_rating={args.min_rating})...")
    t0 = time.time()

    dataset = EnrichedDataset(
        replay_dir=replay_dir,
        vocabs=vocabs,
        feature_tables=feature_tables,
        usage_stats=usage_stats,
        player_profiles=player_profiles,
        min_rating=args.min_rating,
        winner_only=True,
        min_turns=3,
        augment=False,  # no augmentation for cache — applied at training time
        history_mode=args.history,
    )

    parse_time = time.time() - t0
    print(f"Parsed in {parse_time:.1f}s: {len(dataset)} samples "
          f"({len(dataset.samples)} turns, {len(dataset.team_previews)} previews)")

    # Encode all samples into tensor dicts
    print("Encoding to tensors...")
    t0 = time.time()
    encoded_samples = []
    for i in range(len(dataset)):
        try:
            tensors = dataset[i]
            encoded_samples.append(tensors)
        except Exception as e:
            if i < 5:
                print(f"  Error encoding sample {i}: {e}")
            continue

        if (i + 1) % 10000 == 0:
            print(f"  {i+1}/{len(dataset)} encoded...")

    encode_time = time.time() - t0
    print(f"Encoded {len(encoded_samples)} samples in {encode_time:.1f}s")

    # Save cache
    print(f"Saving cache to {cache_file}...")
    t0 = time.time()
    torch.save({
        "samples": encoded_samples,
        "history_mode": args.history,
        "min_rating": args.min_rating,
        "num_battle_turns": len(dataset.samples),
        "num_team_previews": len(dataset.team_previews),
        "created": time.time(),
    }, cache_file)

    # Save manifest
    manifest = {
        "parsed_files": all_replay_files,
        "history_mode": args.history,
        "min_rating": args.min_rating,
        "num_samples": len(encoded_samples),
        "created": time.time(),
        "parse_time_sec": parse_time,
        "encode_time_sec": encode_time,
    }
    manifest_file.write_text(json.dumps(manifest, indent=2))

    save_time = time.time() - t0
    file_size_mb = cache_file.stat().st_size / 1024 / 1024
    print(f"Saved in {save_time:.1f}s ({file_size_mb:.1f} MB)")
    print(f"\nDone! Total time: {parse_time + encode_time + save_time:.1f}s")
    print(f"Next training run: use --cache {cache_file}")


if __name__ == "__main__":
    main()
