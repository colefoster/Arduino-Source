"""VGC Battle Transformer model v2 — LSTM sequence history variant.

Extends v2 by processing ALL prior turns through a small LSTM, encoding
actions, active species, HP, and flags per turn. The final hidden state
is projected and added to the global token before the transformer.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence
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
class ModelConfigV2Seq(ModelConfigV2):
    max_history: int = 30
    lstm_hidden: int = 64


class VGCTransformerV2Seq(nn.Module):
    """V2 model with LSTM-based full history encoding."""

    def __init__(self, vocabs: Vocabs, config: ModelConfigV2Seq):
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

        # Sequence history encoding
        # Per-turn: 4 action embeds (4*16=64) + 4 species embeds (4*16=64) + 4 HP + 3 flags = 135
        self.seq_action_embed = nn.Embedding(config.num_actions + 1, 16)  # +1 for sentinel
        self.seq_species_embed = nn.Embedding(len(vocabs.species), 16)    # small species embed

        per_turn_input = 16 * 4 + 16 * 4 + 4 + 3 + 2  # 137 (+2 speed flags)
        self.per_turn_proj = nn.Linear(per_turn_input, 64)
        self.history_lstm = nn.LSTM(
            input_size=64,
            hidden_size=config.lstm_hidden,
            num_layers=1,
            batch_first=True,
        )
        self.history_proj = nn.Linear(config.lstm_hidden, config.d_model)

        # Fallback: single prior turn encoding (backward compat with v2 data)
        self.prev_action_embed = nn.Embedding(config.num_actions + 1, 16)
        self.prev_turn_proj = nn.Linear(16 * 4, config.d_model)

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

    def _encode_history(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        """Encode variable-length history through LSTM. Returns (B, d_model)."""
        B = batch["prev_seq_actions"].shape[0]
        device = batch["prev_seq_actions"].device

        actions = batch["prev_seq_actions"]    # (B, max_turns, 4)
        species = batch["prev_seq_species"]    # (B, max_turns, 4)
        hp = batch["prev_seq_hp"]              # (B, max_turns, 4)
        flags = batch["prev_seq_flags"]        # (B, max_turns, 3)
        seq_len = batch["prev_seq_len"]        # (B,)

        # Embed actions and species
        action_embs = self.seq_action_embed(actions)   # (B, T, 4, 16)
        species_embs = self.seq_species_embed(species)  # (B, T, 4, 16)

        # Flatten embeddings per turn
        T = actions.shape[1]
        action_flat = action_embs.reshape(B, T, -1)    # (B, T, 64)
        species_flat = species_embs.reshape(B, T, -1)   # (B, T, 64)

        # Speed flags (optional — may not be in batch for older data)
        speed = batch.get("prev_seq_speed",
                          torch.full((B, T, 2), 0.5, device=actions.device))  # (B, T, 2)

        # Concat all features per turn: (B, T, 137)
        per_turn = torch.cat([action_flat, species_flat, hp, flags, speed], dim=-1)

        # Project to LSTM input size: (B, T, 64)
        per_turn_proj = self.per_turn_proj(per_turn)

        # Clamp lengths to at least 1 for pack_padded_sequence
        lengths = seq_len.clamp(min=1).cpu()

        # Pack and run LSTM
        packed = pack_padded_sequence(
            per_turn_proj, lengths, batch_first=True, enforce_sorted=False,
        )
        _, (h_n, _) = self.history_lstm(packed)  # h_n: (1, B, hidden)

        # Project final hidden state
        return self.history_proj(h_n.squeeze(0))  # (B, d_model)

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        out = {}

        # Encode pokemon slots
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

        # Inject history into global token
        if "prev_seq_actions" in batch:
            # Full sequence history via LSTM
            history_token = self._encode_history(batch)  # (B, d_model)
            # Zero out history for samples with no prior turns
            mask = (batch["prev_seq_len"] > 0).float().unsqueeze(-1)  # (B, 1)
            tokens[:, 8] = tokens[:, 8] + history_token * mask
        elif "prev_actions" in batch:
            # Fallback: single prior turn
            prev = batch["prev_actions"]
            prev_embs = self.prev_action_embed(prev)
            prev_token = self.prev_turn_proj(prev_embs.reshape(prev_embs.shape[0], -1))
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
