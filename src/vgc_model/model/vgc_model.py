"""VGC Battle Transformer model.

Small transformer-based policy network for Pokemon VGC doubles decisions.
Processes 8 pokemon slots + 1 global state token through self-attention,
then outputs action distributions for both active slots.
"""

from __future__ import annotations

import math
import torch
import torch.nn as nn
from dataclasses import dataclass

from ..data.vocab import Vocabs


@dataclass
class ModelConfig:
    # Embedding dimensions
    species_dim: int = 64
    move_dim: int = 32
    item_dim: int = 24
    ability_dim: int = 24
    status_dim: int = 8

    # Encoder
    pokemon_repr_dim: int = 128
    encoder_hidden: int = 192

    # Transformer
    d_model: int = 128
    n_heads: int = 4
    n_layers: int = 4
    d_ff: int = 256
    dropout: float = 0.25

    # Output
    num_actions: int = 14  # 4 moves * 3 targets + 2 switches


class PokemonEncoder(nn.Module):
    """Encode a single pokemon into a fixed-size representation."""

    def __init__(self, vocabs: Vocabs, config: ModelConfig):
        super().__init__()
        self.config = config

        self.species_embed = nn.Embedding(len(vocabs.species), config.species_dim)
        self.move_embed = nn.Embedding(len(vocabs.moves), config.move_dim)
        self.item_embed = nn.Embedding(len(vocabs.items), config.item_dim)
        self.ability_embed = nn.Embedding(len(vocabs.abilities), config.ability_dim)
        self.status_embed = nn.Embedding(len(vocabs.status), config.status_dim)

        # Input: species + 4 moves + item + ability + status + hp + 6 boosts + mega flag
        input_dim = (
            config.species_dim
            + 4 * config.move_dim
            + config.item_dim
            + config.ability_dim
            + config.status_dim
            + 1   # hp
            + 6   # boosts
            + 1   # mega flag
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
        species_ids: torch.Tensor,    # (B, 8)
        move_ids: torch.Tensor,       # (B, 8, 4)
        item_ids: torch.Tensor,       # (B, 8)
        ability_ids: torch.Tensor,    # (B, 8)
        status_ids: torch.Tensor,     # (B, 8)
        hp_values: torch.Tensor,      # (B, 8)
        boost_values: torch.Tensor,   # (B, 8, 6)
        mega_flags: torch.Tensor,     # (B, 8)
    ) -> torch.Tensor:
        """Encode all 8 pokemon slots. Returns (B, 8, pokemon_repr_dim)."""
        B, N = species_ids.shape  # N=8

        species_emb = self.species_embed(species_ids)           # (B, 8, species_dim)
        move_emb = self.move_embed(move_ids).flatten(-2, -1)    # (B, 8, 4*move_dim)
        item_emb = self.item_embed(item_ids)                    # (B, 8, item_dim)
        ability_emb = self.ability_embed(ability_ids)           # (B, 8, ability_dim)
        status_emb = self.status_embed(status_ids)              # (B, 8, status_dim)

        # Concat all features
        x = torch.cat([
            species_emb,
            move_emb,
            item_emb,
            ability_emb,
            status_emb,
            hp_values.unsqueeze(-1),
            boost_values,
            mega_flags.unsqueeze(-1),
        ], dim=-1)

        return self.mlp(x)  # (B, 8, pokemon_repr_dim)


class GlobalEncoder(nn.Module):
    """Encode field state into a token."""

    def __init__(self, vocabs: Vocabs, config: ModelConfig):
        super().__init__()
        self.weather_embed = nn.Embedding(len(vocabs.weather), 8)
        self.terrain_embed = nn.Embedding(len(vocabs.terrain), 8)

        # weather(8) + terrain(8) + trick_room(1) + tailwind(2) + screens(6) + turn(1) = 26
        self.proj = nn.Linear(26, config.pokemon_repr_dim)

    def forward(
        self,
        weather_id: torch.Tensor,    # (B,)
        terrain_id: torch.Tensor,    # (B,)
        trick_room: torch.Tensor,    # (B,)
        tailwind_own: torch.Tensor,  # (B,)
        tailwind_opp: torch.Tensor,  # (B,)
        screens_own: torch.Tensor,   # (B, 3)
        screens_opp: torch.Tensor,   # (B, 3)
        turn: torch.Tensor,          # (B,)
    ) -> torch.Tensor:
        """Returns (B, 1, pokemon_repr_dim) global token."""
        weather_emb = self.weather_embed(weather_id)   # (B, 8)
        terrain_emb = self.terrain_embed(terrain_id)   # (B, 8)

        x = torch.cat([
            weather_emb,
            terrain_emb,
            trick_room.unsqueeze(-1),
            tailwind_own.unsqueeze(-1),
            tailwind_opp.unsqueeze(-1),
            screens_own,
            screens_opp,
            (turn / 30.0).unsqueeze(-1),  # normalize turn
        ], dim=-1)

        return self.proj(x).unsqueeze(1)  # (B, 1, d_model)


class VGCTransformer(nn.Module):
    """Main model: encodes game state, outputs action distributions."""

    def __init__(self, vocabs: Vocabs, config: ModelConfig):
        super().__init__()
        self.config = config

        self.pokemon_encoder = PokemonEncoder(vocabs, config)
        self.global_encoder = GlobalEncoder(vocabs, config)

        # Positional embeddings for 9 tokens (8 pokemon + 1 global)
        # Positions encode role: own_active_a(0), own_active_b(1), own_bench(2,3),
        #                         opp_active_a(4), opp_active_b(5), opp_bench(6,7), global(8)
        self.position_embed = nn.Embedding(9, config.d_model)

        # Alive mask projection (to zero out empty slots)
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

        # Action heads - one for each active slot
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

    def forward(self, batch: dict[str, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass.

        Returns:
            (logits_a, logits_b): action logits for slot a and b, each (B, num_actions)
        """
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
        )  # (B, 8, d_model)

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
        )  # (B, 1, d_model)

        # Combine into 9-token sequence
        tokens = torch.cat([pokemon_repr, global_repr], dim=1)  # (B, 9, d_model)

        # Add positional embeddings
        positions = torch.arange(9, device=tokens.device)
        tokens = tokens + self.position_embed(positions)

        # Apply alive gate to mask empty pokemon slots
        alive = batch["alive_flags"]  # (B, 8)
        # Extend with 1 for global token
        alive_ext = torch.cat([alive, torch.ones(alive.shape[0], 1, device=alive.device)], dim=1)
        tokens = tokens * alive_ext.unsqueeze(-1)

        # Create attention mask for empty slots
        # Transformer expects: True = ignore this position
        src_key_padding_mask = (alive_ext == 0)

        # Transformer
        encoded = self.transformer(tokens, src_key_padding_mask=src_key_padding_mask)

        # Use own_active_a (position 0) and own_active_b (position 1) for action prediction
        slot_a_repr = encoded[:, 0]  # (B, d_model)
        slot_b_repr = encoded[:, 1]  # (B, d_model)

        logits_a = self.action_head_a(slot_a_repr)  # (B, num_actions)
        logits_b = self.action_head_b(slot_b_repr)  # (B, num_actions)

        # Mask illegal actions
        logits_a = logits_a.masked_fill(~batch["action_mask_a"], float("-inf"))
        logits_b = logits_b.masked_fill(~batch["action_mask_b"], float("-inf"))

        return logits_a, logits_b

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
