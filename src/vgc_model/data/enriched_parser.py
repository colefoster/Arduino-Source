"""Two-pass enriched battle log parser for model v2 training.

Pass 1: Scan the full log to collect ALL revealed moves/items/abilities per Pokemon.
Pass 2: Re-parse turn-by-turn, generating player-POV training samples with
        progressive revelation and confidence flags.

Own team gets retroactive knowledge (everything revealed in the log) as baseline,
optionally enriched by player profiles and usage stats.
Opponent team only sees information revealed up to the current turn.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable

from .log_parser import (
    Action,
    BattleParser,
    FieldState,
    GameState,
    Pokemon,
    TeamPreview,
    TurnActions,
    normalize_species,
    parse_hp,
    parse_status_from_hp,
)


# ---------------------------------------------------------------------------
# Confidence tiers
# ---------------------------------------------------------------------------
CONF_KNOWN = 1.0       # Revealed in this game's log
CONF_PLAYER = 0.8      # Inferred from same player's other games
CONF_USAGE = 0.5       # Inferred from population usage stats
CONF_UNKNOWN = 0.0     # Not yet revealed, no inference


# ---------------------------------------------------------------------------
# Protocols for optional enrichment sources
# ---------------------------------------------------------------------------
@runtime_checkable
class UsageStats(Protocol):
    """Lookup population-level move/item/ability distributions for a species."""

    def top_moves(self, species: str, n: int = 4) -> list[str]: ...
    def top_item(self, species: str) -> str: ...
    def top_ability(self, species: str) -> str: ...


@runtime_checkable
class PlayerProfiles(Protocol):
    """Lookup a specific player's known sets from cross-game history."""

    def get_moves(self, player: str, species: str) -> list[str]: ...
    def get_item(self, player: str, species: str) -> str: ...
    def get_ability(self, player: str, species: str) -> str: ...


# ---------------------------------------------------------------------------
# Enriched dataclasses
# ---------------------------------------------------------------------------
@dataclass
class EnrichedPokemon(Pokemon):
    """Pokemon with per-slot confidence flags for inferred data."""
    move_confidences: list[float] = field(default_factory=list)  # per move slot
    item_confidence: float = 0.0
    ability_confidence: float = 0.0


@dataclass
class EnrichedSample:
    """One training sample from a single player's POV."""
    state: GameState
    actions: TurnActions
    player: str                           # "p1" or "p2" — the POV player
    is_winner: bool
    rating: int
    own_team_full: list[EnrichedPokemon]  # all own Pokemon with enriched data
    opp_team_preview: list[str]           # opponent's 6 species from team preview
    # Move execution order: which slots moved first this turn (in log order)
    # e.g. ["p2a", "p1a", "p2b", "p1b"] means p2a was fastest
    move_order: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pass 1: full-log knowledge extraction
# ---------------------------------------------------------------------------
@dataclass
class _FullKnowledge:
    """Everything the log eventually reveals about one Pokemon."""
    species: str = ""
    moves: list[str] = field(default_factory=list)
    item: str = ""
    ability: str = ""


