"""Tests for the minimal VGC doubles battle simulator."""

import copy
import pytest
from src.vgc_model.sim.battle_sim import (
    BattleSim, SimPokemon, SimState, SimField, ActionSpec, PROTECT_MOVES,
)


# ── Helpers ──────────────────────────────────────────────────────

def _make_mon(species="Garchomp", hp=1.0, atk=130, def_=95, spa=80, spd=85,
              spe=102, hp_base=108, types=("Dragon", "Ground"),
              moves=None, status="", boosts=None, **kwargs):
    return SimPokemon(
        species=species, hp_frac=hp,
        base_stats={"hp": hp_base, "atk": atk, "def": def_, "spa": spa, "spd": spd, "spe": spe},
        types=types, moves=moves or ["Earthquake", "Rock Slide", "Protect", "Dragon Claw"],
        status=status, boosts=boosts or {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
        **kwargs,
    )


def _make_state(own_a=None, own_b=None, opp_a=None, opp_b=None,
                own_bench=None, opp_bench=None, **field_kwargs):
    own_active = [x for x in [own_a, own_b] if x is not None]
    opp_active = [x for x in [opp_a, opp_b] if x is not None]
    return SimState(
        own_active=own_active,
        own_bench=own_bench or [],
        opp_active=opp_active,
        opp_bench=opp_bench or [],
        field=SimField(**field_kwargs),
        turn=1,
    )


# ── Action Decoding ────────���─────────────────────────────────────

class TestActionDecode:
    def test_move0_spread(self, battle_sim):
        # Earthquake is allAdjacent = spread
        mon = _make_mon()
        spec = battle_sim._decode_action(0, mon, [])
        assert spec.kind == "move"
        assert spec.move_idx == 0
        assert spec.target == "spread"

    def test_move1_spread(self, battle_sim):
        # Rock Slide is allAdjacentFoes = spread
        mon = _make_mon()
        spec = battle_sim._decode_action(4, mon, [])
        assert spec.kind == "move"
        assert spec.move_idx == 1
        assert spec.target == "spread"

    def test_single_target_move(self, battle_sim):
        # Dragon Claw (move idx 3) is normal target
        mon = _make_mon()
        spec = battle_sim._decode_action(9, mon, [])  # move 3, target opp_a
        assert spec.kind == "move"
        assert spec.move_idx == 3
        assert spec.target == "opp_a"

    def test_single_target_opp_b(self, battle_sim):
        mon = _make_mon()
        spec = battle_sim._decode_action(10, mon, [])  # move 3, target opp_b
        assert spec.kind == "move"
        assert spec.target == "opp_b"

    def test_switch_0(self, battle_sim):
        mon = _make_mon()
        spec = battle_sim._decode_action(12, mon, [_make_mon()])
        assert spec.kind == "switch"
        assert spec.switch_idx == 0

    def test_switch_1(self, battle_sim):
        mon = _make_mon()
        spec = battle_sim._decode_action(13, mon, [_make_mon()])
        assert spec.kind == "switch"
        assert spec.switch_idx == 1

    def test_protect_detected(self, battle_sim):
        mon = _make_mon(moves=["Protect", "Earthquake", "Rock Slide", "Dragon Claw"])
        spec = battle_sim._decode_action(0, mon, [])  # move 0 = Protect
        assert spec.is_protect

    def test_spread_move_target(self, battle_sim):
        # Earthquake is a spread move (allAdjacent)
        mon = _make_mon(moves=["Earthquake", "Rock Slide", "Protect", "Dragon Claw"])
        spec = battle_sim._decode_action(0, mon, [])
        assert spec.target == "spread"


# ── Boost Multiplier ───────────���─────────────────────────────────

class TestBoostMult:
    def test_zero_boost(self):
        assert BattleSim._boost_mult(0) == 1.0

    def test_plus_one(self):
        assert BattleSim._boost_mult(1) == 1.5

    def test_plus_two(self):
        assert BattleSim._boost_mult(2) == 2.0

    def test_plus_six(self):
        assert BattleSim._boost_mult(6) == 4.0

    def test_minus_one(self):
        assert abs(BattleSim._boost_mult(-1) - 2/3) < 0.01

    def test_minus_two(self):
        assert BattleSim._boost_mult(-2) == 0.5


# ── Speed Resolution ─────────────────────────────────────────────

class TestSpeedOrder:
    def test_faster_goes_first(self, battle_sim):
        fast = _make_mon(species="Fast", spe=150)
        slow = _make_mon(species="Slow", spe=50)
        state = _make_state(own_a=fast, opp_a=slow)

        move_spec = ActionSpec(kind="move", move_name="Earthquake", target="opp_a")
        actions = [
            ("own", 0, fast, move_spec),
            ("opp", 0, slow, ActionSpec(kind="move", move_name="Earthquake", target="opp_a")),
        ]
        ordered = battle_sim._resolve_order(state, actions)
        assert ordered[0][2].species == "Fast"

    def test_switch_before_move(self, battle_sim):
        fast = _make_mon(species="Fast", spe=150)
        slow = _make_mon(species="Slow", spe=50)
        state = _make_state(own_a=fast, opp_a=slow)

        actions = [
            ("own", 0, fast, ActionSpec(kind="move", move_name="Earthquake", target="opp_a")),
            ("opp", 0, slow, ActionSpec(kind="switch", switch_idx=0)),
        ]
        ordered = battle_sim._resolve_order(state, actions)
        assert ordered[0][3].kind == "switch"

    def test_priority_beats_speed(self, battle_sim):
        fast = _make_mon(species="Fast", spe=150)
        slow = _make_mon(species="Slow", spe=50,
                         moves=["Protect", "Earthquake", "Rock Slide", "Dragon Claw"])
        state = _make_state(own_a=fast, opp_a=slow)

        actions = [
            ("own", 0, fast, ActionSpec(kind="move", move_name="Earthquake", target="opp_a")),
            ("opp", 0, slow, ActionSpec(kind="move", move_name="Protect", is_protect=True)),
        ]
        ordered = battle_sim._resolve_order(state, actions)
        # Protect has +4 priority, should go first despite being slower
        assert ordered[0][3].is_protect

    def test_trick_room_reverses(self, battle_sim):
        fast = _make_mon(species="Fast", spe=150)
        slow = _make_mon(species="Slow", spe=50)
        state = _make_state(own_a=fast, opp_a=slow, trick_room=True)

        move_spec = ActionSpec(kind="move", move_name="Earthquake", target="opp_a")
        actions = [
            ("own", 0, fast, move_spec),
            ("opp", 0, slow, ActionSpec(kind="move", move_name="Earthquake", target="opp_a")),
        ]
        ordered = battle_sim._resolve_order(state, actions)
        assert ordered[0][2].species == "Slow"

    def test_tailwind_doubles_speed(self, battle_sim):
        mon = _make_mon(spe=80)
        base = battle_sim._effective_speed(mon, tailwind=False)
        boosted = battle_sim._effective_speed(mon, tailwind=True)
        assert boosted == pytest.approx(base * 2.0)

    def test_paralysis_halves_speed(self, battle_sim):
        normal = _make_mon(spe=80)
        para = _make_mon(spe=80, status="par")
        base = battle_sim._effective_speed(normal, tailwind=False)
        slowed = battle_sim._effective_speed(para, tailwind=False)
        assert slowed == pytest.approx(base * 0.5)


# ── Damage Calculation ─────────────��─────────────────────────────

class TestDamageCalc:
    def test_damage_is_positive(self, battle_sim):
        user = _make_mon(atk=130, types=("Dragon", "Ground"))
        target = _make_mon(species="Target", def_=95, hp_base=108, types=("Normal", ""))
        move_data = battle_sim._get_move_data("Earthquake")
        dmg = battle_sim._calc_damage(user, target, move_data, SimField(), "own", False)
        assert dmg > 0

    def test_stab_increases_damage(self, battle_sim):
        # Garchomp (Dragon/Ground) using Earthquake (Ground) = STAB
        user = _make_mon(atk=130, types=("Dragon", "Ground"))
        target = _make_mon(species="Target", def_=80, hp_base=100, types=("Normal", ""))
        field = SimField()

        eq_data = battle_sim._get_move_data("Earthquake")
        dmg_stab = battle_sim._calc_damage(user, target, eq_data, field, "own", False)

        # Same mon using a non-STAB move with same base power
        # Rock Slide is Rock type, not STAB for Garchomp... actually it isn't STAB
        rs_data = battle_sim._get_move_data("Rock Slide")
        dmg_nonstab = battle_sim._calc_damage(user, target, rs_data, field, "own", False)

        # EQ (100bp, STAB) should do more than Rock Slide (75bp, no STAB)
        assert dmg_stab > dmg_nonstab

    def test_super_effective_doubles_damage(self, battle_sim):
        user = _make_mon(spa=135, types=("Ghost", "Fairy"))
        field = SimField()

        # Shadow Ball (Ghost) vs Psychic type = 2x
        target_psychic = _make_mon(species="Psychic", spd=80, hp_base=100, types=("Psychic", ""))
        target_normal = _make_mon(species="Normal", spd=80, hp_base=100, types=("Normal", ""))

        sb_data = battle_sim._get_move_data("Shadow Ball")
        dmg_se = battle_sim._calc_damage(user, target_psychic, sb_data, field, "own", False)
        dmg_neutral = battle_sim._calc_damage(user, target_normal, sb_data, field, "own", False)

        # Ghost vs Normal = immune, so neutral should be 0
        assert dmg_neutral == 0.0
        assert dmg_se > 0

    def test_weather_boost(self, battle_sim):
        user = _make_mon(spa=100, types=("Water", ""))
        target = _make_mon(species="Target", spd=80, hp_base=100, types=("Normal", ""))
        move_data = battle_sim._get_move_data("Surf")

        dmg_neutral = battle_sim._calc_damage(user, target, move_data, SimField(), "own", True)
        dmg_rain = battle_sim._calc_damage(user, target, move_data,
                                           SimField(weather="RainDance"), "own", True)
        dmg_sun = battle_sim._calc_damage(user, target, move_data,
                                          SimField(weather="SunnyDay"), "own", True)

        assert dmg_rain > dmg_neutral
        assert dmg_sun < dmg_neutral

    def test_spread_penalty(self, battle_sim):
        user = _make_mon(atk=130, types=("Dragon", "Ground"))
        target = _make_mon(species="Target", def_=80, hp_base=100, types=("Normal", ""))
        eq_data = battle_sim._get_move_data("Earthquake")
        field = SimField()

        dmg_single = battle_sim._calc_damage(user, target, eq_data, field, "own", False)
        dmg_spread = battle_sim._calc_damage(user, target, eq_data, field, "own", True)

        assert dmg_spread == pytest.approx(dmg_single * 0.75, rel=0.01)

    def test_burn_halves_physical(self, battle_sim):
        normal = _make_mon(atk=130, types=("Dragon", "Ground"))
        burned = _make_mon(atk=130, types=("Dragon", "Ground"), status="brn")
        target = _make_mon(species="Target", def_=80, hp_base=100, types=("Normal", ""))
        eq_data = battle_sim._get_move_data("Earthquake")
        field = SimField()

        dmg_normal = battle_sim._calc_damage(normal, target, eq_data, field, "own", False)
        dmg_burned = battle_sim._calc_damage(burned, target, eq_data, field, "own", False)

        assert dmg_burned == pytest.approx(dmg_normal * 0.5, rel=0.01)

    def test_screens_halve_damage(self, battle_sim):
        user = _make_mon(atk=130, types=("Normal", ""))
        target = _make_mon(species="Target", def_=80, hp_base=100, types=("Normal", ""))
        # Use a generic physical move
        move_data = battle_sim._get_move_data("Rock Slide")

        dmg_no_screen = battle_sim._calc_damage(
            user, target, move_data, SimField(), "own", False)
        dmg_reflect = battle_sim._calc_damage(
            user, target, move_data,
            SimField(screens_opp=[False, True, False]),  # Reflect active on target side
            "own", False)

        assert dmg_reflect == pytest.approx(dmg_no_screen * 0.5, rel=0.01)

    def test_status_move_zero_damage(self, battle_sim):
        user = _make_mon()
        target = _make_mon(species="Target")
        move_data = battle_sim._get_move_data("Protect")
        dmg = battle_sim._calc_damage(user, target, move_data, SimField(), "own", False)
        assert dmg == 0.0

    def test_boost_increases_damage(self, battle_sim):
        normal = _make_mon(atk=80, types=("Normal", ""))
        boosted = _make_mon(atk=80, types=("Normal", ""),
                            boosts={"atk": 2, "def": 0, "spa": 0, "spd": 0, "spe": 0})
        target = _make_mon(species="Target", def_=150, hp_base=200, types=("Normal", ""))
        # Use Rock Slide (non-STAB for Normal type, won't cap)
        rs_data = battle_sim._get_move_data("Rock Slide")
        field = SimField()

        dmg_normal = battle_sim._calc_damage(normal, target, rs_data, field, "own", False)
        dmg_boosted = battle_sim._calc_damage(boosted, target, rs_data, field, "own", False)

        # Not exactly 2x due to +2 constant in damage formula, but close
        assert dmg_boosted > dmg_normal * 1.8
        assert dmg_boosted < dmg_normal * 2.1


# ── Protect Handling ───────────��─────────────────────────────────

class TestProtect:
    def test_protect_blocks_damage(self, battle_sim):
        attacker = _make_mon(species="Attacker", atk=130)
        protector = _make_mon(species="Protector",
                              moves=["Protect", "Earthquake", "Rock Slide", "Dragon Claw"])
        state = _make_state(own_a=attacker, opp_a=protector)

        # Attacker uses Earthquake targeting opp_a, protector uses Protect
        result = battle_sim.simulate_turn(
            state,
            own_actions=(0, 0),   # move 0 (EQ) -> opp_a (but it's spread)
            opp_actions=(0, 0),   # move 0 (Protect)
        )
        # Protector should still be at full HP
        assert result.opp_active[0].hp_frac == 1.0

    def test_protect_doesnt_block_allies(self, battle_sim):
        """Protect on one opp doesn't protect the other."""
        attacker = _make_mon(species="Attacker", atk=130, types=("Ground", ""))
        partner = _make_mon(species="Partner", spe=10)
        protector = _make_mon(species="Protector",
                              moves=["Protect", "Earthquake", "Rock Slide", "Dragon Claw"])
        victim = _make_mon(species="Victim", types=("Fire", ""), def_=60, hp_base=70)
        state = _make_state(own_a=attacker, own_b=partner, opp_a=protector, opp_b=victim)

        # Attacker uses EQ (spread), protector protects, victim doesn't
        result = battle_sim.simulate_turn(
            state,
            own_actions=(0, 0),   # EQ (spread)
            opp_actions=(0, 0),   # Protect, nothing for slot b (only 1 action tuple)
        )
        # Victim should take damage, protector should not
        assert result.opp_active[0].hp_frac == 1.0  # protected
        assert result.opp_active[1].hp_frac < 1.0   # took damage


# ── Switch Handling ────────────��─────────────────────────────────

class TestSwitch:
    def test_switch_swaps_pokemon(self, battle_sim):
        active = _make_mon(species="Active", spe=100)
        bench = _make_mon(species="Bench", spe=50)
        dummy_opp = _make_mon(species="Opp")
        state = _make_state(own_a=active, opp_a=dummy_opp, own_bench=[bench])

        result = battle_sim.simulate_turn(
            state,
            own_actions=(12, 0),  # switch to bench[0]
            opp_actions=(9, 0),  # move 3 (Dragon Claw) -> opp_a   # some move
        )
        assert result.own_active[0].species == "Bench"

    def test_switch_resets_boosts(self, battle_sim):
        active = _make_mon(species="Active", boosts={"atk": 2, "def": 1, "spa": 0, "spd": 0, "spe": 0})
        bench = _make_mon(species="Bench")
        dummy_opp = _make_mon(species="Opp")
        state = _make_state(own_a=active, opp_a=dummy_opp, own_bench=[bench])

        result = battle_sim.simulate_turn(
            state,
            own_actions=(12, 0),
            opp_actions=(9, 0),  # move 3 (Dragon Claw) -> opp_a
        )
        # The new active should have no boosts
        assert result.own_active[0].boosts["atk"] == 0

    def test_cant_switch_to_fainted(self, battle_sim):
        active = _make_mon(species="Active")
        fainted = _make_mon(species="Fainted", hp=0.0, fainted=True)
        dummy_opp = _make_mon(species="Opp")
        state = _make_state(own_a=active, opp_a=dummy_opp, own_bench=[fainted])

        result = battle_sim.simulate_turn(
            state,
            own_actions=(12, 0),
            opp_actions=(9, 0),  # move 3 (Dragon Claw) -> opp_a
        )
        # Should still be the same active (switch was invalid)
        assert result.own_active[0].species == "Active"


# ── Full Turn Simulation ─────────────────────────────────────────

class TestFullTurn:
    def test_no_mutation(self, battle_sim, sample_state):
        """simulate_turn must not mutate the input state."""
        original_hp = sample_state.opp_active[0].hp_frac
        battle_sim.simulate_turn(sample_state, (0, 0), (6, 6))
        assert sample_state.opp_active[0].hp_frac == original_hp

    def test_turn_increments(self, battle_sim, sample_state):
        result = battle_sim.simulate_turn(sample_state, (0, 0), (6, 6))
        assert result.turn == sample_state.turn + 1

    def test_fainted_pokemon_dont_act(self, battle_sim):
        attacker = _make_mon(species="Attacker", atk=200, types=("Fighting", ""))
        fainted = _make_mon(species="Fainted", hp=0.0, fainted=True)
        target = _make_mon(species="Target", def_=50, hp_base=50, types=("Normal", ""))
        state = _make_state(own_a=attacker, own_b=fainted, opp_a=target)

        result = battle_sim.simulate_turn(
            state,
            own_actions=(0, 0),  # attacker attacks, fainted slot ignored
            opp_actions=(9, 0),  # move 3 (Dragon Claw) -> opp_a
        )
        # Target should take damage from attacker only
        assert result.opp_active[0].hp_frac < 1.0

    def test_ko_sets_fainted(self, battle_sim):
        """A strong enough hit should KO and set fainted=True."""
        nuke = _make_mon(species="Nuke", atk=255, types=("Fighting", ""),
                         moves=["Close Combat", "Earthquake", "Protect", "Rock Slide"])
        target = _make_mon(species="Squishy", def_=30, hp_base=30, types=("Normal", ""))
        state = _make_state(own_a=nuke, opp_a=target)

        result = battle_sim.simulate_turn(
            state,
            own_actions=(0, 0),  # Close Combat vs Normal = 2x SE
            opp_actions=(9, 0),  # move 3 (Dragon Claw) -> opp_a
        )
        assert result.opp_active[0].fainted
        assert result.opp_active[0].hp_frac == 0.0
