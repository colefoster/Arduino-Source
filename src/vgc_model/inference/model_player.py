"""VGC Model Player — bridges the trained transformer to poke_env's Player interface.

Translates DoubleBattle state into our tensor format, runs inference,
and converts the model's action indices back to Showdown commands.
"""

from __future__ import annotations

import random
from typing import Optional

import torch

from poke_env.environment import AbstractBattle
from poke_env.environment.double_battle import DoubleBattle
from poke_env.player.battle_order import BattleOrder, DoubleBattleOrder
from poke_env.player.player import Player

from ..data.vocab import Vocabs
from ..data.dataset import BOOST_STATS, MAX_ACTIONS
from ..model.vgc_model import VGCTransformer, ModelConfig


class VGCModelPlayer(Player):
    """Plays VGC doubles using a trained VGCTransformer model."""

    def __init__(
        self,
        model: VGCTransformer,
        vocabs: Vocabs,
        device: torch.device = torch.device("cpu"),
        temperature: float = 0.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.model = model
        self.model.eval()
        self.vocabs = vocabs
        self.device = device
        self.temperature = temperature  # 0 = greedy, >0 = sampling

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)
        return self._choose_doubles_move(battle)

    def teampreview(self, battle: AbstractBattle) -> str:
        """Use the team selection + lead selection heads to pick 4 and order them."""
        team = battle.team
        team_species = [p.species for p in team.values()]

        # If we don't have exactly 6, fall back to default
        if len(team_species) != 6:
            return self.random_teampreview(battle)

        # Encode own team and opponent team
        opp_species = [p.species for p in (battle.opponent_team or {}).values()]
        # Pad opponent to 6 (might not be fully revealed)
        opp_species = opp_species[:6]
        opp_species += [""] * (6 - len(opp_species))

        own_ids = torch.tensor([[self.vocabs.species[s] for s in team_species]], dtype=torch.long)
        opp_ids = torch.tensor([[self.vocabs.species[s] for s in opp_species]], dtype=torch.long)

        with torch.no_grad():
            # Team selection: pick 4 of 6
            team_logits = self.model.team_head(
                own_ids.to(self.device), opp_ids.to(self.device)
            )  # (1, 6)
            team_scores = team_logits.squeeze(0)
            _, top4_indices = team_scores.topk(4)
            selected_indices = sorted(top4_indices.tolist())

            # Lead selection: pick 2 of 4
            selected_ids = torch.tensor(
                [[self.vocabs.species[team_species[i]] for i in selected_indices]],
                dtype=torch.long,
            )
            lead_logits = self.model.lead_head(
                selected_ids.to(self.device), opp_ids.to(self.device)
            )  # (1, 4)
            lead_scores = lead_logits.squeeze(0)
            _, top2_leads = lead_scores.topk(2)

        # Build team order: leads first, then back
        lead_idx = [selected_indices[i] for i in top2_leads.tolist()]
        back_idx = [i for i in selected_indices if i not in lead_idx]
        order = lead_idx + back_idx

        # Convert to 1-based indices for Showdown
        return "/team " + "".join(str(i + 1) for i in order)

    def _choose_doubles_move(self, battle: DoubleBattle) -> DoubleBattleOrder:
        """Use the model to pick actions for both active slots."""
        orders = [None, None]

        # Handle force switches first
        if any(battle.force_switch):
            for i in range(2):
                if battle.force_switch[i]:
                    if battle.available_switches[i]:
                        orders[i] = self.create_order(
                            random.choice(battle.available_switches[i])
                        )
            return DoubleBattleOrder(first_order=orders[0], second_order=orders[1])

        # Build state tensor
        batch = self._battle_to_tensor(battle)

        with torch.no_grad():
            out = self.model(batch)
            logits_a = out["logits_a"].squeeze(0)  # (num_actions,)
            logits_b = out["logits_b"].squeeze(0)

        # Decode actions for each slot
        for slot_idx, logits in enumerate([logits_a, logits_b]):
            active = battle.active_pokemon[slot_idx]
            if active is None or active.fainted:
                if battle.available_switches[slot_idx]:
                    orders[slot_idx] = self.create_order(
                        random.choice(battle.available_switches[slot_idx])
                    )
                continue

            # Mask illegal actions based on actual available moves/switches
            mask = self._build_action_mask(battle, slot_idx)
            logits = logits.masked_fill(~mask, float("-inf"))

            # Pick action
            if self.temperature > 0:
                probs = torch.softmax(logits / self.temperature, dim=-1)
                action_idx = torch.multinomial(probs, 1).item()
            else:
                action_idx = logits.argmax().item()

            order = self._action_to_order(action_idx, battle, slot_idx)
            if order is not None:
                orders[slot_idx] = order

        # Fallback: if either slot has no order, pick random
        for i in range(2):
            if orders[i] is None:
                if battle.available_moves[i]:
                    move = random.choice(battle.available_moves[i])
                    orders[i] = self.create_order(move, move_target=random.choice([1, 2]))
                elif battle.available_switches[i]:
                    orders[i] = self.create_order(
                        random.choice(battle.available_switches[i])
                    )

        return DoubleBattleOrder(first_order=orders[0], second_order=orders[1])

    def _battle_to_tensor(self, battle: DoubleBattle) -> dict[str, torch.Tensor]:
        """Convert a DoubleBattle to our model's input tensor format."""
        # 8 slots: own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1
        species_ids = [0] * 8
        hp_values = [0.0] * 8
        status_ids = [0] * 8
        boost_values = [[0] * 6 for _ in range(8)]
        item_ids = [0] * 8
        ability_ids = [0] * 8
        mega_flags = [0] * 8
        alive_flags = [0] * 8
        move_ids = [[0, 0, 0, 0] for _ in range(8)]

        # Own active (slots 0-1)
        for i, poke in enumerate(battle.active_pokemon[:2]):
            if poke is None or poke.fainted:
                continue
            slot = i
            species_ids[slot] = self.vocabs.species[poke.species]
            hp_values[slot] = poke.current_hp_fraction
            if poke.status:
                status_ids[slot] = self.vocabs.status[poke.status.name.lower()]
            if poke.ability:
                ability_ids[slot] = self.vocabs.abilities[poke.ability]
            if poke.item:
                item_ids[slot] = self.vocabs.items[poke.item]
            mega_flags[slot] = 1 if getattr(poke, 'is_mega', False) else 0
            alive_flags[slot] = 1
            boosts = [poke.boosts.get(s, 0) for s in BOOST_STATS]
            boost_values[slot] = boosts
            moves = list(poke.moves.keys())[:4]
            move_ids[slot] = [self.vocabs.moves[m] for m in moves] + [0] * (4 - len(moves))

        # Own bench (slots 2-3)
        bench = [p for p in battle.team.values()
                 if p not in battle.active_pokemon and not p.fainted]
        for i, poke in enumerate(bench[:2]):
            slot = 2 + i
            species_ids[slot] = self.vocabs.species[poke.species]
            hp_values[slot] = poke.current_hp_fraction
            alive_flags[slot] = 1
            if poke.status:
                status_ids[slot] = self.vocabs.status[poke.status.name.lower()]

        # Opponent active (slots 4-5)
        for i, poke in enumerate(battle.opponent_active_pokemon[:2]):
            if poke is None or poke.fainted:
                continue
            slot = 4 + i
            species_ids[slot] = self.vocabs.species[poke.species]
            hp_values[slot] = poke.current_hp_fraction
            if poke.status:
                status_ids[slot] = self.vocabs.status[poke.status.name.lower()]
            if poke.ability:
                ability_ids[slot] = self.vocabs.abilities[poke.ability]
            mega_flags[slot] = 1 if getattr(poke, 'is_mega', False) else 0
            alive_flags[slot] = 1
            boosts = [poke.boosts.get(s, 0) for s in BOOST_STATS]
            boost_values[slot] = boosts
            moves = list(poke.moves.keys())[:4]
            move_ids[slot] = [self.vocabs.moves[m] for m in moves] + [0] * (4 - len(moves))

        # Opponent bench (slots 6-7)
        opp_bench = [p for p in (battle.opponent_team or {}).values()
                     if p not in battle.opponent_active_pokemon and not p.fainted]
        for i, poke in enumerate(opp_bench[:2]):
            slot = 6 + i
            species_ids[slot] = self.vocabs.species[poke.species]
            hp_values[slot] = poke.current_hp_fraction
            alive_flags[slot] = 1

        # Field state
        weather_str = battle.weather.name.lower() if battle.weather else ""
        weather_map = {"sunnyday": "SunnyDay", "raindance": "RainDance",
                       "sandstorm": "Sandstorm", "snow": "Snow", "hail": "Snow"}
        weather_id = self.vocabs.weather[weather_map.get(weather_str, "")] if weather_str else 0

        terrain_str = battle.fields.get("terrain", "") if hasattr(battle, "fields") else ""
        terrain_id = 0  # simplified

        trick_room = 1.0 if hasattr(battle, "trick_room") and battle.trick_room else 0.0

        # Side conditions
        own_sc = battle.side_conditions if hasattr(battle, "side_conditions") else {}
        opp_sc = battle.opponent_side_conditions if hasattr(battle, "opponent_side_conditions") else {}

        def has_sc(sc_dict, name):
            return 1.0 if any(name.lower() in str(k).lower() for k in sc_dict) else 0.0

        batch = {
            "species_ids": torch.tensor([species_ids], dtype=torch.long).to(self.device),
            "hp_values": torch.tensor([hp_values], dtype=torch.float).to(self.device),
            "status_ids": torch.tensor([status_ids], dtype=torch.long).to(self.device),
            "boost_values": torch.tensor([boost_values], dtype=torch.float).to(self.device),
            "item_ids": torch.tensor([item_ids], dtype=torch.long).to(self.device),
            "ability_ids": torch.tensor([ability_ids], dtype=torch.long).to(self.device),
            "mega_flags": torch.tensor([mega_flags], dtype=torch.float).to(self.device),
            "alive_flags": torch.tensor([alive_flags], dtype=torch.float).to(self.device),
            "move_ids": torch.tensor([move_ids], dtype=torch.long).to(self.device),
            "weather_id": torch.tensor([weather_id], dtype=torch.long).to(self.device),
            "terrain_id": torch.tensor([terrain_id], dtype=torch.long).to(self.device),
            "trick_room": torch.tensor([trick_room], dtype=torch.float).to(self.device),
            "tailwind_own": torch.tensor([has_sc(own_sc, "tailwind")], dtype=torch.float).to(self.device),
            "tailwind_opp": torch.tensor([has_sc(opp_sc, "tailwind")], dtype=torch.float).to(self.device),
            "screens_own": torch.tensor([[has_sc(own_sc, "lightscreen"), has_sc(own_sc, "reflect"), has_sc(own_sc, "auroraveil")]], dtype=torch.float).to(self.device),
            "screens_opp": torch.tensor([[has_sc(opp_sc, "lightscreen"), has_sc(opp_sc, "reflect"), has_sc(opp_sc, "auroraveil")]], dtype=torch.float).to(self.device),
            "turn": torch.tensor([min(battle.turn, 30)], dtype=torch.float).to(self.device),
            "action_mask_a": torch.ones(1, MAX_ACTIONS, dtype=torch.bool).to(self.device),
            "action_mask_b": torch.ones(1, MAX_ACTIONS, dtype=torch.bool).to(self.device),
        }

        # Team preview data for the heads
        own_team = [p.species for p in battle.team.values()][:6]
        own_team += [""] * (6 - len(own_team))
        opp_team = [p.species for p in (battle.opponent_team or {}).values()][:6]
        opp_team += [""] * (6 - len(opp_team))

        batch["own_team_ids"] = torch.tensor(
            [[self.vocabs.species[s] for s in own_team]], dtype=torch.long
        ).to(self.device)
        batch["opp_team_ids"] = torch.tensor(
            [[self.vocabs.species[s] for s in opp_team]], dtype=torch.long
        ).to(self.device)

        # Selected (current team of 4)
        selected = [p.species for p in battle.team.values()][:4]
        selected += [""] * (4 - len(selected))
        batch["selected_ids"] = torch.tensor(
            [[self.vocabs.species[s] for s in selected]], dtype=torch.long
        ).to(self.device)

        batch["has_team_preview"] = torch.tensor([True], dtype=torch.bool).to(self.device)

        return batch

    def _build_action_mask(self, battle: DoubleBattle, slot_idx: int) -> torch.Tensor:
        """Build a boolean mask of legal actions for a slot."""
        mask = torch.zeros(MAX_ACTIONS, dtype=torch.bool)

        # Moves: indices 0-11 (move_i * 3 + target_j)
        moves = battle.available_moves[slot_idx]
        for i, move in enumerate(moves[:4]):
            for target_j in range(3):  # opp_a, opp_b, ally
                mask[i * 3 + target_j] = True

        # Switches: indices 12-13
        switches = battle.available_switches[slot_idx]
        for i in range(min(len(switches), 2)):
            mask[12 + i] = True

        # If nothing is legal, allow everything (fallback)
        if not mask.any():
            mask[:] = True

        return mask.to(self.device)

    def _action_to_order(
        self, action_idx: int, battle: DoubleBattle, slot_idx: int
    ) -> Optional[BattleOrder]:
        """Convert a flat action index back to a BattleOrder."""
        if action_idx >= 12:
            # Switch
            switch_idx = action_idx - 12
            switches = battle.available_switches[slot_idx]
            if switch_idx < len(switches):
                return self.create_order(switches[switch_idx])
            elif switches:
                return self.create_order(switches[0])
            return None

        # Move with target
        move_idx = action_idx // 3
        target_idx = action_idx % 3  # 0=opp_a, 1=opp_b, 2=ally

        moves = battle.available_moves[slot_idx]
        if move_idx >= len(moves):
            if moves:
                move_idx = 0
            else:
                return None

        # Convert target: 0->1 (opp left), 1->2 (opp right), 2->-1 (ally)
        target_map = {0: 1, 1: 2, 2: -1}
        target = target_map[target_idx]

        return self.create_order(moves[move_idx], move_target=target)
