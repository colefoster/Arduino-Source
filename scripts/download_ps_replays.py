#!/usr/bin/env python3
"""
Bulk download Pokemon Showdown replays for Pokemon Champions formats.

Usage:
    python3 scripts/download_ps_replays.py

Supports resuming — skips already-downloaded replay files.
Downloads replays incrementally during pagination to avoid memory issues.
"""

from __future__ import annotations

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
SEARCH_DELAY = 2.0   # seconds between search requests
REPLAY_DELAY = 0.5   # seconds between individual replay downloads


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


def download_replay(replay_id: str, output_dir: Path) -> bool:
    """Download a single replay JSON. Returns True if downloaded, False if skipped/failed."""
    out_file = output_dir / f"{replay_id}.json"
    if out_file.exists():
        return False  # already downloaded

    url = REPLAY_URL.format(replay_id)
    data = fetch_json(url)
    if data is None:
        return False

    out_file.write_text(json.dumps(data, indent=2))
    return True


def process_format(fmt: str, index: dict) -> dict:
    """Search and download replays for a format, one page at a time."""
    fmt_dir = OUTPUT_DIR / fmt
    fmt_dir.mkdir(exist_ok=True)

    before = None
    page = 0
    total_found = 0
    downloaded = 0
    skipped = 0
    failed = 0

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
        print(f"  Page {page}: {len(data)} results (total: {total_found})", flush=True)

        # Download replays from this page immediately
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

            success = download_replay(replay_id, fmt_dir)
            if success:
                downloaded += 1
                time.sleep(REPLAY_DELAY)
            elif (fmt_dir / f"{replay_id}.json").exists():
                skipped += 1
            else:
                failed += 1

        print(f"    -> new: {downloaded}, skipped: {skipped}, failed: {failed}", flush=True)

        # Save index after each page
        INDEX_FILE.write_text(json.dumps(index, indent=2))

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


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing index if resuming
    index = {}
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text())

    stats = {}

    for fmt in FORMATS:
        print(f"\n{'='*60}")
        print(f"Format: {fmt}")
        print(f"{'='*60}", flush=True)

        stats[fmt] = process_format(fmt, index)

    # Final report
    print(f"\n{'='*60}")
    print("DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    total_replays = 0
    for fmt, s in stats.items():
        print(f"  {fmt}: {s['search_results']} found, "
              f"{s['downloaded']} downloaded, {s['skipped']} skipped, {s['failed']} failed")
        total_replays += s["search_results"]
    print(f"  TOTAL: {total_replays} replays")
    print(f"  Index: {len(index)} entries in {INDEX_FILE}")


if __name__ == "__main__":
    main()
