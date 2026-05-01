"""Read encoded ``.pt`` shards into training samples.

Loads all shards under ``encoded/<format>/<encoding_version>/<mode>/`` (or a
specified subset), applies row-level filters (``min_rating``, ``since``,
``pov_player``), and exposes a flat ``Dataset`` interface.

The shard format is the v2 stacked layout written by ``encode_runner._stack_samples``:
each shard is a dict with per-column numpy arrays of length N. Loading is fast
because we ``torch.from_numpy`` once per column and slice into samples on
``__getitem__``.

Designed to be light: no augmentation here. ``GpuSlotSwap`` runs post-collate
on GPU.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import torch
from torch.utils.data import Dataset


# Columns that the trainer reads. Keep this list as the contract between
# encoder + dataset.
SAMPLE_COLUMNS = (
    "species_ids", "hp_values", "status_ids", "alive_flags",
    "item_ids", "item_confidences",
    "ability_ids", "ability_confidences",
    "move_ids", "move_confidences",
    "weather_id", "terrain_id", "trick_room",
    "action_a_type", "action_a_move_id", "action_a_switch_id",
    "action_a_target", "action_a_mega",
    "action_b_type", "action_b_move_id", "action_b_switch_id",
    "action_b_target", "action_b_mega",
    "prev_seq_active_species", "prev_seq_active_hp",
    "prev_seq_action_types", "prev_seq_action_moves",
)


def _iter_shards(root: Path) -> Iterable[Path]:
    """Yield every ``YYYY-MM-DD/HH.pt`` under root."""
    if not root.exists():
        return
    for day in sorted(root.iterdir()):
        if not day.is_dir():
            continue
        for f in sorted(day.iterdir()):
            if f.suffix == ".pt":
                yield f


def _shard_in_date_range(shard_path: Path, since: Optional[str], until: Optional[str]) -> bool:
    """Match ``YYYY-MM-DD/HH.pt`` against the date range. Cheap path-level filter."""
    if since is None and until is None:
        return True
    day = shard_path.parent.name
    try:
        dt = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return True
    if since is not None:
        if dt < datetime.strptime(since, "%Y-%m-%d").date():
            return False
    if until is not None:
        if dt > datetime.strptime(until, "%Y-%m-%d").date():
            return False
    return True


class TrainingDataset(Dataset):
    """Concatenated dataset over many encoded shards with row-level filters.

    Loads metadata eagerly (small, needed for filtering); data columns lazily
    from shard files mapped via memory-friendly numpy + torch.from_numpy.
    Each ``__getitem__`` returns one sample dict ready for the model.
    """

    def __init__(
        self,
        encoded_root: Path,
        *,
        fmt: str,
        encoding_version: str,
        mode: str,
        min_rating: int = 0,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ):
        super().__init__()
        self._encoded_root = Path(encoded_root)
        self._fmt = fmt
        self._encoding_version = encoding_version
        self._mode = mode

        shard_root = self._encoded_root / fmt / encoding_version / mode
        self._shards: list[dict] = []
        # Each shard entry: {"path", "n_in_shard", "indices" (np.array of selected rows)}
        # We resolve filtered indices once at construction.

        total_kept = 0
        total_seen = 0
        for shard_path in _iter_shards(shard_root):
            if not _shard_in_date_range(shard_path, since, until):
                continue
            payload = torch.load(shard_path, weights_only=False, map_location="cpu")
            n = int(payload.get("n_samples", 0))
            if n == 0:
                continue
            cols = payload["columns"]
            keep_mask = np.ones(n, dtype=bool)
            if min_rating > 0:
                keep_mask &= cols["_meta_rating"] >= min_rating
            kept_idx = np.nonzero(keep_mask)[0].astype(np.int32)
            total_seen += n
            if kept_idx.size == 0:
                continue
            total_kept += kept_idx.size
            self._shards.append({
                "path": shard_path,
                "indices": kept_idx,
                "n_kept": int(kept_idx.size),
                "_columns": cols,  # keep loaded; lazily-clear if memory matters
            })

        if not self._shards:
            raise ValueError(
                f"No samples after filtering under {shard_root} "
                f"(min_rating={min_rating}, since={since}, until={until})"
            )

        self._cum = np.cumsum([s["n_kept"] for s in self._shards], dtype=np.int64)
        self._total = int(self._cum[-1])
        self._total_seen = total_seen
        self._total_kept = total_kept

    def __len__(self) -> int:
        return self._total

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < 0 or idx >= self._total:
            raise IndexError(idx)
        shard_pos = int(np.searchsorted(self._cum, idx, side="right"))
        local_pos = idx - (self._cum[shard_pos - 1] if shard_pos > 0 else 0)
        shard = self._shards[shard_pos]
        row_idx = int(shard["indices"][local_pos])
        cols = shard["_columns"]
        sample = {}
        for k in SAMPLE_COLUMNS:
            if k not in cols:
                # Older shard schemas (pre-history) lack ``prev_seq_*`` etc.
                # Skip — the model handles missing optional columns.
                continue
            arr = cols[k][row_idx]
            t = torch.as_tensor(arr)
            # Embedding layers + cross-entropy require long; everything stored
            # int8/int32 needs to be promoted. Floats stay floats.
            if t.dtype in (torch.int8, torch.int32, torch.int16):
                t = t.long()
            sample[k] = t
        # Carry rating + winner label for any aux objective the trainer wants.
        sample["rating"] = torch.tensor(
            int(cols["_meta_rating"][row_idx]), dtype=torch.long,
        )
        sample["is_winner"] = torch.tensor(
            bool(cols["_meta_is_winner"][row_idx]), dtype=torch.bool,
        )
        return sample

    @property
    def total_seen(self) -> int:
        return self._total_seen

    @property
    def total_kept(self) -> int:
        return self._total_kept

    @property
    def shard_count(self) -> int:
        return len(self._shards)