def _pass1_extract(log: str) -> dict[str, _FullKnowledge]:
    """Scan the full log and collect all revealed info per pokemon.

    Returns a dict keyed by "p1|Species" or "p2|Species".
    """
    knowledge: dict[str, _FullKnowledge] = {}
    # We need to track slot -> species mapping to attribute moves correctly
    active_slots: dict[str, str] = {}           # "p1a" -> "p1|Species"
    nickname_to_key: dict[str, str] = {}        # "p1: Nickname" -> "p1|Species"

    for line in log.strip().split("\n"):
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        cmd = parts[1]

        if cmd == "poke" and len(parts) >= 4:
            player = parts[2]
            species = normalize_species(parts[3])
            key = f"{player}|{species}"
            if key not in knowledge:
                knowledge[key] = _FullKnowledge(species=species)

        elif cmd in ("switch", "drag") and len(parts) >= 4:
            slot_info = parts[2]
            slot = slot_info[:3]
            player = slot[:2]
            nickname = slot_info.split(": ", 1)[1] if ": " in slot_info else slot_info[5:]
            species = normalize_species(parts[3])
            base = _base_species(species)
            key = f"{player}|{base}"
            nick_key = f"{player}: {nickname}"

            if key not in knowledge:
                knowledge[key] = _FullKnowledge(species=base)

            active_slots[slot] = key
            nickname_to_key[nick_key] = key

        elif cmd == "move" and len(parts) >= 4:
            slot_info = parts[2]
            slot = slot_info[:3]
            move_name = parts[3]

            # Skip forced moves (copycat, metronome, etc.)
            rest = "|".join(parts[4:])
            if "[from]" in rest:
                continue

            key = active_slots.get(slot)
            if key and key in knowledge:
                if move_name not in knowledge[key].moves:
                    knowledge[key].moves.append(move_name)

        elif cmd == "-item" and len(parts) >= 4:
            slot_info = parts[2]
            slot = slot_info[:3]
            item = parts[3]
            key = active_slots.get(slot)
            if key and key in knowledge:
                knowledge[key].item = item

        elif cmd == "-enditem" and len(parts) >= 4:
            slot_info = parts[2]
            slot = slot_info[:3]
            item = parts[3]
            key = active_slots.get(slot)
            if key and key in knowledge:
                if not knowledge[key].item:
                    knowledge[key].item = item

        elif cmd == "-ability" and len(parts) >= 4:
            slot_info = parts[2]
            slot = slot_info[:3]
            ability = parts[3]
            key = active_slots.get(slot)
            if key and key in knowledge:
                knowledge[key].ability = ability

        elif cmd == "-mega" and len(parts) >= 5:
            slot_info = parts[2]
            slot = slot_info[:3]
            mega_stone = parts[4]
            key = active_slots.get(slot)
            if key and key in knowledge:
                knowledge[key].item = mega_stone

    return knowledge


