"""VGC doubles battle simulator for 1-ply search (v2).

Simulates one turn of a doubles battle given both players' actions.
Handles: speed/priority, damage calc with items/abilities/auras,
Protect, switching with Intimidate, Focus Sash, Sitrus Berry, resist
berries, type-boosting items, Fairy/Dark Aura, ability immunities,
weather setters, Choice Scarf, Pixilate-family, Adaptability.

Tuned for the Champions VGC (Regulation M-A) format with Mega Evolution.
Reference: Pokemon Showdown's sim/ directory for formulas.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Optional

from ..data.feature_tables import FeatureTables
from .type_chart import type_effectiveness


# ── Data structures ──────────────────────────────────────────────

@dataclass
class SimPokemon:
    species: str
    hp_frac: float              # 0.0-1.0
    base_stats: dict            # hp, atk, def, spa, spd, spe (raw base stats)
    types: tuple[str, str]      # (type1, type2), type2="" if monotype
    moves: list[str]            # up to 4 move names
    item: str = ""
    ability: str = ""
    status: str = ""            # brn, par, psn, slp, frz, tox
    boosts: dict = field(default_factory=lambda: {
        "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0,
    })
    is_mega: bool = False
    fainted: bool = False

    @property
    def alive(self) -> bool:
        return not self.fainted and self.hp_frac > 0


@dataclass
class SimField:
    weather: str = ""
    terrain: str = ""
    trick_room: bool = False
    tailwind_own: bool = False
    tailwind_opp: bool = False
    screens_own: list = field(default_factory=lambda: [False, False, False])  # LS, Reflect, AV
    screens_opp: list = field(default_factory=lambda: [False, False, False])


@dataclass
class SimState:
    own_active: list[SimPokemon] = field(default_factory=list)   # 0-2
    own_bench: list[SimPokemon] = field(default_factory=list)    # 0-2
    opp_active: list[SimPokemon] = field(default_factory=list)   # 0-2
    opp_bench: list[SimPokemon] = field(default_factory=list)    # 0-2
    field: SimField = field(default_factory=SimField)
    turn: int = 1


@dataclass
class ActionSpec:
    kind: str           # "move" or "switch" or "none"
    move_name: str = ""
    move_idx: int = 0   # 0-3
    target: str = ""    # "opp_a", "opp_b", "ally", "spread", "self"
    switch_idx: int = 0 # bench index to switch to
    is_protect: bool = False


# ── Constants ────────────────────────────────────────────────────

# Spread moves hit both opponents (0.75x damage in doubles)
SPREAD_TARGETS = {"allAdjacentFoes", "allAdjacent", "all", "foeSide"}

# Protect-like moves
PROTECT_MOVES = {
    "Protect", "Detect", "King's Shield", "Spiky Shield", "Baneful Bunker",
    "Obstruct", "Silk Trap", "Burning Bulwark", "Max Guard",
}

# Level for VGC
LEVEL = 50

# Average random damage roll (0.85-1.0 range, avg = 0.925)
AVG_ROLL = 0.925

# ── Type-boosting items (1.2x to a specific type) ───────────────
TYPE_BOOST_ITEMS: dict[str, str] = {
    "Mystic Water": "Water", "Charcoal": "Fire", "Fairy Feather": "Fairy",
    "Black Glasses": "Dark", "Spell Tag": "Ghost", "Sharp Beak": "Flying",
    "Dragon Fang": "Dragon", "Magnet": "Electric", "Miracle Seed": "Grass",
    "Poison Barb": "Poison", "Silk Scarf": "Normal", "Hard Stone": "Rock",
    "Soft Sand": "Ground", "Never-Melt Ice": "Ice", "Twisted Spoon": "Psychic",
    "Metal Coat": "Steel",
}

# ── Resist berries (halve SE damage of a specific type, one-time) ─
RESIST_BERRIES: dict[str, str] = {
    "Chople Berry": "Fighting", "Colbur Berry": "Dark", "Occa Berry": "Fire",
    "Shuca Berry": "Ground", "Passho Berry": "Water", "Roseli Berry": "Fairy",
    "Yache Berry": "Ice", "Charti Berry": "Rock", "Kebia Berry": "Poison",
    "Kasib Berry": "Ghost", "Coba Berry": "Flying", "Rindo Berry": "Grass",
    "Babiri Berry": "Steel", "Haban Berry": "Dragon", "Wacan Berry": "Electric",
    "Payapa Berry": "Psychic", "Chilan Berry": "Normal",
}

# ── Ability-based type immunities ────────────────────────────────
ABILITY_IMMUNITIES: dict[str, str] = {
    "Levitate": "Ground", "Lightning Rod": "Electric", "Storm Drain": "Water",
    "Water Absorb": "Water", "Volt Absorb": "Electric", "Sap Sipper": "Grass",
    "Flash Fire": "Fire", "Motor Drive": "Electric", "Dry Skin": "Water",
}

# ── Weather-setting abilities ────────────────────────────────────
WEATHER_ABILITIES: dict[str, str] = {
    "Drizzle": "RainDance", "Drought": "SunnyDay",
    "Sand Stream": "Sandstorm", "Snow Warning": "Snow",
}

# ── -ate abilities (Normal → Type + 1.2x) ───────────────────────
ATE_ABILITIES: dict[str, str] = {
    "Pixilate": "Fairy", "Aerilate": "Flying",
    "Refrigerate": "Ice", "Galvanize": "Electric",
}

# ── Fake Out (priority +3, flinch) ──────────────────────────────
FLINCH_PRIORITY_MOVES = {"Fake Out"}


# ── Battle Simulator ─────────────────────────────────────────────

class BattleSim:
    """Simulate one turn of a VGC doubles battle."""

    def __init__(self, feature_tables: FeatureTables):
        self.ft = feature_tables
        # Cache move data lookups
        self._move_cache: dict[str, dict] = {}

    def _get_move_data(self, move_name: str) -> dict:
        if move_name not in self._move_cache:
            self._move_cache[move_name] = self.ft.get_move_features(move_name)
        return self._move_cache[move_name]

    def simulate_turn(
        self, state: SimState,
        own_actions: tuple[int, int],
        opp_actions: tuple[int, int],
    ) -> SimState:
        """Apply one turn and return new state. Does NOT modify input."""
        s = copy.deepcopy(state)
        s.turn += 1

        # Decode all 4 actions
        actions = []  # list of (side, slot_idx, pokemon, ActionSpec)

        for slot_idx, act_idx in enumerate(own_actions):
            if slot_idx < len(s.own_active) and s.own_active[slot_idx].alive:
                spec = self._decode_action(act_idx, s.own_active[slot_idx], s.own_bench)
                actions.append(("own", slot_idx, s.own_active[slot_idx], spec))

        for slot_idx, act_idx in enumerate(opp_actions):
            if slot_idx < len(s.opp_active) and s.opp_active[slot_idx].alive:
                spec = self._decode_action(act_idx, s.opp_active[slot_idx], s.opp_bench)
                actions.append(("opp", slot_idx, s.opp_active[slot_idx], spec))

        # Mark who is protecting (must be done before move resolution)
        protecting: set[int] = set()  # id() of pokemon using Protect
        for side, slot_idx, poke, spec in actions:
            if spec.is_protect:
                protecting.add(id(poke))

        # Resolve execution order
        ordered = self._resolve_order(s, actions)

        # Execute each action
        for side, slot_idx, poke, spec in ordered:
            if poke.fainted:
                continue

            if spec.kind == "switch":
                self._execute_switch(s, side, slot_idx, spec.switch_idx)
            elif spec.kind == "move" and not spec.is_protect:
                self._execute_move(s, side, slot_idx, poke, spec, protecting)

        return s

    def _decode_action(
        self, action_idx: int, pokemon: SimPokemon, bench: list[SimPokemon],
    ) -> ActionSpec:
        """Convert flat action index (0-13) to ActionSpec.

        0-11: move (move_idx = action // 3, target_idx = action % 3)
              targets: 0=opp_a, 1=opp_b, 2=ally
        12-13: switch to bench[0] or bench[1]
        """
        if action_idx >= 12:
            bench_idx = action_idx - 12
            return ActionSpec(kind="switch", switch_idx=bench_idx)

        move_idx = action_idx // 3
        target_idx = action_idx % 3
        target_names = ["opp_a", "opp_b", "ally"]

        move_name = pokemon.moves[move_idx] if move_idx < len(pokemon.moves) else ""
        if not move_name:
            return ActionSpec(kind="none")

        # Check if this is a protect move
        is_protect = move_name in PROTECT_MOVES

        # Check if spread move
        move_data = self._get_move_data(move_name)
        target_type = move_data.get("target", "normal")
        if target_type in SPREAD_TARGETS:
            target = "spread"
        else:
            target = target_names[target_idx]

        return ActionSpec(
            kind="move",
            move_name=move_name,
            move_idx=move_idx,
            target=target,
            is_protect=is_protect,
        )

    def _resolve_order(
        self, state: SimState,
        actions: list[tuple[str, int, SimPokemon, ActionSpec]],
    ) -> list[tuple[str, int, SimPokemon, ActionSpec]]:
        """Sort actions by: switches first, then priority, then speed."""

        def sort_key(item):
            side, slot_idx, poke, spec = item

            # Switches always go first (priority +7 equivalent)
            if spec.kind == "switch":
                order = 0
            elif spec.kind == "move":
                move_data = self._get_move_data(spec.move_name)
                # Priority is stored shifted: (actual + 7) / 12
                # Reverse it: actual = raw * 12 - 7
                raw_priority = move_data.get("priority", 0)
                if isinstance(raw_priority, float) and raw_priority <= 1.0:
                    actual_priority = round(raw_priority * 12 - 7)
                else:
                    actual_priority = int(raw_priority)
                # Protect has +4 priority
                if spec.is_protect:
                    actual_priority = 4
                order = 1
            else:
                order = 2
                actual_priority = 0

            # Effective speed
            tailwind = state.field.tailwind_own if side == "own" else state.field.tailwind_opp
            eff_speed = self._effective_speed(poke, tailwind)

            # Under Trick Room, slower goes first (negate speed)
            if state.field.trick_room:
                eff_speed = -eff_speed

            if spec.kind == "switch":
                return (0, -eff_speed)
            return (1, -actual_priority, -eff_speed, random.random())

        return sorted(actions, key=sort_key)

    def _effective_speed(self, poke: SimPokemon, tailwind: bool) -> float:
        """Calculate effective speed stat."""
        base_spe = poke.base_stats.get("spe", 80)
        # Approximate actual speed at level 50: (2*base + 31) * 50/100 + 5
        actual = base_spe + 36

        # Boost multiplier
        boost = poke.boosts.get("spe", 0)
        if boost > 0:
            actual *= (2 + boost) / 2
        elif boost < 0:
            actual *= 2 / (2 + abs(boost))

        # Paralysis
        if poke.status == "par":
            actual *= 0.5

        # Choice Scarf
        if poke.item == "Choice Scarf":
            actual *= 1.5

        # Unburden (after item consumption — assume active if no item)
        if poke.ability == "Unburden" and not poke.item:
            actual *= 2.0

        # Tailwind
        if tailwind:
            actual *= 2.0

        return actual

    def _execute_move(
        self, state: SimState, side: str, slot_idx: int,
        user: SimPokemon, spec: ActionSpec, protecting: set[int],
    ):
        """Execute a move against target(s)."""
        move_data = self._get_move_data(spec.move_name)
        bp = move_data.get("base_power", 0)
        category = move_data.get("category", "")

        # Status moves — handle key ones, skip the rest
        if category == "Status" or bp == 0:
            self._handle_status_move(state, side, user, spec)
            return

        # Find targets
        targets = self._resolve_targets(state, side, slot_idx, spec)
        is_spread = spec.target == "spread" and len(targets) > 1

        # Collect all Pokemon on field for aura checks
        all_pokemon = (state.own_active + state.own_bench +
                       state.opp_active + state.opp_bench)

        for target in targets:
            if target.fainted:
                continue
            if id(target) in protecting:
                continue

            # Check ability immunity (unless user has Mold Breaker)
            if user.ability != "Mold Breaker":
                move_type = self._get_effective_move_type(user, move_data)
                immune_type = ABILITY_IMMUNITIES.get(target.ability, "")
                if immune_type and immune_type == move_type:
                    continue

            # Calculate and apply damage
            hp_before = target.hp_frac
            damage_frac = self._calc_damage(user, target, move_data, state.field,
                                            side, is_spread, all_pokemon)

            target.hp_frac = max(0.0, target.hp_frac - damage_frac)

            # Focus Sash: survive at 1 HP if was at full HP
            if target.hp_frac <= 0 and hp_before >= 0.99 and target.item == "Focus Sash":
                target.hp_frac = 0.01

            # Check faint
            if target.hp_frac <= 0:
                target.hp_frac = 0.0
                target.fainted = True
                continue

            # Sitrus Berry: heal 25% when dropping below 50%
            if (target.item == "Sitrus Berry"
                    and hp_before >= 0.5 and target.hp_frac < 0.5):
                target.hp_frac = min(1.0, target.hp_frac + 0.25)

    def _handle_status_move(self, state: SimState, side: str,
                            user: SimPokemon, spec: ActionSpec):
        """Handle key status moves that affect board state."""
        move = spec.move_name

        if move == "Swords Dance":
            user.boosts["atk"] = min(6, user.boosts.get("atk", 0) + 2)
        elif move == "Nasty Plot":
            user.boosts["spa"] = min(6, user.boosts.get("spa", 0) + 2)
        elif move in ("Dragon Dance",):
            user.boosts["atk"] = min(6, user.boosts.get("atk", 0) + 1)
            user.boosts["spe"] = min(6, user.boosts.get("spe", 0) + 1)
        elif move == "Calm Mind":
            user.boosts["spa"] = min(6, user.boosts.get("spa", 0) + 1)
            user.boosts["spd"] = min(6, user.boosts.get("spd", 0) + 1)
        elif move == "Tailwind":
            if side == "own":
                state.field.tailwind_own = True
            else:
                state.field.tailwind_opp = True
        elif move == "Trick Room":
            state.field.trick_room = not state.field.trick_room

    def _get_effective_move_type(self, user: SimPokemon, move_data: dict) -> str:
        """Get the move's effective type after ability modifications."""
        move_type = move_data.get("type", "")
        # -ate abilities: Normal → new type
        if move_type == "Normal" and user.ability in ATE_ABILITIES:
            move_type = ATE_ABILITIES[user.ability]
        return move_type

    def _resolve_targets(
        self, state: SimState, side: str, slot_idx: int, spec: ActionSpec,
    ) -> list[SimPokemon]:
        """Resolve which Pokemon are targeted."""
        opp_active = state.opp_active if side == "own" else state.own_active
        own_active = state.own_active if side == "own" else state.opp_active

        if spec.target == "spread":
            # Hit all opponents
            return [p for p in opp_active if p.alive]
        elif spec.target == "opp_a":
            if opp_active and opp_active[0].alive:
                return [opp_active[0]]
            elif len(opp_active) > 1 and opp_active[1].alive:
                return [opp_active[1]]  # Redirect to other slot
            return []
        elif spec.target == "opp_b":
            if len(opp_active) > 1 and opp_active[1].alive:
                return [opp_active[1]]
            elif opp_active and opp_active[0].alive:
                return [opp_active[0]]  # Redirect
            return []
        elif spec.target == "ally":
            # Target ally (for moves like Heal Pulse — but we skip status moves)
            return []
        elif spec.target == "self":
            return []

        return []

    def _calc_damage(
        self, user: SimPokemon, target: SimPokemon,
        move_data: dict, field: SimField, user_side: str,
        is_spread: bool, all_pokemon: list[SimPokemon] = None,
    ) -> float:
        """Calculate damage as HP fraction lost by target.

        Implements the Gen 5+ damage formula with Champions VGC modifiers:
        items, abilities, auras, resist berries, -ate abilities.
        """
        bp = move_data.get("base_power", 0)
        if bp == 0:
            return 0.0

        category = move_data.get("category", "Physical")
        move_type = move_data.get("type", "")

        # -ate abilities: Normal moves become typed + 1.2x
        ate_boost = 1.0
        if move_type == "Normal" and user.ability in ATE_ABILITIES:
            move_type = ATE_ABILITIES[user.ability]
            ate_boost = 1.2

        # Attack and defense stats
        if category == "Physical":
            atk_base = user.base_stats.get("atk", 80)
            def_base = target.base_stats.get("def", 80)
            atk_boost = user.boosts.get("atk", 0)
            def_boost = target.boosts.get("def", 0)
        else:
            atk_base = user.base_stats.get("spa", 80)
            def_base = target.base_stats.get("spd", 80)
            atk_boost = user.boosts.get("spa", 0)
            def_boost = target.boosts.get("spd", 0)

        # Approximate actual stats at level 50
        # (2 * base + 31 + 0) * 50/100 + 5 = base + 36
        atk_stat = atk_base + 36
        def_stat = def_base + 36

        # Huge Power / Pure Power: double attack
        if user.ability in ("Huge Power", "Pure Power") and category == "Physical":
            atk_stat *= 2.0

        # Apply boost multipliers
        atk_stat *= self._boost_mult(atk_boost)
        def_stat *= self._boost_mult(def_boost)

        # Core damage formula
        damage = ((2 * LEVEL / 5 + 2) * bp * atk_stat / def_stat) / 50 + 2

        # ── Modifier chain ───────────────────────────────────────
        modifier = 1.0

        # STAB
        if move_type and move_type in (user.types[0], user.types[1]):
            if user.ability == "Adaptability":
                modifier *= 2.0
            else:
                modifier *= 1.5

        # Type effectiveness
        eff = type_effectiveness(move_type, target.types[0], target.types[1])
        modifier *= eff

        # Spread penalty
        if is_spread:
            modifier *= 0.75

        # Weather
        if field.weather == "SunnyDay":
            if move_type == "Fire":
                modifier *= 1.5
            elif move_type == "Water":
                modifier *= 0.5
        elif field.weather == "RainDance":
            if move_type == "Water":
                modifier *= 1.5
            elif move_type == "Fire":
                modifier *= 0.5

        # Terrain (simplified — assume grounded)
        if field.terrain == "Electric" and move_type == "Electric":
            modifier *= 1.3
        elif field.terrain == "Grassy" and move_type == "Grass":
            modifier *= 1.3
        elif field.terrain == "Psychic" and move_type == "Psychic":
            modifier *= 1.3
        elif field.terrain == "Misty" and move_type == "Dragon":
            modifier *= 0.5

        # Screens
        target_side = "opp" if user_side == "own" else "own"
        screens = field.screens_opp if target_side == "opp" else field.screens_own
        if category == "Special" and (screens[0] or screens[2]):
            modifier *= 0.5
        elif category == "Physical" and (screens[1] or screens[2]):
            modifier *= 0.5

        # Burn halves physical
        if user.status == "brn" and category == "Physical":
            modifier *= 0.5

        # ── Item modifiers ───────────────────────────────────────

        # Type-boosting items (1.2x)
        boosted_type = TYPE_BOOST_ITEMS.get(user.item, "")
        if boosted_type and boosted_type == move_type:
            modifier *= 1.2

        # Choice Band / Choice Specs
        if user.item == "Choice Band" and category == "Physical":
            modifier *= 1.5
        elif user.item == "Choice Specs" and category == "Special":
            modifier *= 1.5

        # Life Orb (1.3x but 10% recoil — skip recoil for simplicity)
        if user.item == "Life Orb":
            modifier *= 1.3

        # -ate ability boost
        modifier *= ate_boost

        # ── Ability modifiers ────────────────────────────────────

        # Fairy Aura / Dark Aura (global — check ALL pokemon on field)
        if all_pokemon and move_type in ("Fairy", "Dark"):
            aura_name = "Fairy Aura" if move_type == "Fairy" else "Dark Aura"
            has_aura = any(p.ability == aura_name for p in all_pokemon if p.alive)
            if has_aura:
                # Aura Break inverts, but extremely rare — skip
                modifier *= 1.33

        # Multiscale: halve damage when target is at full HP
        if target.ability in ("Multiscale", "Shadow Shield") and target.hp_frac >= 0.99:
            if user.ability != "Mold Breaker":
                modifier *= 0.5

        # Thick Fat: halve Fire and Ice damage
        if target.ability == "Thick Fat" and move_type in ("Fire", "Ice"):
            if user.ability != "Mold Breaker":
                modifier *= 0.5

        # ── Resist berries ───────────────────────────────────────
        resist_type = RESIST_BERRIES.get(target.item, "")
        if resist_type and resist_type == move_type and eff > 1.0:
            modifier *= 0.5

        # Average random roll
        modifier *= AVG_ROLL

        # Final damage
        damage *= modifier

        # Convert to HP fraction
        target_max_hp = target.base_stats.get("hp", 80) + 91
        damage_frac = damage / target_max_hp

        return min(damage_frac, target.hp_frac)

    @staticmethod
    def _boost_mult(boost: int) -> float:
        """Convert a stat boost stage (-6 to +6) to a multiplier."""
        if boost >= 0:
            return (2 + boost) / 2
        return 2 / (2 + abs(boost))

    def _execute_switch(
        self, state: SimState, side: str, slot_idx: int, bench_idx: int,
    ):
        """Swap an active Pokemon with a bench Pokemon.

        Handles: boost reset, Intimidate, weather-setting abilities.
        """
        active = state.own_active if side == "own" else state.opp_active
        bench = state.own_bench if side == "own" else state.opp_bench

        if slot_idx >= len(active) or bench_idx >= len(bench):
            return
        if not bench[bench_idx].alive:
            return

        # Swap
        active[slot_idx], bench[bench_idx] = bench[bench_idx], active[slot_idx]
        new_mon = active[slot_idx]

        # Reset boosts on the newly switched-in Pokemon
        new_mon.boosts = {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}

        # Intimidate: -1 atk to all opposing active Pokemon
        if new_mon.ability == "Intimidate":
            opp_active = state.opp_active if side == "own" else state.own_active
            for opp in opp_active:
                if opp.alive:
                    # Defiant: +2 atk instead of -1
                    if opp.ability == "Defiant":
                        opp.boosts["atk"] = min(6, opp.boosts.get("atk", 0) + 2)
                    # Competitive: +2 spa instead of -1
                    elif opp.ability == "Competitive":
                        opp.boosts["spa"] = min(6, opp.boosts.get("spa", 0) + 2)
                    # Clear Body / White Smoke / etc. block it
                    elif opp.ability in ("Clear Body", "White Smoke", "Full Metal Body",
                                         "Hyper Cutter"):
                        pass
                    else:
                        opp.boosts["atk"] = max(-6, opp.boosts.get("atk", 0) - 1)
                    # White Herb: clear the stat drop
                    if opp.item == "White Herb" and opp.boosts.get("atk", 0) < 0:
                        opp.boosts["atk"] = 0

        # Weather-setting abilities
        weather = WEATHER_ABILITIES.get(new_mon.ability, "")
        if weather:
            state.field.weather = weather


# ── State conversion ─────────────────────────────────────────────

def predict_request_to_sim_state(
    req_dict: dict, feature_tables: FeatureTables,
    usage_stats=None,
) -> SimState:
    """Convert a PredictRequest-style dict to SimState.

    Fills unknown moves/items/abilities from usage_stats.
    """
    def _make_pokemon(poke_data: dict) -> SimPokemon:
        species = poke_data.get("species", "")
        if not species:
            return SimPokemon(
                species="", hp_frac=0.0,
                base_stats={"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
                types=("", ""), moves=[], fainted=True,
            )

        # Get base stats and types from feature tables
        sf = feature_tables.get_species_features(species)
        base_stats = {
            "hp": sf.get("hp", 80), "atk": sf.get("atk", 80),
            "def": sf.get("def", 80), "spa": sf.get("spa", 80),
            "spd": sf.get("spd", 80), "spe": sf.get("spe", 80),
        }
        types = (sf.get("type1", ""), sf.get("type2", ""))

        # Moves — fill from usage stats if incomplete
        moves = list(poke_data.get("moves", []))[:4]
        if usage_stats and len(moves) < 4:
            moves = usage_stats.infer_moveset(species, moves)

        # Item and ability — fill from usage stats if missing
        item = poke_data.get("item", "")
        if not item and usage_stats:
            item = usage_stats.get_likely_item(species) or ""

        ability = poke_data.get("ability", "")
        if not ability and usage_stats:
            ability = usage_stats.get_likely_ability(species) or ""

        hp_frac = poke_data.get("hp", 1.0)
        alive = poke_data.get("alive", True)

        boosts_list = poke_data.get("boosts", [0]*6)
        boost_names = ["atk", "def", "spa", "spd", "spe"]
        boosts = {n: boosts_list[i] if i < len(boosts_list) else 0 for i, n in enumerate(boost_names)}

        return SimPokemon(
            species=species,
            hp_frac=hp_frac if alive else 0.0,
            base_stats=base_stats,
            types=types,
            moves=moves,
            item=item,
            ability=ability,
            status=poke_data.get("status", ""),
            boosts=boosts,
            is_mega=poke_data.get("is_mega", False),
            fainted=not alive or hp_frac <= 0,
        )

    def _make_list(data_list):
        return [_make_pokemon(p) for p in data_list] if data_list else []

    own_active = _make_list(req_dict.get("own_active", []))
    own_bench = _make_list(req_dict.get("own_bench", []))
    opp_active = _make_list(req_dict.get("opp_active", []))
    opp_bench = _make_list(req_dict.get("opp_bench", []))

    f = req_dict.get("field", {})
    sim_field = SimField(
        weather=f.get("weather", ""),
        terrain=f.get("terrain", ""),
        trick_room=f.get("trick_room", False),
        tailwind_own=f.get("tailwind_own", False),
        tailwind_opp=f.get("tailwind_opp", False),
        screens_own=f.get("screens_own", [False, False, False])[:3],
        screens_opp=f.get("screens_opp", [False, False, False])[:3],
    )

    return SimState(
        own_active=own_active,
        own_bench=own_bench,
        opp_active=opp_active,
        opp_bench=opp_bench,
        field=sim_field,
        turn=f.get("turn", 1),
    )
