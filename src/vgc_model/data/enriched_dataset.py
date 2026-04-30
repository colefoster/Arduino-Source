"""PyTorch Dataset for enriched VGC battle training samples (model v2).

Uses the two-pass EnrichedBattleParser for player-POV samples with
progressive revelation, confidence flags, and explicit feature vectors.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset

from .enriched_parser import (
    EnrichedBattleParser,
    EnrichedPokemon,
    EnrichedSample,
    CONF_UNKNOWN,
)
from .feature_tables import FeatureTables
from .log_parser import Action, Pokemon, GameState, TeamPreview, TurnActions
from .usage_stats import UsageStats as UsageStatsClass
from .player_profiles import PlayerProfiles as PlayerProfilesClass
from .vocab import Vocabs


# ---------------------------------------------------------------------------
# Rating weight brackets (same as v1)
# ---------------------------------------------------------------------------
RATING_WEIGHTS = {
    (0, 1200): 0.3,
    (1200, 1300): 1.0,
    (1300, 1400): 2.0,
    (1400, 9999): 4.0,
}


def get_rating_weight(rating: int) -> float:
    for (lo, hi), weight in RATING_WEIGHTS.items():
        if lo <= rating < hi:
            return weight
    return 0.3


# Action space: 4 moves × 3 targets + 2 switches = 14
MAX_ACTIONS = 14
BOOST_STATS = ["atk", "def", "spa", "spd", "spe", "evasion"]

# Feature dimensions (must match FeatureTables output)
SPECIES_FEAT_DIM = 46
MOVE_FEAT_DIM = 56
ITEM_FEAT_DIM = 13
ABILITY_FEAT_DIM = 16


class EnrichedDataset(Dataset):
    """Dataset using EnrichedBattleParser for model v2 training."""

    def __init__(
        self,
        replay_dir: Path,
        vocabs: Vocabs,
        feature_tables: FeatureTables,
        usage_stats: Optional[UsageStatsClass] = None,
        player_profiles: Optional[PlayerProfilesClass] = None,
        min_rating: int = 0,
        winner_only: bool = True,
        min_turns: int = 3,
        augment: bool = True,
        history_mode: str = "single",  # "single", "window", "sequence"
    ):
        self.vocabs = vocabs
        self.feature_tables = feature_tables
        self.usage_stats = usage_stats
        self.player_profiles = player_profiles
        self.winner_only = winner_only
        self.min_turns = min_turns
        self.augment = augment
        self.history_mode = history_mode

        # Index replay files with ratings
        self.replay_files: list[tuple[Path, int]] = []
        self._index_replays(replay_dir, min_rating)

        # Pre-parse all replays — each sample includes own + opponent prior turn samples
        self.samples: list[tuple[EnrichedSample, TeamPreview, Optional[EnrichedSample], Optional[EnrichedSample]]] = []
        # Extended history: list of prior (own, opp) sample pairs per sample
        # For "window" mode: up to 3 pairs; for "sequence" mode: all pairs
        self.samples_history: list[list[tuple[Optional[EnrichedSample], Optional[EnrichedSample]]]] = []
        self.team_previews: list[tuple[TeamPreview, int, str]] = []  # (preview, rating, winner)
        self._load_all()

    def _index_replays(self, replay_dir: Path, min_rating: int):
        """Find replay files and their ratings."""
        # Check for index file (could be sibling or parent)
        ratings: dict[str, int] = {}
        for index_candidate in [
            replay_dir.parent / "index.json",
            replay_dir / "index.json",
        ]:
            if index_candidate.exists():
                index = json.loads(index_candidate.read_text(encoding="utf-8"))
                for replay_id, meta in index.items():
                    r = meta.get("rating", 0)
                    if r:
                        ratings[replay_id] = r
                break

        for f in sorted(replay_dir.glob("*.json")):
            if f.name == "index.json":
                continue
            replay_id = f.stem
            rating = ratings.get(replay_id, 0)
            if rating >= min_rating:
                self.replay_files.append((f, rating))

    def _load_all(self):
        """Parse all replays with the enriched parser."""
        for filepath, rating in self.replay_files:
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                log = data.get("log", "")
                if not log:
                    continue

                parser = EnrichedBattleParser(
                    log,
                    rating=rating,
                    usage_stats=self.usage_stats,
                    player_profiles=self.player_profiles,
                )
                result = parser.parse()
            except Exception:
                continue

            if result is None:
                continue

            # Skip short games
            max_turn = max((s.state.turn for s in result), default=0)
            if max_turn < self.min_turns:
                continue

            # Extract team preview from the first sample
            first = result[0]
            # Build a TeamPreview from the enriched data
            preview = first.state  # we'll extract from the parser below
            # Actually we need team preview info — get it from BattleParser
            from .log_parser import BattleParser
            try:
                base_result = BattleParser(log, rating).parse()
                if base_result is None:
                    continue
                tp = base_result.team_preview
                winner = base_result.winner
            except Exception:
                continue

            # Group samples by player and turn to link prior turn actions
            # We track both players' previous samples so we can encode
            # opponent actions from the prior turn (which are known — we saw them)
            opp_of = {"p1": "p2", "p2": "p1"}

            # First pass: index all samples by (player, turn) for opponent lookups
            by_player_turn: dict[tuple[str, int], EnrichedSample] = {}
            for sample in result:
                by_player_turn[(sample.player, sample.state.turn)] = sample

            # Build per-player ordered sample lists for history chain
            player_samples: dict[str, list[EnrichedSample]] = {"p1": [], "p2": []}
            for sample in result:
                player_samples[sample.player].append(sample)

            for sample in result:
                if self.winner_only and not sample.is_winner:
                    continue

                player = sample.player
                opp_player = opp_of[player]
                turn = sample.state.turn

                # Find the index of this sample in the player's ordered list
                own_history = player_samples[player]
                # Current sample's position — all prior samples in own_history
                # are those with turn < current turn
                own_prior_samples = [s for s in own_history if s.state.turn < turn]

                # Build the history chain: list of (own_prev, opp_prev) pairs
                # ordered from oldest to newest
                history_chain: list[tuple[Optional[EnrichedSample], Optional[EnrichedSample]]] = []
                for prior_own in own_prior_samples:
                    prior_turn = prior_own.state.turn
                    # Opponent's sample from the same prior turn (their actions are revealed)
                    prior_opp = by_player_turn.get((opp_player, prior_turn))
                    history_chain.append((prior_own, prior_opp))

                # Immediate prior (last in chain, or None)
                own_prev = own_prior_samples[-1] if own_prior_samples else None
                opp_prev_turn = turn - 1
                opp_prev = by_player_turn.get((opp_player, opp_prev_turn))

                self.samples.append((sample, tp, own_prev, opp_prev))
                self.samples_history.append(history_chain)

            # Team preview sample (from winner's perspective)
            if (len(tp.p1_team) == 6 and len(tp.p2_team) == 6
                    and len(tp.p1_selected) >= 4 and len(tp.p2_selected) >= 4):
                self.team_previews.append((tp, rating, winner))

    def __len__(self) -> int:
        return len(self.samples) + len(self.team_previews)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < len(self.samples):
            sample, tp, prev_own, prev_opp = self.samples[idx]
            history_chain = self.samples_history[idx]
            tensors = self._encode_sample(sample, tp, prev_own, prev_opp)

            # Add extended history encoding based on mode
            if self.history_mode == "window":
                self._encode_history_window(tensors, sample, history_chain)
            elif self.history_mode == "sequence":
                self._encode_history_sequence(tensors, sample, history_chain)

            if self.augment and random.random() < 0.5:
                tensors = self._swap_slots(tensors)

            return tensors
        else:
            tp_idx = idx - len(self.samples)
            tp, rating, winner = self.team_previews[tp_idx]
            return self._encode_team_preview(tp, rating, winner)

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def _encode_sample(
        self, sample: EnrichedSample, tp: TeamPreview,
        prev_own: Optional[EnrichedSample] = None,
        prev_opp: Optional[EnrichedSample] = None,
    ) -> dict[str, torch.Tensor]:
        """Encode an EnrichedSample into tensor dict for model v2."""
        player = sample.player
        if player == "p1":
            own_active = sample.state.p1_active
            own_bench = sample.state.p1_bench
            opp_active = sample.state.p2_active
            opp_bench = sample.state.p2_bench
            tailwind_own = sample.state.field.tailwind_p1
            tailwind_opp = sample.state.field.tailwind_p2
            screens_own = [
                int(sample.state.field.light_screen_p1),
                int(sample.state.field.reflect_p1),
                int(sample.state.field.aurora_veil_p1),
            ]
            screens_opp = [
                int(sample.state.field.light_screen_p2),
                int(sample.state.field.reflect_p2),
                int(sample.state.field.aurora_veil_p2),
            ]
        else:
            own_active = sample.state.p2_active
            own_bench = sample.state.p2_bench
            opp_active = sample.state.p1_active
            opp_bench = sample.state.p1_bench
            tailwind_own = sample.state.field.tailwind_p2
            tailwind_opp = sample.state.field.tailwind_p1
            screens_own = [
                int(sample.state.field.light_screen_p2),
                int(sample.state.field.reflect_p2),
                int(sample.state.field.aurora_veil_p2),
            ]
            screens_opp = [
                int(sample.state.field.light_screen_p1),
                int(sample.state.field.reflect_p1),
                int(sample.state.field.aurora_veil_p1),
            ]

        # Build enriched pokemon lookup from own_team_full
        # Key: species -> EnrichedPokemon
        enriched_lookup: dict[str, EnrichedPokemon] = {}
        for ep in sample.own_team_full:
            enriched_lookup[ep.species] = ep
            # Also store base species for mega lookup
            base = self._base_species(ep.species)
            if base != ep.species:
                enriched_lookup[base] = ep

        # 8 slots: [own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1]
        all_pokemon: list[Optional[Pokemon]] = [None] * 8
        is_own: list[bool] = [True] * 4 + [False] * 4

        if len(own_active) > 0:
            all_pokemon[0] = own_active[0]
        if len(own_active) > 1:
            all_pokemon[1] = own_active[1]
        if len(own_bench) > 0:
            all_pokemon[2] = own_bench[0]
        if len(own_bench) > 1:
            all_pokemon[3] = own_bench[1]
        if len(opp_active) > 0:
            all_pokemon[4] = opp_active[0]
        if len(opp_active) > 1:
            all_pokemon[5] = opp_active[1]
        if len(opp_bench) > 0:
            all_pokemon[6] = opp_bench[0]
        if len(opp_bench) > 1:
            all_pokemon[7] = opp_bench[1]

        # Output arrays
        species_ids = []
        hp_values = []
        status_ids = []
        boost_values = []
        item_ids = []
        ability_ids = []
        mega_flags = []
        alive_flags = []
        move_ids = []

        species_features = []
        move_features = []
        item_features = []
        ability_features = []
        move_confidences = []
        item_confidences = []
        ability_confidences = []

        for slot_idx, poke in enumerate(all_pokemon):
            if poke is None:
                # Empty slot
                species_ids.append(0)
                hp_values.append(0.0)
                status_ids.append(0)
                boost_values.append([0] * 6)
                item_ids.append(0)
                ability_ids.append(0)
                mega_flags.append(0)
                alive_flags.append(0)
                move_ids.append([0, 0, 0, 0])
                species_features.append(torch.zeros(SPECIES_FEAT_DIM))
                move_features.append(torch.zeros(4, MOVE_FEAT_DIM))
                item_features.append(torch.zeros(ITEM_FEAT_DIM))
                ability_features.append(torch.zeros(ABILITY_FEAT_DIM))
                move_confidences.append([0.0] * 4)
                item_confidences.append(0.0)
                ability_confidences.append(0.0)
                continue

            base_sp = self._base_species(poke.species)
            species_ids.append(self.vocabs.species[poke.species])
            hp_values.append(poke.hp)
            status_ids.append(self.vocabs.status[poke.status] if poke.status else 0)
            boosts = [poke.boosts.get(s, 0) for s in BOOST_STATS]
            boost_values.append(boosts)
            mega_flags.append(int(poke.mega))
            alive_flags.append(1)

            # Species features (always available)
            sp_feat = self.feature_tables.get_species_features(poke.species)
            species_features.append(FeatureTables.to_tensor(sp_feat, "species"))

            # For own pokemon, use enriched data; for opponent, use what's revealed
            enriched = enriched_lookup.get(base_sp) if is_own[slot_idx] else None

            if enriched is not None:
                # Own pokemon: use enriched moves/items/abilities
                moves = enriched.moves_known[:4]
                m_confs = enriched.move_confidences[:4]
                item_name = enriched.item
                i_conf = enriched.item_confidence
                ability_name = enriched.ability
                a_conf = enriched.ability_confidence
            else:
                # Opponent pokemon: only what's revealed in-game
                moves = poke.moves_known[:4]
                m_confs = [1.0] * len(moves)  # revealed = known
                item_name = poke.item
                i_conf = 1.0 if item_name else 0.0
                ability_name = poke.ability
                a_conf = 1.0 if ability_name else 0.0

            # Pad moves to 4
            while len(moves) < 4:
                moves.append("")
                m_confs.append(0.0)
            while len(m_confs) < 4:
                m_confs.append(0.0)

            move_idx = [self.vocabs.moves[m] if m else 0 for m in moves[:4]]
            move_ids.append(move_idx)
            move_confidences.append(m_confs[:4])

            # Move features
            slot_move_feats = []
            for m in moves[:4]:
                if m:
                    mf = self.feature_tables.get_move_features(m)
                    slot_move_feats.append(FeatureTables.to_tensor(mf, "move"))
                else:
                    slot_move_feats.append(torch.zeros(MOVE_FEAT_DIM))
            move_features.append(torch.stack(slot_move_feats))

            # Item
            item_ids.append(self.vocabs.items[item_name] if item_name else 0)
            item_confidences.append(i_conf)
            if item_name:
                itf = self.feature_tables.get_item_features(item_name)
                item_features.append(FeatureTables.to_tensor(itf, "item"))
            else:
                item_features.append(torch.zeros(ITEM_FEAT_DIM))

            # Ability
            ability_ids.append(self.vocabs.abilities[ability_name] if ability_name else 0)
            ability_confidences.append(a_conf)
            if ability_name:
                abf = self.feature_tables.get_ability_features(ability_name)
                ability_features.append(FeatureTables.to_tensor(abf, "ability"))
            else:
                ability_features.append(torch.zeros(ABILITY_FEAT_DIM))

        # Encode actions
        action_a = self._encode_action(sample.actions.slot_a, 0, own_active, own_bench, player)
        action_b = self._encode_action(sample.actions.slot_b, 1, own_active, own_bench, player)

        mask_a = [1] * MAX_ACTIONS
        mask_b = [1] * MAX_ACTIONS

        # Team preview encoding
        own_team_ids = self._encode_team_species_from_tp(tp, player, "team")
        opp_team_ids = self._encode_team_species_from_tp(tp, player, "opp_team")
        team_select_labels = self._encode_team_select_labels_from_tp(tp, player)
        selected_ids = self._encode_team_species_from_tp(tp, player, "selected")
        lead_labels = self._encode_lead_labels_from_tp(tp, player)

        return {
            # Learned embedding IDs
            "species_ids": torch.tensor(species_ids, dtype=torch.long),
            "hp_values": torch.tensor(hp_values, dtype=torch.float),
            "status_ids": torch.tensor(status_ids, dtype=torch.long),
            "boost_values": torch.tensor(boost_values, dtype=torch.float),
            "item_ids": torch.tensor(item_ids, dtype=torch.long),
            "ability_ids": torch.tensor(ability_ids, dtype=torch.long),
            "mega_flags": torch.tensor(mega_flags, dtype=torch.float),
            "alive_flags": torch.tensor(alive_flags, dtype=torch.float),
            "move_ids": torch.tensor(move_ids, dtype=torch.long),
            # Explicit feature vectors (NEW)
            "species_features": torch.stack(species_features),           # (8, 45)
            "move_features": torch.stack(move_features),                 # (8, 4, 48)
            "item_features": torch.stack(item_features),                 # (8, 13)
            "ability_features": torch.stack(ability_features),           # (8, 16)
            # Confidence flags (NEW)
            "move_confidences": torch.tensor(move_confidences, dtype=torch.float),  # (8, 4)
            "item_confidences": torch.tensor(item_confidences, dtype=torch.float),  # (8,)
            "ability_confidences": torch.tensor(ability_confidences, dtype=torch.float),  # (8,)
            # Field state
            "weather_id": torch.tensor(
                self.vocabs.weather[sample.state.field.weather] if sample.state.field.weather else 0,
                dtype=torch.long,
            ),
            "terrain_id": torch.tensor(
                self.vocabs.terrain[sample.state.field.terrain] if sample.state.field.terrain else 0,
                dtype=torch.long,
            ),
            "trick_room": torch.tensor(int(sample.state.field.trick_room), dtype=torch.float),
            "tailwind_own": torch.tensor(int(tailwind_own), dtype=torch.float),
            "tailwind_opp": torch.tensor(int(tailwind_opp), dtype=torch.float),
            "screens_own": torch.tensor(screens_own, dtype=torch.float),
            "screens_opp": torch.tensor(screens_opp, dtype=torch.float),
            "turn": torch.tensor(min(sample.state.turn, 30), dtype=torch.float),
            # Actions
            "action_slot_a": torch.tensor(action_a, dtype=torch.long),
            "action_slot_b": torch.tensor(action_b, dtype=torch.long),
            "action_mask_a": torch.tensor(mask_a, dtype=torch.bool),
            "action_mask_b": torch.tensor(mask_b, dtype=torch.bool),
            # Team preview
            "own_team_ids": torch.tensor(own_team_ids, dtype=torch.long),
            "opp_team_ids": torch.tensor(opp_team_ids, dtype=torch.long),
            "team_select_labels": torch.tensor(team_select_labels, dtype=torch.float),
            "selected_ids": torch.tensor(selected_ids, dtype=torch.long),
            "lead_labels": torch.tensor(lead_labels, dtype=torch.float),
            "has_team_preview": torch.tensor(True, dtype=torch.bool),
            # Prior turn actions: [own_a, own_b, opp_a, opp_b]
            # Index 14 = "no prior" (turn 1 or no previous sample)
            "prev_actions": self._encode_prev_actions(prev_own, prev_opp, player),
            # Prior turn speed order: [own_a_went_first, own_b_went_first]
            # 1.0 = moved before any opponent slot, 0.0 = didn't, 0.5 = unknown
            "prev_speed": self._encode_speed_order(prev_own, player),
            # Metadata
            "rating_weight": torch.tensor(get_rating_weight(sample.rating), dtype=torch.float),
        }

    @staticmethod
    def _encode_speed_order(
        prev_sample: Optional[EnrichedSample], player: str,
    ) -> torch.Tensor:
        """Encode whether own slots moved before opponent slots last turn.

        Returns (2,) tensor: [own_a_went_first, own_b_went_first]
        1.0 = moved before any opponent, 0.0 = moved after, 0.5 = unknown/no data.
        """
        if prev_sample is None or not prev_sample.move_order:
            return torch.full((2,), 0.5, dtype=torch.float)

        order = prev_sample.move_order  # e.g. ["p2a", "p1a", "p2b", "p1b"]
        own_prefix = player      # "p1" or "p2"
        opp_prefix = "p2" if player == "p1" else "p1"

        def went_first(own_slot: str) -> float:
            """Did own_slot move before any opp slot?"""
            if own_slot not in order:
                return 0.5  # didn't move (switch, fainted, etc.)
            own_pos = order.index(own_slot)
            opp_positions = [order.index(s) for s in order if s.startswith(opp_prefix)]
            if not opp_positions:
                return 0.5
            return 1.0 if own_pos < min(opp_positions) else 0.0

        return torch.tensor([
            went_first(f"{own_prefix}a"),
            went_first(f"{own_prefix}b"),
        ], dtype=torch.float)

    # ------------------------------------------------------------------
    # Extended history encoding
    # ------------------------------------------------------------------

    def _get_active_species_ids(
        self, sample: EnrichedSample,
    ) -> list[int]:
        """Get species IDs for the 4 active slots (own_a, own_b, opp_a, opp_b)."""
        player = sample.player
        if player == "p1":
            own_active = sample.state.p1_active
            opp_active = sample.state.p2_active
        else:
            own_active = sample.state.p2_active
            opp_active = sample.state.p1_active

        ids = []
        for active_list in (own_active, opp_active):
            for i in range(2):
                if i < len(active_list):
                    ids.append(self.vocabs.species[active_list[i].species])
                else:
                    ids.append(0)
        return ids

    def _get_active_hp(
        self, sample: EnrichedSample,
    ) -> list[float]:
        """Get HP values for the 4 active slots (own_a, own_b, opp_a, opp_b)."""
        player = sample.player
        if player == "p1":
            own_active = sample.state.p1_active
            opp_active = sample.state.p2_active
        else:
            own_active = sample.state.p2_active
            opp_active = sample.state.p1_active

        hps = []
        for active_list in (own_active, opp_active):
            for i in range(2):
                if i < len(active_list):
                    hps.append(active_list[i].hp)
                else:
                    hps.append(0.0)
        return hps

    def _compute_flags(
        self,
        current: EnrichedSample,
        prior: Optional[EnrichedSample],
    ) -> list[float]:
        """Compute [any_own_fainted, any_opp_fainted, any_switch] flags.

        Compares active species between prior and current turn.
        """
        if prior is None:
            return [0.0, 0.0, 0.0]

        player = current.player
        if player == "p1":
            cur_own = current.state.p1_active
            cur_opp = current.state.p2_active
            prev_own = prior.state.p1_active
            prev_opp = prior.state.p2_active
        else:
            cur_own = current.state.p2_active
            cur_opp = current.state.p1_active
            prev_own = prior.state.p2_active
            prev_opp = prior.state.p1_active

        # Check for own fainted: species in prior active but not in current, with HP=0
        prev_own_species = {self._base_species(p.species) for p in prev_own}
        cur_own_species = {self._base_species(p.species) for p in cur_own}
        disappeared_own = prev_own_species - cur_own_species
        any_own_fainted = 0.0
        for p in prev_own:
            if self._base_species(p.species) in disappeared_own and p.hp <= 0:
                any_own_fainted = 1.0
                break

        # Check for opp fainted
        prev_opp_species = {self._base_species(p.species) for p in prev_opp}
        cur_opp_species = {self._base_species(p.species) for p in cur_opp}
        disappeared_opp = prev_opp_species - cur_opp_species
        any_opp_fainted = 0.0
        for p in prev_opp:
            if self._base_species(p.species) in disappeared_opp and p.hp <= 0:
                any_opp_fainted = 1.0
                break

        # Any switch: any species changed in active slots
        any_switch = 1.0 if (prev_own_species != cur_own_species or
                             prev_opp_species != cur_opp_species) else 0.0

        return [any_own_fainted, any_opp_fainted, any_switch]

    def _compute_seq_flags(
        self,
        current_own: Optional[EnrichedSample],
        prev_own: Optional[EnrichedSample],
        current_opp: Optional[EnrichedSample],
        prev_opp: Optional[EnrichedSample],
        player: str,
    ) -> list[float]:
        """Compute [any_fainted, any_switch, field_changed] for sequence model."""
        if current_own is None or prev_own is None:
            return [0.0, 0.0, 0.0]

        if player == "p1":
            cur_own_a = current_own.state.p1_active
            cur_opp_a = current_own.state.p2_active
            prev_own_a = prev_own.state.p1_active
            prev_opp_a = prev_own.state.p2_active
        else:
            cur_own_a = current_own.state.p2_active
            cur_opp_a = current_own.state.p1_active
            prev_own_a = prev_own.state.p2_active
            prev_opp_a = prev_own.state.p1_active

        # Any fainted
        any_fainted = 0.0
        for p in prev_own_a + prev_opp_a:
            if p.hp <= 0:
                any_fainted = 1.0
                break

        # Any switch
        prev_species = {self._base_species(p.species) for p in prev_own_a + prev_opp_a}
        cur_species = {self._base_species(p.species) for p in cur_own_a + cur_opp_a}
        any_switch = 1.0 if prev_species != cur_species else 0.0

        # Field changed
        cur_field = current_own.state.field
        prev_field = prev_own.state.field
        field_changed = 0.0
        if (cur_field.weather != prev_field.weather or
                cur_field.terrain != prev_field.terrain or
                cur_field.trick_room != prev_field.trick_room):
            field_changed = 1.0

        return [any_fainted, any_switch, field_changed]

    def _encode_history_window(
        self,
        tensors: dict[str, torch.Tensor],
        sample: EnrichedSample,
        history_chain: list[tuple[Optional[EnrichedSample], Optional[EnrichedSample]]],
    ):
        """Add 3-turn window history to tensors dict."""
        player = sample.player
        HISTORY_TURNS = 3
        NO_PRIOR = MAX_ACTIONS  # sentinel

        # Take last 3 entries from history chain
        recent = history_chain[-HISTORY_TURNS:]

        actions_window = []  # (3, 4)
        flags_window = []    # (3, 3)

        for turn_idx in range(HISTORY_TURNS):
            if turn_idx < len(recent):
                prior_own, prior_opp = recent[turn_idx]
                # Encode actions for this prior turn
                action_indices = self._encode_prev_actions(prior_own, prior_opp, player).tolist()

                # Compute flags by comparing this turn to the next one
                # The "next" sample is either the next in chain or the current sample
                if turn_idx + 1 < len(recent):
                    next_own = recent[turn_idx + 1][0]
                elif prior_own is not None:
                    next_own = sample  # current sample is next after the last prior
                else:
                    next_own = None

                # For flags: compare prior_own state to next_own state
                if prior_own is not None and next_own is not None:
                    flags = self._compute_flags_between(prior_own, next_own, player)
                else:
                    flags = [0.0, 0.0, 0.0]
            else:
                action_indices = [NO_PRIOR] * 4
                flags = [0.0, 0.0, 0.0]

            actions_window.append(action_indices)
            flags_window.append(flags)

        # Speed order per prior turn
        speed_window = []
        for turn_idx in range(HISTORY_TURNS):
            if turn_idx < len(recent):
                prior_own = recent[turn_idx][0]
                speed_window.append(self._encode_speed_order(prior_own, player).tolist())
            else:
                speed_window.append([0.5, 0.5])

        tensors["prev_actions_window"] = torch.tensor(actions_window, dtype=torch.long)   # (3, 4)
        tensors["prev_flags_window"] = torch.tensor(flags_window, dtype=torch.float)      # (3, 3)
        tensors["prev_speed_window"] = torch.tensor(speed_window, dtype=torch.float)      # (3, 2)

    def _compute_flags_between(
        self,
        prior: EnrichedSample,
        next_sample: EnrichedSample,
        player: str,
    ) -> list[float]:
        """Compute [any_own_fainted, any_opp_fainted, any_switch] between two samples."""
        if player == "p1":
            prev_own = prior.state.p1_active
            prev_opp = prior.state.p2_active
            next_own = next_sample.state.p1_active
            next_opp = next_sample.state.p2_active
        else:
            prev_own = prior.state.p2_active
            prev_opp = prior.state.p1_active
            next_own = next_sample.state.p2_active
            next_opp = next_sample.state.p1_active

        prev_own_sp = {self._base_species(p.species) for p in prev_own}
        next_own_sp = {self._base_species(p.species) for p in next_own}
        prev_opp_sp = {self._base_species(p.species) for p in prev_opp}
        next_opp_sp = {self._base_species(p.species) for p in next_opp}

        # Own fainted: disappeared and had HP=0
        disappeared_own = prev_own_sp - next_own_sp
        any_own_fainted = 0.0
        for p in prev_own:
            if self._base_species(p.species) in disappeared_own and p.hp <= 0:
                any_own_fainted = 1.0
                break

        # Opp fainted
        disappeared_opp = prev_opp_sp - next_opp_sp
        any_opp_fainted = 0.0
        for p in prev_opp:
            if self._base_species(p.species) in disappeared_opp and p.hp <= 0:
                any_opp_fainted = 1.0
                break

        any_switch = 1.0 if (prev_own_sp != next_own_sp or
                             prev_opp_sp != next_opp_sp) else 0.0

        return [any_own_fainted, any_opp_fainted, any_switch]

    def _encode_history_sequence(
        self,
        tensors: dict[str, torch.Tensor],
        sample: EnrichedSample,
        history_chain: list[tuple[Optional[EnrichedSample], Optional[EnrichedSample]]],
    ):
        """Add full sequence history to tensors dict for LSTM model."""
        player = sample.player
        MAX_TURNS = 30
        NO_PRIOR = MAX_ACTIONS

        actual_len = min(len(history_chain), MAX_TURNS)

        # Pre-allocate
        seq_actions = torch.full((MAX_TURNS, 4), NO_PRIOR, dtype=torch.long)
        seq_species = torch.zeros(MAX_TURNS, 4, dtype=torch.long)
        seq_hp = torch.zeros(MAX_TURNS, 4, dtype=torch.float)
        seq_flags = torch.zeros(MAX_TURNS, 3, dtype=torch.float)

        # Take last MAX_TURNS entries
        recent = history_chain[-MAX_TURNS:]

        for i, (prior_own, prior_opp) in enumerate(recent):
            # Actions
            seq_actions[i] = self._encode_prev_actions(prior_own, prior_opp, player)

            # Active species IDs and HP
            if prior_own is not None:
                if player == "p1":
                    own_active = prior_own.state.p1_active
                    opp_active = prior_own.state.p2_active
                else:
                    own_active = prior_own.state.p2_active
                    opp_active = prior_own.state.p1_active

                active_lists = [own_active, opp_active]
                slot = 0
                for active_list in active_lists:
                    for j in range(2):
                        if j < len(active_list):
                            seq_species[i, slot] = self.vocabs.species[active_list[j].species]
                            seq_hp[i, slot] = active_list[j].hp
                        slot += 1

            # Flags: compare this turn to the next
            if i + 1 < len(recent):
                next_own = recent[i + 1][0]
            else:
                next_own = sample  # current sample

            if prior_own is not None and next_own is not None:
                # [any_fainted, any_switch, field_changed]
                if player == "p1":
                    prev_all = prior_own.state.p1_active + prior_own.state.p2_active
                    next_all = next_own.state.p1_active + next_own.state.p2_active
                else:
                    prev_all = prior_own.state.p2_active + prior_own.state.p1_active
                    next_all = next_own.state.p2_active + next_own.state.p1_active

                prev_sp = {self._base_species(p.species) for p in prev_all}
                next_sp = {self._base_species(p.species) for p in next_all}

                any_fainted = 0.0
                for p in prev_all:
                    if self._base_species(p.species) not in next_sp and p.hp <= 0:
                        any_fainted = 1.0
                        break

                any_switch = 1.0 if prev_sp != next_sp else 0.0

                field_changed = 0.0
                cur_f = next_own.state.field
                prev_f = prior_own.state.field
                if (cur_f.weather != prev_f.weather or
                        cur_f.terrain != prev_f.terrain or
                        cur_f.trick_room != prev_f.trick_room):
                    field_changed = 1.0

                seq_flags[i] = torch.tensor([any_fainted, any_switch, field_changed])

        # Speed order per turn
        seq_speed = torch.full((MAX_TURNS, 2), 0.5, dtype=torch.float)
        for i, (prior_own, _) in enumerate(recent):
            seq_speed[i] = self._encode_speed_order(prior_own, player)

        tensors["prev_seq_actions"] = seq_actions      # (30, 4)
        tensors["prev_seq_species"] = seq_species      # (30, 4)
        tensors["prev_seq_hp"] = seq_hp                # (30, 4)
        tensors["prev_seq_flags"] = seq_flags          # (30, 3)
        tensors["prev_seq_speed"] = seq_speed           # (30, 2)
        tensors["prev_seq_len"] = torch.tensor(actual_len, dtype=torch.long)

    def _encode_team_preview(
        self, tp: TeamPreview, rating: int, winner: str,
    ) -> dict[str, torch.Tensor]:
        """Encode a team-preview-only sample (no battle state)."""
        player = winner
        z8 = torch.zeros(8)

        return {
            "species_ids": torch.zeros(8, dtype=torch.long),
            "hp_values": z8,
            "status_ids": torch.zeros(8, dtype=torch.long),
            "boost_values": torch.zeros(8, 6),
            "item_ids": torch.zeros(8, dtype=torch.long),
            "ability_ids": torch.zeros(8, dtype=torch.long),
            "mega_flags": z8,
            "alive_flags": z8,
            "move_ids": torch.zeros(8, 4, dtype=torch.long),
            "species_features": torch.zeros(8, SPECIES_FEAT_DIM),
            "move_features": torch.zeros(8, 4, MOVE_FEAT_DIM),
            "item_features": torch.zeros(8, ITEM_FEAT_DIM),
            "ability_features": torch.zeros(8, ABILITY_FEAT_DIM),
            "move_confidences": torch.zeros(8, 4),
            "item_confidences": z8.clone(),
            "ability_confidences": z8.clone(),
            "weather_id": torch.tensor(0, dtype=torch.long),
            "terrain_id": torch.tensor(0, dtype=torch.long),
            "trick_room": torch.tensor(0, dtype=torch.float),
            "tailwind_own": torch.tensor(0, dtype=torch.float),
            "tailwind_opp": torch.tensor(0, dtype=torch.float),
            "screens_own": torch.zeros(3),
            "screens_opp": torch.zeros(3),
            "turn": torch.tensor(0, dtype=torch.float),
            "action_slot_a": torch.tensor(0, dtype=torch.long),
            "action_slot_b": torch.tensor(0, dtype=torch.long),
            "action_mask_a": torch.ones(MAX_ACTIONS, dtype=torch.bool),
            "action_mask_b": torch.ones(MAX_ACTIONS, dtype=torch.bool),
            "own_team_ids": torch.tensor(
                self._encode_team_species_from_tp(tp, player, "team"), dtype=torch.long),
            "opp_team_ids": torch.tensor(
                self._encode_team_species_from_tp(tp, player, "opp_team"), dtype=torch.long),
            "team_select_labels": torch.tensor(
                self._encode_team_select_labels_from_tp(tp, player), dtype=torch.float),
            "selected_ids": torch.tensor(
                self._encode_team_species_from_tp(tp, player, "selected"), dtype=torch.long),
            "lead_labels": torch.tensor(
                self._encode_lead_labels_from_tp(tp, player), dtype=torch.float),
            "has_team_preview": torch.tensor(True, dtype=torch.bool),
            "prev_actions": torch.full((4,), MAX_ACTIONS, dtype=torch.long),  # no prior
            "prev_speed": torch.full((2,), 0.5, dtype=torch.float),  # unknown
            "rating_weight": torch.tensor(get_rating_weight(rating), dtype=torch.float),
            **self._team_preview_history_tensors(),
        }

    def _team_preview_history_tensors(self) -> dict[str, torch.Tensor]:
        """Return zeroed-out history tensors for team preview samples."""
        result = {}
        if self.history_mode == "window":
            result["prev_actions_window"] = torch.full((3, 4), MAX_ACTIONS, dtype=torch.long)
            result["prev_flags_window"] = torch.zeros(3, 3, dtype=torch.float)
            result["prev_speed_window"] = torch.full((3, 2), 0.5, dtype=torch.float)
        elif self.history_mode == "sequence":
            result["prev_seq_actions"] = torch.full((30, 4), MAX_ACTIONS, dtype=torch.long)
            result["prev_seq_species"] = torch.zeros(30, 4, dtype=torch.long)
            result["prev_seq_hp"] = torch.zeros(30, 4, dtype=torch.float)
            result["prev_seq_flags"] = torch.zeros(30, 3, dtype=torch.float)
            result["prev_seq_speed"] = torch.full((30, 2), 0.5, dtype=torch.float)
            result["prev_seq_len"] = torch.tensor(0, dtype=torch.long)
        return result

    # ------------------------------------------------------------------
    # Action encoding (same logic as v1)
    # ------------------------------------------------------------------

    def _encode_action(
        self,
        action: Optional[Action],
        slot_idx: int,
        own_active: list[Pokemon],
        own_bench: list[Pokemon],
        player: str,
    ) -> int:
        """Encode action into flat index (0-13).

        0-11: move_i * 3 + target_j (4 moves × 3 targets)
        12-13: switch to bench slot 0 or 1
        """
        if action is None:
            return 0

        if action.type == "switch":
            for i, poke in enumerate(own_bench):
                if (poke.species == action.switch_to
                        or self._base_species(poke.species) == self._base_species(action.switch_to)):
                    return 12 + min(i, 1)
            return 12

        if action.type == "move":
            move_idx = 0
            if slot_idx < len(own_active):
                poke = own_active[slot_idx]
                if action.move in poke.moves_known:
                    move_idx = poke.moves_known.index(action.move)

            # Spread moves (Earthquake, Rock Slide, Heat Wave, etc.) hit all
            # targets — normalize to target_idx=0 so the model isn't penalized
            # for picking a different target on a spread move.
            move_feat = self.feature_tables.get_move_features(action.move)
            is_spread = move_feat.get("target") in ("allAdjacentFoes", "allAdjacent")

            target_idx = 0
            if not is_spread and action.target:
                target_player = action.target[:2]
                target_slot = action.target[2]
                if target_player == player:
                    target_idx = 2
                else:
                    target_idx = 0 if target_slot == "a" else 1

            return min(move_idx, 3) * 3 + min(target_idx, 2)

        return 0

    def _encode_prev_actions(
        self,
        prev_own: Optional[EnrichedSample],
        prev_opp: Optional[EnrichedSample],
        player: str,
    ) -> torch.Tensor:
        """Encode previous turn's actions as [own_a, own_b, opp_a, opp_b].

        Index 14 (MAX_ACTIONS) = no prior turn / unknown.
        """
        no_prior = MAX_ACTIONS  # sentinel for "no previous action"
        result = [no_prior] * 4

        # Own actions from previous turn
        if prev_own is not None:
            state = prev_own.state
            if player == "p1":
                own_active, own_bench = state.p1_active, state.p1_bench
            else:
                own_active, own_bench = state.p2_active, state.p2_bench
            a = self._encode_action(prev_own.actions.slot_a, 0, own_active, own_bench, player)
            b = self._encode_action(prev_own.actions.slot_b, 1, own_active, own_bench, player)
            if a >= 0: result[0] = a
            if b >= 0: result[1] = b

        # Opponent actions from previous turn (revealed — we saw them happen)
        if prev_opp is not None:
            opp_player = prev_opp.player
            state = prev_opp.state
            if opp_player == "p1":
                opp_active, opp_bench = state.p1_active, state.p1_bench
            else:
                opp_active, opp_bench = state.p2_active, state.p2_bench
            a = self._encode_action(prev_opp.actions.slot_a, 0, opp_active, opp_bench, opp_player)
            b = self._encode_action(prev_opp.actions.slot_b, 1, opp_active, opp_bench, opp_player)
            if a >= 0: result[2] = a
            if b >= 0: result[3] = b

        return torch.tensor(result, dtype=torch.long)

    # ------------------------------------------------------------------
    # Team preview helpers
    # ------------------------------------------------------------------

    def _encode_team_species_from_tp(self, tp: TeamPreview, player: str, which: str) -> list[int]:
        if which == "team":
            species_list = tp.p1_team if player == "p1" else tp.p2_team
        elif which == "opp_team":
            species_list = tp.p2_team if player == "p1" else tp.p1_team
        elif which == "selected":
            species_list = tp.p1_selected if player == "p1" else tp.p2_selected
        else:
            species_list = []

        target_len = 6 if which != "selected" else 4
        ids = [self.vocabs.species[s] for s in species_list[:target_len]]
        ids += [0] * (target_len - len(ids))
        return ids

    def _encode_team_select_labels_from_tp(self, tp: TeamPreview, player: str) -> list[int]:
        team = tp.p1_team if player == "p1" else tp.p2_team
        selected = set(tp.p1_selected if player == "p1" else tp.p2_selected)
        labels = [1 if s in selected else 0 for s in team[:6]]
        labels += [0] * (6 - len(labels))
        return labels

    def _encode_lead_labels_from_tp(self, tp: TeamPreview, player: str) -> list[int]:
        selected = (tp.p1_selected if player == "p1" else tp.p2_selected)[:4]
        leads = set(tp.p1_leads if player == "p1" else tp.p2_leads)
        labels = [1 if s in leads else 0 for s in selected]
        labels += [0] * (4 - len(labels))
        return labels

    # ------------------------------------------------------------------
    # Augmentation
    # ------------------------------------------------------------------

    @staticmethod
    def _swap_slots(t: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Swap slot A and slot B (own active 0<->1, opp active 4<->5)."""
        t = dict(t)

        # Swap 1D per-slot features
        for key in ("species_ids", "hp_values", "status_ids", "item_ids",
                     "ability_ids", "mega_flags", "alive_flags",
                     "item_confidences", "ability_confidences"):
            v = t[key].clone()
            v[0], v[1] = t[key][1], t[key][0]
            v[4], v[5] = t[key][5], t[key][4]
            t[key] = v

        # Swap 2D per-slot features
        for key in ("boost_values", "move_ids", "move_confidences",
                     "species_features", "item_features", "ability_features",
                     "move_features"):
            v = t[key].clone()
            v[0], v[1] = t[key][1], t[key][0]
            v[4], v[5] = t[key][5], t[key][4]
            t[key] = v

        # Swap action labels
        t["action_slot_a"], t["action_slot_b"] = t["action_slot_b"].clone(), t["action_slot_a"].clone()
        t["action_mask_a"], t["action_mask_b"] = t["action_mask_b"].clone(), t["action_mask_a"].clone()

        # Swap prior own actions (indices 0,1) and prior opp actions (indices 2,3)
        prev = t["prev_actions"].clone()
        prev[0], prev[1] = t["prev_actions"][1], t["prev_actions"][0]
        prev[2], prev[3] = t["prev_actions"][3], t["prev_actions"][2]
        t["prev_actions"] = prev

        # Swap window history actions (indices 0↔1, 2↔3 per turn)
        if "prev_actions_window" in t:
            paw = t["prev_actions_window"].clone()  # (3, 4)
            for turn in range(paw.shape[0]):
                paw[turn, 0], paw[turn, 1] = t["prev_actions_window"][turn, 1].clone(), t["prev_actions_window"][turn, 0].clone()
                paw[turn, 2], paw[turn, 3] = t["prev_actions_window"][turn, 3].clone(), t["prev_actions_window"][turn, 2].clone()
            t["prev_actions_window"] = paw
            # Flags don't need swapping — they're aggregate (any_own_fainted etc.)
            # But own vs opp faint flags swap: index 0↔1
            pfw = t["prev_flags_window"].clone()  # (3, 3)
            for turn in range(pfw.shape[0]):
                pfw[turn, 0], pfw[turn, 1] = t["prev_flags_window"][turn, 1].clone(), t["prev_flags_window"][turn, 0].clone()
            t["prev_flags_window"] = pfw

        # Swap sequence history actions (indices 0↔1, 2↔3 per turn)
        if "prev_seq_actions" in t:
            psa = t["prev_seq_actions"].clone()  # (max_turns, 4)
            for turn in range(psa.shape[0]):
                psa[turn, 0], psa[turn, 1] = t["prev_seq_actions"][turn, 1].clone(), t["prev_seq_actions"][turn, 0].clone()
                psa[turn, 2], psa[turn, 3] = t["prev_seq_actions"][turn, 3].clone(), t["prev_seq_actions"][turn, 2].clone()
            t["prev_seq_actions"] = psa

            # Swap sequence species (own_a↔own_b = 0↔1, opp_a↔opp_b = 2↔3)
            pss = t["prev_seq_species"].clone()
            for turn in range(pss.shape[0]):
                pss[turn, 0], pss[turn, 1] = t["prev_seq_species"][turn, 1].clone(), t["prev_seq_species"][turn, 0].clone()
                pss[turn, 2], pss[turn, 3] = t["prev_seq_species"][turn, 3].clone(), t["prev_seq_species"][turn, 2].clone()
            t["prev_seq_species"] = pss

            # Swap sequence HP
            psh = t["prev_seq_hp"].clone()
            for turn in range(psh.shape[0]):
                psh[turn, 0], psh[turn, 1] = t["prev_seq_hp"][turn, 1].clone(), t["prev_seq_hp"][turn, 0].clone()
                psh[turn, 2], psh[turn, 3] = t["prev_seq_hp"][turn, 3].clone(), t["prev_seq_hp"][turn, 2].clone()
            t["prev_seq_hp"] = psh

        return t

    @staticmethod
    def _base_species(species: str) -> str:
        if "-Mega" in species:
            return species.split("-Mega")[0]
        return species


