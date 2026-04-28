"""Shared fixtures for VGC battle sim and search engine tests."""

import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def feature_tables():
    from src.vgc_model.data.feature_tables import FeatureTables
    return FeatureTables()


@pytest.fixture(scope="session")
def battle_sim(feature_tables):
    from src.vgc_model.sim.battle_sim import BattleSim
    return BattleSim(feature_tables)


@pytest.fixture(scope="session")
def usage_stats():
    try:
        from src.vgc_model.data.usage_stats import UsageStats
        return UsageStats()
    except Exception:
        pytest.skip("Usage stats not available")


@pytest.fixture
def sample_state():
    """A reusable 2v2 state: Garchomp+Rillaboom vs Incineroar+Flutter Mane."""
    from src.vgc_model.sim.battle_sim import SimPokemon, SimState, SimField

    garchomp = SimPokemon(
        species="Garchomp", hp_frac=1.0,
        base_stats={"hp": 108, "atk": 130, "def": 95, "spa": 80, "spd": 85, "spe": 102},
        types=("Dragon", "Ground"),
        moves=["Earthquake", "Rock Slide", "Protect", "Dragon Claw"],
    )
    rillaboom = SimPokemon(
        species="Rillaboom", hp_frac=1.0,
        base_stats={"hp": 100, "atk": 125, "def": 90, "spa": 60, "spd": 70, "spe": 85},
        types=("Grass", ""),
        moves=["Grassy Glide", "Wood Hammer", "Fake Out", "U-turn"],
    )
    incineroar = SimPokemon(
        species="Incineroar", hp_frac=1.0,
        base_stats={"hp": 95, "atk": 115, "def": 90, "spa": 80, "spd": 90, "spe": 60},
        types=("Fire", "Dark"),
        moves=["Flare Blitz", "Knock Off", "Fake Out", "Protect"],
    )
    flutter_mane = SimPokemon(
        species="Flutter Mane", hp_frac=1.0,
        base_stats={"hp": 55, "atk": 55, "def": 55, "spa": 135, "spd": 135, "spe": 135},
        types=("Ghost", "Fairy"),
        moves=["Moonblast", "Shadow Ball", "Dazzling Gleam", "Protect"],
    )

    return SimState(
        own_active=[garchomp, rillaboom],
        own_bench=[],
        opp_active=[incineroar, flutter_mane],
        opp_bench=[],
        field=SimField(),
        turn=1,
    )
