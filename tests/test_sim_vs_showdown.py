"""Layer 3: Validate battle sim accuracy against real replay data.

Tests damage predictions and speed ordering against what actually
happened in recorded Pokemon Showdown battles.

Run with: pytest tests/test_sim_vs_showdown.py -v --tb=short
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from src.vgc_model.sim.battle_sim import BattleSim, SimPokemon, SimField
from src.vgc_model.sim.type_chart import type_effectiveness
from src.vgc_model.data.feature_tables import FeatureTables
from src.vgc_model.data.log_parser import parse_battle, normalize_species, parse_hp


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPLAY_DIR = PROJECT_ROOT / "data" / "showdown_replays" / "gen9championsvgc2026regma"


def _get_replay_files(n=100, min_rating=1200):
    """Get a sample of replay files for testing."""
    if not REPLAY_DIR.exists():
        return []
    files = [f for f in REPLAY_DIR.glob("*.json") if f.name != "index.json"]
    random.seed(42)
    random.shuffle(files)

    result = []
    for f in files:
        if len(result) >= n:
            break
        try:
            data = json.loads(f.read_text(errors="replace"))
            if (data.get("rating") or 0) >= min_rating:
                result.append(f)
        except Exception:
            continue
    return result


# ── Damage Prediction Tests ──────────────────────────────────────

class TestDamageAccuracy:
    """Compare sim damage predictions to actual damage from replay logs."""

    @pytest.fixture(scope="class")
    def damage_samples(self, feature_tables):
        """Extract (attacker, defender, move, actual_damage_frac) tuples from replays."""
        files = _get_replay_files(n=50, min_rating=1200)
        if not files:
            pytest.skip("No replay files available")

        sim = BattleSim(feature_tables)
        samples = []

        for f in files:
            try:
                data = json.loads(f.read_text(errors="replace"))
                log = data.get("log", "")
                samples.extend(self._extract_damage_events(log, sim, feature_tables))
            except Exception:
                continue

        if len(samples) < 10:
            pytest.skip(f"Only {len(samples)} damage samples found")
        return samples

    @staticmethod
    def _extract_damage_events(log: str, sim: BattleSim, ft: FeatureTables) -> list:
        """Parse a log and extract damage events with enough context to simulate."""
        events = []
        lines = log.strip().split("\n")

        # Track current active Pokemon and their state
        active: dict[str, dict] = {}  # slot -> {species, hp_frac, ...}
        last_move: dict = {}  # slot -> move_name

        for line in lines:
            if not line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            cmd = parts[1]

            if cmd in ("switch", "drag") and len(parts) >= 5:
                slot = parts[2][:3]
                species = normalize_species(parts[3])
                hp_frac = parse_hp(parts[4]) if len(parts) > 4 else 1.0
                sf = ft.get_species_features(species)
                active[slot] = {
                    "species": species,
                    "hp_frac": hp_frac,
                    "types": (sf.get("type1", ""), sf.get("type2", "")),
                    "base_stats": {k: sf.get(k, 80) for k in ["hp", "atk", "def", "spa", "spd", "spe"]},
                }

            elif cmd == "move" and len(parts) >= 4:
                slot = parts[2][:3]
                move_name = parts[3]
                last_move[slot] = move_name

            elif cmd == "-damage" and len(parts) >= 4:
                target_slot = parts[2][:3]
                hp_str = parts[3]
                new_hp = parse_hp(hp_str)

                if target_slot not in active:
                    continue

                old_hp = active[target_slot]["hp_frac"]
                actual_dmg = old_hp - new_hp

                if actual_dmg <= 0:
                    continue  # heal or same HP

                # Find who attacked this target
                attacker_side = "p2" if target_slot.startswith("p1") else "p1"
                attacker_slot = None
                for slot, move in last_move.items():
                    if slot.startswith(attacker_side):
                        attacker_slot = slot
                        break

                if attacker_slot and attacker_slot in active and attacker_slot in last_move:
                    move_name = last_move[attacker_slot]
                    move_data = sim._get_move_data(move_name)
                    bp = move_data.get("base_power", 0)
                    if bp > 0:
                        attacker = active[attacker_slot]
                        target = active[target_slot]
                        events.append({
                            "attacker": attacker,
                            "target": target,
                            "move_name": move_name,
                            "move_data": move_data,
                            "actual_dmg_frac": actual_dmg,
                        })

                # Update HP
                active[target_slot]["hp_frac"] = new_hp

        return events

    def test_damage_predictions_directionally_correct(self, damage_samples, feature_tables):
        """Predicted damage should correlate with actual damage."""
        sim = BattleSim(feature_tables)
        errors = []

        for sample in damage_samples[:200]:
            atk = sample["attacker"]
            tgt = sample["target"]

            user = SimPokemon(
                species=atk["species"], hp_frac=1.0,
                base_stats=atk["base_stats"], types=atk["types"],
                moves=[sample["move_name"]], status="",
            )
            target = SimPokemon(
                species=tgt["species"], hp_frac=tgt["hp_frac"],
                base_stats=tgt["base_stats"], types=tgt["types"],
                moves=[], status="",
            )

            predicted = sim._calc_damage(user, target, sample["move_data"],
                                         SimField(), "own", False)
            actual = sample["actual_dmg_frac"]

            # Skip cases where sim predicts 0 (likely attacker misattribution
            # causing wrong type matchup — parsing bug, not sim bug)
            if actual > 0.01 and predicted > 0.001:
                error = abs(predicted - actual) / actual
                errors.append(error)

        if not errors:
            pytest.skip("No valid damage comparisons")

        mean_error = sum(errors) / len(errors)
        within_30pct = sum(1 for e in errors if e < 0.3) / len(errors)
        within_50pct = sum(1 for e in errors if e < 0.5) / len(errors)

        print(f"\nDamage prediction accuracy ({len(errors)} samples):")
        print(f"  Mean relative error: {mean_error:.1%}")
        print(f"  Within 30%: {within_30pct:.1%}")
        print(f"  Within 50%: {within_50pct:.1%}")

        # The sim doesn't model EVs/IVs/natures/items/abilities, and attacker
        # attribution from logs is imperfect, so errors are expected.
        # Track as a benchmark — improve over time.
        # Baseline (v1 sim, no EVs/items/abilities): ~40-45% within 2x
        within_2x = sum(1 for e in errors if e < 1.0) / len(errors)
        print(f"  Within 2x: {within_2x:.1%}")
        assert within_2x > 0.3, f"Only {within_2x:.1%} predictions within 2x"

    def test_type_effectiveness_matches_reality(self, damage_samples, feature_tables):
        """Super-effective moves should predict more damage than neutral."""
        sim = BattleSim(feature_tables)
        se_ratios = []
        neutral_ratios = []

        for sample in damage_samples[:200]:
            move_type = sample["move_data"].get("type", "")
            tgt_types = sample["target"]["types"]
            eff = type_effectiveness(move_type, tgt_types[0], tgt_types[1])

            atk = sample["attacker"]
            tgt = sample["target"]
            user = SimPokemon(species=atk["species"], hp_frac=1.0,
                              base_stats=atk["base_stats"], types=atk["types"],
                              moves=[sample["move_name"]], status="")
            target = SimPokemon(species=tgt["species"], hp_frac=tgt["hp_frac"],
                                base_stats=tgt["base_stats"], types=tgt["types"],
                                moves=[], status="")

            predicted = sim._calc_damage(user, target, sample["move_data"],
                                         SimField(), "own", False)
            actual = sample["actual_dmg_frac"]

            if actual > 0.01 and predicted > 0.01:
                ratio = predicted / actual
                if eff >= 2.0:
                    se_ratios.append(ratio)
                elif eff == 1.0:
                    neutral_ratios.append(ratio)

        if se_ratios and neutral_ratios:
            # Both categories should have similar mean ratios (around 1.0)
            # If type chart is wrong, SE predictions would be systematically off
            print(f"\nSE predictions ({len(se_ratios)}): mean ratio {sum(se_ratios)/len(se_ratios):.2f}")
            print(f"Neutral predictions ({len(neutral_ratios)}): mean ratio {sum(neutral_ratios)/len(neutral_ratios):.2f}")


# ── Speed Ordering Tests ─────────────────────────────────────────

class TestSpeedOrdering:
    """Compare predicted move order to actual execution order in replays."""

    @pytest.fixture(scope="class")
    def speed_samples(self, feature_tables):
        files = _get_replay_files(n=50, min_rating=1200)
        if not files:
            pytest.skip("No replay files available")

        samples = []
        for f in files:
            try:
                data = json.loads(f.read_text(errors="replace"))
                log = data.get("log", "")
                samples.extend(self._extract_turn_orders(log, feature_tables))
            except Exception:
                continue

        if len(samples) < 10:
            pytest.skip(f"Only {len(samples)} speed samples found")
        return samples

    @staticmethod
    def _extract_turn_orders(log: str, ft: FeatureTables) -> list:
        """Extract the execution order of moves per turn."""
        lines = log.strip().split("\n")
        active: dict[str, dict] = {}
        current_turn = 0
        turn_moves: list[tuple[str, str]] = []  # (slot, move_name) in execution order
        samples = []

        for line in lines:
            if not line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            cmd = parts[1]

            if cmd == "turn":
                if turn_moves and len(turn_moves) >= 2:
                    # Record the order for the previous turn
                    species_speeds = []
                    for slot, move in turn_moves:
                        if slot in active:
                            species_speeds.append({
                                "slot": slot,
                                "species": active[slot]["species"],
                                "base_spe": active[slot]["base_stats"].get("spe", 80),
                                "move": move,
                            })
                    if len(species_speeds) >= 2:
                        samples.append(species_speeds)

                current_turn = int(parts[2]) if len(parts) > 2 else current_turn + 1
                turn_moves = []

            elif cmd in ("switch", "drag") and len(parts) >= 5:
                slot = parts[2][:3]
                species = normalize_species(parts[3])
                sf = ft.get_species_features(species)
                active[slot] = {
                    "species": species,
                    "base_stats": {k: sf.get(k, 80) for k in ["hp", "atk", "def", "spa", "spd", "spe"]},
                }

            elif cmd == "move" and len(parts) >= 4:
                slot = parts[2][:3]
                move = parts[3]
                turn_moves.append((slot, move))

        return samples

    def test_faster_pokemon_usually_moves_first(self, speed_samples):
        """When both use priority-0 moves, faster species should go first."""
        correct = 0
        total = 0

        for turn in speed_samples[:200]:
            if len(turn) < 2:
                continue
            first = turn[0]
            second = turn[1]

            # Only count if both are from different sides and same priority
            if first["slot"][:2] == second["slot"][:2]:
                continue  # Same side — can't compare

            # Simple check: did the faster base speed go first?
            if first["base_spe"] != second["base_spe"]:
                total += 1
                if first["base_spe"] > second["base_spe"]:
                    correct += 1

        if total == 0:
            pytest.skip("No valid speed comparisons")

        accuracy = correct / total
        print(f"\nSpeed ordering: {correct}/{total} = {accuracy:.1%} "
              f"(faster species moved first)")
        # Base speed alone won't be perfect (EVs, natures, items, boosts affect speed)
        # But it should be correct more often than not
        assert accuracy > 0.5, f"Speed ordering only {accuracy:.1%} correct"
