"""Action model for the new training pipeline.

Lean transformer baseline for predicting per-slot actions in the new
encoded-shard pipeline (Phase 5+). Reads the per-column tensors produced by
``Encoder`` + ``_stack_samples`` and emits two heads: action_type/move/target
for slot-A and the same for slot-B.

When ``use_history`` is on, an LSTM consumes the per-sample sequence-history
window (last K turns of active species + hp + action types + action moves) and
emits a single embedding that gets concatenated as a "history" token alongside
the 8 slot tokens and the field token in the transformer encoder.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class ActionModel(nn.Module):
    """Transformer encoder over 8 slot embeddings + field token (+ optional
    history token), two action heads.
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
        use_history: bool = False,
        history_k: int = 8,
        n_action_types: int = 3,  # noop / move / switch
    ):
        super().__init__()
        self.d_model = d_model
        self.use_history = use_history
        self.history_k = history_k

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
        self.slot_proj = nn.Linear(d_model * 5, d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_ff,
            dropout=dropout, batch_first=True, activation="gelu", norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        if use_history:
            self.history_action_type_emb = nn.Embedding(n_action_types, d_model // 4)
            self.history_lstm = nn.LSTM(
                input_size=d_model,  # see _build_history_seq
                hidden_size=d_model,
                num_layers=1,
                batch_first=True,
            )
            # Combine 4 slot species + 4 slot hp + 4 action types + 4 action moves into d_model.
            # Active species: 4 emb of d_model -> averaged then projected.
            self.history_step_proj = nn.Linear(
                d_model + 4 + 4 * (d_model // 4) + d_model, d_model,
            )

        # Heads — one set per active slot (a, b)
        self.head_type_a = nn.Linear(d_model, n_action_types)
        self.head_move_a = nn.Linear(d_model, n_moves)
        self.head_target_a = nn.Linear(d_model, 4)
        self.head_switch_a = nn.Linear(d_model, n_species)
        self.head_type_b = nn.Linear(d_model, n_action_types)
        self.head_move_b = nn.Linear(d_model, n_moves)
        self.head_target_b = nn.Linear(d_model, 4)
        self.head_switch_b = nn.Linear(d_model, n_species)

    def _history_token(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        """Build a (B, d_model) embedding from the prev-K sequence."""
        species = self.species_emb(batch["prev_seq_active_species"])  # (B, K, 4, d)
        species_avg = species.mean(dim=2)  # (B, K, d)
        hp = batch["prev_seq_active_hp"].float()  # (B, K, 4)
        act_types = self.history_action_type_emb(batch["prev_seq_action_types"])  # (B, K, 4, d/4)
        bsz, K, _, _ = act_types.shape
        act_types_flat = act_types.reshape(bsz, K, -1)  # (B, K, 4 * d/4)
        moves = self.move_emb(batch["prev_seq_action_moves"])  # (B, K, 4, d)
        moves_avg = moves.mean(dim=2)  # (B, K, d)

        step = torch.cat([species_avg, hp, act_types_flat, moves_avg], dim=-1)
        step = self.history_step_proj(step)
        # LSTM over the K time dimension.
        _, (h_n, _) = self.history_lstm(step)
        return h_n[-1]  # (B, d_model)

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        species = self.species_emb(batch["species_ids"])
        items = self.item_emb(batch["item_ids"]) * batch["item_confidences"].unsqueeze(-1)
        abilities = self.ability_emb(batch["ability_ids"]) * batch["ability_confidences"].unsqueeze(-1)
        status = self.status_emb(batch["status_ids"])
        move_emb = self.move_emb(batch["move_ids"])  # (B, 8, 4, d_model)
        move_w = batch["move_confidences"].unsqueeze(-1)
        moves = (move_emb * move_w).sum(dim=2)  # (B, 8, d_model)

        slots = torch.cat([species, items, abilities, status, moves], dim=-1)
        slots = self.slot_proj(slots)
        slots = slots + self.slot_pos.unsqueeze(0)
        slots = slots + self.hp_proj(batch["hp_values"].unsqueeze(-1))

        weather = self.weather_emb(batch["weather_id"])
        terrain = self.terrain_emb(batch["terrain_id"])
        tr = self.tr_emb(batch["trick_room"])
        field = (weather + terrain + tr).unsqueeze(1)  # (B, 1, d)

        tokens = [slots, field]
        slot_mask = (batch["alive_flags"] == 0)
        masks = [slot_mask, torch.zeros(slot_mask.size(0), 1, dtype=torch.bool, device=slot_mask.device)]

        if self.use_history:
            history = self._history_token(batch).unsqueeze(1)  # (B, 1, d)
            tokens.append(history)
            masks.append(torch.zeros(slot_mask.size(0), 1, dtype=torch.bool, device=slot_mask.device))

        x = torch.cat(tokens, dim=1)
        attn_mask = torch.cat(masks, dim=1)

        x = self.encoder(x, src_key_padding_mask=attn_mask)
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
