"""Drive Layer 1 parsing over hour-bucketed replays.

Used both as the cron entry point (every hour at :15) and the one-shot backfill
runner. Idempotent — only re-parses buckets whose parsed parquet is missing or
older than at least one of its inputs.

Usage:
    python scripts/run_layer1_parse.py                    # all formats, all buckets
    python scripts/run_layer1_parse.py --format gen9...   # one format
    python scripts/run_layer1_parse.py --limit 5          # only first 5 buckets
    python scripts/run_layer1_parse.py --force            # re-parse everything
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.vgc_model.data.parse_runner import run_all_buckets
from src.vgc_model.data.replay_parser import ReplayParser
from src.vgc_model.data.stats_source import PikalyticsStatsSource


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--replays-root", type=Path,
        default=PROJECT_ROOT / "data" / "replays",
        help="Root of the bucketed replay layout.",
    )
    ap.add_argument(
        "--parsed-root", type=Path,
        default=PROJECT_ROOT / "data" / "parsed",
        help="Where to write parsed parquet shards.",
    )
    ap.add_argument(
        "--failed-root", type=Path,
        default=PROJECT_ROOT / "data" / "failed",
        help="Where to write per-bucket failure JSONLs.",
    )
    ap.add_argument(
        "--format", default="gen9championsvgc2026regma",
        help="Format subdir to process. Pass 'all' for every format under replays-root.",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N buckets per format (smoke test).",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Re-parse buckets even if parquet is fresh.",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    stats = PikalyticsStatsSource()
    parser = ReplayParser(stats)

    if args.format == "all":
        formats = [
            d.name for d in args.replays_root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
    else:
        formats = [args.format]

    overall_start = time.time()
    grand = {"buckets": 0, "fresh": 0, "parsed_rows": 0, "failed_rows": 0}
    for fmt in formats:
        result = run_all_buckets(
            replays_root=args.replays_root,
            parsed_root=args.parsed_root,
            failed_root=args.failed_root,
            fmt=fmt,
            parser=parser,
            force=args.force,
            limit=args.limit,
        )
        if not args.quiet:
            print(
                f"[{fmt}] buckets={result['buckets']} fresh={result['fresh']} "
                f"parsed={result['parsed_rows']} failed={result['failed_rows']} "
                f"took={result['took_sec']:.1f}s"
            )
        for k in ("buckets", "fresh", "parsed_rows", "failed_rows"):
            grand[k] += result[k]

    overall_elapsed = time.time() - overall_start
    print(
        f"\nTOTAL ({overall_elapsed:.1f}s): "
        f"buckets={grand['buckets']} fresh={grand['fresh']} "
        f"parsed={grand['parsed_rows']} failed={grand['failed_rows']} "
        f"stats_source={stats.source_id}"
    )


if __name__ == "__main__":
    main()
