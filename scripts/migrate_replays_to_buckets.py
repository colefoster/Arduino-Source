"""One-shot migration: flat-layout replays → hour-bucketed layout.

Source : <root>/data/showdown_replays/<format>/<id>.json
Target : <root>/data/replays/<format>/YYYY-MM-DD/HH/<id>.json

Bucketing key: replay's uploadtime (set when spectator saved the file). Falls
back to parsing the |t:|<unix> line out of the battle log when uploadtime is
missing (downloaded archive replays may not have it).

Idempotent. Re-runs are safe — files already present at target are skipped.
By default the script *moves* files (rename) to avoid duplicating ~100 GB on
disk. Use --copy if you want to preserve the source.

Designed to run on unraid against /mnt/user/data/pokemon-champions/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

T_LINE_RE = re.compile(r"\|t:\|(\d+)")


def extract_timestamp(replay_path: Path) -> int | None:
    """Return unix timestamp for a replay, or None if it can't be determined."""
    try:
        with open(replay_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    ts = data.get("uploadtime")
    if isinstance(ts, int) and ts > 0:
        return ts

    log = data.get("log", "")
    m = T_LINE_RE.search(log)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    return None


def bucket_for_ts(ts: int) -> tuple[str, str]:
    """Return (YYYY-MM-DD, HH) for a unix timestamp, in UTC."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H")


def migrate_one(
    src: Path, fmt_target_root: Path, copy: bool, dry_run: bool,
) -> tuple[str, Path | None]:
    """Returns (status, target_path). Status: 'moved' | 'skipped' | 'no_ts' | 'err'."""
    ts = extract_timestamp(src)
    if ts is None:
        return ("no_ts", None)

    day, hour = bucket_for_ts(ts)
    target_dir = fmt_target_root / day / hour
    target = target_dir / src.name

    if target.exists():
        return ("skipped", target)

    if dry_run:
        return ("moved", target)

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        if copy:
            import shutil
            shutil.copy2(src, target)
        else:
            os.rename(src, target)
    except OSError as e:
        return (f"err:{e}", None)

    return ("moved", target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source-root", required=True, type=Path,
        help="Path to data/showdown_replays/ (the flat-layout source).",
    )
    ap.add_argument(
        "--target-root", required=True, type=Path,
        help="Path to data/replays/ (the bucketed-layout target).",
    )
    ap.add_argument(
        "--format", default="gen9championsvgc2026regma",
        help="Format subdir to migrate. Pass 'all' to migrate every format dir.",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="Migrate at most N files (for smoke testing). 0 = unlimited.",
    )
    ap.add_argument(
        "--workers", type=int, default=16,
        help="Concurrent worker threads. Default 16.",
    )
    ap.add_argument(
        "--copy", action="store_true",
        help="Copy instead of move (preserves source files). Default: move (rename).",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Don't actually move/copy; just report what would happen.",
    )
    args = ap.parse_args()

    source_root = args.source_root.resolve()
    target_root = args.target_root.resolve()

    if not source_root.exists():
        print(f"Source {source_root} doesn't exist.", file=sys.stderr)
        sys.exit(1)

    if args.format == "all":
        format_dirs = [
            d for d in source_root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
    else:
        d = source_root / args.format
        if not d.exists():
            print(f"Format dir {d} doesn't exist.", file=sys.stderr)
            sys.exit(1)
        format_dirs = [d]

    overall_start = time.time()
    grand_total = {"moved": 0, "skipped": 0, "no_ts": 0, "err": 0}

    for fmt_dir in format_dirs:
        fmt_target_root = target_root / fmt_dir.name
        srcs = [p for p in fmt_dir.iterdir() if p.is_file() and p.suffix == ".json"]
        if args.limit:
            srcs = srcs[: args.limit]

        print(
            f"\n[{fmt_dir.name}] {len(srcs)} files -> {fmt_target_root}",
            flush=True,
        )

        counts = {"moved": 0, "skipped": 0, "no_ts": 0, "err": 0}
        start = time.time()

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [
                ex.submit(migrate_one, p, fmt_target_root, args.copy, args.dry_run)
                for p in srcs
            ]
            for i, fut in enumerate(as_completed(futures), 1):
                status, _ = fut.result()
                if status.startswith("err"):
                    counts["err"] += 1
                    if counts["err"] <= 5:
                        print(f"  err: {status}", flush=True)
                else:
                    counts[status] += 1
                if i % 5000 == 0:
                    elapsed = time.time() - start
                    rate = i / elapsed if elapsed else 0
                    print(
                        f"  {i}/{len(srcs)} "
                        f"({rate:.0f}/s, "
                        f"moved={counts['moved']} "
                        f"skipped={counts['skipped']} "
                        f"no_ts={counts['no_ts']} "
                        f"err={counts['err']})",
                        flush=True,
                    )

        elapsed = time.time() - start
        print(
            f"[{fmt_dir.name}] done in {elapsed:.1f}s | "
            f"moved={counts['moved']} skipped={counts['skipped']} "
            f"no_ts={counts['no_ts']} err={counts['err']}",
            flush=True,
        )
        for k in counts:
            grand_total[k] += counts[k]

    overall_elapsed = time.time() - overall_start
    print(
        f"\nTOTAL ({overall_elapsed:.1f}s): "
        f"moved={grand_total['moved']} skipped={grand_total['skipped']} "
        f"no_ts={grand_total['no_ts']} err={grand_total['err']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
