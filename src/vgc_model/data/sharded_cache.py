"""Sharded, incremental tensor cache for replay datasets.

Layout:
    <cache_dir>/
        manifest.json              # variant config + list of shards
        shard_0000.pt              # {"samples": [tensor_dict, ...], "replay_ids": [str, ...]}
        shard_0001.pt
        ...

Adding new replays = encode just the missing ones, write a new shard, append
to manifest. No need to re-encode prior replays.

Variant changes (history_mode, min_rating, winner_only) produce different
caches — keep them in separate directories.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Iterable, Optional

import torch
from torch.utils.data import Dataset


SCHEMA_VERSION = 1


def variant_key(history_mode: str, min_rating: int, winner_only: bool) -> str:
    return f"{history_mode}_r{min_rating}_w{1 if winner_only else 0}"


class ShardedCacheManifest:
    """Read/write the manifest.json that describes a sharded cache."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.path = self.cache_dir / "manifest.json"
        self.data: dict = {
            "schema_version": SCHEMA_VERSION,
            "history_mode": None,
            "min_rating": None,
            "winner_only": None,
            "created": None,
            "shards": [],
        }
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    @property
    def shards(self) -> list[dict]:
        return self.data["shards"]

    def covered_replay_ids(self) -> set[str]:
        """All replay IDs already encoded into some shard."""
        out: set[str] = set()
        for shard in self.data["shards"]:
            out.update(shard.get("replay_ids", []))
        return out

    def total_samples(self) -> int:
        return sum(s.get("num_samples", 0) for s in self.data["shards"])

    def init_variant(self, history_mode: str, min_rating: int, winner_only: bool):
        """Set variant config on a fresh manifest. Call once when creating the cache."""
        self.data.update({
            "history_mode": history_mode,
            "min_rating": min_rating,
            "winner_only": winner_only,
            "created": time.time(),
        })
        self.save()

    def validate_variant(self, history_mode: str, min_rating: int, winner_only: bool):
        """Raise if variant doesn't match this manifest. Called at training time."""
        for k, v in [
            ("history_mode", history_mode),
            ("min_rating", min_rating),
            ("winner_only", winner_only),
        ]:
            if self.data.get(k) is not None and self.data[k] != v:
                raise ValueError(
                    f"Cache at {self.cache_dir} has {k}={self.data[k]!r} but "
                    f"requested {v!r}. Use a different cache dir for this variant."
                )

    def add_shard(self, filename: str, replay_ids: list[str], num_samples: int):
        self.data["shards"].append({
            "file": filename,
            "replay_ids": replay_ids,
            "num_samples": num_samples,
            "encoded_at": time.time(),
        })
        self.save()

    def next_shard_filename(self) -> str:
        idx = len(self.data["shards"])
        return f"shard_{idx:04d}.pt"

    def save(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write (write to .tmp then rename) so a crash mid-write doesn't
        # corrupt the manifest.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def write_shard(
    cache_dir: Path,
    samples: list[dict[str, torch.Tensor]],
    replay_ids: list[str],
    history_mode: str,
) -> str:
    """Write one shard file and return its filename. Caller updates the manifest."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = ShardedCacheManifest(cache_dir)
    filename = manifest.next_shard_filename()
    out_path = cache_dir / filename
    tmp = out_path.with_suffix(".pt.tmp")
    torch.save({
        "samples": samples,
        "replay_ids": replay_ids,
        "history_mode": history_mode,
    }, tmp)
    tmp.replace(out_path)
    return filename


class ShardedCachedDataset(Dataset):
    """Dataset that lazily loads samples from a sharded cache directory.

    Holds at most ONE shard in memory at a time — random access within the
    current shard is O(1), accessing a different shard triggers a load. For a
    51 GB cache on 31 GB RAM, the eager-load design (concat everything into
    a single list) page-faulted the whole machine; this lazy variant keeps
    the working set bounded to one shard (~1.6 GB).

    For training, use ``ShardLocalSampler`` (defined below) to traverse all
    samples in one shard before moving to the next — gives random sample
    order within shards + random shard order, which preserves most of the
    regularization benefit of full shuffle without thrashing.
    """

    def __init__(self, cache_dir: Path, augment: bool = True):
        cache_dir = Path(cache_dir)
        if not cache_dir.exists():
            raise FileNotFoundError(f"Cache dir not found: {cache_dir}")
        self.cache_dir = cache_dir
        self.augment = augment
        manifest = ShardedCacheManifest(cache_dir)
        self.history_mode = manifest.data.get("history_mode", "single")

        if not manifest.shards:
            raise RuntimeError(f"Cache at {cache_dir} has no shards")

        # Build a flat-index → (shard_idx, local_idx) map. Cheap: 2M ints.
        self._shard_files: list[Path] = []
        self._shard_starts: list[int] = []  # flat-index where each shard begins
        cumulative = 0
        for shard in manifest.shards:
            sf = cache_dir / shard["file"]
            if not sf.exists():
                raise FileNotFoundError(
                    f"Shard listed in manifest but missing on disk: {sf}"
                )
            self._shard_files.append(sf)
            self._shard_starts.append(cumulative)
            cumulative += shard["num_samples"]
        self._total = cumulative

        # Currently-loaded shard
        self._loaded_shard_idx: int = -1
        self._loaded_samples: list[dict[str, torch.Tensor]] | None = None

        print(
            f"Sharded cache at {cache_dir}: "
            f"{self._total} samples across {len(self._shard_files)} shards (lazy)"
        )

    @property
    def num_shards(self) -> int:
        return len(self._shard_files)

    def shard_size(self, shard_idx: int) -> int:
        """Number of samples in the given shard."""
        if shard_idx == len(self._shard_files) - 1:
            return self._total - self._shard_starts[shard_idx]
        return self._shard_starts[shard_idx + 1] - self._shard_starts[shard_idx]

    def shard_global_range(self, shard_idx: int) -> tuple[int, int]:
        """(start, end) flat indices for samples in the given shard."""
        start = self._shard_starts[shard_idx]
        end = start + self.shard_size(shard_idx)
        return start, end

    def _ensure_shard(self, shard_idx: int):
        if self._loaded_shard_idx == shard_idx:
            return
        # Drop the previous shard before loading the next so we don't briefly
        # hold both in memory.
        self._loaded_samples = None
        data = torch.load(
            self._shard_files[shard_idx], map_location="cpu", weights_only=False,
        )
        self._loaded_samples = data["samples"]
        self._loaded_shard_idx = shard_idx

    def _locate(self, idx: int) -> tuple[int, int]:
        """Map flat idx → (shard_idx, local_idx). Binary search."""
        # bisect_right gives the index of the first start > idx; subtract 1.
        import bisect
        shard_idx = bisect.bisect_right(self._shard_starts, idx) - 1
        local = idx - self._shard_starts[shard_idx]
        return shard_idx, local

    def __len__(self) -> int:
        return self._total

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        shard_idx, local = self._locate(idx)
        self._ensure_shard(shard_idx)
        tensors = self._loaded_samples[local]
        if self.augment and random.random() < 0.5:
            tensors = self._swap_slots(tensors)
        return tensors

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        tensors = self._samples[idx]
        if self.augment and random.random() < 0.5:
            tensors = self._swap_slots(tensors)
        return tensors

    @staticmethod
    def _swap_slots(t: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Slot A/B swap — same logic as EnrichedDataset._swap_slots.

        Defined here so the cached dataset doesn't depend on the heavy
        EnrichedDataset module at training time.
        """
        t = dict(t)

        for key in ("species_ids", "hp_values", "status_ids", "item_ids",
                    "ability_ids", "mega_flags", "alive_flags",
                    "item_confidences", "ability_confidences"):
            if key not in t:
                continue
            v = t[key].clone()
            v[0], v[1] = t[key][1], t[key][0]
            v[4], v[5] = t[key][5], t[key][4]
            t[key] = v

        for key in ("boost_values", "move_ids", "move_confidences",
                    "species_features", "item_features", "ability_features",
                    "move_features"):
            if key not in t:
                continue
            v = t[key].clone()
            v[0], v[1] = t[key][1], t[key][0]
            v[4], v[5] = t[key][5], t[key][4]
            t[key] = v

        if "action_slot_a" in t and "action_slot_b" in t:
            t["action_slot_a"], t["action_slot_b"] = (
                t["action_slot_b"].clone(), t["action_slot_a"].clone(),
            )
        if "action_mask_a" in t and "action_mask_b" in t:
            t["action_mask_a"], t["action_mask_b"] = (
                t["action_mask_b"].clone(), t["action_mask_a"].clone(),
            )

        if "prev_actions" in t:
            prev = t["prev_actions"].clone()
            prev[0], prev[1] = t["prev_actions"][1], t["prev_actions"][0]
            prev[2], prev[3] = t["prev_actions"][3], t["prev_actions"][2]
            t["prev_actions"] = prev

        if "prev_seq_actions" in t:
            psa = t["prev_seq_actions"].clone()
            for turn in range(psa.shape[0]):
                psa[turn, 0], psa[turn, 1] = t["prev_seq_actions"][turn, 1].clone(), t["prev_seq_actions"][turn, 0].clone()
                psa[turn, 2], psa[turn, 3] = t["prev_seq_actions"][turn, 3].clone(), t["prev_seq_actions"][turn, 2].clone()
            t["prev_seq_actions"] = psa

            pss = t["prev_seq_species"].clone()
            for turn in range(pss.shape[0]):
                pss[turn, 0], pss[turn, 1] = t["prev_seq_species"][turn, 1].clone(), t["prev_seq_species"][turn, 0].clone()
                pss[turn, 2], pss[turn, 3] = t["prev_seq_species"][turn, 3].clone(), t["prev_seq_species"][turn, 2].clone()
            t["prev_seq_species"] = pss

            psh = t["prev_seq_hp"].clone()
            for turn in range(psh.shape[0]):
                psh[turn, 0], psh[turn, 1] = t["prev_seq_hp"][turn, 1].clone(), t["prev_seq_hp"][turn, 0].clone()
                psh[turn, 2], psh[turn, 3] = t["prev_seq_hp"][turn, 3].clone(), t["prev_seq_hp"][turn, 2].clone()
            t["prev_seq_hp"] = psh

        return t


