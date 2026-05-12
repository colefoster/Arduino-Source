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

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

import numpy as np
import torch
from torch.utils.data import Dataset, Sampler


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
    # Optional state-richness columns (v6+ shards). Older shards skip these
    # via the "if k not in cols: continue" branch in __getitem__.
    "stat_boosts", "side_conditions", "hazards",
    "volatiles", "sub_hps", "last_move_ids",
)


class ShardChunkSampler(Sampler[int]):
    """Yield indices shard-by-shard, shuffled within each shard.

    Avoids global random access across all shards so the dataset's small LRU
    shard cache hits — instead of touching every shard per batch (cache thrash),
    we exhaust one shard at a time. Across epochs the shard order is shuffled
    too, so the model still sees a non-trivial reordering.

    Use this with ``DataLoader(shuffle=False)``; pass as ``sampler=...``.
    """

    def __init__(self, dataset: "TrainingDataset", seed: int = 0):
        self._ranges = dataset.shard_index_ranges()
        self._seed = seed
        self._epoch = 0

    def __len__(self) -> int:
        return sum(end - start for start, end in self._ranges)

    def set_epoch(self, epoch: int) -> None:
        self._epoch = epoch

    def __iter__(self) -> Iterator[int]:
        rng = np.random.default_rng(self._seed + self._epoch)
        shard_order = rng.permutation(len(self._ranges))
        for s in shard_order:
            start, end = self._ranges[int(s)]
            local = rng.permutation(end - start) + start
            yield from local.tolist()


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
            # Open the shard ONLY to read the rating column for filtering;
            # don't keep payload in memory. Full data is loaded lazily on
            # __getitem__ via the LRU cache.
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
            })
            # Free the payload — only path + filter result are retained.
            del payload, cols

        if not self._shards:
            raise ValueError(
                f"No samples after filtering under {shard_root} "
                f"(min_rating={min_rating}, since={since}, until={until})"
            )

        self._cum = np.cumsum([s["n_kept"] for s in self._shards], dtype=np.int64)
        self._total = int(self._cum[-1])
        self._total_seen = total_seen
        self._total_kept = total_kept

        # Per-process LRU cache of loaded shard column dicts. Capped to keep
        # RAM bounded; the `ShardChunkSampler` (default for training) groups
        # access shard-by-shard so a small cache hits well.
        self._shard_cache: "OrderedDict[int, dict]" = OrderedDict()
        self._shard_cache_max = 4

    def __len__(self) -> int:
        return self._total

    def _get_cols(self, shard_pos: int) -> dict:
        cache = self._shard_cache
        if shard_pos in cache:
            cache.move_to_end(shard_pos)
            return cache[shard_pos]
        path = self._shards[shard_pos]["path"]
        payload = torch.load(path, weights_only=False, map_location="cpu")
        cols = payload["columns"]
        cache[shard_pos] = cols
        if len(cache) > self._shard_cache_max:
            cache.popitem(last=False)
        return cols

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < 0 or idx >= self._total:
            raise IndexError(idx)
        shard_pos = int(np.searchsorted(self._cum, idx, side="right"))
        local_pos = idx - (self._cum[shard_pos - 1] if shard_pos > 0 else 0)
        shard = self._shards[shard_pos]
        row_idx = int(shard["indices"][local_pos])
        cols = self._get_cols(shard_pos)
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

    def shard_index_ranges(self) -> list[tuple[int, int]]:
        """Per-shard (start, end) global-index ranges, for chunk-coherent sampling."""
        out: list[tuple[int, int]] = []
        prev = 0
        for cum in self._cum:
            out.append((prev, int(cum)))
            prev = int(cum)
        return out

    def split_by_shard(
        self, val_fraction: float, seed: int = 42,
    ) -> tuple["TrainingDataset", "TrainingDataset"]:
        """Split shards into (train, val) datasets that share this LRU cache.

        Approximate val_fraction by shard count, not sample count — close
        enough for a 5% val split with hundreds of shards. Both children
        return TrainingDataset instances that bypass the file-loading
        constructor; their `_shards` are subsets of this dataset's list.
        """
        n = len(self._shards)
        rng = np.random.default_rng(seed)
        perm = rng.permutation(n)
        n_val = max(1, int(round(n * val_fraction)))
        val_shard_idx = set(int(i) for i in perm[:n_val])
        train_shards = [s for i, s in enumerate(self._shards) if i not in val_shard_idx]
        val_shards = [s for i, s in enumerate(self._shards) if i in val_shard_idx]

        return (
            self._clone_with_shards(train_shards),
            self._clone_with_shards(val_shards),
        )

    def _clone_with_shards(self, shards: list[dict]) -> "TrainingDataset":
        """Return a sibling dataset that shares the LRU cache + file roots."""
        clone = TrainingDataset.__new__(TrainingDataset)
        Dataset.__init__(clone)
        clone._encoded_root = self._encoded_root
        clone._fmt = self._fmt
        clone._encoding_version = self._encoding_version
        clone._mode = self._mode
        clone._shards = shards
        clone._cum = np.cumsum([s["n_kept"] for s in shards], dtype=np.int64)
        clone._total = int(clone._cum[-1]) if len(clone._cum) else 0
        clone._total_seen = clone._total
        clone._total_kept = clone._total
        clone._shard_cache = self._shard_cache  # shared cache
        clone._shard_cache_max = self._shard_cache_max
        return clone

    @property
    def total_seen(self) -> int:
        return self._total_seen

    @property
    def total_kept(self) -> int:
        return self._total_kept

    @property
    def shard_count(self) -> int:
        return len(self._shards)
