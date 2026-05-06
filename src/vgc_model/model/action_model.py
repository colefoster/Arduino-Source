"""Action model for the new training pipeline.

Lean transformer baseline for predicting per-slot actions in the new
encoded-shard pipeline (Phase 5+). Reads the per-column tensors produced by
``Encoder`` + ``_stack_samples`` and emits two heads: action_type/move/target
for slot-A and the same for slot-B.

When ``use_history`` is on, an LSTM consumes the per-sample sequence-history
window (last K turns of active species + hp + action types + action moves) and
emits a single embedding that gets concatenated as a "history" token alongside
the 8 slot tokens and the field token in the transformer encoder.

When ``use_features`` is on, static lookup tables (built from
``FeatureTables``) inject explicit per-species and per-move features (type,
base stats, BP, accuracy, priority, ...) as additive biases on the ID
embeddings. Action heads also mask illegal moves / switch targets to ``-inf``
at the logits.
"""
from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn

from ..data.feature_tables import FeatureTables
from ..data.vocab import Vocabs


# Phase-1 feature dimensions. Kept in sync with `_species_to_tensor` and
# `_move_to_tensor` in feature_tables.py.
SPECIES_FEAT_DIM = 46
MOVE_FEAT_DIM = 56


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
        seq_history: bool = False,
        history_k: int = 8,
        n_action_types: int = 3,  # noop / move / switch
        use_features: bool = False,
        use_reveal: bool = False,
        use_boosts: bool = False,
        use_side_cond: bool = False,
        use_hazards: bool = False,
        use_volatile: bool = False,
        use_sub_hp: bool = False,
        use_last_move: bool = False,
        mask_actions: bool = False,
        feature_tables: Optional[FeatureTables] = None,
        vocabs: Optional[Vocabs] = None,
    ):
        super().__init__()
        self.d_model = d_model
        self.use_history = use_history
        self.seq_history = seq_history
        if use_history and seq_history:
            raise ValueError("use_history and seq_history are mutually exclusive")
        self.history_k = history_k
        self.use_features = use_features
        self.use_reveal = use_reveal
        self.use_boosts = use_boosts
        self.use_side_cond = use_side_cond
        self.use_hazards = use_hazards
        self.use_volatile = use_volatile
        self.use_sub_hp = use_sub_hp
        self.use_last_move = use_last_move
        self.mask_actions = mask_actions

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

        if use_history or seq_history:
            self.history_action_type_emb = nn.Embedding(n_action_types, d_model // 4)
            self.history_step_proj = nn.Linear(
                d_model + 4 + 4 * (d_model // 4) + d_model, d_model,
            )
        if use_history:
            self.history_lstm = nn.LSTM(
                input_size=d_model,
                hidden_size=d_model,
                num_layers=1,
                batch_first=True,
            )
        if seq_history:
            # Per-turn position embedding so attention can distinguish recency.
            self.turn_pos = nn.Parameter(torch.randn(history_k, d_model) * 0.02)

        if use_features:
            if feature_tables is None or vocabs is None:
                raise ValueError("use_features requires feature_tables and vocabs")
            species_table = _build_species_feat_table(feature_tables, vocabs, n_species)
            move_table = _build_move_feat_table(feature_tables, vocabs, n_moves)
            # Buffers (not learned) — features are static lookups by ID.
            self.register_buffer("species_feat_table", species_table)
            self.register_buffer("move_feat_table", move_table)
            self.species_feat_proj = nn.Linear(SPECIES_FEAT_DIM, d_model)
            self.move_feat_proj = nn.Linear(MOVE_FEAT_DIM, d_model)

        if use_reveal:
            # 2 scalars: own_revealed_count (0..4), opp_revealed_count (0..4),
            # added to the field token so attention can route reveal context
            # to all slots/heads.
            self.reveal_proj = nn.Linear(2, d_model)

        if use_boosts:
            # 7 stat-stage boosts per slot, normalized to [-1, +1] in encoder.
            self.boost_proj = nn.Linear(7, d_model)

        if use_side_cond:
            # 8 side-condition flags (own 4 + opp 4), added to field token.
            self.side_cond_proj = nn.Linear(8, d_model)

        if use_hazards:
            # 14 hazard + status-protection floats, added to field token.
            self.hazards_proj = nn.Linear(14, d_model)

        if use_volatile:
            # Per-slot volatile-status bitmask projected into slot embedding.
            from ..data.volatile_statuses import N_VOLATILE_STATUSES
            self.volatile_proj = nn.Linear(N_VOLATILE_STATUSES, d_model)

        if use_sub_hp:
            # Per-slot substitute HP scalar projected into slot embedding.
            self.sub_hp_proj = nn.Linear(1, d_model)

        if use_last_move:
            # Per-side last move IDs projected via the existing move embedding.
            # Concatenate (own, opp) move embeddings -> 2*d_model -> d_model.
            self.last_move_proj = nn.Linear(2 * d_model, d_model)

        # Heads — one set per active slot (a, b)
        self.head_type_a = nn.Linear(d_model, n_action_types)
        self.head_move_a = nn.Linear(d_model, n_moves)
        self.head_target_a = nn.Linear(d_model, 4)
        self.head_switch_a = nn.Linear(d_model, n_species)
        self.head_type_b = nn.Linear(d_model, n_action_types)
        self.head_move_b = nn.Linear(d_model, n_moves)
        self.head_target_b = nn.Linear(d_model, 4)
        self.head_switch_b = nn.Linear(d_model, n_species)

    def _history_steps(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        """Build (B, K, d_model): one token per prior turn."""
        species = self.species_emb(batch["prev_seq_active_species"])  # (B, K, 4, d)
        species_avg = species.mean(dim=2)  # (B, K, d)
        hp = batch["prev_seq_active_hp"].float()  # (B, K, 4)
        act_types = self.history_action_type_emb(batch["prev_seq_action_types"])  # (B, K, 4, d/4)
        bsz, K, _, _ = act_types.shape
        act_types_flat = act_types.reshape(bsz, K, -1)  # (B, K, 4 * d/4)
        moves = self.move_emb(batch["prev_seq_action_moves"])  # (B, K, 4, d)
        moves_avg = moves.mean(dim=2)  # (B, K, d)
        step = torch.cat([species_avg, hp, act_types_flat, moves_avg], dim=-1)
        return self.history_step_proj(step)  # (B, K, d_model)

    def _history_pad_mask(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        """(B, K) bool: True where the turn is left-pad (no real data)."""
        return batch["prev_seq_active_species"].sum(dim=-1) == 0

    def _history_token(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        step = self._history_steps(batch)
        _, (h_n, _) = self.history_lstm(step)
        return h_n[-1]  # (B, d_model)

    def _embed_species(self, species_ids: torch.Tensor) -> torch.Tensor:
        emb = self.species_emb(species_ids)
        if self.use_features:
            feat = self.species_feat_table[species_ids]
            emb = emb + self.species_feat_proj(feat)
        return emb

    def _embed_moves(self, move_ids: torch.Tensor) -> torch.Tensor:
        emb = self.move_emb(move_ids)
        if self.use_features:
            feat = self.move_feat_table[move_ids]
            emb = emb + self.move_feat_proj(feat)
        return emb

    def _legal_move_mask(
        self, slot_move_ids: torch.Tensor, n_moves: int,
    ) -> torch.Tensor:
        """Build (B, n_moves) bool mask: True at the slot's 4 legal move IDs.

        PAD (index 0) is always disallowed. Duplicates in the slot's move
        list (impossible in a real Pokemon set, but possible if the parser
        emits the same ID twice) just collapse to one True.
        """
        B = slot_move_ids.size(0)
        mask = torch.zeros(B, n_moves, dtype=torch.bool, device=slot_move_ids.device)
        mask.scatter_(1, slot_move_ids, True)
        mask[:, 0] = False
        return mask

    def _legal_switch_mask(
        self,
        bench_species: torch.Tensor,    # (B, 2)
        bench_alive: torch.Tensor,      # (B, 2)
        n_species: int,
    ) -> torch.Tensor:
        """Build (B, n_species) bool mask: True at alive own-bench species."""
        legal = bench_species * bench_alive.long()
        B = bench_species.size(0)
        mask = torch.zeros(B, n_species, dtype=torch.bool, device=bench_species.device)
        mask.scatter_(1, legal, True)
        mask[:, 0] = False
        return mask

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        species = self._embed_species(batch["species_ids"])
        items = self.item_emb(batch["item_ids"]) * batch["item_confidences"].unsqueeze(-1)
        abilities = self.ability_emb(batch["ability_ids"]) * batch["ability_confidences"].unsqueeze(-1)
        status = self.status_emb(batch["status_ids"])
        # Move embedding with optional features baked in. Shape (B, 8, 4, d).
        move_emb = self._embed_moves(batch["move_ids"])
        move_w = batch["move_confidences"].unsqueeze(-1)
        moves = (move_emb * move_w).sum(dim=2)  # (B, 8, d_model)

        slots = torch.cat([species, items, abilities, status, moves], dim=-1)
        slots = self.slot_proj(slots)
        slots = slots + self.slot_pos.unsqueeze(0)
        slots = slots + self.hp_proj(batch["hp_values"].unsqueeze(-1))
        if self.use_boosts:
            slots = slots + self.boost_proj(batch["stat_boosts"])
        if self.use_volatile:
            slots = slots + self.volatile_proj(batch["volatiles"])
        if self.use_sub_hp:
            slots = slots + self.sub_hp_proj(batch["sub_hps"].unsqueeze(-1))

        weather = self.weather_emb(batch["weather_id"])
        terrain = self.terrain_emb(batch["terrain_id"])
        tr = self.tr_emb(batch["trick_room"])
        field_vec = weather + terrain + tr
        if self.use_side_cond:
            field_vec = field_vec + self.side_cond_proj(batch["side_conditions"])
        if self.use_hazards:
            field_vec = field_vec + self.hazards_proj(batch["hazards"])
        if self.use_last_move:
            lm = self.move_emb(batch["last_move_ids"])  # (B, 2, d)
            B = lm.size(0)
            lm_flat = lm.reshape(B, -1)  # (B, 2*d)
            field_vec = field_vec + self.last_move_proj(lm_flat)
        if self.use_reveal:
            sids = batch["species_ids"]  # (B, 8): 0..3 own, 4..7 opp
            own_n = (sids[:, :4] > 0).sum(dim=-1, dtype=torch.float32)
            opp_n = (sids[:, 4:] > 0).sum(dim=-1, dtype=torch.float32)
            reveal = torch.stack([own_n, opp_n], dim=-1)  # (B, 2)
            field_vec = field_vec + self.reveal_proj(reveal)
        field = field_vec.unsqueeze(1)  # (B, 1, d)

        tokens = [slots, field]
        slot_mask = (batch["alive_flags"] == 0)
        masks = [slot_mask, torch.zeros(slot_mask.size(0), 1, dtype=torch.bool, device=slot_mask.device)]

        if self.use_history:
            history = self._history_token(batch).unsqueeze(1)  # (B, 1, d)
            tokens.append(history)
            masks.append(torch.zeros(slot_mask.size(0), 1, dtype=torch.bool, device=slot_mask.device))
        elif self.seq_history:
            steps = self._history_steps(batch)  # (B, K, d)
            steps = steps + self.turn_pos.unsqueeze(0)
            tokens.append(steps)
            masks.append(self._history_pad_mask(batch))  # (B, K)

        x = torch.cat(tokens, dim=1)
        attn_mask = torch.cat(masks, dim=1)

        x = self.encoder(x, src_key_padding_mask=attn_mask)
        slot_a = x[:, 0]
        slot_b = x[:, 1]

        # Heads always emit unmasked logits — mandatory for stable CE loss.
        # Under meta-off (and during early reveals), the ground-truth move/
        # switch label may sit outside the "legal" set defined by the visible
        # state (e.g., a switch target whose bench slot hasn't been revealed
        # yet). Masking those logits to -inf in the loss path turned CE into
        # Inf->NaN. Instead, return separate masks so callers can apply them
        # at argmax time (accuracy + inference) while loss stays clean.
        out = {
            "type_a": self.head_type_a(slot_a),
            "move_a": self.head_move_a(slot_a),
            "target_a": self.head_target_a(slot_a),
            "switch_a": self.head_switch_a(slot_a),
            "type_b": self.head_type_b(slot_b),
            "move_b": self.head_move_b(slot_b),
            "target_b": self.head_target_b(slot_b),
            "switch_b": self.head_switch_b(slot_b),
        }

        if self.mask_actions:
            n_moves = out["move_a"].size(-1)
            n_species = out["switch_a"].size(-1)
            out["move_a_mask"] = self._legal_move_mask(batch["move_ids"][:, 0, :], n_moves)
            out["move_b_mask"] = self._legal_move_mask(batch["move_ids"][:, 1, :], n_moves)
            bench_species = batch["species_ids"][:, 2:4]
            bench_alive = batch["alive_flags"][:, 2:4]
            switch_mask = self._legal_switch_mask(bench_species, bench_alive, n_species)
            out["switch_a_mask"] = switch_mask
            out["switch_b_mask"] = switch_mask

        return out


def _build_species_feat_table(
    ft: FeatureTables, vocabs: Vocabs, n_species: int,
) -> torch.Tensor:
    """(n_species, SPECIES_FEAT_DIM) lookup, indexed by species vocab ID."""
    table = torch.zeros(n_species, SPECIES_FEAT_DIM, dtype=torch.float32)
    for idx in range(n_species):
        name = vocabs.species.idx_to_token.get(idx, "")
        if not name or name.startswith("<"):
            continue
        feats = ft.get_species_features(name)
        table[idx] = FeatureTables.to_tensor(feats, "species")
    return table


def _build_move_feat_table(
    ft: FeatureTables, vocabs: Vocabs, n_moves: int,
) -> torch.Tensor:
    """(n_moves, MOVE_FEAT_DIM) lookup, indexed by move vocab ID."""
    table = torch.zeros(n_moves, MOVE_FEAT_DIM, dtype=torch.float32)
    for idx in range(n_moves):
        name = vocabs.moves.idx_to_token.get(idx, "")
        if not name or name.startswith("<"):
            continue
        feats = ft.get_move_features(name)
        table[idx] = FeatureTables.to_tensor(feats, "move")
    return table
