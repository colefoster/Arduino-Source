"""Bucket-level orchestrator for Layer 2 encoding.

Reads parsed parquet rows from one hour-bucket and produces an encoded shard
``encoded/<format>/<encoding_version>/<mode>/YYYY-MM-DD/HH.pt``. Idempotent —
if the shard exists and is newer than its parsed parquet, the bucket is
skipped. ``--force`` re-encodes everything.

Encoding versions are explicit in the output path so a feature change is a
new versioned dir, never an in-place rewrite. Old versions stay until manually
pruned.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

import pyarrow.parquet as pq
import torch

from .encoder import EncodeMode, Encoder, EncodedSample
from .vocab import Vocabs


log = logging.getLogger(__name__)


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
    """Encode one parsed parquet → one .pt shard. Returns stats dict."""
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
            "samples": [],
            "metadata": [],
            "schema_version": 1,
        }, out_pt)
        return {"samples": 0, "fresh": False, "skipped_empty": True, "took_sec": 0.0}

    columns = table.column_names
    samples_list = []
    metadata_list = []

    for row_idx in range(n_rows):
        row = {col: table.column(col)[row_idx].as_py() for col in columns}
        for sample in encoder.encode_row(row):
            samples_list.append(sample.tensors)
            metadata_list.append({
                "replay_id": sample.replay_id,
                "bucket_hour": sample.bucket_hour,
                "rating": sample.rating,
                "pov_player": sample.pov_player,
                "is_winner": sample.is_winner,
                "turn_num": sample.turn_num,
            })

    out_pt.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_pt.with_suffix(out_pt.suffix + ".tmp")
    torch.save({
        "samples": samples_list,
        "metadata": metadata_list,
        "schema_version": 1,
        "mode": encoder.mode,
    }, tmp)
    tmp.replace(out_pt)

    return {
        "samples": len(samples_list),
        "fresh": False,
        "skipped_empty": False,
        "took_sec": round(time.time() - started, 2),
    }


def iter_parsed_buckets(parsed_root: Path, fmt: str) -> Iterable[Path]:
    """Yield every ``parsed/<fmt>/YYYY-MM-DD/HH.parquet`` in date+hour order."""
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
    """Map ``parsed/<fmt>/YYYY-MM-DD/HH.parquet`` to the matching encoded ``.pt``."""
    day = parsed_parquet.parent.name
    hour = parsed_parquet.stem  # "HH"
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
    """Walk parsed parquets and build vocabularies.

    Builds species/moves/abilities/items/weather/terrain/status from any string
    that appears anywhere in the parsed data. Idempotent in the sense that
    re-running on the same parsed data produces the same vocab (modulo dict
    iteration order, which is insertion-ordered in CPython).

    A more principled future implementation might use the Pikalytics species
    list + a curated move/item/ability list. For now this gives us a complete
    vocab covering everything that actually appears in our replays.
    """
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
