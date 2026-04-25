"""VGC Battle Transformer model v2.

Extends v1 with explicit feature vectors and confidence flags from the
enriched parser. Pokemon encoder input grows from ~280d to ~528d to
incorporate type charts, base stats, move properties, etc.
"""

from __future__ import annotations

import math
import torch
import torch.nn as nn
from dataclasses import dataclass

from ..data.vocab import Vocabs


@dataclass
class ModelConfigV2:
    # Learned embedding dims (same as v1)
    species_dim: int = 64
    move_dim: int = 32
    item_dim: int = 24
    ability_dim: int = 24
    status_dim: int = 8

    # Explicit feature dims (from FeatureTables)
    species_feat_dim: int = 46
    move_feat_dim: int = 56
    item_feat_dim: int = 13
    ability_feat_dim: int = 16

    # Encoder
    pokemon_repr_dim: int = 128
    encoder_hidden: int = 256  # bigger to accommodate more input

    # Transformer (same as v1)
    d_model: int = 128
    n_heads: int = 4
    n_layers: int = 4
    d_ff: int = 256
    dropout: float = 0.25

    num_actions: int = 14


class PokemonEncoderV2(nn.Module):
    """Encode a single pokemon with learned embeddings + explicit features + confidence."""

    def __init__(self, vocabs: Vocabs, config: ModelConfigV2):
        super().__init__()
        self.config = config

        self.species_embed = nn.Embedding(len(vocabs.species), config.species_dim)
        self.move_embed = nn.Embedding(len(vocabs.moves), config.move_dim)
        self.item_embed = nn.Embedding(len(vocabs.items), config.item_dim)
        self.ability_embed = nn.Embedding(len(vocabs.abilities), config.ability_dim)
        self.status_embed = nn.Embedding(len(vocabs.status), config.status_dim)

        # Input per pokemon slot:
        # species_embed(64) + species_features(45) = 109
        # 4 × (move_embed(32) + move_features(48) + move_confidence(1)) = 324
        # item_embed(24) + item_features(13) + item_confidence(1) = 38
        # ability_embed(24) + ability_features(16) + ability_confidence(1) = 41
        # status_embed(8) + hp(1) + boosts(6) + mega(1) = 16
        # Total: 528
        input_dim = (
            config.species_dim + config.species_feat_dim           # 109
            + 4 * (config.move_dim + config.move_feat_dim + 1)     # 324
            + config.item_dim + config.item_feat_dim + 1           # 38
            + config.ability_dim + config.ability_feat_dim + 1     # 41
            + config.status_dim + 1 + 6 + 1                       # 16
        )

        self.mlp = nn.Sequential(
            nn.Linear(input_dim, config.encoder_hidden),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.encoder_hidden, config.pokemon_repr_dim),
            nn.GELU(),
        )

    def forward(
        self,
        species_ids: torch.Tensor,          # (B, 8)
        move_ids: torch.Tensor,             # (B, 8, 4)
        item_ids: torch.Tensor,             # (B, 8)
        ability_ids: torch.Tensor,          # (B, 8)
        status_ids: torch.Tensor,           # (B, 8)
        hp_values: torch.Tensor,            # (B, 8)
        boost_values: torch.Tensor,         # (B, 8, 6)
        mega_flags: torch.Tensor,           # (B, 8)
        species_features: torch.Tensor,     # (B, 8, 45)
        move_features: torch.Tensor,        # (B, 8, 4, 48)
        item_features: torch.Tensor,        # (B, 8, 13)
        ability_features: torch.Tensor,     # (B, 8, 16)
        move_confidences: torch.Tensor,     # (B, 8, 4)
        item_confidences: torch.Tensor,     # (B, 8)
        ability_confidences: torch.Tensor,  # (B, 8)
    ) -> torch.Tensor:
        """Encode all 8 pokemon slots. Returns (B, 8, pokemon_repr_dim)."""
        B, N = species_ids.shape  # N=8

        # Learned embeddings
        species_emb = self.species_embed(species_ids)       # (B, 8, 64)
        move_emb = self.move_embed(move_ids)                # (B, 8, 4, 32)
        item_emb = self.item_embed(item_ids)                # (B, 8, 24)
        ability_emb = self.ability_embed(ability_ids)       # (B, 8, 24)
        status_emb = self.status_embed(status_ids)          # (B, 8, 8)

        # Per-move: concat embed + features + confidence
        # move_emb: (B, 8, 4, 32), move_features: (B, 8, 4, 48), move_confidences: (B, 8, 4)
        move_conf_expanded = move_confidences.unsqueeze(-1)  # (B, 8, 4, 1)
        move_combined = torch.cat([
            move_emb, move_features, move_conf_expanded
        ], dim=-1)  # (B, 8, 4, 81)
        move_flat = move_combined.flatten(-2, -1)  # (B, 8, 324)

        # Concat everything
        x = torch.cat([
            species_emb,                            # (B, 8, 64)
            species_features,                       # (B, 8, 45)
            move_flat,                              # (B, 8, 324)
            item_emb,                               # (B, 8, 24)
            item_features,                          # (B, 8, 13)
            item_confidences.unsqueeze(-1),         # (B, 8, 1)
            ability_emb,                            # (B, 8, 24)
            ability_features,                       # (B, 8, 16)
            ability_confidences.unsqueeze(-1),      # (B, 8, 1)
            status_emb,                             # (B, 8, 8)
            hp_values.unsqueeze(-1),                # (B, 8, 1)
            boost_values,                           # (B, 8, 6)
            mega_flags.unsqueeze(-1),               # (B, 8, 1)
        ], dim=-1)

        return self.mlp(x)  # (B, 8, pokemon_repr_dim)


