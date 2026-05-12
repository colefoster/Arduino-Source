"""Win Probability model for VGC battles.

Predicts the probability that the POV player wins from the current
board state. Reuses PokemonEncoderV2 and GlobalEncoder from v2,
replaces action heads with a single sigmoid classification head.

Useful as an eval function for search: simulate turns ahead and
pick the line with highest win%.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from dataclasses import dataclass

from ..data.vocab import Vocabs
from .vgc_model_v2 import PokemonEncoderV2, GlobalEncoder, ModelConfigV2


@dataclass
class WinrateModelConfig:
    # Same as ModelConfigV2 encoder dims
    species_dim: int = 64
    move_dim: int = 32
    item_dim: int = 24
    ability_dim: int = 24
    status_dim: int = 8
    species_feat_dim: int = 46
    move_feat_dim: int = 56
    item_feat_dim: int = 13
    ability_feat_dim: int = 16
    pokemon_repr_dim: int = 128
    encoder_hidden: int = 256
    d_model: int = 128
    n_heads: int = 4
    n_layers: int = 4
    d_ff: int = 256
    dropout: float = 0.25

    # Not used by winrate but needed by PokemonEncoderV2's parent config
    num_actions: int = 14


class WinrateModel(nn.Module):
    """Predict win probability from current board state."""

    def __init__(self, vocabs: Vocabs, config: WinrateModelConfig):
        super().__init__()
        self.config = config

        # Reuse v2 encoders
        # WinrateModelConfig has the same fields as ModelConfigV2
        v2_config = ModelConfigV2(
            species_dim=config.species_dim, move_dim=config.move_dim,
            item_dim=config.item_dim, ability_dim=config.ability_dim,
            status_dim=config.status_dim, species_feat_dim=config.species_feat_dim,
            move_feat_dim=config.move_feat_dim, item_feat_dim=config.item_feat_dim,
            ability_feat_dim=config.ability_feat_dim,
            pokemon_repr_dim=config.pokemon_repr_dim,
            encoder_hidden=config.encoder_hidden,
            d_model=config.d_model, n_heads=config.n_heads,
            n_layers=config.n_layers, d_ff=config.d_ff, dropout=config.dropout,
        )
        self.pokemon_encoder = PokemonEncoderV2(vocabs, v2_config)
        self.global_encoder = GlobalEncoder(vocabs, v2_config)

        # 9 position embeddings (8 pokemon + 1 global)
        self.position_embed = nn.Embedding(9, config.d_model)

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

        # Classification head: global token -> win probability
        self.win_head = nn.Sequential(
            nn.Linear(config.d_model, config.d_model),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.d_model, 1),
        )

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
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

        # 9-token sequence
        tokens = torch.cat([pokemon_repr, global_repr], dim=1)
        positions = torch.arange(9, device=tokens.device)
        tokens = tokens + self.position_embed(positions)

        # Alive mask
        alive = batch["alive_flags"]
        alive_ext = torch.cat([alive, torch.ones(alive.shape[0], 1, device=alive.device)], dim=1)
        tokens = tokens * alive_ext.unsqueeze(-1)
        src_key_padding_mask = (alive_ext == 0)

        # Transformer
        encoded = self.transformer(tokens, src_key_padding_mask=src_key_padding_mask)

        # Global token (position 8) -> win probability
        global_token = encoded[:, 8]
        win_logit = self.win_head(global_token).squeeze(-1)  # (B,)

        return {"win_logit": win_logit}

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
