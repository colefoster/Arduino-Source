"""VGC Battle Transformer model v2 — fixed 3-turn history window variant.

Extends v2 by encoding the last 3 turns of actions + faint/switch flags,
projected and added to the global token before the transformer.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from dataclasses import dataclass

from ..data.vocab import Vocabs
from .vgc_model_v2 import (
    ModelConfigV2,
    PokemonEncoderV2,
    GlobalEncoder,
    TeamSelectionHead,
    LeadSelectionHead,
)


@dataclass
class ModelConfigV2Window(ModelConfigV2):
    history_turns: int = 3


class VGCTransformerV2Window(nn.Module):
    """V2 model with a fixed 3-turn history window."""

    def __init__(self, vocabs: Vocabs, config: ModelConfigV2Window):
        super().__init__()
        self.config = config

        self.pokemon_encoder = PokemonEncoderV2(vocabs, config)
        self.global_encoder = GlobalEncoder(vocabs, config)

        # 9 position embeddings (8 pokemon + 1 global)
        self.position_embed = nn.Embedding(9, config.d_model)

        # Alive mask projection
        self.alive_gate = nn.Linear(1, config.d_model)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.n_heads,
            dim_feedforward=config.d_ff,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=config.n_layers)

        # History window encoding: shared action embedding across all turns
        # 14 actions + 1 "no prior" sentinel
        self.prev_action_embed = nn.Embedding(config.num_actions + 1, 16)
        # Per turn: 4 action embeds (4*16=64) + 3 binary flags + 2 speed flags = 69
        # 3 turns: 69 * 3 = 207
        per_turn_dim = 16 * 4 + 3 + 2  # 69
        self.history_proj = nn.Linear(per_turn_dim * config.history_turns, config.d_model)

        # Joint slot cross-attention
        self.slot_cross_attn = nn.MultiheadAttention(
            config.d_model, num_heads=2, dropout=config.dropout, batch_first=True,
        )
        self.slot_cross_norm = nn.LayerNorm(config.d_model)

        # Action heads
        self.action_head_a = nn.Sequential(
            nn.Linear(config.d_model, config.d_model),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.d_model, config.num_actions),
        )
        self.action_head_b = nn.Sequential(
            nn.Linear(config.d_model, config.d_model),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.d_model, config.num_actions),
        )

        # Team & lead selection heads
        self.team_head = TeamSelectionHead(self.pokemon_encoder.species_embed, config)
        self.lead_head = LeadSelectionHead(self.pokemon_encoder.species_embed, config)

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        out = {}

        # Encode pokemon slots with enriched features
        pokemon_repr = self.pokemon_encoder(
            species_ids=batch["species_ids"],
            move_ids=batch["move_ids"],
            item_ids=batch["item_ids"],
            ability_ids=batch["ability_ids"],
            status_ids=batch["status_ids"],
            hp_values=batch["hp_values"],
            boost_values=batch["boost_values"],
            mega_flags=batch["mega_flags"],
            species_features=batch["species_features"],
            move_features=batch["move_features"],
            item_features=batch["item_features"],
            ability_features=batch["ability_features"],
            move_confidences=batch["move_confidences"],
            item_confidences=batch["item_confidences"],
            ability_confidences=batch["ability_confidences"],
        )

        # Encode global state
        global_repr = self.global_encoder(
            weather_id=batch["weather_id"],
            terrain_id=batch["terrain_id"],
            trick_room=batch["trick_room"],
            tailwind_own=batch["tailwind_own"],
            tailwind_opp=batch["tailwind_opp"],
            screens_own=batch["screens_own"],
            screens_opp=batch["screens_opp"],
            turn=batch["turn"],
        )

        # Combine into 9-token sequence
        tokens = torch.cat([pokemon_repr, global_repr], dim=1)

        # Add positional embeddings
        positions = torch.arange(9, device=tokens.device)
        tokens = tokens + self.position_embed(positions)

        # Apply alive gate
        alive = batch["alive_flags"]
        alive_ext = torch.cat([alive, torch.ones(alive.shape[0], 1, device=alive.device)], dim=1)
        tokens = tokens * alive_ext.unsqueeze(-1)

        src_key_padding_mask = (alive_ext == 0)

        # Inject 3-turn history window into global token
        if "prev_actions_window" in batch and "prev_flags_window" in batch:
            # prev_actions_window: (B, 3, 4) action indices
            # prev_flags_window: (B, 3, 3) binary flags
            # prev_speed_window: (B, 3, 2) speed order flags
            B = tokens.shape[0]
            actions = batch["prev_actions_window"]  # (B, 3, 4)
            flags = batch["prev_flags_window"]      # (B, 3, 3)
            speed = batch.get("prev_speed_window",
                              torch.full((B, self.config.history_turns, 2), 0.5, device=tokens.device))

            # Embed actions: (B, 3, 4) -> (B, 3, 4, 16)
            action_embs = self.prev_action_embed(actions)
            # Flatten to (B, 3, 64)
            action_flat = action_embs.reshape(B, self.config.history_turns, -1)
            # Concat with flags + speed: (B, 3, 69)
            per_turn = torch.cat([action_flat, flags, speed], dim=-1)
            # Flatten all turns: (B, 207)
            history_flat = per_turn.reshape(B, -1)
            # Project to d_model
            history_token = self.history_proj(history_flat)  # (B, d_model)
            tokens[:, 8] = tokens[:, 8] + history_token
        elif "prev_actions" in batch:
            # Fallback: single prior turn (backward compat)
            prev = batch["prev_actions"]
            prev_embs = self.prev_action_embed(prev)
            prev_token = nn.functional.linear(
                prev_embs.reshape(prev_embs.shape[0], -1),
                self.history_proj.weight[:, :64],
                None,
            )
            tokens[:, 8] = tokens[:, 8] + prev_token

        # Transformer
        encoded = self.transformer(tokens, src_key_padding_mask=src_key_padding_mask)

        # Joint slot prediction
        slot_a_repr = encoded[:, 0]
        slot_b_repr = encoded[:, 1]
        slot_pair = torch.stack([slot_a_repr, slot_b_repr], dim=1)
        cross_out, _ = self.slot_cross_attn(slot_pair, slot_pair, slot_pair)
        slot_pair = self.slot_cross_norm(slot_pair + cross_out)
        slot_a_repr = slot_pair[:, 0]
        slot_b_repr = slot_pair[:, 1]

        logits_a = self.action_head_a(slot_a_repr)
        logits_b = self.action_head_b(slot_b_repr)

        logits_a = logits_a.masked_fill(~batch["action_mask_a"], float("-inf"))
        logits_b = logits_b.masked_fill(~batch["action_mask_b"], float("-inf"))

        out["logits_a"] = logits_a
        out["logits_b"] = logits_b

        if "own_team_ids" in batch:
            out["team_logits"] = self.team_head(batch["own_team_ids"], batch["opp_team_ids"])

        if "selected_ids" in batch:
            out["lead_logits"] = self.lead_head(batch["selected_ids"], batch["opp_team_ids"])

        return out

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
