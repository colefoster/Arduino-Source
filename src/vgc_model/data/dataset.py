"""PyTorch Dataset for VGC battle training samples."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset

from .log_parser import parse_battle, ParsedBattle, TrainingSample, GameState, Pokemon
from .vocab import Vocabs

# Rating weight brackets
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


@dataclass
class EncodedSample:
    """Tensorized training sample ready for the model."""
    # Pokemon features: [8 slots] x features
    # Slots: own_a, own_b, own_bench_0, own_bench_1, opp_a, opp_b, opp_bench_0, opp_bench_1
    species_ids: list[int]       # [8]
    hp_values: list[float]       # [8]
    status_ids: list[int]        # [8]
    boost_values: list[list[int]]  # [8, 6] (atk,def,spa,spd,spe,evasion)
    item_ids: list[int]          # [8]
    ability_ids: list[int]       # [8]
    mega_flags: list[int]        # [8]
    alive_flags: list[int]       # [8] - 1 if slot is populated

    # Move knowledge: [8 slots, 4 moves]
    move_ids: list[list[int]]    # [8, 4]

    # Field features
    weather_id: int
    terrain_id: int
    trick_room: int
    tailwind_own: int
    tailwind_opp: int
    screens_own: list[int]       # [3] light_screen, reflect, aurora_veil
    screens_opp: list[int]       # [3]
    turn: int

    # Action labels (for battle action prediction)
    action_slot_a: int           # action index
    action_slot_b: int           # action index
    action_mask_a: list[int]     # [max_actions] legal action mask
    action_mask_b: list[int]     # [max_actions] legal action mask

    # Team preview labels (only populated for team preview samples)
    own_team_ids: list[int]      # [6] species IDs of own team
    opp_team_ids: list[int]      # [6] species IDs of opp team
    team_select_labels: list[int]  # [6] binary — was this pokemon selected?
    selected_ids: list[int]      # [4] species IDs of selected pokemon
    lead_labels: list[int]       # [4] binary — was this pokemon a lead?
    has_team_preview: bool       # whether this sample has team preview data

    # Metadata
    rating_weight: float
    is_winner: bool


# Maximum actions per slot: 4 moves * 3 targets + 2 switches + 1 mega_move_variant = 15
# Simplified: move_0..move_3 (no target distinction for now) + switch_0 + switch_1 = 6
# With targeting: move_0_opp_a, move_0_opp_b, move_0_ally, ... = 12 + switch_0, switch_1 = 14
# We'll use a flat action space: 4 moves * 3 targets + 2 switches = 14
MAX_ACTIONS = 14
BOOST_STATS = ["atk", "def", "spa", "spd", "spe", "evasion"]


class VGCDataset(Dataset):
    """Dataset that lazily loads and encodes VGC battle replays."""

    def __init__(
        self,
        replay_dir: Path,
        vocabs: Vocabs,
        min_rating: int = 0,
        winner_only: bool = True,
        min_turns: int = 3,
        augment: bool = True,
    ):
        self.vocabs = vocabs
        self.winner_only = winner_only
        self.min_turns = min_turns
        self.augment = augment

        # Index all replay files with their ratings
        self.replay_files: list[tuple[Path, int]] = []
        index_file = replay_dir.parent / "index.json"
        ratings = {}
        if index_file.exists():
            index = json.loads(index_file.read_text())
            for replay_id, meta in index.items():
                r = meta.get("rating", 0)
                if r:
                    ratings[replay_id] = r

        for f in sorted(replay_dir.glob("*.json")):
            replay_id = f.stem
            rating = ratings.get(replay_id, 0)
            if rating >= min_rating:
                self.replay_files.append((f, rating))

        # Pre-parse all replays and flatten into samples
        self.samples: list[tuple[TrainingSample, ParsedBattle]] = []
        self.team_previews: list[tuple[ParsedBattle, int]] = []  # (battle, rating)
        self._load_all()

    def _load_all(self):
        """Parse all replays and collect training samples."""
        for filepath, rating in self.replay_files:
            try:
                data = json.loads(filepath.read_text())
                log = data.get("log", "")
                result = parse_battle(log, rating)
            except Exception:
                continue

            if result is None:
                continue

            # Skip short games
            max_turn = max((s.state.turn for s in result.samples), default=0)
            if max_turn < self.min_turns:
                continue

            for sample in result.samples:
                if self.winner_only and not sample.is_winner:
                    continue
                self.samples.append((sample, result))

            # Add one team preview sample per battle (from winner's perspective)
            tp = result.team_preview
            if len(tp.p1_team) == 6 and len(tp.p2_team) == 6:
                if len(tp.p1_selected) >= 4 and len(tp.p2_selected) >= 4:
                    self.team_previews.append((result, rating))

    def __len__(self) -> int:
        return len(self.samples) + len(self.team_previews)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < len(self.samples):
            sample, battle = self.samples[idx]
            encoded = self._encode_sample(sample, battle)
            tensors = self._to_tensors(encoded)

            if self.augment and random.random() < 0.5:
                tensors = self._swap_slots(tensors)

            return tensors
        else:
            # Team preview sample
            tp_idx = idx - len(self.samples)
            battle, rating = self.team_previews[tp_idx]
            encoded = self._encode_team_preview(battle, rating)
            return self._to_tensors(encoded)

    def _encode_sample(self, sample: TrainingSample, battle: ParsedBattle) -> EncodedSample:
        """Encode a training sample into model-ready indices."""
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

        # Build 8-slot arrays: [own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1]
        all_pokemon: list[Optional[Pokemon]] = [None] * 8
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

        species_ids = []
        hp_values = []
        status_ids = []
        boost_values = []
        item_ids = []
        ability_ids = []
        mega_flags = []
        alive_flags = []
        move_ids = []

        for poke in all_pokemon:
            if poke is None:
                species_ids.append(0)
                hp_values.append(0.0)
                status_ids.append(0)
                boost_values.append([0] * 6)
                item_ids.append(0)
                ability_ids.append(0)
                mega_flags.append(0)
                alive_flags.append(0)
                move_ids.append([0, 0, 0, 0])
            else:
                species_ids.append(self.vocabs.species[poke.species])
                hp_values.append(poke.hp)
                status_ids.append(self.vocabs.status[poke.status] if poke.status else 0)
                boosts = [poke.boosts.get(s, 0) for s in BOOST_STATS]
                boost_values.append(boosts)
                item_ids.append(self.vocabs.items[poke.item] if poke.item else 0)
                ability_ids.append(self.vocabs.abilities[poke.ability] if poke.ability else 0)
                mega_flags.append(int(poke.mega))
                alive_flags.append(1)
                moves = poke.moves_known[:4]
                move_idx = [self.vocabs.moves[m] for m in moves]
                move_idx += [0] * (4 - len(move_idx))
                move_ids.append(move_idx)

        # Encode actions as indices (pass slot index + player for correct attribution)
        action_a = self._encode_action(sample.actions.slot_a, 0, own_active, own_bench, sample.player)
        action_b = self._encode_action(sample.actions.slot_b, 1, own_active, own_bench, sample.player)

        # Action masks (simplified: all moves + switches available)
        # In reality should be computed from game state, but we start simple
        mask_a = [1] * MAX_ACTIONS
        mask_b = [1] * MAX_ACTIONS

        return EncodedSample(
            species_ids=species_ids,
            hp_values=hp_values,
            status_ids=status_ids,
            boost_values=boost_values,
            item_ids=item_ids,
            ability_ids=ability_ids,
            mega_flags=mega_flags,
            alive_flags=alive_flags,
            move_ids=move_ids,
            weather_id=self.vocabs.weather[sample.state.field.weather] if sample.state.field.weather else 0,
            terrain_id=self.vocabs.terrain[sample.state.field.terrain] if sample.state.field.terrain else 0,
            trick_room=int(sample.state.field.trick_room),
            tailwind_own=int(tailwind_own),
            tailwind_opp=int(tailwind_opp),
            screens_own=screens_own,
            screens_opp=screens_opp,
            turn=min(sample.state.turn, 30),  # cap at 30
            action_slot_a=action_a,
            action_slot_b=action_b,
            action_mask_a=mask_a,
            action_mask_b=mask_b,
            own_team_ids=self._encode_team_species(battle, sample.player, "team"),
            opp_team_ids=self._encode_team_species(battle, sample.player, "opp_team"),
            team_select_labels=self._encode_team_select_labels(battle, sample.player),
            selected_ids=self._encode_team_species(battle, sample.player, "selected"),
            lead_labels=self._encode_lead_labels(battle, sample.player),
            has_team_preview=True,
            rating_weight=get_rating_weight(sample.rating),
            is_winner=sample.is_winner,
        )

    def _encode_team_species(self, battle: ParsedBattle, player: str, which: str) -> list[int]:
        """Encode species IDs for team preview fields."""
        tp = battle.team_preview
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

    def _encode_team_select_labels(self, battle: ParsedBattle, player: str) -> list[int]:
        """Binary labels: was each of the 6 team members selected?"""
        tp = battle.team_preview
        team = tp.p1_team if player == "p1" else tp.p2_team
        selected = set(tp.p1_selected if player == "p1" else tp.p2_selected)
        labels = [1 if s in selected else 0 for s in team[:6]]
        labels += [0] * (6 - len(labels))
        return labels

    def _encode_lead_labels(self, battle: ParsedBattle, player: str) -> list[int]:
        """Binary labels: was each of the 4 selected pokemon a lead?"""
        tp = battle.team_preview
        selected = (tp.p1_selected if player == "p1" else tp.p2_selected)[:4]
        leads = set(tp.p1_leads if player == "p1" else tp.p2_leads)
        labels = [1 if s in leads else 0 for s in selected]
        labels += [0] * (4 - len(labels))
        return labels

    def _encode_team_preview(self, battle: ParsedBattle, rating: int) -> EncodedSample:
        """Encode a team-preview-only sample (no battle state)."""
        player = battle.winner  # use winner's perspective

        return EncodedSample(
            # Empty battle state (zeros)
            species_ids=[0] * 8,
            hp_values=[0.0] * 8,
            status_ids=[0] * 8,
            boost_values=[[0] * 6 for _ in range(8)],
            item_ids=[0] * 8,
            ability_ids=[0] * 8,
            mega_flags=[0] * 8,
            alive_flags=[0] * 8,
            move_ids=[[0, 0, 0, 0] for _ in range(8)],
            weather_id=0,
            terrain_id=0,
            trick_room=0,
            tailwind_own=0,
            tailwind_opp=0,
            screens_own=[0, 0, 0],
            screens_opp=[0, 0, 0],
            turn=0,
            action_slot_a=0,
            action_slot_b=0,
            action_mask_a=[1] * MAX_ACTIONS,
            action_mask_b=[1] * MAX_ACTIONS,
            own_team_ids=self._encode_team_species(battle, player, "team"),
            opp_team_ids=self._encode_team_species(battle, player, "opp_team"),
            team_select_labels=self._encode_team_select_labels(battle, player),
            selected_ids=self._encode_team_species(battle, player, "selected"),
            lead_labels=self._encode_lead_labels(battle, player),
            has_team_preview=True,
            rating_weight=get_rating_weight(rating),
            is_winner=True,
        )

    def _encode_action(
        self,
        action: Optional["Action"],
        slot_idx: int,
        own_active: list[Pokemon],
        own_bench: list[Pokemon],
        player: str,
    ) -> int:
        """Encode an action into a flat index.

        Action space (14 total):
          0-11: move_i * 3 + target_j (4 moves × 3 targets: opp_a, opp_b, ally)
          12-13: switch to bench slot 0 or 1
        """
        if action is None:
            return 0

        if action.type == "switch":
            for i, poke in enumerate(own_bench):
                if poke.species == action.switch_to or self._base_species(poke.species) == self._base_species(action.switch_to):
                    return 12 + min(i, 1)
            return 12

        if action.type == "move":
            # Find move index in THIS slot's pokemon's known moves
            move_idx = 0
            if slot_idx < len(own_active):
                poke = own_active[slot_idx]
                if action.move in poke.moves_known:
                    move_idx = poke.moves_known.index(action.move)

            # Target encoding: determine if target is opp_a(0), opp_b(1), or ally(2)
            target_idx = 0  # default: opp_a / spread / self-target
            if action.target:
                target_player = action.target[:2]  # "p1" or "p2"
                target_slot = action.target[2]      # "a" or "b"

                if target_player == player:
                    # Targeting own side = ally
                    target_idx = 2
                else:
                    # Targeting opponent: a=0, b=1
                    target_idx = 0 if target_slot == "a" else 1

            return min(move_idx, 3) * 3 + min(target_idx, 2)

        return 0

    @staticmethod
    def _base_species(species: str) -> str:
        if "-Mega" in species:
            return species.split("-Mega")[0]
        return species

    def _to_tensors(self, enc: EncodedSample) -> dict[str, torch.Tensor]:
        """Convert encoded sample to tensor dict for DataLoader."""
        return {
            "species_ids": torch.tensor(enc.species_ids, dtype=torch.long),
            "hp_values": torch.tensor(enc.hp_values, dtype=torch.float),
            "status_ids": torch.tensor(enc.status_ids, dtype=torch.long),
            "boost_values": torch.tensor(enc.boost_values, dtype=torch.float),
            "item_ids": torch.tensor(enc.item_ids, dtype=torch.long),
            "ability_ids": torch.tensor(enc.ability_ids, dtype=torch.long),
            "mega_flags": torch.tensor(enc.mega_flags, dtype=torch.float),
            "alive_flags": torch.tensor(enc.alive_flags, dtype=torch.float),
            "move_ids": torch.tensor(enc.move_ids, dtype=torch.long),
            "weather_id": torch.tensor(enc.weather_id, dtype=torch.long),
            "terrain_id": torch.tensor(enc.terrain_id, dtype=torch.long),
            "trick_room": torch.tensor(enc.trick_room, dtype=torch.float),
            "tailwind_own": torch.tensor(enc.tailwind_own, dtype=torch.float),
            "tailwind_opp": torch.tensor(enc.tailwind_opp, dtype=torch.float),
            "screens_own": torch.tensor(enc.screens_own, dtype=torch.float),
            "screens_opp": torch.tensor(enc.screens_opp, dtype=torch.float),
            "turn": torch.tensor(enc.turn, dtype=torch.float),
            "action_slot_a": torch.tensor(enc.action_slot_a, dtype=torch.long),
            "action_slot_b": torch.tensor(enc.action_slot_b, dtype=torch.long),
            "action_mask_a": torch.tensor(enc.action_mask_a, dtype=torch.bool),
            "action_mask_b": torch.tensor(enc.action_mask_b, dtype=torch.bool),
            "rating_weight": torch.tensor(enc.rating_weight, dtype=torch.float),
            "own_team_ids": torch.tensor(enc.own_team_ids, dtype=torch.long),
            "opp_team_ids": torch.tensor(enc.opp_team_ids, dtype=torch.long),
            "team_select_labels": torch.tensor(enc.team_select_labels, dtype=torch.float),
            "selected_ids": torch.tensor(enc.selected_ids, dtype=torch.long),
            "lead_labels": torch.tensor(enc.lead_labels, dtype=torch.float),
            "has_team_preview": torch.tensor(enc.has_team_preview, dtype=torch.bool),
        }

    @staticmethod
    def _swap_slots(t: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Swap slot A and slot B in both inputs and labels.

        Slot layout: [own_a(0), own_b(1), own_bench0(2), own_bench1(3),
                       opp_a(4), opp_b(5), opp_bench0(6), opp_bench1(7)]
        Swapping own active: 0<->1, opp active: 4<->5
        """
        t = dict(t)  # shallow copy

        # Swap own active slots (0,1) and opp active slots (4,5) in pokemon features
        for key in ("species_ids", "hp_values", "status_ids", "item_ids",
                     "ability_ids", "mega_flags", "alive_flags"):
            v = t[key].clone()
            v[0], v[1] = t[key][1], t[key][0]
            v[4], v[5] = t[key][5], t[key][4]
            t[key] = v

        for key in ("boost_values", "move_ids"):
            v = t[key].clone()
            v[0], v[1] = t[key][1], t[key][0]
            v[4], v[5] = t[key][5], t[key][4]
            t[key] = v

        # Swap action labels
        t["action_slot_a"], t["action_slot_b"] = t["action_slot_b"].clone(), t["action_slot_a"].clone()
        t["action_mask_a"], t["action_mask_b"] = t["action_mask_b"].clone(), t["action_mask_a"].clone()

        return t
