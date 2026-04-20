"""Parse Pokemon Showdown VGC battle logs into structured training data.

Extracts per-turn game states and actions from the winner's perspective.
Handles the Champions VGC doubles format (bring 6, pick 4, Mega Evolution).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Pokemon:
    species: str
    hp: float = 1.0  # 0.0 - 1.0
    max_hp: int = 100
    status: str = ""  # brn, par, slp, frz, psn, tox
    boosts: dict[str, int] = field(default_factory=dict)
    item: str = ""  # only known once revealed
    ability: str = ""  # only known once revealed
    moves_known: list[str] = field(default_factory=list)
    mega: bool = False
    fainted: bool = False
    gender: str = ""
    level: int = 50


@dataclass
class FieldState:
    weather: str = ""  # SunnyDay, RainDance, Sandstorm, Snow
    terrain: str = ""  # Electric, Grassy, Psychic, Misty
    trick_room: bool = False
    # Per-side effects
    tailwind_p1: bool = False
    tailwind_p2: bool = False
    light_screen_p1: bool = False
    light_screen_p2: bool = False
    reflect_p1: bool = False
    reflect_p2: bool = False
    aurora_veil_p1: bool = False
    aurora_veil_p2: bool = False


@dataclass
class Action:
    type: str  # "move" or "switch"
    move: str = ""
    target: str = ""  # "p1a", "p1b", "p2a", "p2b", or "" for self/spread
    mega: bool = False
    switch_to: str = ""  # species name when switching


@dataclass
class TurnActions:
    """Actions for both active slots of one player in a turn."""
    slot_a: Optional[Action] = None
    slot_b: Optional[Action] = None


@dataclass
class TeamPreview:
    p1_team: list[str] = field(default_factory=list)  # 6 species
    p2_team: list[str] = field(default_factory=list)  # 6 species
    p1_selected: list[str] = field(default_factory=list)  # 4 species brought
    p2_selected: list[str] = field(default_factory=list)
    p1_leads: list[str] = field(default_factory=list)  # 2 species leading
    p2_leads: list[str] = field(default_factory=list)


@dataclass
class GameState:
    """Complete game state at a decision point."""
    # Active pokemon (slot a, slot b) for each side
    p1_active: list[Pokemon] = field(default_factory=list)  # len 0-2
    p2_active: list[Pokemon] = field(default_factory=list)
    # Bench pokemon
    p1_bench: list[Pokemon] = field(default_factory=list)
    p2_bench: list[Pokemon] = field(default_factory=list)
    # Field
    field: FieldState = field(default_factory=FieldState)
    turn: int = 0


@dataclass
class TrainingSample:
    """One training sample: state + action taken by a player."""
    state: GameState
    actions: TurnActions
    player: str  # "p1" or "p2"
    is_winner: bool = False
    rating: int = 0


@dataclass
class ParsedBattle:
    team_preview: TeamPreview
    samples: list[TrainingSample]
    winner: str  # "p1" or "p2"
    p1_rating: int = 0
    p2_rating: int = 0


def normalize_species(species: str) -> str:
    """Normalize species name: 'Charizard-Mega-Y, L50, M, shiny' -> 'Charizard-Mega-Y'"""
    return species.split(",")[0].strip()


def parse_hp(hp_str: str) -> float:
    """Parse HP string like '85/100' or '0 fnt' -> float 0.0-1.0"""
    if "fnt" in hp_str:
        return 0.0
    hp_str = hp_str.split()[0]  # strip status like "85/100 brn"
    if "/" in hp_str:
        cur, max_hp = hp_str.split("/")
        return float(cur) / float(max_hp)
    return float(hp_str) / 100.0


def parse_status_from_hp(hp_str: str) -> str:
    """Extract status from HP string like '85/100 brn'"""
    parts = hp_str.split()
    if len(parts) > 1 and parts[1] in ("brn", "par", "slp", "frz", "psn", "tox"):
        return parts[1]
    return ""


class BattleParser:
    """Parses a single battle log into training samples."""

    def __init__(self, log: str, rating: int = 0):
        self.lines = log.strip().split("\n")
        self.rating = rating

        # Player info
        self.p1_name = ""
        self.p2_name = ""
        self.winner_player = ""  # "p1" or "p2"

        # Team preview
        self.preview = TeamPreview()

        # Live game state - pokemon tracked by nickname
        self.pokemon: dict[str, Pokemon] = {}  # "p1a" slot -> Pokemon, etc.
        self.all_pokemon: dict[str, Pokemon] = {}  # "p1: Nickname" -> Pokemon
        self.nickname_to_species: dict[str, str] = {}  # "p1: Nickname" -> species
        self.species_to_nickname: dict[str, str] = {}  # "p1|Species" -> nickname key

        # Field state
        self.field = FieldState()

        # Current active slots
        self.active_slots: dict[str, str] = {}  # "p1a" -> "p1: Nickname"

        # Turn tracking
        self.current_turn = 0
        self.turn_actions: dict[str, list[Action]] = {"p1": [], "p2": []}
        self.samples: list[TrainingSample] = []

        # Mega tracking per turn
        self.mega_this_turn: set[str] = set()  # slots that mega'd

    def parse(self) -> Optional[ParsedBattle]:
        """Parse the full battle log. Returns None if invalid."""
        for line in self.lines:
            self._process_line(line)

        if not self.winner_player or not self.preview.p1_team:
            return None

        return ParsedBattle(
            team_preview=self.preview,
            samples=self.samples,
            winner=self.winner_player,
            p1_rating=self.rating,
            p2_rating=self.rating,
        )

    def _process_line(self, line: str):
        if not line.startswith("|"):
            return
        parts = line.split("|")
        if len(parts) < 2:
            return
        cmd = parts[1]

        # Commands like "-ability" -> "cmd_neg_ability"
        if cmd.startswith("-"):
            handler_name = f"_cmd_neg_{cmd[1:]}"
        else:
            handler_name = f"_cmd_{cmd}"
        handler = getattr(self, handler_name, None)
        if handler:
            handler(parts)

    def _cmd_player(self, parts: list[str]):
        if len(parts) < 4:
            return
        player = parts[2]  # p1 or p2
        name = parts[3]
        if player == "p1" and name:
            self.p1_name = name
        elif player == "p2" and name:
            self.p2_name = name

    def _cmd_poke(self, parts: list[str]):
        """Team preview: |poke|p1|Species, L50, M|"""
        player = parts[2]
        species = normalize_species(parts[3])
        if player == "p1":
            self.preview.p1_team.append(species)
        else:
            self.preview.p2_team.append(species)

    def _cmd_start(self, parts: list[str]):
        """Battle starts - what follows are the initial switches."""
        pass

    def _cmd_switch(self, parts: list[str]):
        """|switch|p1a: Nickname|Species, L50, M|HP/MaxHP"""
        if len(parts) < 5:
            return
        slot_info = parts[2]  # "p1a: Nickname"
        species_info = parts[3]
        hp_str = parts[4] if len(parts) > 4 else "100/100"

        # Parse slot and nickname
        slot = slot_info[:3]  # "p1a"
        nickname = slot_info.split(": ", 1)[1] if ": " in slot_info else slot_info[5:]
        player = slot[:2]  # "p1"
        species = normalize_species(species_info)

        # Create/update pokemon record
        key = f"{player}: {nickname}"
        if key not in self.all_pokemon:
            poke = Pokemon(species=species)
            self.all_pokemon[key] = poke
            self.nickname_to_species[key] = species
            self.species_to_nickname[f"{player}|{species}"] = key
        else:
            poke = self.all_pokemon[key]
            # Update species in case of form change
            poke.species = species

        poke.hp = parse_hp(hp_str)
        status = parse_status_from_hp(hp_str)
        if status:
            poke.status = status

        # Track active slot
        self.active_slots[slot] = key

        # Track selected/leads for team preview (use base species for mega forms)
        base_species = self._base_species(species)
        selected_list = self.preview.p1_selected if player == "p1" else self.preview.p2_selected
        leads_list = self.preview.p1_leads if player == "p1" else self.preview.p2_leads

        if base_species not in selected_list:
            selected_list.append(base_species)
        if self.current_turn == 0 and base_species not in leads_list:
            leads_list.append(base_species)

        # Record as switch action if during a turn
        if self.current_turn > 0:
            self.turn_actions[player].append(Action(
                type="switch",
                switch_to=species,
            ))

    def _cmd_drag(self, parts: list[str]):
        """Forced switch (e.g. Whirlwind) - same format as switch."""
        self._cmd_switch(parts)

    def _cmd_move(self, parts: list[str]):
        """|move|p1a: Nickname|MoveName|target"""
        if len(parts) < 4:
            return
        slot_info = parts[2]
        move_name = parts[3]
        target = parts[4] if len(parts) > 4 else ""

        slot = slot_info[:3]
        player = slot[:2]

        # Check if this move was from a forced action (copycat, metronome, etc.)
        rest = "|".join(parts[4:])
        if "[from]" in rest:
            return  # not a player decision

        # Parse target slot
        target_slot = ""
        if target and ":" in target:
            target_slot = target[:3]  # "p2a" from "p2a: Nickname"

        mega = slot in self.mega_this_turn

        self.turn_actions[player].append(Action(
            type="move",
            move=move_name,
            target=target_slot,
            mega=mega,
        ))

    def _cmd_turn(self, parts: list[str]):
        """|turn|N - emit training sample for previous turn, start new turn."""
        new_turn = int(parts[2])

        if self.current_turn > 0:
            self._emit_turn_sample()

        self.current_turn = new_turn
        self.turn_actions = {"p1": [], "p2": []}
        self.mega_this_turn = set()

    def _cmd_win(self, parts: list[str]):
        """|win|PlayerName"""
        winner_name = parts[2]
        if winner_name == self.p1_name:
            self.winner_player = "p1"
        elif winner_name == self.p2_name:
            self.winner_player = "p2"

        # Emit final turn
        if self.current_turn > 0:
            self._emit_turn_sample()

    def _cmd_detailschange(self, parts: list[str]):
        """|detailschange|p1a: Nickname|Species-Mega, L50, M"""
        if len(parts) < 4:
            return
        slot_info = parts[2]
        species = normalize_species(parts[3])
        player = slot_info[:2]
        key = f"{player}: {slot_info.split(': ', 1)[1]}" if ": " in slot_info else None
        if key and key in self.all_pokemon:
            self.all_pokemon[key].species = species

    def _cmd_neg_mega(self, parts: list[str]):
        """|-mega|p1a: Nickname|Species|MegaStone"""
        if len(parts) < 3:
            return
        slot_info = parts[2]
        slot = slot_info[:3]
        self.mega_this_turn.add(slot)

        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].mega = True

    def _cmd_neg_damage(self, parts: list[str]):
        """|-damage|p1a: Nickname|HP/MaxHP"""
        if len(parts) < 4:
            return
        self._update_hp(parts[2], parts[3])

    def _cmd_neg_heal(self, parts: list[str]):
        """|-heal|p1a: Nickname|HP/MaxHP"""
        if len(parts) < 4:
            return
        self._update_hp(parts[2], parts[3])

    def _cmd_faint(self, parts: list[str]):
        """|faint|p1a: Nickname"""
        if len(parts) < 3:
            return
        slot_info = parts[2]
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].hp = 0.0
            self.all_pokemon[key].fainted = True

    def _cmd_neg_status(self, parts: list[str]):
        """|-status|p1a: Nickname|brn"""
        if len(parts) < 4:
            return
        slot_info = parts[2]
        status = parts[3]
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].status = status

    def _cmd_neg_curestatus(self, parts: list[str]):
        """|-curestatus|p1a: Nickname|brn"""
        if len(parts) < 3:
            return
        slot_info = parts[2]
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].status = ""

    def _cmd_neg_boost(self, parts: list[str]):
        """|-boost|p1a: Nickname|atk|1"""
        if len(parts) < 5:
            return
        slot_info = parts[2]
        stat = parts[3]
        amount = int(parts[4])
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            poke = self.all_pokemon[key]
            poke.boosts[stat] = poke.boosts.get(stat, 0) + amount

    def _cmd_neg_unboost(self, parts: list[str]):
        """|-unboost|p1a: Nickname|atk|1"""
        if len(parts) < 5:
            return
        slot_info = parts[2]
        stat = parts[3]
        amount = int(parts[4])
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            poke = self.all_pokemon[key]
            poke.boosts[stat] = poke.boosts.get(stat, 0) - amount

    def _cmd_neg_weather(self, parts: list[str]):
        """|-weather|SunnyDay|[from]..."""
        if len(parts) < 3:
            return
        weather = parts[2]
        if weather == "none":
            self.field.weather = ""
        elif "[upkeep]" not in "|".join(parts):
            self.field.weather = weather

    def _cmd_neg_fieldstart(self, parts: list[str]):
        """|-fieldstart|move: Trick Room"""
        if len(parts) < 3:
            return
        effect = parts[2]
        if "Trick Room" in effect:
            self.field.trick_room = True
        elif "Electric Terrain" in effect:
            self.field.terrain = "Electric"
        elif "Grassy Terrain" in effect:
            self.field.terrain = "Grassy"
        elif "Psychic Terrain" in effect:
            self.field.terrain = "Psychic"
        elif "Misty Terrain" in effect:
            self.field.terrain = "Misty"

    def _cmd_neg_fieldend(self, parts: list[str]):
        """|-fieldend|move: Trick Room"""
        if len(parts) < 3:
            return
        effect = parts[2]
        if "Trick Room" in effect:
            self.field.trick_room = False
        elif "Terrain" in effect:
            self.field.terrain = ""

    def _cmd_neg_sidestart(self, parts: list[str]):
        """|-sidestart|p1: Name|move: Tailwind"""
        if len(parts) < 4:
            return
        side = parts[2][:2]  # "p1" or "p2"
        effect = parts[3]
        if "Tailwind" in effect:
            setattr(self.field, f"tailwind_{side}", True)
        elif "Light Screen" in effect:
            setattr(self.field, f"light_screen_{side}", True)
        elif "Reflect" in effect:
            setattr(self.field, f"reflect_{side}", True)
        elif "Aurora Veil" in effect:
            setattr(self.field, f"aurora_veil_{side}", True)

    def _cmd_neg_sideend(self, parts: list[str]):
        """|-sideend|p1: Name|move: Tailwind"""
        if len(parts) < 4:
            return
        side = parts[2][:2]
        effect = parts[3]
        if "Tailwind" in effect:
            setattr(self.field, f"tailwind_{side}", False)
        elif "Light Screen" in effect:
            setattr(self.field, f"light_screen_{side}", False)
        elif "Reflect" in effect:
            setattr(self.field, f"reflect_{side}", False)
        elif "Aurora Veil" in effect:
            setattr(self.field, f"aurora_veil_{side}", False)

    def _cmd_neg_ability(self, parts: list[str]):
        """|-ability|p1a: Nickname|Intimidate"""
        if len(parts) < 4:
            return
        slot_info = parts[2]
        ability = parts[3]
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].ability = ability

    def _cmd_neg_enditem(self, parts: list[str]):
        """|-enditem|p1a: Nickname|Sitrus Berry"""
        if len(parts) < 4:
            return
        slot_info = parts[2]
        item = parts[3]
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].item = item

    def _cmd_neg_item(self, parts: list[str]):
        """|-item|p1a: Nickname|Leftovers|[from]..."""
        if len(parts) < 4:
            return
        slot_info = parts[2]
        item = parts[3]
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].item = item

    @staticmethod
    def _base_species(species: str) -> str:
        """Strip Mega suffix: 'Charizard-Mega-Y' -> 'Charizard'"""
        if "-Mega" in species:
            return species.split("-Mega")[0]
        return species

    def _update_hp(self, slot_info: str, hp_str: str):
        slot = slot_info[:3]
        key = self.active_slots.get(slot)
        if key and key in self.all_pokemon:
            self.all_pokemon[key].hp = parse_hp(hp_str)
            status = parse_status_from_hp(hp_str)
            if status:
                self.all_pokemon[key].status = status

    def _build_game_state(self) -> GameState:
        """Build current game state snapshot."""
        state = GameState(field=FieldState(
            weather=self.field.weather,
            terrain=self.field.terrain,
            trick_room=self.field.trick_room,
            tailwind_p1=self.field.tailwind_p1,
            tailwind_p2=self.field.tailwind_p2,
            light_screen_p1=self.field.light_screen_p1,
            light_screen_p2=self.field.light_screen_p2,
            reflect_p1=self.field.reflect_p1,
            reflect_p2=self.field.reflect_p2,
            aurora_veil_p1=self.field.aurora_veil_p1,
            aurora_veil_p2=self.field.aurora_veil_p2,
        ), turn=self.current_turn)

        # Build active/bench lists for each player
        for player in ("p1", "p2"):
            active = []
            bench = []
            active_species = set()

            for slot_suffix in ("a", "b"):
                slot = f"{player}{slot_suffix}"
                key = self.active_slots.get(slot)
                if key and key in self.all_pokemon:
                    poke = self.all_pokemon[key]
                    if not poke.fainted:
                        active.append(Pokemon(
                            species=poke.species,
                            hp=poke.hp,
                            status=poke.status,
                            boosts=dict(poke.boosts),
                            item=poke.item,
                            ability=poke.ability,
                            moves_known=list(poke.moves_known),
                            mega=poke.mega,
                            fainted=poke.fainted,
                        ))
                        active_species.add(poke.species)

            # Find bench pokemon (selected but not active and not fainted)
            selected = self.preview.p1_selected if player == "p1" else self.preview.p2_selected
            for species in selected:
                if species in active_species:
                    continue
                # Find this pokemon in our records
                nick_key = self.species_to_nickname.get(f"{player}|{species}")
                if nick_key and nick_key in self.all_pokemon:
                    poke = self.all_pokemon[nick_key]
                    if not poke.fainted:
                        bench.append(Pokemon(
                            species=poke.species,
                            hp=poke.hp,
                            status=poke.status,
                            boosts=dict(poke.boosts),
                            item=poke.item,
                            ability=poke.ability,
                            moves_known=list(poke.moves_known),
                            mega=poke.mega,
                            fainted=poke.fainted,
                        ))

            if player == "p1":
                state.p1_active = active
                state.p1_bench = bench
            else:
                state.p2_active = active
                state.p2_bench = bench

        return state

    def _emit_turn_sample(self):
        """Create training samples from the current turn's actions."""
        state = self._build_game_state()

        for player in ("p1", "p2"):
            actions = self.turn_actions[player]
            if not actions:
                continue

            turn_actions = TurnActions()
            if len(actions) >= 1:
                turn_actions.slot_a = actions[0]
            if len(actions) >= 2:
                turn_actions.slot_b = actions[1]

            self.samples.append(TrainingSample(
                state=state,
                actions=turn_actions,
                player=player,
                is_winner=False,  # set after we know winner
                rating=self.rating,
            ))

        # Track moves for known moves
        for player in ("p1", "p2"):
            for action in self.turn_actions[player]:
                if action.type == "move":
                    # Find which pokemon used this move
                    for slot_suffix in ("a", "b"):
                        slot = f"{player}{slot_suffix}"
                        key = self.active_slots.get(slot)
                        if key and key in self.all_pokemon:
                            poke = self.all_pokemon[key]
                            if action.move not in poke.moves_known:
                                poke.moves_known.append(action.move)
                            break


def parse_battle(log: str, rating: int = 0) -> Optional[ParsedBattle]:
    """Parse a battle log string into structured training data."""
    parser = BattleParser(log, rating)
    result = parser.parse()

    if result is None:
        return None

    # Mark winner's samples
    for sample in result.samples:
        sample.is_winner = (sample.player == result.winner)

    return result