class CachedDataset(Dataset):
    """Dataset that loads pre-encoded tensors from a .pt cache file.

    Created by scripts/preparse_dataset.py. Loads in seconds instead of
    re-parsing 80k+ JSON files.
    """

    def __init__(self, cache_path: Path, augment: bool = True):
        print(f"Loading cached dataset from {cache_path}...")
        t0 = __import__("time").time()
        data = torch.load(cache_path, map_location="cpu", weights_only=False)
        self._samples: list[dict[str, torch.Tensor]] = data["samples"]
        self.history_mode = data.get("history_mode", "single")
        self.augment = augment

        elapsed = __import__("time").time() - t0
        print(f"Loaded {len(self._samples)} samples in {elapsed:.1f}s "
              f"(history_mode={self.history_mode})")

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        tensors = self._samples[idx]
        if self.augment and random.random() < 0.5:
            tensors = self._swap_slots(tensors)
        return tensors

    @staticmethod
    def _swap_slots(t: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Swap slot A and B — same logic as EnrichedDataset._swap_slots."""
        t = dict(t)
        for key in ("species_ids", "hp_values", "status_ids", "item_ids",
                     "ability_ids", "mega_flags", "alive_flags",
                     "item_confidences", "ability_confidences"):
            if key in t:
                v = t[key].clone()
                v[0], v[1] = t[key][1], t[key][0]
                v[4], v[5] = t[key][5], t[key][4]
                t[key] = v

        for key in ("boost_values", "move_ids", "move_confidences",
                     "species_features", "item_features", "ability_features",
                     "move_features"):
            if key in t:
                v = t[key].clone()
                v[0], v[1] = t[key][1], t[key][0]
                v[4], v[5] = t[key][5], t[key][4]
                t[key] = v

        if "action_slot_a" in t:
            t["action_slot_a"], t["action_slot_b"] = t["action_slot_b"].clone(), t["action_slot_a"].clone()
        if "action_mask_a" in t:
            t["action_mask_a"], t["action_mask_b"] = t["action_mask_b"].clone(), t["action_mask_a"].clone()

        if "prev_actions" in t:
            prev = t["prev_actions"].clone()
            prev[0], prev[1] = t["prev_actions"][1], t["prev_actions"][0]
            prev[2], prev[3] = t["prev_actions"][3], t["prev_actions"][2]
            t["prev_actions"] = prev

        if "prev_speed" in t:
            ps = t["prev_speed"].clone()
            ps[0], ps[1] = t["prev_speed"][1], t["prev_speed"][0]
            t["prev_speed"] = ps

        return t
