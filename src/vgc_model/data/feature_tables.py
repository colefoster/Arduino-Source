"""Feature lookup tables for species, moves, items, and abilities.

Loads pre-built JSON feature tables and provides dict/tensor lookup methods.
"""

import json
from pathlib import Path
from typing import Dict, List

import torch

TABLES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "feature_tables"

# All 18 Pokemon types for one-hot encoding
TYPES = [
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
    "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
]
TYPE_TO_IDX = {t: i for i, t in enumerate(TYPES)}

# Move categories
MOVE_CATEGORIES = ["Physical", "Special", "Status"]
MOVE_CAT_TO_IDX = {c: i for i, c in enumerate(MOVE_CATEGORIES)}

# Move targets (most common in VGC)
MOVE_TARGETS = ["normal", "allAdjacentFoes", "self", "adjacentAlly", "allAdjacent",
                "adjacentFoe", "all", "foeSide", "allySide", "allyTeam", "any",
                "scripted", "randomNormal"]
MOVE_TARGET_TO_IDX = {t: i for i, t in enumerate(MOVE_TARGETS)}

# Item categories
ITEM_CATEGORIES = ["berry", "choice", "mega_stone", "focus_sash", "recovery",
                   "life_orb", "stat_boost", "resist_berry", "misc"]
ITEM_CAT_TO_IDX = {c: i for i, c in enumerate(ITEM_CATEGORIES)}

# Ability categories
ABILITY_CATEGORIES = [
    "weather_setter", "terrain_setter", "intimidate_like", "stat_boost_on_switch",
    "contact_punish", "immunity", "speed_control", "mold_breaker_like",
    "team_support", "power_boost", "defensive", "disruption", "recovery", "misc",
]
ABILITY_CAT_TO_IDX = {c: i for i, c in enumerate(ABILITY_CATEGORIES)}

# Secondary statuses for one-hot
SECONDARY_STATUSES = ["brn", "par", "slp", "frz", "psn", "tox"]
SEC_STATUS_TO_IDX = {s: i for i, s in enumerate(SECONDARY_STATUSES)}

# Normalization constants
MAX_BASE_STAT = 255
MAX_BST = 780
MAX_WEIGHT = 999.9
MAX_BASE_POWER = 250
MAX_PRIORITY = 12  # range is -7 to +5, we shift by 7
MAX_ABILITY_RATING = 5


class FeatureTables:
    """Loads feature JSONs and provides lookup + tensor conversion."""

    def __init__(self, tables_dir: Path = TABLES_DIR):
        self._species = self._load(tables_dir / "species_features.json")
        self._moves = self._load(tables_dir / "move_features.json")
        self._items = self._load(tables_dir / "item_features.json")
        self._abilities = self._load(tables_dir / "ability_features.json")

    @staticmethod
    def _load(path: Path) -> Dict:
        return json.loads(path.read_text(encoding="utf-8"))

    # ── dict lookups (return zeroed defaults for unknown names) ───────

    def get_species_features(self, name: str) -> dict:
        return self._species.get(name, {
            "hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0,
            "type1": "", "type2": "", "weight_kg": 0, "bst": 0,
            "is_fully_evolved": False, "is_mega": False,
        })

    def get_move_features(self, name: str) -> dict:
        return self._moves.get(name, {
            "base_power": 0, "accuracy": 0, "priority": 0,
            "type": "", "category": "", "target": "",
            "contact": False, "sound": False,
            "secondary_chance": 0, "secondary_flinch": False, "secondary_status": "",
            "drain": 0, "recoil": 0,
            "self_switch": False, "force_switch": False, "stalling_move": False,
            "sets_weather": False, "sets_terrain": False, "sets_side_condition": False,
        })

    def get_item_features(self, name: str) -> dict:
        return self._items.get(name, {
            "category": "misc", "is_berry": False, "is_choice": False,
            "is_mega_stone": False, "is_focus_sash": False,
        })

    def get_ability_features(self, name: str) -> dict:
        return self._abilities.get(name, {
            "rating": 0, "breakable": False, "category": "misc",
        })

    # ── tensor conversion ────────────────────────────────────────────

    @staticmethod
    def to_tensor(features: dict, feature_type: str) -> torch.Tensor:
        """Convert a feature dict to a flat float tensor.

        Args:
            features: dict from one of the get_*_features methods
            feature_type: one of "species", "move", "item", "ability"
        """
        if feature_type == "species":
            return _species_to_tensor(features)
        elif feature_type == "move":
            return _move_to_tensor(features)
        elif feature_type == "item":
            return _item_to_tensor(features)
        elif feature_type == "ability":
            return _ability_to_tensor(features)
        else:
            raise ValueError(f"Unknown feature_type: {feature_type}")


