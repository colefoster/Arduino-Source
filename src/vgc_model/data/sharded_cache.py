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
    """Dataset that loads samples from a sharded cache directory.

    Concatenates all shards into a flat sample list. Eager-loads on
    construction (each shard is one torch.load); use ``lazy=True`` to keep
    file handles open and load shards on first access (not yet implemented).
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

        self._samples: list[dict[str, torch.Tensor]] = []
        t0 = time.time()
        for shard in manifest.shards:
            sf = cache_dir / shard["file"]
            if not sf.exists():
                raise FileNotFoundError(
                    f"Shard listed in manifest but missing on disk: {sf}"
                )
            data = torch.load(sf, map_location="cpu", weights_only=False)
            self._samples.extend(data["samples"])
        elapsed = time.time() - t0
        print(
            f"Loaded sharded cache from {cache_dir}: "
            f"{len(self._samples)} samples across {len(manifest.shards)} shards "
            f"in {elapsed:.1f}s"
        )

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
