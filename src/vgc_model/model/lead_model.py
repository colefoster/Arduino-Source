"""Standalone Lead Advisor model for VGC team/lead selection.

Given full knowledge of your own team and species-level knowledge of the
opponent (+ usage-stat priors), predicts:
  1. Which 4 of 6 Pokemon to bring (team selection)
  2. Which 2 of those 4 to lead with (lead selection)

Architecture: set-based cross-attention (no positional embeddings).
Own Pokemon are richly encoded (species feats + move/item/ability feats
+ confidence flags). Opponent Pokemon use the same encoder with
usage-stat-inferred sets.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from dataclasses import dataclass


@dataclass
class LeadModelConfig:
    # Feature dims (from FeatureTables)
    species_feat_dim: int = 46
    move_feat_dim: int = 56
    item_feat_dim: int = 13
    ability_feat_dim: int = 16

    # Encoder
    pokemon_repr_dim: int = 64
    encoder_hidden: int = 128

    # Cross-attention
    n_cross_heads: int = 4
    dropout: float = 0.2


class PokemonEncoderLead(nn.Module):
    """Encode a Pokemon from feature-table vectors + confidence flags.

    Per-Pokemon input (305 dim):
      species_feat(46) + 4 * (move_feat(56) + conf(1)) + item_feat(13)
      + item_conf(1) + ability_feat(16) + ability_conf(1)
    """

    def __init__(self, config: LeadModelConfig):
        super().__init__()
        input_dim = (
            config.species_feat_dim                         # 46
            + 4 * (config.move_feat_dim + 1)                # 228
            + config.item_feat_dim + 1                      # 14
            + config.ability_feat_dim + 1                   # 17
        )  # = 305

        self.mlp = nn.Sequential(
            nn.Linear(input_dim, config.encoder_hidden),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.encoder_hidden, config.pokemon_repr_dim),
            nn.GELU(),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Encode Pokemon from pre-computed feature vectors.

        Args:
            features: (B, N, 305) per-Pokemon feature vectors
        Returns:
            (B, N, pokemon_repr_dim)
        """
        return self.mlp(features)


class LeadAdvisorModel(nn.Module):
    """Two-stage team preview model: team selection then lead selection."""

    def __init__(self, config: LeadModelConfig):
        super().__init__()
        self.config = config
        D = config.pokemon_repr_dim

        self.encoder = PokemonEncoderLead(config)

        # Team selection: own Pokemon attend to opponent Pokemon
        self.team_cross_attn = nn.MultiheadAttention(
            embed_dim=D, num_heads=config.n_cross_heads,
            dropout=config.dropout, batch_first=True,
        )
        self.team_cross_norm = nn.LayerNorm(D)
        self.team_head = nn.Sequential(
            nn.Linear(D, D),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(D, 1),
        )

        # Lead selection: selected-4 attend to opponent again
        self.lead_cross_attn = nn.MultiheadAttention(
            embed_dim=D, num_heads=config.n_cross_heads,
            dropout=config.dropout, batch_first=True,
        )
        self.lead_cross_norm = nn.LayerNorm(D)
        self.lead_head = nn.Sequential(
            nn.Linear(D, D),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(D, 1),
        )

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        own_feat = batch["own_features"]   # (B, 6, 305)
        opp_feat = batch["opp_features"]   # (B, 6, 305)

        # Encode all Pokemon
        own_repr = self.encoder(own_feat)   # (B, 6, D)
        opp_repr = self.encoder(opp_feat)   # (B, 6, D)

        # Team selection: own attends to opponent
        attended, _ = self.team_cross_attn(own_repr, opp_repr, opp_repr)
        team_repr = self.team_cross_norm(own_repr + attended)  # (B, 6, D)
        team_logits = self.team_head(team_repr).squeeze(-1)    # (B, 6)

        # Gather selected-4 representations
        # During training: use ground-truth indices
        # During inference: use top-4 from team_logits
        if "selected_indices" in batch:
            sel_idx = batch["selected_indices"]  # (B, 4)
        else:
            sel_idx = team_logits.topk(4, dim=-1).indices  # (B, 4)

        # Gather: (B, 4, D)
        sel_repr = team_repr.gather(
            1, sel_idx.unsqueeze(-1).expand(-1, -1, team_repr.shape[-1])
        )

        # Lead selection: selected-4 attend to opponent
        lead_attended, _ = self.lead_cross_attn(sel_repr, opp_repr, opp_repr)
        lead_repr = self.lead_cross_norm(sel_repr + lead_attended)  # (B, 4, D)
        lead_logits = self.lead_head(lead_repr).squeeze(-1)         # (B, 4)

        return {
            "team_logits": team_logits,   # (B, 6)
            "lead_logits": lead_logits,   # (B, 4)
        }

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
