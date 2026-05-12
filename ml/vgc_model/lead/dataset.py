"""Lead advisor dataset.

Reads hour-bucketed parquet files from data/parsed/<format>/YYYY-MM-DD/HH.parquet
and yields per-side training samples. One replay → 2 samples (one per side),
each weighted by (winner/loser) × rating.

Sample shape:
  own_features:  dict of [6, ...] tensors built by FeatureBuilder
  opp_features:  same shape
  team_label:    [6] float — 1.0 for each mon brought into battle
  lead_label:    int — index in C(4,2)=6 over the canonical lead-pair ordering,
                       restricted to the 4 brought mons. We store the raw lead
                       species pair and resolve the index at training time so
                       the same record can be reused with different team picks
                       during evaluation.
  weight:        float — combined winner/loser × rating weight
  rating:        int   — ego player rating
  is_winner:     bool
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .features import FeatureBuilder


# ---------------------------------------------------------------------------
# Sample weighting
# ---------------------------------------------------------------------------

def winner_loser_weight(is_winner: bool, loser_weight: float = 0.5) -> float:
    return 1.0 if is_winner else loser_weight


def rating_weight(rating: int | None) -> float:
    if rating is None or rating <= 0:
        return 0.5
    # 1300 -> 0.5, 1500 -> 1.0, 1700 -> 1.5, 1900+ -> 2.0
    w = (rating - 1300.0) / 400.0 + 0.5
    return float(max(0.5, min(2.0, w)))


# ---------------------------------------------------------------------------
# Lead extraction
# ---------------------------------------------------------------------------

def _to_team_form(species: str, team_species: list[str]) -> str:
    """Map an in-battle species (possibly Mega/forme) back to its team-sheet name.

    Handles `-Mega`, `-Mega-X`, `-Mega-Y` by stripping suffixes if the base is
    in `team_species`. Otherwise returns the original.
    """
    if species in team_species:
        return species
    for suffix in ("-Mega-X", "-Mega-Y", "-Mega"):
        if species.endswith(suffix):
            base = species[: -len(suffix)]
            if base in team_species:
                return base
    return species


def extract_lead_and_team(team_json: str, turns_json: str, side: str) -> tuple[list[str], list[str], list[str]]:
    """Parse one side of a replay.

    Returns:
      team6:    [<= 6] species in team-sheet order
      brought:  [<= 4] species brought into battle, names normalized to team-sheet form
      leads:    [2] species that led turn 1 (active_slot 0 and 1), team-sheet form
    """
    team = json.loads(team_json)
    team_species = [m["species"] for m in team]

    turns = json.loads(turns_json)
    if not turns:
        return team_species, [], []

    revealed_key = f"{side}_revealed"

    # Lead pair = turn 1 actives at slots 0 and 1.
    t1 = turns[0]
    leads_by_slot: dict[int, str] = {}
    for mon in t1.get(revealed_key, []):
        slot = mon.get("active_slot")
        if slot in (0, 1):
            leads_by_slot[slot] = _to_team_form(mon["species"], team_species)
    leads = [leads_by_slot.get(0, ""), leads_by_slot.get(1, "")]

    # Team selection: any mon ever active. Normalize Mega -> base; dedupe.
    brought: list[str] = []
    seen: set[str] = set()
    for turn in turns:
        for mon in turn.get(revealed_key, []) or []:
            if mon.get("active_slot") is None:
                continue
            sp = _to_team_form(mon["species"], team_species)
            if sp not in seen:
                seen.add(sp)
                brought.append(sp)

    return team_species, brought, leads


# ---------------------------------------------------------------------------
# Sample
# ---------------------------------------------------------------------------

@dataclass
class LeadSample:
    own_team: list[str]      # 6 species
    opp_team: list[str]      # 6 species
    own_brought: list[str]   # 4 species (subset of own_team) — team-selection target
    own_leads: list[str]     # 2 species (subset of own_brought)
    rating: int
    is_winner: bool
    weight: float

    def team_label_vec(self) -> np.ndarray:
        """[6] float: 1.0 if mon was brought, else 0.0."""
        out = np.zeros(6, dtype=np.float32)
        for i, sp in enumerate(self.own_team[:6]):
            if sp in self.own_brought:
                out[i] = 1.0
        return out

    def lead_index_in_team6(self) -> tuple[int, int]:
        """Indices of the 2 lead mons within the 6-team slot order. (-1, -1) if lookup fails."""
        if len(self.own_leads) != 2:
            return (-1, -1)
        idx_a = self.own_team.index(self.own_leads[0]) if self.own_leads[0] in self.own_team else -1
        idx_b = self.own_team.index(self.own_leads[1]) if self.own_leads[1] in self.own_team else -1
        return (idx_a, idx_b)


# ---------------------------------------------------------------------------
# Iterator over parquet shards
# ---------------------------------------------------------------------------

def iter_samples_from_parquet(
    path: str | Path,
    *,
    min_rating: int = 0,
    loser_weight: float = 0.5,
    require_full_brought: bool = False,
) -> Iterable[LeadSample]:
    """Yield 2 samples per row (one per side).

    `require_full_brought=True` drops samples where fewer than 4 distinct
    own-mons ever went active (battles that ended early or had parser misses).
    """
    import pyarrow.parquet as pq
    table = pq.read_table(str(path))
    cols = {c: table[c].to_pylist() for c in table.column_names}
    n = table.num_rows

    for i in range(n):
        winner = cols["winner"][i]  # "p1" / "p2" / None
        if winner not in ("p1", "p2"):
            continue
        p1_rating = cols.get("p1_rating", [0] * n)[i] or 0
        p2_rating = cols.get("p2_rating", [0] * n)[i] or 0
        turns_json = cols["turns_json"][i]
        if not turns_json:
            continue

        for side in ("p1", "p2"):
            rating = p1_rating if side == "p1" else p2_rating
            if rating < min_rating:
                continue
            opp = "p2" if side == "p1" else "p1"

            team_json = cols[f"{side}_team_json"][i]
            opp_team_json = cols[f"{opp}_team_json"][i]
            if not team_json or not opp_team_json:
                continue

            own_team, own_brought, own_leads = extract_lead_and_team(team_json, turns_json, side)
            opp_team, _, _ = extract_lead_and_team(opp_team_json, turns_json, opp)

            if len(own_team) < 4 or len(own_brought) < 2 or len(own_leads) < 2:
                continue
            if require_full_brought and len(own_brought) < 4:
                continue
            if "" in own_leads:
                continue
            # Strict: lead must come from team sheet
            if any(sp not in own_team for sp in own_leads):
                continue
            # Two distinct lead slots: skip rare cases where both leads collapse
            # to the same team-sheet index (e.g. malformed team or both Mega
            # variants of the same base).
            if own_leads[0] == own_leads[1]:
                continue
            if len(set(own_team)) < len(own_team):
                # team-sheet duplicates would make .index() ambiguous
                continue

            is_winner = (side == winner)
            w = winner_loser_weight(is_winner, loser_weight) * rating_weight(rating)

            yield LeadSample(
                own_team=own_team,
                opp_team=opp_team,
                own_brought=own_brought[:4],
                own_leads=own_leads,
                rating=int(rating),
                is_winner=is_winner,
                weight=float(w),
            )


def iter_samples_from_dir(
    parsed_dir: str | Path,
    *,
    min_rating: int = 0,
    loser_weight: float = 0.5,
    glob: str = "*/*.parquet",
    require_full_brought: bool = False,
) -> Iterable[LeadSample]:
    parsed_dir = Path(parsed_dir)
    for shard in sorted(parsed_dir.glob(glob)):
        yield from iter_samples_from_parquet(
            shard,
            min_rating=min_rating,
            loser_weight=loser_weight,
            require_full_brought=require_full_brought,
        )


# ---------------------------------------------------------------------------
# Tensor collation
# ---------------------------------------------------------------------------

def collate(samples: list[LeadSample], builder: FeatureBuilder) -> dict[str, np.ndarray]:
    """Build a batch of numpy tensors. Caller converts to torch.Tensor."""
    B = len(samples)

    per_mon_keys = list(builder.encode_pokemon("<PAD>").keys())
    # team-level keys produced by encode_team but not by encode_pokemon
    team_keys = ["arch_hist"]

    own: dict[str, list] = {k: [] for k in per_mon_keys + team_keys}
    opp: dict[str, list] = {k: [] for k in per_mon_keys + team_keys}
    team_lbl = np.zeros((B, 6), dtype=np.float32)
    lead_idx = np.zeros((B, 2), dtype=np.int64)
    weights = np.zeros(B, dtype=np.float32)
    ratings = np.zeros(B, dtype=np.float32)

    for b, s in enumerate(samples):
        ofeat = builder.encode_team(s.own_team)
        pfeat = builder.encode_team(s.opp_team)
        for k in per_mon_keys + team_keys:
            own[k].append(ofeat[k])
            opp[k].append(pfeat[k])
        team_lbl[b] = s.team_label_vec()
        ia, ib = s.lead_index_in_team6()
        lead_idx[b] = [ia, ib]
        weights[b] = s.weight
        ratings[b] = float(s.rating)

    out: dict[str, np.ndarray] = {}
    for k in per_mon_keys + team_keys:
        out[f"own_{k}"] = np.stack(own[k], axis=0)
        out[f"opp_{k}"] = np.stack(opp[k], axis=0)
    out["team_label"] = team_lbl
    out["lead_index"] = lead_idx
    out["weight"] = weights
    out["rating"] = ratings
    return out