def _one_hot(idx: int, size: int) -> List[float]:
    vec = [0.0] * size
    if 0 <= idx < size:
        vec[idx] = 1.0
    return vec


def _species_to_tensor(f: dict) -> torch.Tensor:
    """Species → 45d tensor: 6 stats + 18 type1 + 18 type2 + weight + bst + evolved + mega"""
    vals = [
        f["hp"] / MAX_BASE_STAT,
        f["atk"] / MAX_BASE_STAT,
        f["def"] / MAX_BASE_STAT,
        f["spa"] / MAX_BASE_STAT,
        f["spd"] / MAX_BASE_STAT,
        f["spe"] / MAX_BASE_STAT,
    ]
    vals += _one_hot(TYPE_TO_IDX.get(f["type1"], -1), len(TYPES))
    vals += _one_hot(TYPE_TO_IDX.get(f["type2"], -1), len(TYPES))
    vals += [
        f["weight_kg"] / MAX_WEIGHT,
        f["bst"] / MAX_BST,
        float(f["is_fully_evolved"]),
        float(f["is_mega"]),
    ]
    return torch.tensor(vals, dtype=torch.float32)


def _move_to_tensor(f: dict) -> torch.Tensor:
    """Move → 48d tensor per the plan."""
    vals = [
        f["base_power"] / MAX_BASE_POWER,
        f["accuracy"] / 100.0 if f["accuracy"] else 0.0,
        (f["priority"] + 7) / MAX_PRIORITY,  # shift to 0-1 range
    ]
    vals += _one_hot(TYPE_TO_IDX.get(f["type"], -1), len(TYPES))
    vals += _one_hot(MOVE_CAT_TO_IDX.get(f["category"], -1), len(MOVE_CATEGORIES))
    vals += _one_hot(MOVE_TARGET_TO_IDX.get(f["target"], -1), len(MOVE_TARGETS))
    vals += [
        float(f["contact"]),
        float(f["sound"]),
        float(bool(f["secondary_chance"])),  # has secondary effect
        f["secondary_chance"] / 100.0,
        float(f["secondary_flinch"]),
    ]
    vals += _one_hot(SEC_STATUS_TO_IDX.get(f["secondary_status"], -1), len(SECONDARY_STATUSES))
    vals += [
        float(f["drain"]),
        float(f["recoil"]),
        float(f["self_switch"]),
        float(f["force_switch"]),
        float(f["stalling_move"]),
        float(f["sets_weather"]),
        float(f["sets_terrain"]),
        float(f["sets_side_condition"]),
    ]
    return torch.tensor(vals, dtype=torch.float32)


def _item_to_tensor(f: dict) -> torch.Tensor:
    """Item → 13d tensor: 9 category one-hot + 4 binary flags."""
    vals = _one_hot(ITEM_CAT_TO_IDX.get(f["category"], -1), len(ITEM_CATEGORIES))
    vals += [
        float(f["is_berry"]),
        float(f["is_choice"]),
        float(f["is_mega_stone"]),
        float(f["is_focus_sash"]),
    ]
    return torch.tensor(vals, dtype=torch.float32)


def _ability_to_tensor(f: dict) -> torch.Tensor:
    """Ability → 16d tensor: 14 category one-hot + rating + breakable."""
    vals = [f["rating"] / MAX_ABILITY_RATING]
    vals += _one_hot(ABILITY_CAT_TO_IDX.get(f["category"], -1), len(ABILITY_CATEGORIES))
    vals += [float(f["breakable"])]
    return torch.tensor(vals, dtype=torch.float32)
