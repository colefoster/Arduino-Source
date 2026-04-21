#!/usr/bin/env python3
"""
Download Pokemon Showdown replays for Pokemon Champions formats.

Usage:
    python3 scripts/download_ps_replays.py           # incremental (new replays only)
    python3 scripts/download_ps_replays.py --full     # full backfill from scratch

Designed to be run daily. Stops early once it hits already-downloaded replays.
Supports full backfill mode for initial setup.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

SEARCH_URL = "https://replay.pokemonshowdown.com/search.json"
REPLAY_URL = "https://replay.pokemonshowdown.com/{}.json"

FORMATS = [
    "gen9championsbssregma",
    "gen9championsvgc2026regma",
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
INDEX_FILE = OUTPUT_DIR / "index.json"

# Rate limiting
SEARCH_DELAY = 2.0
REPLAY_DELAY = 0.5

# How many consecutive already-seen replays before stopping in incremental mode
SEEN_THRESHOLD = 100


def fetch_json(url: str, retries: int = 5) -> dict | list | None:
    """Fetch JSON from a URL with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "PokemonChampionsResearch/1.0"})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (HTTPError, URLError, json.JSONDecodeError, socket.timeout, OSError) as e:
            print(f"  [attempt {attempt+1}/{retries}] Error fetching {url}: {e}", flush=True)
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
    return None


def download_replay(replay_id: str, output_dir: Path) -> bool | None:
    """Download a single replay JSON.

    Returns:
        True = downloaded new replay
        False = already existed (skipped)
        None = download failed
    """
    out_file = output_dir / f"{replay_id}.json"
    if out_file.exists():
        return False

    url = REPLAY_URL.format(replay_id)
    data = fetch_json(url)
    if data is None:
        return None

    out_file.write_text(json.dumps(data, indent=2))
    return True


def process_format(fmt: str, index: dict, full: bool = False) -> dict:
    """Search and download replays for a format, one page at a time.

    In incremental mode (full=False), stops after hitting SEEN_THRESHOLD
    consecutive already-downloaded replays.
    """
    fmt_dir = OUTPUT_DIR / fmt
    fmt_dir.mkdir(exist_ok=True)

    before = None
    page = 0
    total_found = 0
    downloaded = 0
    skipped = 0
    failed = 0
    consecutive_seen = 0

    while True:
        url = f"{SEARCH_URL}?format={fmt}"
        if before is not None:
            url += f"&before={before}"

        page += 1
        data = fetch_json(url)
        if data is None:
            print(f"  Search failed on page {page}, retrying after 30s...", flush=True)
            time.sleep(30)
            data = fetch_json(url)
            if data is None:
                print(f"  Search failed again on page {page}, stopping.", flush=True)
                break
        if len(data) == 0:
            break

        total_found += len(data)

        # Download replays from this page
        page_new = 0
        for entry in data:
            replay_id = entry["id"]

            # Update index
            index[replay_id] = {
                "format": entry.get("format"),
                "format_id": fmt,
                "players": entry.get("players"),
                "rating": entry.get("rating"),
                "uploadtime": entry.get("uploadtime"),
            }

            result = download_replay(replay_id, fmt_dir)
            if result is True:
                downloaded += 1
                page_new += 1
                consecutive_seen = 0
                time.sleep(REPLAY_DELAY)
            elif result is False:
                skipped += 1
                consecutive_seen += 1
            else:
                failed += 1
                consecutive_seen = 0

        print(
            f"  Page {page}: {len(data)} results "
            f"(+{page_new} new, {total_found} total, {downloaded} downloaded)",
            flush=True,
        )

        # Save index after each page
        INDEX_FILE.write_text(json.dumps(index, indent=2))

        # Incremental mode: stop once we've caught up
        if not full and consecutive_seen >= SEEN_THRESHOLD:
            print(f"  Caught up — {consecutive_seen} consecutive existing replays, stopping.", flush=True)
            break

        if len(data) < 51:
            break

        before = data[-1]["uploadtime"]
        time.sleep(SEARCH_DELAY)

    return {
        "search_results": total_found,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
    }


def rebuild_rating_symlinks(index: dict):
    """Rebuild rating-filtered symlink directories."""
    for fmt in FORMATS:
        fmt_dir = OUTPUT_DIR / fmt
        if not fmt_dir.exists():
            continue

        for threshold in [1200, 1300, 1400]:
            link_dir = OUTPUT_DIR / f"{fmt}_{threshold}plus"
            link_dir.mkdir(exist_ok=True)

        for replay_id, meta in index.items():
            if meta.get("format_id") != fmt:
                continue
            rating = meta.get("rating")
            if not rating:
                continue

            src = fmt_dir / f"{replay_id}.json"
            if not src.exists():
                continue

            for threshold in [1200, 1300, 1400]:
                if rating >= threshold:
                    dest = OUTPUT_DIR / f"{fmt}_{threshold}plus" / f"{replay_id}.json"
                    if not dest.exists():
                        dest.symlink_to(src.resolve())


def main():
    parser = argparse.ArgumentParser(description="Download Pokemon Showdown replays")
    parser.add_argument("--full", action="store_true",
                        help="Full backfill (don't stop at already-seen replays)")
    parser.add_argument("--no-symlinks", action="store_true",
                        help="Skip rebuilding rating-filtered symlink directories")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing index
    index = {}
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text())

    mode = "FULL BACKFILL" if args.full else "INCREMENTAL"
    print(f"Mode: {mode}")
    print(f"Existing index: {len(index)} replays")

    stats = {}
    for fmt in FORMATS:
        print(f"\n{'='*60}")
        print(f"Format: {fmt}")
        print(f"{'='*60}", flush=True)

        stats[fmt] = process_format(fmt, index, full=args.full)

    # Rebuild symlinks
    if not args.no_symlinks:
        print("\nRebuilding rating-filtered symlinks...", flush=True)
        rebuild_rating_symlinks(index)

    # Report
    print(f"\n{'='*60}")
    print("DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    total_new = 0
    for fmt, s in stats.items():
        print(f"  {fmt}: {s['downloaded']} new, {s['skipped']} skipped, {s['failed']} failed")
        total_new += s["downloaded"]
    print(f"  Total new: {total_new}")
    print(f"  Index: {len(index)} entries")


if __name__ == "__main__":
    main()
