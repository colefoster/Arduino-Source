"""Player profile lookup for enriching battle data with cross-game knowledge.

Loads per-player team histories built by scripts/build_player_profiles.py
and provides inference methods for filling unknown move/item/ability slots.
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_FORMAT = "gen9championsvgc2026regma"


class PlayerProfiles:
    """Loads player profiles and provides lookup/inference methods.

    Handles both single-file and sharded (per-letter) profile formats.
    """

    def __init__(self, data_dir: str | Path | None = None, format_name: str = DEFAULT_FORMAT):
        self._profiles: dict[str, dict] = {}
        self._sharded = False
        self._shard_index: dict[str, dict] = {}
        self._loaded_shards: set[str] = set()
        self._data_dir: Path | None = None
        self._format = format_name

        if data_dir is None:
            data_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "player_profiles"

        data_dir = Path(data_dir)
        if not data_dir.exists():
            return

        self._data_dir = data_dir

        # Check for sharded format first
        index_path = data_dir / f"{format_name}_index.json"
        if index_path.exists():
            self._sharded = True
            self._shard_index = json.loads(index_path.read_text(encoding="utf-8"))
            return

        # Single file
        single_path = data_dir / f"{format_name}.json"
        if single_path.exists():
            self._profiles = json.loads(single_path.read_text(encoding="utf-8"))

    def _ensure_shard_loaded(self, letter: str):
        """Lazily load a shard file when needed."""
        if not self._sharded or letter in self._loaded_shards:
            return
        self._loaded_shards.add(letter)

        shard_info = self._shard_index.get(letter)
        if not shard_info or not self._data_dir:
            return

        shard_path = self._data_dir / shard_info["file"]
        if shard_path.exists():
            shard_data = json.loads(shard_path.read_text(encoding="utf-8"))
            self._profiles.update(shard_data)

    def get_profile(self, player_name: str) -> dict | None:
        """Look up a player's full profile.

        Returns dict with keys: games, display_name, pokemon
        or None if player not found.
        """
        key = player_name.lower().strip()
        if not key:
            return None

        if self._sharded:
            letter = key[0] if key[0].isalpha() else "_"
            self._ensure_shard_loaded(letter)

        return self._profiles.get(key)

    def infer_moveset(
        self, player_name: str, species: str, known_moves: list[str]
    ) -> list[str] | None:
        """Fill unknown move slots from player's history for this species.

        Returns a list of up to 4 moves (known + inferred) ordered by
        frequency, or None if no player data exists for this species.
        """
        profile = self.get_profile(player_name)
        if not profile:
            return None

        sp_data = profile["pokemon"].get(species)
        if not sp_data:
            return None

        # Start with known moves
        result = list(known_moves)
        known_set = {m.lower() for m in known_moves}

        # Fill remaining slots from player's most-used moves for this species
        sorted_moves = sorted(sp_data["moves"].items(), key=lambda x: x[1], reverse=True)
        for move, _count in sorted_moves:
            if len(result) >= 4:
                break
            if move.lower() not in known_set:
                result.append(move)
                known_set.add(move.lower())

        return result if len(result) > len(known_moves) else result

    def infer_item(self, player_name: str, species: str) -> str | None:
        """Return the player's most-used item for this species, or None."""
        profile = self.get_profile(player_name)
        if not profile:
            return None

        sp_data = profile["pokemon"].get(species)
        if not sp_data or not sp_data["items"]:
            return None

        return max(sp_data["items"], key=sp_data["items"].get)

    def infer_ability(self, player_name: str, species: str) -> str | None:
        """Return the player's most-used ability for this species, or None."""
        profile = self.get_profile(player_name)
        if not profile:
            return None

        sp_data = profile["pokemon"].get(species)
        if not sp_data or not sp_data["abilities"]:
            return None

        return max(sp_data["abilities"], key=sp_data["abilities"].get)

    def __len__(self) -> int:
        """Number of loaded player profiles."""
        if self._sharded:
            return sum(s["players"] for s in self._shard_index.values())
        return len(self._profiles)

    def __repr__(self) -> str:
        return f"PlayerProfiles({len(self)} players, format={self._format!r})"

    # -- Protocol adapters (satisfy enriched_parser.PlayerProfiles Protocol) --

    def get_moves(self, player: str, species: str) -> list[str]:
        return self.infer_moveset(player, species, []) or []

    def get_item(self, player: str, species: str) -> str:
        return self.infer_item(player, species) or ""

    def get_ability(self, player: str, species: str) -> str:
        return self.infer_ability(player, species) or ""