# ---------------------------------------------------------------------------
# Pass 2: turn-by-turn enriched sample generation
# ---------------------------------------------------------------------------
class EnrichedBattleParser:
    """Two-pass parser producing player-POV enriched training samples."""

    def __init__(
        self,
        log: str,
        rating: int = 0,
        usage_stats: Optional[UsageStats] = None,
        player_profiles: Optional[PlayerProfiles] = None,
        player_name: Optional[str] = None,
    ):
        self.log = log
        self.rating = rating
        self.usage_stats = usage_stats
        self.player_profiles = player_profiles
        self.player_name = player_name

    def parse(self) -> Optional[list[EnrichedSample]]:
        """Run both passes and return enriched samples, or None if invalid."""
        # Use the existing parser for pass 2 mechanics
        base_parser = BattleParser(self.log, self.rating)
        base_result = base_parser.parse()
        if base_result is None:
            return None

        # Pass 1: retroactive knowledge
        full_knowledge = _pass1_extract(self.log)

        # Pass 2: re-parse turn-by-turn with progressive revelation
        return self._pass2_generate(base_result, base_parser, full_knowledge)

    def _pass2_generate(
        self,
        base_result,
        base_parser: BattleParser,
        full_knowledge: dict[str, _FullKnowledge],
    ) -> list[EnrichedSample]:
        """Generate enriched samples by replaying the log turn-by-turn."""
        samples: list[EnrichedSample] = []

        # Track what the opponent has revealed per turn
        # Key: "p1|Species" or "p2|Species" -> _FullKnowledge (revealed so far)
        revealed: dict[str, _FullKnowledge] = {}

        # Re-parse line by line tracking revelations per turn
        lines = self.log.strip().split("\n")
        active_slots: dict[str, str] = {}   # "p1a" -> "p1|Species"
        current_turn = 0
        turn_actions: dict[str, dict[str, Action]] = {"p1": {}, "p2": {}}
        mega_this_turn: set[str] = set()
        move_order_this_turn: list[str] = []  # slots in execution order, e.g. ["p2a", "p1a"]

        # Player info
        p1_name = ""
        p2_name = ""
        winner_player = ""
        preview = base_result.team_preview

        # Pokemon state tracking (mirrors BattleParser but we need our own)
        all_pokemon: dict[str, Pokemon] = {}       # "p1: Nick" -> Pokemon
        nickname_to_species: dict[str, str] = {}   # "p1: Nick" -> species
        species_to_nickname: dict[str, str] = {}   # "p1|Species" -> "p1: Nick"
        slot_to_nick: dict[str, str] = {}           # "p1a" -> "p1: Nick"
        field_state = FieldState()

        for line in lines:
            if not line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            cmd = parts[1]

            if cmd == "player" and len(parts) >= 4:
                player = parts[2]
                name = parts[3]
                if player == "p1" and name:
                    p1_name = name
                elif player == "p2" and name:
                    p2_name = name

            elif cmd in ("switch", "drag") and len(parts) >= 4:
                slot_info = parts[2]
                slot = slot_info[:3]
                player = slot[:2]
                nickname = slot_info.split(": ", 1)[1] if ": " in slot_info else slot_info[5:]
                species = normalize_species(parts[3])
                base = _base_species(species)
                hp_str = parts[4] if len(parts) > 4 else "100/100"

                nick_key = f"{player}: {nickname}"
                pkey = f"{player}|{base}"

                if nick_key not in all_pokemon:
                    poke = Pokemon(species=species)
                    all_pokemon[nick_key] = poke
                    nickname_to_species[nick_key] = base
                    species_to_nickname[pkey] = nick_key
                else:
                    poke = all_pokemon[nick_key]
                    poke.species = species

                poke.hp = parse_hp(hp_str)
                status = parse_status_from_hp(hp_str)
                if status:
                    poke.status = status
                poke.fainted = False  # reset on switch-in

                active_slots[slot] = pkey
                slot_to_nick[slot] = nick_key

                # Record switch action during turns
                slot_suffix = slot[2]
                if current_turn > 0:
                    turn_actions[player][slot_suffix] = Action(
                        type="switch", switch_to=species, slot=slot_suffix
                    )

            elif cmd == "move" and len(parts) >= 4:
                slot_info = parts[2]
                slot = slot_info[:3]
                player = slot[:2]
                slot_suffix = slot[2]
                move_name = parts[3]
                target = parts[4] if len(parts) > 4 else ""

                rest = "|".join(parts[4:])
                if "[from]" in rest:
                    continue

                if slot_suffix in turn_actions[player]:
                    continue

                target_slot = ""
                if target and ":" in target:
                    target_slot = target[:3]

                mega = slot in mega_this_turn

                turn_actions[player][slot_suffix] = Action(
                    type="move", move=move_name, target=target_slot,
                    mega=mega, slot=slot_suffix,
                )

                # Track move execution order
                move_order_this_turn.append(slot)

                # Track revelation
                pkey = active_slots.get(slot)
                if pkey:
                    if pkey not in revealed:
                        revealed[pkey] = _FullKnowledge(species=pkey.split("|", 1)[1])
                    if move_name not in revealed[pkey].moves:
                        revealed[pkey].moves.append(move_name)
                    # Also update the pokemon's moves_known
                    nick_key = slot_to_nick.get(slot)
                    if nick_key and nick_key in all_pokemon:
                        poke = all_pokemon[nick_key]
                        if move_name not in poke.moves_known:
                            poke.moves_known.append(move_name)

            elif cmd == "-ability" and len(parts) >= 4:
                slot_info = parts[2]
                slot = slot_info[:3]
                ability = parts[3]
                nick_key = slot_to_nick.get(slot)
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].ability = ability
                pkey = active_slots.get(slot)
                if pkey:
                    if pkey not in revealed:
                        revealed[pkey] = _FullKnowledge(species=pkey.split("|", 1)[1])
                    revealed[pkey].ability = ability

            elif cmd in ("-item", "-enditem") and len(parts) >= 4:
                slot_info = parts[2]
                slot = slot_info[:3]
                item = parts[3]
                nick_key = slot_to_nick.get(slot)
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].item = item
                pkey = active_slots.get(slot)
                if pkey:
                    if pkey not in revealed:
                        revealed[pkey] = _FullKnowledge(species=pkey.split("|", 1)[1])
                    if not revealed[pkey].item:
                        revealed[pkey].item = item

            elif cmd == "-mega" and len(parts) >= 5:
                slot_info = parts[2]
                slot = slot_info[:3]
                mega_stone = parts[4]
                mega_this_turn.add(slot)
                nick_key = slot_to_nick.get(slot)
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].mega = True
                pkey = active_slots.get(slot)
                if pkey:
                    if pkey not in revealed:
                        revealed[pkey] = _FullKnowledge(species=pkey.split("|", 1)[1])
                    revealed[pkey].item = mega_stone

            elif cmd == "-damage" and len(parts) >= 4:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].hp = parse_hp(parts[3])
                    s = parse_status_from_hp(parts[3])
                    if s:
                        all_pokemon[nick_key].status = s

            elif cmd == "-heal" and len(parts) >= 4:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].hp = parse_hp(parts[3])
                    s = parse_status_from_hp(parts[3])
                    if s:
                        all_pokemon[nick_key].status = s

            elif cmd == "faint" and len(parts) >= 3:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].hp = 0.0
                    all_pokemon[nick_key].fainted = True

            elif cmd == "-status" and len(parts) >= 4:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].status = parts[3]

            elif cmd == "-curestatus" and len(parts) >= 3:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    all_pokemon[nick_key].status = ""

            elif cmd == "-boost" and len(parts) >= 5:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    poke = all_pokemon[nick_key]
                    poke.boosts[parts[3]] = poke.boosts.get(parts[3], 0) + int(parts[4])

            elif cmd == "-unboost" and len(parts) >= 5:
                nick_key = slot_to_nick.get(parts[2][:3])
                if nick_key and nick_key in all_pokemon:
                    poke = all_pokemon[nick_key]
                    poke.boosts[parts[3]] = poke.boosts.get(parts[3], 0) - int(parts[4])

            elif cmd == "-weather" and len(parts) >= 3:
                weather = parts[2]
                if weather == "none":
                    field_state.weather = ""
                elif "[upkeep]" not in "|".join(parts):
                    field_state.weather = weather

            elif cmd == "-fieldstart" and len(parts) >= 3:
                effect = parts[2]
                if "Trick Room" in effect:
                    field_state.trick_room = True
                elif "Electric Terrain" in effect:
                    field_state.terrain = "Electric"
                elif "Grassy Terrain" in effect:
                    field_state.terrain = "Grassy"
                elif "Psychic Terrain" in effect:
                    field_state.terrain = "Psychic"
                elif "Misty Terrain" in effect:
                    field_state.terrain = "Misty"

            elif cmd == "-fieldend" and len(parts) >= 3:
                effect = parts[2]
                if "Trick Room" in effect:
                    field_state.trick_room = False
                elif "Terrain" in effect:
                    field_state.terrain = ""

            elif cmd == "-sidestart" and len(parts) >= 4:
                side = parts[2][:2]
                effect = parts[3]
                if "Tailwind" in effect:
                    setattr(field_state, f"tailwind_{side}", True)
                elif "Light Screen" in effect:
                    setattr(field_state, f"light_screen_{side}", True)
                elif "Reflect" in effect:
                    setattr(field_state, f"reflect_{side}", True)
                elif "Aurora Veil" in effect:
                    setattr(field_state, f"aurora_veil_{side}", True)

            elif cmd == "-sideend" and len(parts) >= 4:
                side = parts[2][:2]
                effect = parts[3]
                if "Tailwind" in effect:
                    setattr(field_state, f"tailwind_{side}", False)
                elif "Light Screen" in effect:
                    setattr(field_state, f"light_screen_{side}", False)
                elif "Reflect" in effect:
                    setattr(field_state, f"reflect_{side}", False)
                elif "Aurora Veil" in effect:
                    setattr(field_state, f"aurora_veil_{side}", False)

            elif cmd == "turn":
                new_turn = int(parts[2])
                if current_turn > 0:
                    # Emit samples for the previous turn
                    state = self._build_state(
                        active_slots, slot_to_nick, all_pokemon,
                        preview, field_state, current_turn,
                        species_to_nickname,
                    )
                    self._emit_samples(
                        samples, state, turn_actions, current_turn,
                        preview, full_knowledge, revealed,
                        winner_player, active_slots, move_order_this_turn,
                    )
                current_turn = new_turn
                turn_actions = {"p1": {}, "p2": {}}
                mega_this_turn = set()
                move_order_this_turn = []

            elif cmd == "win" and len(parts) >= 3:
                winner_name = parts[2]
                if winner_name == p1_name:
                    winner_player = "p1"
                elif winner_name == p2_name:
                    winner_player = "p2"

                # Emit final turn
                if current_turn > 0:
                    state = self._build_state(
                        active_slots, slot_to_nick, all_pokemon,
                        preview, field_state, current_turn,
                        species_to_nickname,
                    )
                    self._emit_samples(
                        samples, state, turn_actions, current_turn,
                        preview, full_knowledge, revealed,
                        winner_player, active_slots, move_order_this_turn,
                    )

        # Retroactively set is_winner (winner_player only known at |win|)
        if winner_player:
            for s in samples:
                s.is_winner = (s.player == winner_player)

        return samples if samples else None

    def _build_state(
        self,
        active_slots: dict[str, str],
        slot_to_nick: dict[str, str],
        all_pokemon: dict[str, Pokemon],
        preview: TeamPreview,
        field_state: FieldState,
        turn: int,
        species_to_nickname: dict[str, str],
    ) -> GameState:
        """Build a GameState snapshot (same logic as BattleParser)."""
        state = GameState(
            field=copy.deepcopy(field_state),
            turn=turn,
        )
        for player in ("p1", "p2"):
            active = []
            bench = []
            active_species = set()

            for slot_suffix in ("a", "b"):
                slot = f"{player}{slot_suffix}"
                nick_key = slot_to_nick.get(slot)
                if nick_key and nick_key in all_pokemon:
                    poke = all_pokemon[nick_key]
                    if not poke.fainted:
                        active.append(Pokemon(
                            species=poke.species, hp=poke.hp, status=poke.status,
                            boosts=dict(poke.boosts), item=poke.item,
                            ability=poke.ability, moves_known=list(poke.moves_known),
                            mega=poke.mega, fainted=poke.fainted,
                        ))
                        active_species.add(_base_species(poke.species))

            selected = preview.p1_selected if player == "p1" else preview.p2_selected
            for species in selected:
                if species in active_species:
                    continue
                nick_key = species_to_nickname.get(f"{player}|{species}")
                if nick_key and nick_key in all_pokemon:
                    poke = all_pokemon[nick_key]
                    if not poke.fainted:
                        bench.append(Pokemon(
                            species=poke.species, hp=poke.hp, status=poke.status,
                            boosts=dict(poke.boosts), item=poke.item,
                            ability=poke.ability, moves_known=list(poke.moves_known),
                            mega=poke.mega, fainted=poke.fainted,
                        ))

            if player == "p1":
                state.p1_active = active
                state.p1_bench = bench
            else:
                state.p2_active = active
                state.p2_bench = bench

        return state

    def _emit_samples(
        self,
        samples: list[EnrichedSample],
        state: GameState,
        turn_actions: dict[str, dict[str, Action]],
        turn: int,
        preview: TeamPreview,
        full_knowledge: dict[str, _FullKnowledge],
        revealed: dict[str, _FullKnowledge],
        winner_player: str,
        active_slots: dict[str, str],
        move_order: list[str] = None,
    ):
        """Emit one EnrichedSample per player that acted this turn."""
        for pov_player in ("p1", "p2"):
            slot_actions = turn_actions[pov_player]
            if not slot_actions:
                continue

            ta = TurnActions(
                slot_a=slot_actions.get("a"),
                slot_b=slot_actions.get("b"),
            )

            opp_player = "p2" if pov_player == "p1" else "p1"
            own_preview = preview.p1_team if pov_player == "p1" else preview.p2_team
            opp_preview = preview.p1_team if pov_player == "p2" else preview.p2_team

            # Build own team with retroactive enrichment
            own_team = self._build_own_team(
                pov_player, own_preview, full_knowledge
            )

            # Build opponent team with progressive revelation only
            # (already reflected in the state — opponent pokemon only have
            # what's been revealed so far via the state's moves_known/item/ability)

            samples.append(EnrichedSample(
                state=copy.deepcopy(state),
                actions=ta,
                player=pov_player,
                is_winner=(pov_player == winner_player),
                rating=self.rating,
                own_team_full=own_team,
                opp_team_preview=list(opp_preview),
                move_order=list(move_order or []),
            ))

    def _build_own_team(
        self,
        player: str,
        team_species: list[str],
        full_knowledge: dict[str, _FullKnowledge],
    ) -> list[EnrichedPokemon]:
        """Build the full own team with retroactive + inferred enrichment."""
        team: list[EnrichedPokemon] = []

        # Determine player name for profile lookups
        lookup_name = self.player_name

        for species in team_species:
            key = f"{player}|{species}"
            known = full_knowledge.get(key, _FullKnowledge(species=species))

            # Start with what the log revealed
            moves = list(known.moves)
            move_confs = [CONF_KNOWN] * len(moves)
            item = known.item
            item_conf = CONF_KNOWN if item else CONF_UNKNOWN
            ability = known.ability
            ability_conf = CONF_KNOWN if ability else CONF_UNKNOWN

            # Tier 2: player profile enrichment
            if self.player_profiles and lookup_name:
                if len(moves) < 4:
                    profile_moves = self.player_profiles.get_moves(lookup_name, species)
                    for m in profile_moves:
                        if m not in moves and len(moves) < 4:
                            moves.append(m)
                            move_confs.append(CONF_PLAYER)
                if not item:
                    profile_item = self.player_profiles.get_item(lookup_name, species)
                    if profile_item:
                        item = profile_item
                        item_conf = CONF_PLAYER
                if not ability:
                    profile_ability = self.player_profiles.get_ability(lookup_name, species)
                    if profile_ability:
                        ability = profile_ability
                        ability_conf = CONF_PLAYER

            # Tier 3: usage stats fallback
            if self.usage_stats:
                if len(moves) < 4:
                    usage_moves = self.usage_stats.top_moves(species, 4)
                    for m in usage_moves:
                        if m not in moves and len(moves) < 4:
                            moves.append(m)
                            move_confs.append(CONF_USAGE)
                if not item:
                    usage_item = self.usage_stats.top_item(species)
                    if usage_item:
                        item = usage_item
                        item_conf = CONF_USAGE
                if not ability:
                    usage_ability = self.usage_stats.top_ability(species)
                    if usage_ability:
                        ability = usage_ability
                        ability_conf = CONF_USAGE

            # Pad moves to 4 slots
            while len(moves) < 4:
                moves.append("")
                move_confs.append(CONF_UNKNOWN)

            team.append(EnrichedPokemon(
                species=species,
                moves_known=moves,
                move_confidences=move_confs,
                item=item,
                item_confidence=item_conf,
                ability=ability,
                ability_confidence=ability_conf,
            ))

        return team


def _base_species(species: str) -> str:
    """Strip Mega suffix: 'Charizard-Mega-Y' -> 'Charizard'"""
    if "-Mega" in species:
        return species.split("-Mega")[0]
    return species


def parse_battle_enriched(
    log: str,
    rating: int = 0,
    usage_stats: Optional[UsageStats] = None,
    player_profiles: Optional[PlayerProfiles] = None,
    player_name: Optional[str] = None,
) -> Optional[list[EnrichedSample]]:
    """Convenience function: parse a battle log into enriched samples."""
    parser = EnrichedBattleParser(
        log, rating,
        usage_stats=usage_stats,
        player_profiles=player_profiles,
        player_name=player_name,
    )
    return parser.parse()
