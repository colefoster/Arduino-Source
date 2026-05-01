"""Pluggable usage-stats source.

Phase 2 of the pipeline redesign. Used by Layer 1 parsing (training-time) and
eventually by the live-inference encoder (deployment-time) — same interface,
different implementations.

Today's only implementation is `PikalyticsStatsSource`, backed by the JSON
file that `scripts/build_usage_stats.py` produces. A `MultiSourceStatsSource`
chain (try first, fall back) is the design path for adding replay-corpus or
Champions-game sources later.

Lookups return a `StatsLookup`: the most-likely value, an absolute probability
(0..1), and a `source_id` that records *which* snapshot produced the guess.
The probability is data, not a tuning knob — it's the actual usage frequency
recorded by the source.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StatsLookup:
    """Result of one stats query.

    `value` is the most-likely item/ability/move name (case-preserved as in
    the source). `prob` is the absolute usage frequency in 0..1. `source_id`
    identifies which snapshot produced this guess (e.g. "pikalytics-2026-04-30").

    For "no data" results, `value` is "" and `prob` is 0.0. Callers should not
    treat empty-value results as errors — they're a real outcome of the lookup
    interface (some species are too rare for any source to have data on them).
    """
    value: str
    prob: float
    source_id: str

    @classmethod
    def empty(cls, source_id: str) -> StatsLookup:
        return cls(value="", prob=0.0, source_id=source_id)


class UsageStatsSource(Protocol):
    """Pluggable source of per-species usage statistics.

    Implementations: `PikalyticsStatsSource` (now). Future: `ReplayCorpusStatsSource`,
    `ChampionsGameStatsSource`, `MultiSourceStatsSource` (chain).

    The interface intentionally returns one best-guess + probability per slot
    rather than a full distribution. If a downstream consumer ever needs the
    distribution, that's a separate method we can add — keeping this minimal
    keeps the surface area small.
    """

    @property
    def source_id(self) -> str:
        """Identifier for this source/snapshot. Stored per-row in Layer 1."""
        ...

    def lookup_item(self, species: str) -> StatsLookup:
        """Most-common item for this species + its frequency."""
        ...

    def lookup_ability(self, species: str) -> StatsLookup:
        """Most-common ability for this species + its frequency."""
        ...

    def lookup_moves(self, species: str, n: int = 4) -> list[StatsLookup]:
        """Top-n moves for this species. Each entry has its own probability."""
        ...

    def coverage_score(self, species: str) -> float:
        """How confident this source is in this species' stats, 0..1.

        Used by `MultiSourceStatsSource` to decide whether to fall back. A
        Pikalytics species with full team data scores ~1.0; a species not in
        the source at all scores 0.0.
        """
        ...


# ---------------------------------------------------------------------------
# Pikalytics implementation
# ---------------------------------------------------------------------------

DEFAULT_PIKALYTICS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "usage_stats" / "gen9championsvgc2026regma.json"
)


class PikalyticsStatsSource:
    """`UsageStatsSource` backed by a Pikalytics JSON snapshot.

    The JSON file is produced by `scripts/build_usage_stats.py` (an unrelated
    runtime concern — the scraper writes the file, this class only reads it).
    Pikalytics percentages are 0..100; this class normalizes to 0..1 in
    `StatsLookup.prob`.

    `source_id` is `"pikalytics-YYYY-MM-DD"` derived from the snapshot's mtime
    (UTC). Treat the file as immutable once written; new scrapes overwrite it
    and bump the implicit source_id.
    """

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else DEFAULT_PIKALYTICS_PATH
        with open(self._path, encoding="utf-8") as f:
            self._data: dict = json.load(f)
        mtime = datetime.fromtimestamp(self._path.stat().st_mtime, tz=timezone.utc)
        self._source_id = f"pikalytics-{mtime.strftime('%Y-%m-%d')}"

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def species_list(self) -> list[str]:
        return list(self._data.keys())

    def has_species(self, species: str) -> bool:
        return species in self._data

    def lookup_item(self, species: str) -> StatsLookup:
        return self._top_of(species, "items")

    def lookup_ability(self, species: str) -> StatsLookup:
        return self._top_of(species, "abilities")

    def lookup_moves(self, species: str, n: int = 4) -> list[StatsLookup]:
        entry = self._data.get(species)
        if not entry or not entry.get("moves"):
            return []
        items = list(entry["moves"].items())[:n]
        return [
            StatsLookup(value=name, prob=self._pct_to_prob(pct), source_id=self._source_id)
            for name, pct in items
        ]

    def coverage_score(self, species: str) -> float:
        entry = self._data.get(species)
        if not entry:
            return 0.0
        # Heuristic: full coverage if we have at least one item, ability, and
        # one move. Halve the score for each missing slot. Tunable later but
        # keeps things simple.
        score = 0.0
        if entry.get("items"):
            score += 0.4
        if entry.get("abilities"):
            score += 0.3
        if entry.get("moves"):
            score += 0.3
        return score

    def _top_of(self, species: str, key: str) -> StatsLookup:
        entry = self._data.get(species)
        if not entry or not entry.get(key):
            return StatsLookup.empty(self._source_id)
        first_name, first_pct = next(iter(entry[key].items()))
        return StatsLookup(
            value=first_name,
            prob=self._pct_to_prob(first_pct),
            source_id=self._source_id,
        )

    @staticmethod
    def _pct_to_prob(value: float) -> float:
        """Pikalytics stores percentages 0..100; normalize to 0..1.

        Defensive clamp in case any source returns an out-of-range value.
        """
        return max(0.0, min(1.0, float(value) / 100.0))
