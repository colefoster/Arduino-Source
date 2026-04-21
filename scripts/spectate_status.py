#!/usr/bin/env python3
"""Quick status dashboard for the live spectator and replay collection."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
INDEX_FILE = OUTPUT_DIR / "index.json"

FORMATS = {
    "gen9championsvgc2026regma": "VGC",
    "gen9championsbssregma": "BSS",
}


def count_by_source(fmt_dir: Path) -> tuple[int, int]:
    """Count spectated vs downloaded replays by checking the JSON source field.
    Returns (spectated, downloaded)."""
    spectated = 0
    downloaded = 0
    if not fmt_dir.exists():
        return 0, 0
    for f in fmt_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text())
            if data.get("source") == "spectated":
                spectated += 1
            else:
                downloaded += 1
        except Exception:
            downloaded += 1
    return spectated, downloaded


def recent_spectated(fmt_dir: Path, minutes: int) -> int:
    """Count spectated replays saved in the last N minutes."""
    if not fmt_dir.exists():
        return 0
    cutoff = time.time() - (minutes * 60)
    count = 0
    for f in fmt_dir.iterdir():
        if f.suffix != ".json" or f.stat().st_mtime <= cutoff:
            continue
        try:
            data = json.loads(f.read_text())
            if data.get("source") == "spectated":
                count += 1
        except Exception:
            pass
    return count


def spectator_session_info(fmt_dir: Path) -> dict:
    """Get info about the current/recent spectator session."""
    if not fmt_dir.exists():
        return {}

    # Find all spectated files, get timestamps
    spectated_times = []
    for f in fmt_dir.iterdir():
        if f.suffix != ".json":
            continue
        mtime = f.stat().st_mtime
        # Only check recent files (last 24h) to avoid scanning everything
        if time.time() - mtime > 86400:
            continue
        try:
            data = json.loads(f.read_text())
            if data.get("source") == "spectated":
                spectated_times.append(mtime)
        except Exception:
            pass

    if not spectated_times:
        return {}

    spectated_times.sort()
    newest = spectated_times[-1]
    age_minutes = (time.time() - newest) / 60

    # Find session start (gap of >10 min = new session)
    session_start = spectated_times[0]
    for i in range(1, len(spectated_times)):
        if spectated_times[i] - spectated_times[i - 1] > 600:
            session_start = spectated_times[i]

    session_count = sum(1 for t in spectated_times if t >= session_start)
    session_duration = (newest - session_start) / 60

    return {
        "active": age_minutes < 5,
        "last_save_ago": age_minutes,
        "session_start": session_start,
        "session_duration": session_duration,
        "session_count": session_count,
        "session_rate": (session_count / session_duration * 60) if session_duration > 1 else 0,
    }


def main():
    now = datetime.now()
    print()
    print("=" * 60)
    print("  Live Spectator Dashboard")
    print(f"  {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    for fmt_id, label in FORMATS.items():
        fmt_dir = OUTPUT_DIR / fmt_id
        info = spectator_session_info(fmt_dir)

        if not info:
            continue

        status = "ACTIVE" if info["active"] else f"IDLE ({info['last_save_ago']:.0f}m ago)"
        print()
        print(f"  {label} Spectator: {status}")
        print(f"  {'-' * 50}")

        # Session stats
        start_time = datetime.fromtimestamp(info["session_start"])
        print(f"  Session start:    {start_time.strftime('%H:%M:%S')}")
        print(f"  Session duration: {info['session_duration']:.0f} min")
        print(f"  Session battles:  {info['session_count']:,}")
        if info["session_rate"] > 0:
            print(f"  Collection rate:  {info['session_rate']:.0f}/hr")

        # Recent activity
        last_5m = recent_spectated(fmt_dir, 5)
        last_30m = recent_spectated(fmt_dir, 30)
        last_1h = recent_spectated(fmt_dir, 60)
        print()
        print(f"  Last 5m:  {last_5m:>5}")
        print(f"  Last 30m: {last_30m:>5}")
        print(f"  Last 1h:  {last_1h:>5}")

    # Totals
    print()
    print(f"  {'=' * 50}")
    print(f"  Total Collection")
    print(f"  {'-' * 50}")
    print(f"  {'Format':<8} {'Spectated':>10} {'Downloaded':>11} {'Total':>8}")
    print(f"  {'-'*8} {'-'*10} {'-'*11} {'-'*8}")

    for fmt_id, label in FORMATS.items():
        fmt_dir = OUTPUT_DIR / fmt_id
        spec, dl = count_by_source(fmt_dir)
        print(f"  {label:<8} {spec:>10,} {dl:>11,} {spec+dl:>8,}")

    print()
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
