#!/usr/bin/env python3
"""Migrate test_images manifests to unified BattleHUDReader format.

Collapses legacy split keys
  SpeciesReader, SpeciesReader_Doubles,
  OpponentHPReader, OpponentHPReader_Doubles,
  legacy scalar BattleHUDReader fields
into a single per-image
  BattleHUDReader: {
    opponent_species: [str, str],
    opponent_hp_pct:  [int, int],
    own_species:      [str, str],
    own_hp_current:   [int, int],
    own_hp_max:       [int, int],
  }

Conservative + idempotent: arrays already in the new shape pass through
unchanged. Unknown slots become "" or -1.

Run:
  python3 tools/migrate_battlehud_manifest.py
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = [
    REPO / "test_images" / "action_menu" / "manifest.json",
    REPO / "test_images" / "move_select" / "manifest.json",
]

EMPTY_STR_PAIR = ["", ""]
EMPTY_INT_PAIR = [-1, -1]


def _str_pair(value, slot=None):
    if isinstance(value, list):
        out = list(value) + [""] * (2 - len(value))
        return [str(v) if v is not None else "" for v in out[:2]]
    pair = ["", ""]
    if isinstance(value, str) and value:
        idx = slot if slot in (0, 1) else 0
        pair[idx] = value
    return pair


def _int_pair(value, slot=None):
    if isinstance(value, list):
        out = list(value) + [-1] * (2 - len(value))
        return [int(v) if isinstance(v, (int, float)) else -1 for v in out[:2]]
    pair = [-1, -1]
    if isinstance(value, (int, float)):
        idx = slot if slot in (0, 1) else 0
        pair[idx] = int(value)
    return pair


def _merge_pair(base, override, fill):
    """Override slot N when base slot N is empty (fill sentinel)."""
    out = list(base)
    for i in range(2):
        if out[i] == fill and override[i] != fill:
            out[i] = override[i]
    return out


def migrate_entry(labels: dict) -> dict:
    out = dict(labels)
    existing = out.get("BattleHUDReader", {}) or {}

    species = _str_pair(existing.get("opponent_species"))
    hp_pct  = _int_pair(existing.get("opponent_hp_pct"))
    own_sp  = _str_pair(existing.get("own_species"))
    own_cur = _int_pair(existing.get("own_hp_current"))
    own_max = _int_pair(existing.get("own_hp_max"))

    #  Mode preserved from existing entry if present; otherwise inferred
    #  from any populated slot 1, then refined below by detecting legacy
    #  *_Doubles top-level keys.
    mode = existing.get("mode")
    if mode not in ("singles", "doubles"):
        mode = None

    sr = out.pop("SpeciesReader", None)
    if isinstance(sr, dict):
        species = _merge_pair(species, _str_pair(sr.get("opponent_species")), "")

    srd = out.pop("SpeciesReader_Doubles", None)
    if isinstance(srd, dict):
        species = _merge_pair(
            species,
            _str_pair(srd.get("opponent_species"), srd.get("slot")),
            "",
        )
        mode = "doubles"

    hpr = out.pop("OpponentHPReader", None)
    if isinstance(hpr, dict):
        hp_pct = _merge_pair(hp_pct, _int_pair(hpr.get("opponent_hp_pct")), -1)

    hprd = out.pop("OpponentHPReader_Doubles", None)
    if isinstance(hprd, dict):
        hp_pct = _merge_pair(
            hp_pct,
            _int_pair(hprd.get("opponent_hp_pct"), hprd.get("slot")),
            -1,
        )
        mode = "doubles"

    if mode is None:
        any_slot1 = (
            species[1] != "" or own_sp[1] != ""
            or hp_pct[1] != -1 or own_cur[1] != -1 or own_max[1] != -1
        )
        mode = "doubles" if any_slot1 else "singles"

    out["BattleHUDReader"] = {
        "mode":             mode,
        "opponent_species": species,
        "opponent_hp_pct":  hp_pct,
        "own_species":      own_sp,
        "own_hp_current":   own_cur,
        "own_hp_max":       own_max,
    }
    return out


def main():
    for path in TARGETS:
        if not path.exists():
            print(f"skip (not found): {path}")
            continue
        data = json.loads(path.read_text())
        migrated = {fname: migrate_entry(labels) for fname, labels in data.items()}
        path.write_text(json.dumps(migrated, indent=2) + "\n")
        print(f"migrated: {path}  ({len(migrated)} entries)")


if __name__ == "__main__":
    main()
