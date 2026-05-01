"""Action model for the new training pipeline.

Lean transformer baseline for predicting per-slot actions in the new
encoded-shard pipeline (Phase 5). Reads the per-column tensors produced by
``Encoder`` + ``_stack_samples`` and emits two heads: action_type/move/target
for slot-A and the same for slot-B.

Replaces the multi-variant lineup (v2 / v2_window / v2_seq / winrate / lead).
We can layer on a sequence head (LSTM over prior turns) later without
disturbing this baseline.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class ActionModel(nn.Module):
    """Transformer encoder over 8 slot embeddings + field tokens, two action heads.

    Inputs (all (B, 8) unless noted):
        species_ids, status_ids, item_ids, ability_ids: long
        move_ids: long, (B, 8, 4)
        hp_values, item_confidences, ability_confidences: float
        move_confidences: float, (B, 8, 4)
        alive_flags: long
        weather_id, terrain_id, trick_room: scalar long, (B,)

    Outputs (per active slot a/b):
        type_logits: (B, 3)         — noop/move/switch
        move_logits: (B, n_moves)   — which move
        target_logits: (B, 4)       — target offset (-2..1) shifted to 0..3
        switch_logits: (B, n_species) — which species to switch to
    """

    def __init__(
        self,
        *,
        n_species: int,
        n_moves: int,
        n_items: int,
        n_abilities: int,
        n_status: int,
        n_weather: int,
        n_terrain: int,
        d_model: int = 128,
        n_layers: int = 4,
        n_heads: int = 4,
        d_ff: int = 256,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.d_model = d_model

        self.species_emb = nn.Embedding(n_species, d_model)
        self.item_emb = nn.Embedding(n_items, d_model)
        self.ability_emb = nn.Embedding(n_abilities, d_model)
        self.status_emb = nn.Embedding(n_status, d_model)
        self.move_emb = nn.Embedding(n_moves, d_model)
        self.weather_emb = nn.Embedding(n_weather, d_model)
        self.terrain_emb = nn.Embedding(n_terrain, d_model)
        self.tr_emb = nn.Embedding(2, d_model)
        self.slot_pos = nn.Parameter(torch.randn(8, d_model) * 0.02)

        self.hp_proj = nn.Linear(1, d_model)
        # Per-slot fusion: combine species/item/ability/status/aggregated-moves/hp/pos.
        self.slot_proj = nn.Linear(d_model * 5, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_ff,
            dropout=dropout, batch_first=True, activation="gelu", norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # Heads — one set per active slot (a, b)
        self.head_type_a = nn.Linear(d_model, 3)
        self.head_move_a = nn.Linear(d_model, n_moves)
        self.head_target_a = nn.Linear(d_model, 4)  # targets -2..1 -> 0..3
        self.head_switch_a = nn.Linear(d_model, n_species)
        self.head_type_b = nn.Linear(d_model, 3)
        self.head_move_b = nn.Linear(d_model, n_moves)
        self.head_target_b = nn.Linear(d_model, 4)
        self.head_switch_b = nn.Linear(d_model, n_species)

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        # Slot-level features (B, 8, d_model)
        species = self.species_emb(batch["species_ids"])
        items = self.item_emb(batch["item_ids"]) * batch["item_confidences"].unsqueeze(-1)
        abilities = self.ability_emb(batch["ability_ids"]) * batch["ability_confidences"].unsqueeze(-1)
        status = self.status_emb(batch["status_ids"])
        # Move embedding aggregated per slot, weighted by confidence.
        move_emb = self.move_emb(batch["move_ids"])  # (B, 8, 4, d_model)
        move_w = batch["move_confidences"].unsqueeze(-1)  # (B, 8, 4, 1)
        moves = (move_emb * move_w).sum(dim=2)  # (B, 8, d_model)

        slots = torch.cat([species, items, abilities, status, moves], dim=-1)
        slots = self.slot_proj(slots)
        slots = slots + self.slot_pos.unsqueeze(0)  # (1, 8, d) broadcast
        slots = slots + self.hp_proj(batch["hp_values"].unsqueeze(-1))

        # Field token broadcast as a 9th token.
        weather = self.weather_emb(batch["weather_id"])
        terrain = self.terrain_emb(batch["terrain_id"])
        tr = self.tr_emb(batch["trick_room"])
        field = (weather + terrain + tr).unsqueeze(1)  # (B, 1, d)

        x = torch.cat([slots, field], dim=1)  # (B, 9, d)
        # Mask out fainted/empty slots so attention doesn't attend to PAD content.
        slot_mask = (batch["alive_flags"] == 0)
        field_mask = torch.zeros(slot_mask.shape[0], 1, dtype=torch.bool, device=slot_mask.device)
        attn_mask = torch.cat([slot_mask, field_mask], dim=1)  # (B, 9), True = ignore

        x = self.encoder(x, src_key_padding_mask=attn_mask)
        # Slot a is index 0 (own_a), slot b is index 1 (own_b).
        slot_a = x[:, 0]
        slot_b = x[:, 1]

        return {
            "type_a": self.head_type_a(slot_a),
            "move_a": self.head_move_a(slot_a),
            "target_a": self.head_target_a(slot_a),
            "switch_a": self.head_switch_a(slot_a),
            "type_b": self.head_type_b(slot_b),
            "move_b": self.head_move_b(slot_b),
            "target_b": self.head_target_b(slot_b),
            "switch_b": self.head_switch_b(slot_b),
        }
