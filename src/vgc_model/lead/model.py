"""Lead Advisor model — set-transformer with two heads.

Inputs (per side, batch B):
  species_id: [B, 6] long
  item_ids:   [B, 6, K_item] long      item_w: [B, 6, K_item] float
  ability_ids:[B, 6, K_abil] long      ability_w: [B, 6, K_abil] float
  move_ids:   [B, 6, K_move] long      move_w: [B, 6, K_move] float
  scalars:    [B, 6, 3] float
  in_prior:   [B, 6] float

Outputs:
  team_logits: [B, 6]     — per-mon "bring this mon" score
  lead_logits: [B, 15]    — over the C(6,2)=15 unordered pairs of team-sheet slots
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from .constants import PAIRS_6, lead_pair_to_index  # noqa: F401 (re-exported)


class PokemonEncoder(nn.Module):
    """Embed one Pokémon by combining species + Smogon-prior features."""

    def __init__(
        self,
        n_species: int,
        n_items: int,
        n_abilities: int,
        n_moves: int,
        d_model: int = 128,
        d_species: int = 128,
        d_item: int = 32,
        d_ability: int = 16,
        d_move: int = 32,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.species = nn.Embedding(n_species, d_species, padding_idx=0)
        self.items = nn.Embedding(n_items, d_item, padding_idx=0)
        self.abilities = nn.Embedding(n_abilities, d_ability, padding_idx=0)
        self.moves = nn.Embedding(n_moves, d_move, padding_idx=0)
        in_dim = d_species + d_item + d_ability + d_move + 3 + 1  # 3 scalars + in_prior flag
        self.proj = nn.Sequential(
            nn.Linear(in_dim, d_model),
            nn.GELU(),
            nn.LayerNorm(d_model),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        species_id: torch.Tensor,    # [B, 6]
        item_ids: torch.Tensor,      # [B, 6, K]
        item_w: torch.Tensor,        # [B, 6, K]
        ability_ids: torch.Tensor,   # [B, 6, K]
        ability_w: torch.Tensor,     # [B, 6, K]
        move_ids: torch.Tensor,      # [B, 6, K]
        move_w: torch.Tensor,        # [B, 6, K]
        scalars: torch.Tensor,       # [B, 6, 3]
        in_prior: torch.Tensor,      # [B, 6]
    ) -> torch.Tensor:               # [B, 6, d_model]
        sp = self.species(species_id)                          # [B, 6, d_species]
        it = (self.items(item_ids) * item_w.unsqueeze(-1)).sum(dim=2)
        ab = (self.abilities(ability_ids) * ability_w.unsqueeze(-1)).sum(dim=2)
        mv = (self.moves(move_ids) * move_w.unsqueeze(-1)).sum(dim=2)
        x = torch.cat([sp, it, ab, mv, scalars, in_prior.unsqueeze(-1)], dim=-1)
        return self.proj(x)


class CrossAttnBlock(nn.Module):
    """Standard pre-norm transformer block: self-attn over own, cross-attn to opp, FFN."""

    def __init__(self, d_model: int, n_heads: int = 4, ff_mult: int = 2, dropout: float = 0.0) -> None:
        super().__init__()
        self.ln1 = nn.LayerNorm(d_model)
        self.self_attn = nn.MultiheadAttention(d_model, n_heads, batch_first=True, dropout=dropout)
        self.ln2 = nn.LayerNorm(d_model)
        self.cross_attn = nn.MultiheadAttention(d_model, n_heads, batch_first=True, dropout=dropout)
        self.ln3 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_model * ff_mult),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * ff_mult, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, own: torch.Tensor, opp: torch.Tensor) -> torch.Tensor:
        h = self.ln1(own)
        a, _ = self.self_attn(h, h, h, need_weights=False)
        own = own + a
        h = self.ln2(own)
        a, _ = self.cross_attn(h, opp, opp, need_weights=False)
        own = own + a
        h = self.ln3(own)
        own = own + self.ff(h)
        return own


class LeadAdvisorModel(nn.Module):
    def __init__(
        self,
        n_species: int,
        n_items: int,
        n_abilities: int,
        n_moves: int,
        d_model: int = 128,
        n_layers: int = 2,
        n_heads: int = 4,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.encoder = PokemonEncoder(
            n_species, n_items, n_abilities, n_moves,
            d_model=d_model, dropout=dropout,
        )
        self.opp_encoder = self.encoder  # weight-share by default
        self.layers = nn.ModuleList(
            [CrossAttnBlock(d_model, n_heads, dropout=dropout) for _ in range(n_layers)]
        )

        self.team_head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 1),
        )
        # Bilinear pair scorer. lead_logits = (h_i ⨀ W ⨀ h_j) summed over channels.
        self.pair_proj = nn.Linear(d_model, d_model)
        self.pair_bias = nn.Parameter(torch.zeros(1))

        # Register pair index buffers
        ia = torch.tensor([p[0] for p in PAIRS_6], dtype=torch.long)
        ib = torch.tensor([p[1] for p in PAIRS_6], dtype=torch.long)
        self.register_buffer("pair_i", ia, persistent=False)
        self.register_buffer("pair_j", ib, persistent=False)

    def forward(
        self,
        own: dict[str, torch.Tensor],
        opp: dict[str, torch.Tensor],
        team_mask: torch.Tensor | None = None,   # [B, 6] float, 1 if mon brought
    ) -> dict[str, torch.Tensor]:
        own_h = self.encoder(
            own["species_id"], own["item_ids"], own["item_w"],
            own["ability_ids"], own["ability_w"],
            own["move_ids"], own["move_w"],
            own["scalars"], own["in_prior"],
        )
        opp_h = self.opp_encoder(
            opp["species_id"], opp["item_ids"], opp["item_w"],
            opp["ability_ids"], opp["ability_w"],
            opp["move_ids"], opp["move_w"],
            opp["scalars"], opp["in_prior"],
        )

        for layer in self.layers:
            own_h = layer(own_h, opp_h)

        team_logits = self.team_head(own_h).squeeze(-1)   # [B, 6]

        h = self.pair_proj(own_h)                          # [B, 6, d]
        hi = h.index_select(dim=1, index=self.pair_i)      # [B, 15, d]
        hj = h.index_select(dim=1, index=self.pair_j)      # [B, 15, d]
        lead_logits = (hi * hj).sum(dim=-1) + self.pair_bias  # [B, 15]

        if team_mask is not None:
            # Pair (i,j) valid iff both i and j are in the brought set.
            mi = team_mask.index_select(dim=1, index=self.pair_i)   # [B, 15]
            mj = team_mask.index_select(dim=1, index=self.pair_j)
            pair_mask = mi * mj
            lead_logits = lead_logits.masked_fill(pair_mask < 0.5, float("-inf"))

        return {"team_logits": team_logits, "lead_logits": lead_logits}


def num_params(m: nn.Module) -> int:
    return sum(p.numel() for p in m.parameters())
