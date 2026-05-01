"""Bucket-level orchestrator for Layer 1 parsing.

Reads every replay JSON in one hour-bucket dir, runs `ReplayParser` on each,
writes one row-per-replay to a parquet file. Failed replays go to a sidecar
JSONL so a corrupt input never silently disappears.

Idempotent: if the output parquet exists and is newer than the newest input,
the bucket is skipped. Re-runs after partial failures are safe.

Design choice: top-level filterable columns (replay_id, ratings, winner, …)
are stored natively. Deeply nested arrays (turns, teams) are JSON-encoded
into a single string column each — this avoids parquet schema inference
edge cases on optional/empty nested fields, while keeping the file ~50%
of the equivalent JSON-lines size and still queryable with pandas/pyarrow.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .replay_parser import ParsedReplay, ReplayParser
from .stats_source import UsageStatsSource


log = logging.getLogger(__name__)


# Top-level filterable columns + JSON-blob columns for nested arrays.
PARQUET_SCHEMA = pa.schema([
    pa.field("replay_id", pa.string()),
    pa.field("format", pa.string()),
    pa.field("bucket_hour", pa.string()),
    pa.field("replay_end_ts", pa.int64()),
    pa.field("p1_player", pa.string()),
    pa.field("p2_player", pa.string()),
    pa.field("p1_rating", pa.int32()),
    pa.field("p2_rating", pa.int32()),
    pa.field("winner", pa.string()),
    pa.field("p1_team_json", pa.string()),
    pa.field("p2_team_json", pa.string()),
    pa.field("turns_json", pa.string()),
])


def parsed_replay_to_row(p: ParsedReplay) -> dict:
    """Flatten a `ParsedReplay` into the parquet row schema."""
    return {
        "replay_id": p.replay_id,
        "format": p.format,
        "bucket_hour": p.bucket_hour,
        "replay_end_ts": p.replay_end_ts,
        "p1_player": p.p1_player,
        "p2_player": p.p2_player,
        "p1_rating": p.p1_rating,
        "p2_rating": p.p2_rating,
        "winner": p.winner,
        "p1_team_json": json.dumps([asdict(t) for t in p.p1_team]),
        "p2_team_json": json.dumps([asdict(t) for t in p.p2_team]),
        "turns_json": json.dumps([asdict(t) for t in p.turns]),
    }


def is_bucket_fresh(out_parquet: Path, source_dir: Path) -> bool:
    """Return True iff parquet exists and is newer than every input file."""
    if not out_parquet.exists():
        return False
    out_mtime = out_parquet.stat().st_mtime
    for src in source_dir.iterdir():
        if src.is_file() and src.suffix == ".json":
            if src.stat().st_mtime > out_mtime:
                return False
    return True


def parse_bucket(
    bucket_dir: Path,
    parsed_path: Path,
    failed_path: Path,
    parser: ReplayParser,
    *,
    force: bool = False,
) -> dict:
    """Parse one hour-bucket of replays.

    Args:
        bucket_dir: ``replays/<format>/YYYY-MM-DD/HH/``
        parsed_path: target parquet, e.g. ``parsed/<format>/YYYY-MM-DD/HH.parquet``
        failed_path: target failures JSONL, e.g. ``failed/.../HH.errors.jsonl``
        parser: configured ReplayParser
        force: ignore freshness check, always re-parse

    Returns:
        Stats dict: ``{parsed, skipped (fresh), failed, total, took_sec}``
    """
    started = time.time()
    if not bucket_dir.exists():
        return {"parsed": 0, "fresh": False, "failed": 0, "total": 0, "took_sec": 0.0}

    if not force and is_bucket_fresh(parsed_path, bucket_dir):
        return {"parsed": 0, "fresh": True, "failed": 0, "total": 0, "took_sec": 0.0}

    rows: list[dict] = []
    failures: list[dict] = []

    for src in sorted(bucket_dir.iterdir()):
        if not src.is_file() or src.suffix != ".json":
            continue
        try:
            with open(src, encoding="utf-8") as f:
                replay_json = json.load(f)
        except (OSError, ValueError) as e:
            failures.append({"replay_id": src.stem, "error": f"read/json: {e!r}"})
            continue

        try:
            parsed = parser.parse(replay_json)
        except Exception as e:
            failures.append({"replay_id": src.stem, "error": f"parse: {e!r}"})
            continue

        if parsed is None:
            failures.append({"replay_id": src.stem, "error": "parse_returned_none"})
            continue

        try:
            rows.append(parsed_replay_to_row(parsed))
        except Exception as e:
            failures.append({"replay_id": src.stem, "error": f"row: {e!r}"})

    parsed_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        table = pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA)
        # Write to a temp file then rename for atomicity.
        tmp = parsed_path.with_suffix(parsed_path.suffix + ".tmp")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(parsed_path)
    elif parsed_path.exists():
        # No rows this run but the file existed — leave it alone.
        pass
    else:
        # Empty bucket: write an empty table so freshness check passes
        # and subsequent runs don't keep retrying it forever.
        pa.parquet.write_table(
            pa.Table.from_pylist([], schema=PARQUET_SCHEMA),
            parsed_path,
            compression="zstd",
        )

    if failures:
        failed_path.parent.mkdir(parents=True, exist_ok=True)
        with open(failed_path, "w", encoding="utf-8") as f:
            for fail in failures:
                f.write(json.dumps(fail) + "\n")
    elif failed_path.exists():
        failed_path.unlink()

    return {
        "parsed": len(rows),
        "fresh": False,
        "failed": len(failures),
        "total": len(rows) + len(failures),
        "took_sec": round(time.time() - started, 2),
    }


def iter_bucket_dirs(replays_root: Path, fmt: str) -> Iterable[Path]:
    """Yield every ``replays/<fmt>/YYYY-MM-DD/HH/`` directory in date+hour order."""
    fmt_root = replays_root / fmt
    if not fmt_root.exists():
        return
    for day_dir in sorted(fmt_root.iterdir()):
        if not day_dir.is_dir():
            continue
        for hour_dir in sorted(day_dir.iterdir()):
            if hour_dir.is_dir():
                yield hour_dir


def parsed_path_for(parsed_root: Path, fmt: str, bucket_dir: Path) -> Path:
    """Map ``replays/<fmt>/YYYY-MM-DD/HH/`` -> ``parsed/<fmt>/YYYY-MM-DD/HH.parquet``."""
    return parsed_root / fmt / bucket_dir.parent.name / f"{bucket_dir.name}.parquet"


def failed_path_for(failed_root: Path, fmt: str, bucket_dir: Path) -> Path:
    """Map ``replays/<fmt>/YYYY-MM-DD/HH/`` -> ``failed/<fmt>/YYYY-MM-DD/HH.errors.jsonl``."""
    return failed_root / fmt / bucket_dir.parent.name / f"{bucket_dir.name}.errors.jsonl"


def run_all_buckets(
    replays_root: Path,
    parsed_root: Path,
    failed_root: Path,
    fmt: str,
    parser: ReplayParser,
    *,
    force: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """Run `parse_bucket` over every bucket of one format. Returns aggregate stats."""
    total = {"buckets": 0, "fresh": 0, "parsed_rows": 0, "failed_rows": 0, "took_sec": 0.0}
    for i, bucket_dir in enumerate(iter_bucket_dirs(replays_root, fmt)):
        if limit is not None and i >= limit:
            break
        out_parquet = parsed_path_for(parsed_root, fmt, bucket_dir)
        out_failed = failed_path_for(failed_root, fmt, bucket_dir)
        result = parse_bucket(bucket_dir, out_parquet, out_failed, parser, force=force)
        total["buckets"] += 1
        if result["fresh"]:
            total["fresh"] += 1
        total["parsed_rows"] += result["parsed"]
        total["failed_rows"] += result["failed"]
        total["took_sec"] += result["took_sec"]
    total["took_sec"] = round(total["took_sec"], 2)
    return total
