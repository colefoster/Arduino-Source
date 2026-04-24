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
SPECIES_FEAT_DIM = 45
MOVE_FEAT_DIM = 48
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
    ):
        self.vocabs = vocabs
        self.feature_tables = feature_tables
        self.usage_stats = usage_stats
        self.player_profiles = player_profiles
        self.winner_only = winner_only
        self.min_turns = min_turns
        self.augment = augment

        # Index replay files with ratings
        self.replay_files: list[tuple[Path, int]] = []
        self._index_replays(replay_dir, min_rating)

        # Pre-parse all replays
        self.samples: list[tuple[EnrichedSample, TeamPreview]] = []
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
                index = json.loads(index_candidate.read_text())
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
                data = json.loads(filepath.read_text())
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

            for sample in result:
                if self.winner_only and not sample.is_winner:
                    continue
                self.samples.append((sample, tp))

            # Team preview sample (from winner's perspective)
            if (len(tp.p1_team) == 6 and len(tp.p2_team) == 6
                    and len(tp.p1_selected) >= 4 and len(tp.p2_selected) >= 4):
                self.team_previews.append((tp, rating, winner))

    def __len__(self) -> int:
        return len(self.samples) + len(self.team_previews)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < len(self.samples):
            sample, tp = self.samples[idx]
            tensors = self._encode_sample(sample, tp)

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
            # Metadata
            "rating_weight": torch.tensor(get_rating_weight(sample.rating), dtype=torch.float),
        }

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
            "rating_weight": torch.tensor(get_rating_weight(rating), dtype=torch.float),
        }

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

            target_idx = 0
            if action.target:
                target_player = action.target[:2]
                target_slot = action.target[2]
                if target_player == player:
                    target_idx = 2
                else:
                    target_idx = 0 if target_slot == "a" else 1

            return min(move_idx, 3) * 3 + min(target_idx, 2)

        return 0

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

        return t

    @staticmethod
    def _base_species(species: str) -> str:
        if "-Mega" in species:
            return species.split("-Mega")[0]
        return species
