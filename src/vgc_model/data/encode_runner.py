"""Bucket-level orchestrator for Layer 2 encoding.

Reads parsed parquet rows for one hour-bucket, runs ``Encoder`` per row, and
stacks the resulting raw samples into per-column numpy arrays — written as a
single ``.pt`` shard. The stacked layout is essential for fast loading: at
training time we ``torch.from_numpy`` once per column and slice into samples,
instead of paying ``torch.tensor()`` overhead per element.

Idempotent — skips buckets whose ``.pt`` is newer than the parsed parquet.
``--force`` overrides.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pyarrow.parquet as pq
import torch

from .encoder import EncodeMode, Encoder, RawSample
from .vocab import Vocabs


log = logging.getLogger(__name__)

# Per-column dtype + shape spec — drives numpy stacking.
# (column_name, dtype, sample_shape) — N is prepended automatically.
_COLUMN_SPECS: list[tuple[str, np.dtype, tuple]] = [
    ("species_ids",        np.int32,   (8,)),
    ("hp_values",          np.float32, (8,)),
    ("status_ids",         np.int32,   (8,)),
    ("alive_flags",        np.int8,    (8,)),
    ("item_ids",           np.int32,   (8,)),
    ("item_confidences",   np.float32, (8,)),
    ("ability_ids",        np.int32,   (8,)),
    ("ability_confidences",np.float32, (8,)),
    ("move_ids",           np.int32,   (8, 4)),
    ("move_confidences",   np.float32, (8, 4)),
    ("weather_id",         np.int32,   ()),
    ("terrain_id",         np.int32,   ()),
    ("trick_room",         np.int8,    ()),
    ("action_a_type",      np.int8,    ()),
    ("action_a_move_id",   np.int32,   ()),
    ("action_a_switch_id", np.int32,   ()),
    ("action_a_target",    np.int8,    ()),
    ("action_a_mega",      np.int8,    ()),
    ("action_b_type",      np.int8,    ()),
    ("action_b_move_id",   np.int32,   ()),
    ("action_b_switch_id", np.int32,   ()),
    ("action_b_target",    np.int8,    ()),
    ("action_b_mega",      np.int8,    ()),
    # Sequence history (Phase 7). Last 8 turns × 4 slots
    # ([own_a, own_b, opp_a, opp_b]).
    ("prev_seq_active_species", np.int32,   (8, 4)),
    ("prev_seq_active_hp",      np.float32, (8, 4)),
    ("prev_seq_action_types",   np.int8,    (8, 4)),
    ("prev_seq_action_moves",   np.int32,   (8, 4)),
]


def _stack_samples(samples: list[RawSample]) -> dict:
    """Convert a list of RawSamples into per-column numpy arrays + metadata.

    Returns a dict suitable for ``torch.save``. Column shapes have N (sample
    count) prepended; metadata is kept as parallel arrays for fast filtering.
    """
    n = len(samples)
    out: dict = {}
    for name, dtype, shape in _COLUMN_SPECS:
        out[name] = np.empty((n,) + shape, dtype=dtype)
    # Metadata in column form (cheap to filter).
    out["_meta_replay_id"] = np.array(
        [s.replay_id for s in samples], dtype=object,
    )
    out["_meta_bucket_hour"] = np.array(
        [s.bucket_hour for s in samples], dtype=object,
    )
    out["_meta_rating"] = np.array([s.rating for s in samples], dtype=np.int32)
    out["_meta_pov_player"] = np.array(
        [s.pov_player for s in samples], dtype=object,
    )
    out["_meta_is_winner"] = np.array(
        [s.is_winner for s in samples], dtype=np.bool_,
    )
    out["_meta_turn_num"] = np.array([s.turn_num for s in samples], dtype=np.int32)

    for i, s in enumerate(samples):
        for name, _dtype, _shape in _COLUMN_SPECS:
            out[name][i] = s.fields[name]
    return out


def is_shard_fresh(out_pt: Path, source_parquet: Path) -> bool:
    if not out_pt.exists() or not source_parquet.exists():
        return False
    return out_pt.stat().st_mtime >= source_parquet.stat().st_mtime


def encode_one_bucket(
    parsed_parquet: Path,
    out_pt: Path,
    encoder: Encoder,
    *,
    force: bool = False,
) -> dict:
    started = time.time()
    if not parsed_parquet.exists():
        return {"samples": 0, "fresh": False, "skipped_empty": True, "took_sec": 0.0}

    if not force and is_shard_fresh(out_pt, parsed_parquet):
        return {"samples": 0, "fresh": True, "skipped_empty": False, "took_sec": 0.0}

    table = pq.read_table(parsed_parquet)
    n_rows = table.num_rows
    if n_rows == 0:
        out_pt.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "schema_version": 2,
            "mode": encoder.mode,
            "n_samples": 0,
            "columns": {},
        }, out_pt)
        return {"samples": 0, "fresh": False, "skipped_empty": True, "took_sec": 0.0}

    columns = table.column_names
    samples: list[RawSample] = []
    for row_idx in range(n_rows):
        row = {col: table.column(col)[row_idx].as_py() for col in columns}
        for sample in encoder.encode_row(row):
            samples.append(sample)

    stacked = _stack_samples(samples)

    out_pt.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_pt.with_suffix(out_pt.suffix + ".tmp")
    torch.save({
        "schema_version": 2,
        "mode": encoder.mode,
        "n_samples": len(samples),
        "columns": stacked,
    }, tmp)
    tmp.replace(out_pt)

    return {
        "samples": len(samples),
        "fresh": False,
        "skipped_empty": False,
        "took_sec": round(time.time() - started, 2),
    }


def iter_parsed_buckets(parsed_root: Path, fmt: str) -> Iterable[Path]:
    fmt_root = parsed_root / fmt
    if not fmt_root.exists():
        return
    for day_dir in sorted(fmt_root.iterdir()):
        if not day_dir.is_dir():
            continue
        for f in sorted(day_dir.iterdir()):
            if f.suffix == ".parquet":
                yield f


def encoded_path_for(
    encoded_root: Path,
    fmt: str,
    encoding_version: str,
    mode: EncodeMode,
    parsed_parquet: Path,
) -> Path:
    day = parsed_parquet.parent.name
    hour = parsed_parquet.stem
    return encoded_root / fmt / encoding_version / mode / day / f"{hour}.pt"


def run_all_encoding(
    parsed_root: Path,
    encoded_root: Path,
    fmt: str,
    encoding_version: str,
    mode: EncodeMode,
    encoder: Encoder,
    *,
    force: bool = False,
    limit: Optional[int] = None,
) -> dict:
    total = {"buckets": 0, "fresh": 0, "samples": 0, "took_sec": 0.0}
    for i, parsed in enumerate(iter_parsed_buckets(parsed_root, fmt)):
        if limit is not None and i >= limit:
            break
        out_pt = encoded_path_for(encoded_root, fmt, encoding_version, mode, parsed)
        result = encode_one_bucket(parsed, out_pt, encoder, force=force)
        total["buckets"] += 1
        if result["fresh"]:
            total["fresh"] += 1
        total["samples"] += result["samples"]
        total["took_sec"] += result["took_sec"]
    total["took_sec"] = round(total["took_sec"], 2)
    return total


# ---------------------------------------------------------------------------
# Vocab bootstrap
# ---------------------------------------------------------------------------

def bootstrap_vocabs(
    parsed_root: Path,
    fmt: str,
    *,
    max_buckets: Optional[int] = None,
) -> Vocabs:
    vocabs = Vocabs()
    counts = defaultdict(int)

    for i, parsed in enumerate(iter_parsed_buckets(parsed_root, fmt)):
        if max_buckets is not None and i >= max_buckets:
            break
        table = pq.read_table(parsed)
        for r_idx in range(table.num_rows):
            counts["replays"] += 1
            turns_json = table.column("turns_json")[r_idx].as_py()
            turns = json.loads(turns_json)
            for turn in turns:
                counts["turns"] += 1
                vocabs.weather.add(turn.get("weather") or "none")
                vocabs.terrain.add(turn.get("terrain") or "none")
                for revealed_list in (turn["p1_revealed"], turn["p2_revealed"]):
                    for slot in revealed_list:
                        vocabs.species.add(slot["species"])
                        vocabs.status.add(slot["status"] or "ok")
                        if slot["item"]["value"]:
                            vocabs.items.add(slot["item"]["value"])
                        if slot["ability"]["value"]:
                            vocabs.abilities.add(slot["ability"]["value"])
                        for m in slot["moves"]:
                            if m["value"]:
                                vocabs.moves.add(m["value"])
                for action_field in (
                    "p1_action_a", "p1_action_b", "p2_action_a", "p2_action_b",
                ):
                    a = turn[action_field]
                    if a.get("move"):
                        vocabs.moves.add(a["move"])
                    if a.get("switch_to"):
                        vocabs.species.add(a["switch_to"])

    vocabs.weather.add("none")
    vocabs.terrain.add("none")
    vocabs.status.add("ok")
    vocabs.freeze_all()
    return vocabs
