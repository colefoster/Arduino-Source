"""Lead-pair frequency lookup from the replay corpus.

Builds a small table of "given team X (and optionally opp team Y), which 2 mons
do players actually lead with?" — winner-weighted, ELO-weighted, with Jaccard
fallbacks for novel teams.

This is a no-ML baseline. It pairs naturally with the trained LeadAdvisorModel:
  - Lookup wins on common, well-covered matchups
  - Model wins on novel/long-tail matchups
  Final advisor can ensemble: prefer lookup when count >= threshold, else model.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .constants import PAIRS_6
from .dataset import LeadSample, iter_samples_from_dir, iter_samples_from_parquet, rating_weight, winner_loser_weight


# A pair is (i, j) with i < j as team-sheet indices, but here we key by SPECIES
# pair (sorted alphabetically) so the table is independent of slot order.
SpeciesPair = tuple[str, str]


def _sp_pair(a: str, b: str) -> SpeciesPair:
    return tuple(sorted((a, b)))  # type: ignore[return-value]


@dataclass
class LookupStats:
    """Counters for a single key (own_team or own+opp matchup)."""
    pair_w: Counter = field(default_factory=Counter)   # weighted (winner+rating)
    pair_n: Counter = field(default_factory=Counter)   # raw count
    brought_set_w: Counter = field(default_factory=Counter)   # brought-4 frozenset → weight
    brought_set_n: Counter = field(default_factory=Counter)
    brought_member_w: Counter = field(default_factory=Counter)  # per-species brought weight
    total_w: float = 0.0
    total_n: int = 0


@dataclass
class LeadLookup:
    by_own: dict[frozenset, LookupStats]
    # (own, opp) is too sparse usually; we collapse opp_set to a 3-mon "threats"
    # signature defined as the top-3 most-used opp species in their team-set,
    # ranked by global usage frequency. This gives us a ~tractable index that
    # still conditions on opp composition.
    by_own_threats: dict[tuple[frozenset, frozenset], LookupStats]
    species_usage: dict[str, float]  # global usage % for ranking threats

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    @classmethod
    def from_samples(cls, samples: Iterable[LeadSample], usage_path: Path | None = None) -> "LeadLookup":
        species_usage: dict[str, float] = {}
        if usage_path is not None and usage_path.exists():
            with open(usage_path) as f:
                d = json.load(f)
            for sp, info in d.items():
                if isinstance(info, dict) and "usage_pct" in info:
                    species_usage[sp] = float(info["usage_pct"])

        by_own: dict[frozenset, LookupStats] = defaultdict(LookupStats)
        by_threats: dict[tuple[frozenset, frozenset], LookupStats] = defaultdict(LookupStats)

        n_in = 0
        for s in samples:
            if len(s.own_leads) != 2 or s.own_leads[0] == s.own_leads[1]:
                continue
            n_in += 1
            pair = _sp_pair(*s.own_leads)
            own_key = frozenset(s.own_team)
            brought_set = frozenset(s.own_brought) if len(s.own_brought) == 4 else None

            # raw weight: winner_loser × rating, recomputed so callers can re-weight
            w = winner_loser_weight(s.is_winner, 0.5) * rating_weight(s.rating)

            stats = by_own[own_key]
            stats.pair_w[pair] += w
            stats.pair_n[pair] += 1
            if brought_set is not None:
                stats.brought_set_w[brought_set] += w
                stats.brought_set_n[brought_set] += 1
                for sp in brought_set:
                    stats.brought_member_w[sp] += w
            stats.total_w += w
            stats.total_n += 1

            threats = cls._threats_signature(s.opp_team, species_usage, k=3)
            tkey = (own_key, threats)
            tstats = by_threats[tkey]
            tstats.pair_w[pair] += w
            tstats.pair_n[pair] += 1
            if brought_set is not None:
                tstats.brought_set_w[brought_set] += w
                tstats.brought_set_n[brought_set] += 1
                for sp in brought_set:
                    tstats.brought_member_w[sp] += w
            tstats.total_w += w
            tstats.total_n += 1

        return cls(by_own=dict(by_own), by_own_threats=dict(by_threats), species_usage=species_usage)

    @staticmethod
    def _threats_signature(opp_team: list[str], usage: dict[str, float], k: int = 3) -> frozenset:
        ranked = sorted(opp_team, key=lambda sp: -usage.get(sp, 0.0))
        return frozenset(ranked[:k])

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        # frozensets pickle fine; convert Counters to plain dicts for size.
        payload = {
            "by_own": {tuple(sorted(k)): self._stats_to_dict(v) for k, v in self.by_own.items()},
            "by_own_threats": {
                (tuple(sorted(o)), tuple(sorted(t))): self._stats_to_dict(v)
                for (o, t), v in self.by_own_threats.items()
            },
            "species_usage": self.species_usage,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def _stats_to_dict(s: LookupStats) -> dict:
        return {
            "pair_w": dict(s.pair_w),
            "pair_n": dict(s.pair_n),
            "brought_set_w": {tuple(sorted(k)): v for k, v in s.brought_set_w.items()},
            "brought_set_n": {tuple(sorted(k)): v for k, v in s.brought_set_n.items()},
            "brought_member_w": dict(s.brought_member_w),
            "total_w": s.total_w,
            "total_n": s.total_n,
        }

    @classmethod
    def load(cls, path: Path) -> "LeadLookup":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        by_own = {}
        for k, v in payload["by_own"].items():
            stats = LookupStats(
                pair_w=Counter(v["pair_w"]),
                pair_n=Counter(v["pair_n"]),
                brought_set_w=Counter({frozenset(k): val for k, val in (v.get("brought_set_w") or {}).items()}),
                brought_set_n=Counter({frozenset(k): val for k, val in (v.get("brought_set_n") or {}).items()}),
                brought_member_w=Counter(v.get("brought_member_w") or {}),
                total_w=v["total_w"],
                total_n=v["total_n"],
            )
            by_own[frozenset(k)] = stats
        by_threats = {}
        for (o, t), v in payload["by_own_threats"].items():
            stats = LookupStats(
                pair_w=Counter(v["pair_w"]),
                pair_n=Counter(v["pair_n"]),
                brought_set_w=Counter({frozenset(k): val for k, val in (v.get("brought_set_w") or {}).items()}),
                brought_set_n=Counter({frozenset(k): val for k, val in (v.get("brought_set_n") or {}).items()}),
                brought_member_w=Counter(v.get("brought_member_w") or {}),
                total_w=v["total_w"],
                total_n=v["total_n"],
            )
            by_threats[(frozenset(o), frozenset(t))] = stats
        return cls(by_own=by_own, by_own_threats=by_threats,
                   species_usage=payload["species_usage"])

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def recommend(
        self,
        own_team: list[str],
        opp_team: list[str],
        *,
        min_count_threats: int = 5,
        min_count_own: int = 5,
        jaccard_floor: int = 5,
        top_k: int = 5,
    ) -> dict:
        """Return ranked lead pairs with provenance.

        Tier 1: exact own_team + opp threats signature (most specific, sparsest)
        Tier 2: exact own_team match (drops opp signal)
        Tier 3: Jaccard >= jaccard_floor over own_team (handles 1-mon swaps)
        Tier 4: empty — caller falls through to model
        """
        own_set = frozenset(own_team)
        threats = self._threats_signature(opp_team, self.species_usage, k=3)

        tier_used = "none"
        stats = self.by_own_threats.get((own_set, threats))
        if stats and stats.total_n >= min_count_threats:
            tier_used = "tier1_threats"
        else:
            stats = self.by_own.get(own_set)
            if stats and stats.total_n >= min_count_own:
                tier_used = "tier2_own"
            else:
                # Jaccard fallback over own_team
                merged = LookupStats()
                for k, v in self.by_own.items():
                    if len(own_set & k) >= jaccard_floor:
                        for pair, w in v.pair_w.items():
                            merged.pair_w[pair] += w
                        for pair, n in v.pair_n.items():
                            merged.pair_n[pair] += n
                        merged.total_w += v.total_w
                        merged.total_n += v.total_n
                if merged.total_n >= min_count_own:
                    stats = merged
                    tier_used = "tier3_jaccard"

        if stats is None or stats.total_n == 0:
            return {"tier": tier_used, "n": 0, "pairs": []}

        ranked = stats.pair_w.most_common(top_k)
        pairs = [
            {
                "pair": pair,
                "weight": round(w, 2),
                "count": stats.pair_n[pair],
                "share_w": round(w / stats.total_w, 4),
            }
            for pair, w in ranked
        ]
        return {"tier": tier_used, "n": stats.total_n, "n_w": round(stats.total_w, 2), "pairs": pairs}

    def recommend_team(
        self,
        own_team: list[str],
        opp_team: list[str],
        *,
        min_count_threats: int = 5,
        min_count_own: int = 5,
        jaccard_floor: int = 5,
        top_k_sets: int = 5,
    ) -> dict:
        """Pick which 4 of the 6 own_team to bring.

        Returns:
          tier: which fallback fired
          n: support count
          top_brought_sets: top frozensets of size-4 brought_4 picks (with weights)
          top_members: per-mon "share of brought instances" — useful as a logit-like signal
                       even when no full brought-set has enough support on its own.
        """
        own_set = frozenset(own_team)
        threats = self._threats_signature(opp_team, self.species_usage, k=3)

        tier_used = "none"
        stats = self.by_own_threats.get((own_set, threats))
        if stats and stats.total_n >= min_count_threats:
            tier_used = "tier1_threats"
        else:
            stats = self.by_own.get(own_set)
            if stats and stats.total_n >= min_count_own:
                tier_used = "tier2_own"
            else:
                merged = LookupStats()
                for k, v in self.by_own.items():
                    if len(own_set & k) >= jaccard_floor:
                        for spset, w in v.brought_set_w.items():
                            merged.brought_set_w[spset] += w
                        for spset, n in v.brought_set_n.items():
                            merged.brought_set_n[spset] += n
                        for sp, w in v.brought_member_w.items():
                            merged.brought_member_w[sp] += w
                        merged.total_w += v.total_w
                        merged.total_n += v.total_n
                if merged.total_n >= min_count_own:
                    stats = merged
                    tier_used = "tier3_jaccard"

        if stats is None or stats.total_n == 0:
            return {"tier": tier_used, "n": 0, "top_brought_sets": [], "top_members": []}

        # Top brought sets — but only those that are subsets of the queried own_team
        valid_sets = [
            (sp, w) for sp, w in stats.brought_set_w.items() if sp.issubset(own_set)
        ]
        valid_sets.sort(key=lambda x: -x[1])

        # Top members — per-mon weight, normalized to share of brought-instances
        member_total = sum(stats.brought_member_w.values())
        members = []
        if member_total > 0:
            for sp in own_team:
                w = stats.brought_member_w.get(sp, 0.0)
                members.append((sp, round(w / member_total, 4), round(w, 2)))
            members.sort(key=lambda x: -x[1])

        return {
            "tier": tier_used,
            "n": stats.total_n,
            "n_w": round(stats.total_w, 2),
            "top_brought_sets": [
                {
                    "set": tuple(sorted(s)),
                    "weight": round(w, 2),
                    "count": stats.brought_set_n.get(s, 0),
                    "share_w": round(w / stats.total_w, 4) if stats.total_w else 0.0,
                }
                for s, w in valid_sets[:top_k_sets]
            ],
            "top_members": members,
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def coverage_summary(self) -> dict:
        own_counts = [s.total_n for s in self.by_own.values()]
        threat_counts = [s.total_n for s in self.by_own_threats.values()]
        own_counts.sort(reverse=True)
        threat_counts.sort(reverse=True)
        return {
            "n_unique_own_teams": len(self.by_own),
            "n_unique_own_threat_keys": len(self.by_own_threats),
            "own_top10_counts": own_counts[:10],
            "own_pct_with_5plus": round(sum(1 for c in own_counts if c >= 5) / max(1, len(own_counts)) * 100, 2),
            "threats_pct_with_5plus": round(sum(1 for c in threat_counts if c >= 5) / max(1, len(threat_counts)) * 100, 2),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _samples_excluding_last_days(parsed_dir: Path, exclude_days: int, min_rating: int):
    day_dirs = sorted([p for p in parsed_dir.iterdir() if p.is_dir()])
    if exclude_days > 0:
        day_dirs = day_dirs[:-exclude_days]
    for d in day_dirs:
        for shard in sorted(d.glob("*.parquet")):
            yield from iter_samples_from_parquet(shard, min_rating=min_rating)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parsed-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--min-rating", type=int, default=1200)
    p.add_argument("--exclude-last-days", type=int, default=0,
                   help="Drop the last N calendar day-buckets (use to keep model val out of the index)")
    p.add_argument("--usage-stats", default="data/usage_stats/gen9championsvgc2026regma.json", type=Path)
    args = p.parse_args()

    t0 = time.time()
    if args.exclude_last_days > 0:
        samples = _samples_excluding_last_days(
            args.parsed_dir, args.exclude_last_days, args.min_rating
        )
    else:
        samples = iter_samples_from_dir(args.parsed_dir, min_rating=args.min_rating)
    lookup = LeadLookup.from_samples(samples, usage_path=args.usage_stats)
    print(json.dumps(lookup.coverage_summary(), indent=2))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lookup.save(args.out)
    print(f"saved {args.out}  ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