class GlobalEncoder(nn.Module):
    """Encode field state into a token (same as v1)."""

    def __init__(self, vocabs: Vocabs, config: ModelConfigV2):
        super().__init__()
        self.weather_embed = nn.Embedding(len(vocabs.weather), 8)
        self.terrain_embed = nn.Embedding(len(vocabs.terrain), 8)

        # weather(8) + terrain(8) + trick_room(1) + tailwind(2) + screens(6) + turn(1) = 26
        self.proj = nn.Linear(26, config.pokemon_repr_dim)

    def forward(
        self,
        weather_id: torch.Tensor,
        terrain_id: torch.Tensor,
        trick_room: torch.Tensor,
        tailwind_own: torch.Tensor,
        tailwind_opp: torch.Tensor,
        screens_own: torch.Tensor,
        screens_opp: torch.Tensor,
        turn: torch.Tensor,
    ) -> torch.Tensor:
        """Returns (B, 1, pokemon_repr_dim) global token."""
        weather_emb = self.weather_embed(weather_id)
        terrain_emb = self.terrain_embed(terrain_id)

        x = torch.cat([
            weather_emb,
            terrain_emb,
            trick_room.unsqueeze(-1),
            tailwind_own.unsqueeze(-1),
            tailwind_opp.unsqueeze(-1),
            screens_own,
            screens_opp,
            (turn / 30.0).unsqueeze(-1),
        ], dim=-1)

        return self.proj(x).unsqueeze(1)


class TeamSelectionHead(nn.Module):
    """Predict which 4 of 6 pokemon to bring (same as v1)."""

    def __init__(self, species_embed: nn.Embedding, config: ModelConfigV2):
        super().__init__()
        self.cross_attn = nn.MultiheadAttention(
            embed_dim=config.species_dim, num_heads=4,
            dropout=config.dropout, batch_first=True,
        )
        self.head = nn.Sequential(
            nn.Linear(config.species_dim, config.species_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.species_dim, 1),
        )
        self.species_embed = species_embed

    def forward(self, own_team: torch.Tensor, opp_team: torch.Tensor) -> torch.Tensor:
        own_emb = self.species_embed(own_team)
        opp_emb = self.species_embed(opp_team)
        attended, _ = self.cross_attn(own_emb, opp_emb, opp_emb)
        return self.head(attended).squeeze(-1)


class LeadSelectionHead(nn.Module):
    """Predict which 2 of 4 selected pokemon to lead (same as v1)."""

    def __init__(self, species_embed: nn.Embedding, config: ModelConfigV2):
        super().__init__()
        self.cross_attn = nn.MultiheadAttention(
            embed_dim=config.species_dim, num_heads=4,
            dropout=config.dropout, batch_first=True,
        )
        self.head = nn.Sequential(
            nn.Linear(config.species_dim, config.species_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.species_dim, 1),
        )
        self.species_embed = species_embed

    def forward(self, selected_4: torch.Tensor, opp_team: torch.Tensor) -> torch.Tensor:
        sel_emb = self.species_embed(selected_4)
        opp_emb = self.species_embed(opp_team)
        attended, _ = self.cross_attn(sel_emb, opp_emb, opp_emb)
        return self.head(attended).squeeze(-1)


class VGCTransformerV2(nn.Module):
    """V2 model: enriched features + confidence flags."""

    def __init__(self, vocabs: Vocabs, config: ModelConfigV2):
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

        # Prior turn encoding: 4 action embeddings (own_a, own_b, opp_a, opp_b)
        self.prev_action_embed = nn.Embedding(config.num_actions + 1, 16)  # +1 for "no prior"
        self.prev_turn_proj = nn.Linear(16 * 4, config.d_model)

        # Joint slot cross-attention: slots A and B see each other before action heads
        self.slot_cross_attn = nn.MultiheadAttention(
            config.d_model, num_heads=2, dropout=config.dropout, batch_first=True,
        )
        self.slot_cross_norm = nn.LayerNorm(config.d_model)

        # Action heads (now informed by cross-attended joint slot representation)
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

        # Apply alive gate to mask empty pokemon slots
        alive = batch["alive_flags"]
        alive_ext = torch.cat([alive, torch.ones(alive.shape[0], 1, device=alive.device)], dim=1)
        tokens = tokens * alive_ext.unsqueeze(-1)

        # Attention mask (True = ignore)
        src_key_padding_mask = (alive_ext == 0)

        # Inject prior turn context as an extra token if available
        if "prev_actions" in batch:
            prev = batch["prev_actions"]  # (B, 4) — own_a, own_b, opp_a, opp_b
            prev_embs = self.prev_action_embed(prev)  # (B, 4, 16)
            prev_token = self.prev_turn_proj(prev_embs.reshape(prev_embs.shape[0], -1))  # (B, d_model)
            tokens[:, 8] = tokens[:, 8] + prev_token  # add to global token

        # Transformer
        encoded = self.transformer(tokens, src_key_padding_mask=src_key_padding_mask)

        # Joint slot prediction: cross-attend A ↔ B before action heads
        slot_a_repr = encoded[:, 0]  # (B, d_model)
        slot_b_repr = encoded[:, 1]  # (B, d_model)
        slot_pair = torch.stack([slot_a_repr, slot_b_repr], dim=1)  # (B, 2, d_model)
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
