"""Per-Pokémon feature builder for the lead advisor.

At team preview, only species is known for both sides. We pad each species with
Smogon-prior-derived features (modal item/ability + move bag) so the encoder
gets meaningful signal beyond a bare species id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VOCAB_DIR = PROJECT_ROOT / "data" / "vocab"
USAGE_PATH = PROJECT_ROOT / "data" / "usage_stats" / "gen9championsvgc2026regma.json"
ARCHETYPE_PATH = PROJECT_ROOT / "data" / "usage_stats" / "archetypes_1760.json"

# Top-K item/ability/move slots aggregated from Smogon priors per mon.
TOP_ITEMS = 3
TOP_ABILITIES = 2
TOP_MOVES = 6

# Cluster ids: 0 = unknown / out-of-taxonomy mon, 1..N = archetype clusters.
# N_ARCHETYPES is the count of real clusters (excluding the 0/unknown bucket);
# the embedding table size is N_ARCHETYPES + 1.
N_ARCHETYPES = 8


def _load_vocab(name: str) -> dict[str, int]:
    with open(VOCAB_DIR / f"{name}.json") as f:
        return json.load(f)


class FeatureBuilder:
    """Builds dense feature tensors for a Pokémon at team-preview time."""

    def __init__(
        self,
        usage_path: str | Path | None = None,
        archetype_path: str | Path | None = None,
    ) -> None:
        self.species_vocab = _load_vocab("species")
        self.item_vocab = _load_vocab("items")
        self.ability_vocab = _load_vocab("abilities")
        self.move_vocab = _load_vocab("moves")

        with open(usage_path or USAGE_PATH) as f:
            self.usage: dict = json.load(f)

        self.species_size = max(self.species_vocab.values()) + 1
        self.item_size = max(self.item_vocab.values()) + 1
        self.ability_size = max(self.ability_vocab.values()) + 1
        self.move_size = max(self.move_vocab.values()) + 1

        self._UNK = 1  # all vocabs use 1 for <UNK>

        # Cluster lookup: archetype taxonomy at cut1760. Map post-Mega and
        # base names alike so "Charizard" (team-sheet) and "Charizard-Mega-Y"
        # (Smogon entry) both resolve to the same cluster id.
        self.cluster_lookup: dict[str, int] = {}
        ap = Path(archetype_path) if archetype_path else ARCHETYPE_PATH
        if ap.exists():
            with open(ap) as f:
                tax = json.load(f)
            for cluster in tax.get("clusters", []):
                cid = int(cluster["id"])
                for m in cluster.get("members", []):
                    name = m["name"]
                    self.cluster_lookup[name] = cid
                    # also map base forms (strip -Mega / -Mega-X / -Mega-Y)
                    for suffix in ("-Mega-X", "-Mega-Y", "-Mega"):
                        if name.endswith(suffix):
                            base = name[: -len(suffix)]
                            self.cluster_lookup.setdefault(base, cid)

    # ------------------------------------------------------------------
    # Vocab helpers
    # ------------------------------------------------------------------

    def species_id(self, species: str) -> int:
        return self.species_vocab.get(species, self._UNK)

    def item_id(self, name: str) -> int:
        return self.item_vocab.get(name, self._UNK)

    def ability_id(self, name: str) -> int:
        return self.ability_vocab.get(name, self._UNK)

    def move_id(self, name: str) -> int:
        return self.move_vocab.get(name, self._UNK)

    def cluster_id(self, species: str) -> int:
        return self.cluster_lookup.get(species, 0)

    # ------------------------------------------------------------------
    # Per-mon feature
    # ------------------------------------------------------------------

    def encode_pokemon(self, species: str) -> dict:
        """Return tensors describing a species via Smogon priors.

        All ids reference the shared vocabs in `data/vocab/`. Padding is 0.
        """
        prior = self.usage.get(species) or {}

        item_ids = np.zeros(TOP_ITEMS, dtype=np.int64)
        item_w = np.zeros(TOP_ITEMS, dtype=np.float32)
        for i, (name, pct) in enumerate(list((prior.get("items") or {}).items())[:TOP_ITEMS]):
            item_ids[i] = self.item_id(name)
            item_w[i] = pct / 100.0

        abil_ids = np.zeros(TOP_ABILITIES, dtype=np.int64)
        abil_w = np.zeros(TOP_ABILITIES, dtype=np.float32)
        for i, (name, pct) in enumerate(list((prior.get("abilities") or {}).items())[:TOP_ABILITIES]):
            abil_ids[i] = self.ability_id(name)
            abil_w[i] = pct / 100.0

        move_ids = np.zeros(TOP_MOVES, dtype=np.int64)
        move_w = np.zeros(TOP_MOVES, dtype=np.float32)
        for i, (name, pct) in enumerate(list((prior.get("moves") or {}).items())[:TOP_MOVES]):
            move_ids[i] = self.move_id(name)
            move_w[i] = pct / 100.0

        usage_pct = float(prior.get("usage_pct", 0.0)) / 100.0
        vc = prior.get("viability_ceiling") or [0, 0, 0, 0]
        # scalars: usage, gxe_max, gxe_avg (normalize 0-1)
        scalars = np.array([
            usage_pct,
            float(vc[1]) / 100.0 if len(vc) > 1 else 0.0,
            float(vc[2]) / 100.0 if len(vc) > 2 else 0.0,
        ], dtype=np.float32)

        return {
            "species_id": np.int64(self.species_id(species)),
            "item_ids": item_ids,
            "item_w": item_w,
            "ability_ids": abil_ids,
            "ability_w": abil_w,
            "move_ids": move_ids,
            "move_w": move_w,
            "scalars": scalars,
            "in_prior": np.float32(1.0 if prior else 0.0),
            "cluster_id": np.int64(self.cluster_id(species)),
        }

    def encode_team(self, species_list: Iterable[str]) -> dict:
        """Stack 6 mons into batched tensors. Pads with <PAD> if fewer than 6.

        Also returns `arch_hist`: a length-(N_ARCHETYPES+1) float vector with
        the fraction of brought-mons in each cluster (index 0 = unknown).
        """
        mons = list(species_list)[:6]
        while len(mons) < 6:
            mons.append("<PAD>")
        stacked = [self.encode_pokemon(s) for s in mons]
        out: dict = {}
        for k in stacked[0]:
            arr = np.stack([m[k] for m in stacked], axis=0)
            out[k] = arr

        hist = np.zeros(N_ARCHETYPES + 1, dtype=np.float32)
        real = [s for s in mons if s != "<PAD>"]
        if real:
            for s in real:
                hist[self.cluster_id(s)] += 1.0
            hist /= float(len(real))
        out["arch_hist"] = hist
        return out