def find_uncovered_replays(
    replay_files: Iterable[tuple[Path, int]],
    manifest: ShardedCacheManifest,
) -> list[tuple[Path, int]]:
    """Return only the replays whose ID is not yet in any shard."""
    covered = manifest.covered_replay_ids()
    return [(f, r) for f, r in replay_files if f.stem not in covered]


class ShardLocalSampler:
    """Sampler that traverses all samples in one shard before moving to the next.

    With a lazy ``ShardedCachedDataset`` (one shard in RAM at a time), random
    access via DataLoader(shuffle=True) would load N shards per batch and
    thrash. This sampler preserves randomness in two ways:

      - shard order is shuffled per epoch
      - within each shard, sample order is shuffled per epoch

    Net effect: the DataLoader sees an effectively random sequence, but the
    dataset only loads each shard once per epoch.

    Use as: ``DataLoader(dataset, batch_size=N, sampler=ShardLocalSampler(dataset))``.
    Do NOT pass ``shuffle=True`` — the sampler handles that.
    """

    def __init__(
        self,
        dataset: "ShardedCachedDataset",
        shuffle: bool = True,
        seed: int = 42,
    ):
        self.dataset = dataset
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch: int):
        self.epoch = epoch

    def __iter__(self):
        rng = random.Random(self.seed + self.epoch)
        shard_order = list(range(self.dataset.num_shards))
        if self.shuffle:
            rng.shuffle(shard_order)
        for shard_idx in shard_order:
            start, end = self.dataset.shard_global_range(shard_idx)
            indices = list(range(start, end))
            if self.shuffle:
                rng.shuffle(indices)
            yield from indices

    def __len__(self) -> int:
        return len(self.dataset)


class ShardLocalSubsetSampler:
    """Like ShardLocalSampler but restricted to a subset of flat indices.

    Used after ``random_split``-style splits, where the val (or train) subset
    is an arbitrary list of flat indices. We bucket those indices by shard,
    then visit shards in random order, yielding only the in-subset indices
    from each shard before moving on.
    """

    def __init__(
        self,
        dataset: "ShardedCachedDataset",
        indices: list[int],
        shuffle: bool = True,
        seed: int = 42,
    ):
        self.dataset = dataset
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0

        # Bucket indices by shard
        self._buckets: dict[int, list[int]] = {}
        for idx in indices:
            shard_idx, _ = dataset._locate(idx)
            self._buckets.setdefault(shard_idx, []).append(idx)
        self._total = len(indices)

    def set_epoch(self, epoch: int):
        self.epoch = epoch

    def __iter__(self):
        rng = random.Random(self.seed + self.epoch)
        shard_order = list(self._buckets.keys())
        if self.shuffle:
            rng.shuffle(shard_order)
        for shard_idx in shard_order:
            indices = list(self._buckets[shard_idx])
            if self.shuffle:
                rng.shuffle(indices)
            yield from indices

    def __len__(self) -> int:
        return self._total
