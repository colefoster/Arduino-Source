#!/usr/bin/env python3
"""Quick status dashboard for the spectator and replay collection."""

from __future__ import annotations

import json
import time
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
INDEX_FILE = OUTPUT_DIR / "index.json"

FORMATS = {
    "gen9championsvgc2026regma": "VGC",
    "gen9championsbssregma": "BSS",
}


def count_files(d: Path) -> int:
    if not d.exists():
        return 0
    return sum(1 for f in d.iterdir() if f.suffix == ".json")


def recent_files(d: Path, minutes: int = 60) -> int:
    if not d.exists():
        return 0
    cutoff = time.time() - (minutes * 60)
    return sum(1 for f in d.iterdir() if f.suffix == ".json" and f.stat().st_mtime > cutoff)


def main():
    print("=" * 60)
    print("  Pokemon Champions Replay Collection Status")
    print("=" * 60)
    print()

    # Index stats
    index = {}
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text())
    print(f"  Index entries: {len(index):,}")
    print()

    # Per-format stats
    print(f"  {'Format':<8} {'Total':>8} {'Last 1h':>8} {'Last 24h':>9} {'1200+':>8} {'1300+':>8} {'1400+':>8}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*9} {'-'*8} {'-'*8} {'-'*8}")

    for fmt_id, label in FORMATS.items():
        fmt_dir = OUTPUT_DIR / fmt_id
        total = count_files(fmt_dir)
        last_1h = recent_files(fmt_dir, 60)
        last_24h = recent_files(fmt_dir, 1440)

        r1200 = count_files(OUTPUT_DIR / f"{fmt_id}_1200plus")
        r1300 = count_files(OUTPUT_DIR / f"{fmt_id}_1300plus")
        r1400 = count_files(OUTPUT_DIR / f"{fmt_id}_1400plus")

        print(f"  {label:<8} {total:>8,} {last_1h:>8,} {last_24h:>9,} {r1200:>8,} {r1300:>8,} {r1400:>8,}")

    print()

    # Collection rate
    for fmt_id, label in FORMATS.items():
        fmt_dir = OUTPUT_DIR / fmt_id
        last_10m = recent_files(fmt_dir, 10)
        if last_10m > 0:
            rate_per_hour = last_10m * 6
            print(f"  {label} collection rate: ~{rate_per_hour}/hr ({last_10m} in last 10m)")

    # Spectated vs downloaded
    spectated = 0
    downloaded = 0
    for replay_id, meta in index.items():
        if meta.get("source") == "spectated":
            spectated += 1
        else:
            downloaded += 1

    # Actually check files for "source" field since index might not have it
    # Simpler: count files with "spectated" in them
    print()
    print(f"  Sources: {len(index):,} total indexed")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
