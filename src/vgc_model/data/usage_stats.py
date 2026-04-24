"""Per-species usage statistics for Champions VGC format.

Loads the JSON produced by scripts/build_usage_stats.py and provides
inference methods for filling unknown move/item/ability slots.

Handles both source types transparently:
  - Pikalytics: values are percentages (0-100)
  - Replays: values are raw counts
Both are ranked the same way (higher = more common).
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_STATS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "usage_stats" / "gen9championsvgc2026regma.json"
)


class UsageStats:
    """Load and query per-species usage statistics."""

    def __init__(self, path: str | Path | None = None):
        path = Path(path) if path else DEFAULT_STATS_PATH
        with open(path) as f:
            self._data: dict = json.load(f)

    @property
    def species_list(self) -> list[str]:
        return list(self._data.keys())

    def has_species(self, species: str) -> bool:
        return species in self._data

    def get_source(self, species: str) -> str | None:
        entry = self._data.get(species)
        return entry["source"] if entry else None

    def get_likely_moves(self, species: str, n: int = 4) -> list[str]:
        """Top N moves by usage %/count."""
        entry = self._data.get(species)
        if not entry or not entry.get("moves"):
            return []
        # Already sorted by value in JSON (descending for replays; Pikalytics order is by %)
        moves = list(entry["moves"].keys())
        return moves[:n]

    def get_likely_item(self, species: str) -> str | None:
        """Most common item."""
        entry = self._data.get(species)
        if not entry or not entry.get("items"):
            return None
        return next(iter(entry["items"]))

    def get_likely_ability(self, species: str) -> str | None:
        """Most common ability."""
        entry = self._data.get(species)
        if not entry or not entry.get("abilities"):
            return None
        return next(iter(entry["abilities"]))

    def infer_moveset(self, species: str, known_moves: list[str] | None = None) -> list[str]:
        """Fill unknown slots with most likely moves not already known.

        Returns a full 4-move set. If fewer than 4 moves are available
        in the data, returns as many as possible.
        """
        known = list(known_moves) if known_moves else []
        entry = self._data.get(species)
        if not entry or not entry.get("moves"):
            return known[:4]

        known_lower = {m.lower() for m in known}
        candidates = [
            m for m in entry["moves"]
            if m.lower() not in known_lower
        ]

        result = list(known)
        for move in candidates:
            if len(result) >= 4:
                break
            result.append(move)
        return result[:4]

    def get_sample_sets(self, species: str) -> list[dict]:
        """Return featured tournament sets (Pikalytics source only).

        Each set is a dict with keys: moves, item, ability.
        Returns empty list for replay-sourced species.
        """
        entry = self._data.get(species)
        if not entry:
            return []
        return entry.get("sample_sets", [])

    def get_teammates(self, species: str) -> dict[str, float]:
        """Return teammate usage percentages (Pikalytics source only)."""
        entry = self._data.get(species)
        if not entry:
            return {}
        return entry.get("teammates", {})

    def get_move_probability(self, species: str, move: str) -> float:
        """Get the usage value for a specific move on a species.

        Returns percentage (0-100) for Pikalytics, raw count for replays, 0.0 if unknown.
        """
        entry = self._data.get(species)
        if not entry or not entry.get("moves"):
            return 0.0
        return entry["moves"].get(move, 0.0)

    def get_all_moves(self, species: str) -> dict[str, float]:
        """Get all moves with their usage values for a species."""
        entry = self._data.get(species)
        if not entry:
            return {}
        return dict(entry.get("moves", {}))

    def get_all_items(self, species: str) -> dict[str, float]:
        """Get all items with their usage values for a species."""
        entry = self._data.get(species)
        if not entry:
            return {}
        return dict(entry.get("items", {}))

    def get_all_abilities(self, species: str) -> dict[str, float]:
        """Get all abilities with their usage values for a species."""
        entry = self._data.get(species)
        if not entry:
            return {}
        return dict(entry.get("abilities", {}))
