"""Layer 1 parser: replay JSON -> ParsedReplay (schema-stable struct).

Phase 3 of the pipeline redesign. Produces one `ParsedReplay` per replay,
which serializes to one parquet row. Hour-bucketed parquet files live at
``parsed/<format>/YYYY-MM-DD/HH.parquet``.

The parser wraps the existing two-pass `BattleParser` for the structural
parse, then layers on per-turn opponent-revealed state with `UsageStatsSource`
fallbacks for slots that haven't been revealed yet. Confidence floats are NOT
stored — Layer 1 records `source_type` ("revealed" | "meta") and an absolute
`prob` from the stats source. Mapping prob -> confidence float is a Layer 2
encoder concern (so re-tuning never re-parses).

Pure logic: no I/O, no globals. The runner (parse_runner.py) handles the
filesystem and orchestration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .log_parser import (
    Action,
    GameState,
    Pokemon,
    TrainingSample,
    parse_battle,
)
from .stats_source import UsageStatsSource


# ---------------------------------------------------------------------------
# Schema (Layer 1)
# ---------------------------------------------------------------------------

@dataclass
class StatsField:
    """A single hidden-info slot. {value, source_type, prob, stats_source_id}.

    source_type ∈ {"revealed", "meta"}. For "revealed", prob == 1.0 and
    stats_source_id is "". For "meta", prob is the actual usage frequency
    from the stats source at parse time.
    """
    value: str
    source_type: str
    prob: float
    stats_source_id: str

    @classmethod
    def revealed(cls, value: str) -> "StatsField":
        return cls(value=value, source_type="revealed", prob=1.0, stats_source_id="")

    @classmethod
    def meta(cls, value: str, prob: float, source_id: str) -> "StatsField":
        return cls(value=value, source_type="meta", prob=prob, stats_source_id=source_id)


@dataclass
class RevealedPokemon:
    """One Pokémon's per-turn POV state from the opposing player's perspective.

    Fields like item/ability/moves are progressively-revealed: revealed-in-game
    where possible, meta-guess otherwise.
    """
    species: str
    hp_frac: float
    status: str
    fainted: bool
    active_slot: int       # -1 = bench, 0 or 1 = active position
    boosts: dict[str, int]
    item: StatsField
    ability: StatsField
    moves: list[StatsField]   # exactly 4 entries (padded with meta if needed)


@dataclass
class TurnAction:
    """What one player did in a turn (slot a + slot b, or team_select)."""
    type: str            # "move" | "switch" | "team_select" | "noop"
    slot: int            # 0 (a) or 1 (b); -1 for team_select
    move: str
    target: int          # -2..1 in doubles; 0 for team_select
    switch_to: str       # species name when switching
    mega: bool

    @classmethod
    def from_action(cls, a: Optional[Action]) -> "TurnAction":
        if a is None:
            return cls(type="noop", slot=-1, move="", target=0, switch_to="", mega=False)
        slot_idx = {"a": 0, "b": 1}.get(a.slot, -1)
        target_idx = {"p1a": 0, "p1b": 1, "p2a": 0, "p2b": 1}.get(a.target, -2)
        return cls(
            type=a.type,
            slot=slot_idx,
            move=a.move,
            target=target_idx,
            switch_to=a.switch_to,
            mega=a.mega,
        )


@dataclass
class ParsedTurn:
    turn_num: int
    weather: str
    terrain: str
    trick_room: bool
    p1_revealed: list[RevealedPokemon]   # what p2 saw of p1 going into the turn
    p2_revealed: list[RevealedPokemon]
    p1_action_a: TurnAction
    p1_action_b: TurnAction
    p2_action_a: TurnAction
    p2_action_b: TurnAction


@dataclass
class TeamPokemon:
    """One slot of a player's team — what was eventually revealed by end-of-game.

    Note: NOT ground truth. Showdown replays only reveal what was used; moves
    that were never clicked stay empty here.
    """
    species: str
    gender: str
    level: int
    item: str
    ability: str
    moves: list[str]


@dataclass
class ParsedReplay:
    """Layer 1 row. One row per replay, nested arrays of turns + teams."""
    # Header
    replay_id: str
    format: str
    bucket_hour: str
    replay_end_ts: int
    p1_player: str
    p2_player: str
    p1_rating: int
    p2_rating: int
    winner: str

    # Both teams as eventually-revealed (NOT ground truth)
    p1_team: list[TeamPokemon]
    p2_team: list[TeamPokemon]

    # Decision sequence
    turns: list[ParsedTurn]

    def to_dict(self) -> dict:
        """Convert to a plain-dict ready for parquet via pandas/pyarrow."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ReplayParser:
    """Parse a replay JSON into a `ParsedReplay`.

    Pure: no I/O, no globals. Construct once with a `UsageStatsSource` and
    reuse for many replays.
    """

    def __init__(self, stats_source: UsageStatsSource):
        self._stats = stats_source

    def parse(self, replay_json: dict) -> Optional[ParsedReplay]:
        """Parse one replay. Returns None if the log can't be structurally parsed.

        Errors that should be skipped (return None) include:
        - Missing log
        - BattleParser fails to find winner / team preview
        - No turns played
        """
        log = replay_json.get("log") or ""
        if not log:
            return None

        rating = replay_json.get("rating") or 0
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = 0

        parsed = parse_battle(log, rating=rating)
        if parsed is None:
            return None
        if not parsed.samples:
            return None

        replay_id = replay_json.get("id", "")
        replay_format = replay_json.get("format", "")
        upload_ts = int(replay_json.get("uploadtime") or 0)
        bucket_hour = self._bucket_hour(upload_ts)

        players = replay_json.get("players") or ["", ""]
        p1_player = players[0] if len(players) > 0 else ""
        p2_player = players[1] if len(players) > 1 else ""

        # Group samples by turn — we get one (p1) and one (p2) sample per turn.
        # Both share the same GameState (positions, moves_known, etc).
        turns: dict[int, dict] = {}
        for s in parsed.samples:
            t = s.state.turn or 0
            slot = turns.setdefault(t, {"state": s.state, "actions": {}})
            slot["actions"][s.player] = s.actions

        parsed_turns = []
        for turn_num in sorted(turns.keys()):
            entry = turns[turn_num]
            state: GameState = entry["state"]
            p1_actions = entry["actions"].get("p1")
            p2_actions = entry["actions"].get("p2")

            parsed_turns.append(ParsedTurn(
                turn_num=turn_num,
                weather=state.field.weather or "",
                terrain=state.field.terrain or "",
                trick_room=bool(state.field.trick_room),
                p1_revealed=self._revealed_team(state.p1_active, state.p1_bench),
                p2_revealed=self._revealed_team(state.p2_active, state.p2_bench),
                p1_action_a=TurnAction.from_action(p1_actions.slot_a if p1_actions else None),
                p1_action_b=TurnAction.from_action(p1_actions.slot_b if p1_actions else None),
                p2_action_a=TurnAction.from_action(p2_actions.slot_a if p2_actions else None),
                p2_action_b=TurnAction.from_action(p2_actions.slot_b if p2_actions else None),
            ))

        # Build full-team rosters from team preview + final all_pokemon state.
        p1_team = self._build_team(parsed.team_preview.p1_team, parsed.samples, "p1")
        p2_team = self._build_team(parsed.team_preview.p2_team, parsed.samples, "p2")

        return ParsedReplay(
            replay_id=replay_id,
            format=replay_format,
            bucket_hour=bucket_hour,
            replay_end_ts=upload_ts,
            p1_player=p1_player,
            p2_player=p2_player,
            p1_rating=rating,
            p2_rating=rating,
            winner=parsed.winner,
            p1_team=p1_team,
            p2_team=p2_team,
            turns=parsed_turns,
        )

    # -- Per-Pokemon revealed-state construction -----------------------------

    def _revealed_team(
        self,
        active: list[Pokemon],
        bench: list[Pokemon],
    ) -> list[RevealedPokemon]:
        out: list[RevealedPokemon] = []
        for slot_idx, p in enumerate(active):
            out.append(self._revealed_one(p, active_slot=slot_idx))
        for p in bench:
            out.append(self._revealed_one(p, active_slot=-1))
        return out

    def _revealed_one(self, p: Pokemon, active_slot: int) -> RevealedPokemon:
        item_field = self._item_field(p)
        ability_field = self._ability_field(p)
        move_fields = self._move_fields(p)
        return RevealedPokemon(
            species=p.species,
            hp_frac=p.hp,
            status=p.status,
            fainted=p.fainted,
            active_slot=active_slot,
            boosts=dict(p.boosts) if p.boosts else {},
            item=item_field,
            ability=ability_field,
            moves=move_fields,
        )

    def _item_field(self, p: Pokemon) -> StatsField:
        if p.item:
            return StatsField.revealed(p.item)
        guess = self._stats.lookup_item(p.species)
        return StatsField.meta(guess.value, guess.prob, guess.source_id)

    def _ability_field(self, p: Pokemon) -> StatsField:
        if p.ability:
            return StatsField.revealed(p.ability)
        guess = self._stats.lookup_ability(p.species)
        return StatsField.meta(guess.value, guess.prob, guess.source_id)

    def _move_fields(self, p: Pokemon) -> list[StatsField]:
        """Return exactly 4 StatsFields. Revealed slots first, then meta-fill."""
        revealed = list(p.moves_known)
        out: list[StatsField] = [StatsField.revealed(m) for m in revealed]

        if len(out) < 4:
            need = 4 - len(out)
            meta_moves = self._stats.lookup_moves(p.species, n=4)
            for guess in meta_moves:
                if len(out) >= 4:
                    break
                if guess.value in revealed:
                    continue
                out.append(StatsField.meta(guess.value, guess.prob, guess.source_id))

        # Pad with empty meta entries if we still don't have 4 (rare species)
        while len(out) < 4:
            out.append(StatsField.meta("", 0.0, self._stats.source_id))

        return out

    # -- End-of-game team roster --------------------------------------------

    def _build_team(
        self,
        preview_species: list[str],
        samples: list[TrainingSample],
        player: str,
    ) -> list[TeamPokemon]:
        """Build the player's full team from team-preview species + max revealed info.

        Final-turn samples carry the largest accumulated knowledge per Pokemon,
        so we look up each preview species in the last sample's bench+active.
        """
        if not samples:
            return [self._empty_slot(s) for s in preview_species]

        last = samples[-1].state
        actives = last.p1_active if player == "p1" else last.p2_active
        bench = last.p1_bench if player == "p1" else last.p2_bench
        all_p = list(actives) + list(bench)

        by_species: dict[str, Pokemon] = {}
        for p in all_p:
            # Keep the entry with the most known moves (handles mega vs base form)
            existing = by_species.get(p.species)
            if existing is None or len(p.moves_known) > len(existing.moves_known):
                by_species[p.species] = p

        out: list[TeamPokemon] = []
        for sp in preview_species:
            p = by_species.get(sp)
            if p is None:
                out.append(self._empty_slot(sp))
            else:
                out.append(TeamPokemon(
                    species=p.species,
                    gender=p.gender or "",
                    level=p.level,
                    item=p.item,
                    ability=p.ability,
                    moves=list(p.moves_known)[:4],
                ))

        # Some replays expose more than 6 in preview (fringe). Cap at 6.
        return out[:6]

    @staticmethod
    def _empty_slot(species: str) -> TeamPokemon:
        return TeamPokemon(
            species=species, gender="", level=50, item="", ability="", moves=[],
        )

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _bucket_hour(unix_ts: int) -> str:
        if unix_ts <= 0:
            return ""
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d-%H")
