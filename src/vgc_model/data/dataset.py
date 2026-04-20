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
    ):
        self.vocabs = vocabs
        self.winner_only = winner_only
        self.min_turns = min_turns

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

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        sample, battle = self.samples[idx]
        encoded = self._encode_sample(sample)
        return self._to_tensors(encoded)

    def _encode_sample(self, sample: TrainingSample) -> EncodedSample:
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

        # Encode actions as indices
        action_a = self._encode_action(sample.actions.slot_a, own_active, own_bench)
        action_b = self._encode_action(sample.actions.slot_b, own_active, own_bench)

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
            rating_weight=get_rating_weight(sample.rating),
            is_winner=sample.is_winner,
        )

    def _encode_action(
        self,
        action: Optional["Action"],
        own_active: list[Pokemon],
        own_bench: list[Pokemon],
    ) -> int:
        """Encode an action into a flat index.

        Action space (14 total):
          0-11: move_i * 3 + target_j (4 moves × 3 targets)
          12-13: switch to bench slot 0 or 1
        """
        if action is None:
            return 0

        if action.type == "switch":
            # Find which bench slot we're switching to
            for i, poke in enumerate(own_bench):
                if poke.species == action.switch_to or self._base_species(poke.species) == self._base_species(action.switch_to):
                    return 12 + min(i, 1)
            return 12  # default to first switch slot

        if action.type == "move":
            # Find move index among active pokemon's known moves
            move_idx = 0
            if own_active:
                # Check slot a first, then slot b
                for poke in own_active:
                    if action.move in poke.moves_known:
                        move_idx = poke.moves_known.index(action.move)
                        break

            # Target encoding: 0=opp_a, 1=opp_b, 2=ally
            target_idx = 0
            if action.target:
                if "b" in action.target:
                    target_idx = 1
                if action.target[:2] == action.target[:2]:  # same side = ally
                    # Check if targeting ally
                    pass  # default to 0 for now

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
        }
