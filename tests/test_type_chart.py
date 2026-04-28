"""Tests for the type effectiveness chart."""

import pytest
from src.vgc_model.sim.type_chart import type_effectiveness


class TestSuperEffective:
    def test_fire_vs_grass(self):
        assert type_effectiveness("Fire", "Grass") == 2.0

    def test_water_vs_fire(self):
        assert type_effectiveness("Water", "Fire") == 2.0

    def test_ground_vs_electric(self):
        assert type_effectiveness("Ground", "Electric") == 2.0

    def test_fighting_vs_dark(self):
        assert type_effectiveness("Fighting", "Dark") == 2.0

    def test_fairy_vs_dragon(self):
        assert type_effectiveness("Fairy", "Dragon") == 2.0

    def test_ice_vs_dragon(self):
        assert type_effectiveness("Ice", "Dragon") == 2.0

    def test_ghost_vs_psychic(self):
        assert type_effectiveness("Ghost", "Psychic") == 2.0


class TestNotVeryEffective:
    def test_fire_vs_water(self):
        assert type_effectiveness("Fire", "Water") == 0.5

    def test_grass_vs_fire(self):
        assert type_effectiveness("Grass", "Fire") == 0.5

    def test_electric_vs_grass(self):
        assert type_effectiveness("Electric", "Grass") == 0.5

    def test_steel_vs_fire(self):
        assert type_effectiveness("Steel", "Fire") == 0.5


class TestImmune:
    def test_normal_vs_ghost(self):
        assert type_effectiveness("Normal", "Ghost") == 0.0

    def test_ghost_vs_normal(self):
        assert type_effectiveness("Ghost", "Normal") == 0.0

    def test_electric_vs_ground(self):
        assert type_effectiveness("Electric", "Ground") == 0.0

    def test_ground_vs_flying(self):
        assert type_effectiveness("Ground", "Flying") == 0.0

    def test_dragon_vs_fairy(self):
        assert type_effectiveness("Dragon", "Fairy") == 0.0

    def test_fighting_vs_ghost(self):
        assert type_effectiveness("Fighting", "Ghost") == 0.0

    def test_poison_vs_steel(self):
        assert type_effectiveness("Poison", "Steel") == 0.0

    def test_psychic_vs_dark(self):
        assert type_effectiveness("Psychic", "Dark") == 0.0


class TestDualType:
    def test_4x_ground_vs_fire_steel(self):
        assert type_effectiveness("Ground", "Fire", "Steel") == 4.0

    def test_4x_ice_vs_dragon_ground(self):
        assert type_effectiveness("Ice", "Dragon", "Ground") == 4.0

    def test_4x_fighting_vs_normal_rock(self):
        assert type_effectiveness("Fighting", "Normal", "Rock") == 4.0

    def test_quarter_grass_vs_fire_dragon(self):
        assert type_effectiveness("Grass", "Fire", "Dragon") == 0.25

    def test_immune_overrides_super(self):
        # Electric vs Water/Ground — Ground immunity cancels Water SE
        assert type_effectiveness("Electric", "Water", "Ground") == 0.0

    def test_immune_overrides_neutral(self):
        # Normal vs Ghost/Dark — Ghost immunity
        assert type_effectiveness("Normal", "Ghost", "Dark") == 0.0

    def test_neutral_dual(self):
        # Fire vs Water/Grass — 0.5 * 2.0 = 1.0
        assert type_effectiveness("Fire", "Water", "Grass") == 1.0

    def test_se_and_resist(self):
        # Fire vs Grass/Dragon — 2.0 * 0.5 = 1.0
        assert type_effectiveness("Fire", "Grass", "Dragon") == 1.0

    def test_double_resist(self):
        # Bug vs Fire/Flying — 0.5 * 0.5 = 0.25
        assert type_effectiveness("Bug", "Fire", "Flying") == 0.25


class TestEdgeCases:
    def test_empty_attack_type(self):
        assert type_effectiveness("", "Normal") == 1.0

    def test_empty_def_type2(self):
        assert type_effectiveness("Fire", "Grass", "") == 2.0

    def test_neutral_single(self):
        assert type_effectiveness("Normal", "Normal") == 1.0

    def test_neutral_unrelated(self):
        assert type_effectiveness("Fire", "Normal") == 1.0
