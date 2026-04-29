"""Win Probability model with LSTM sequence history.

Mirrors the v2 -> v2_seq evolution that lifted the action model from
54% to 68% top-1: encodes prior turns (actions, species, HP, flags, speed)
through an LSTM and adds the final hidden state to the global token before
the transformer.

The intuition: winrate from a single turn is harder than winrate from a
trajectory. HP trends, revealed items, and prior switches encode momentum
that a stateless model can't see.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence
from dataclasses import dataclass

from ..data.vocab import Vocabs
from .winrate_model import WinrateModel, WinrateModelConfig


@dataclass
class WinrateModelSeqConfig(WinrateModelConfig):
    max_history: int = 30
    lstm_hidden: int = 64


class WinrateModelSeq(WinrateModel):
    """Win Probability model with LSTM-encoded sequence history."""

    def __init__(self, vocabs: Vocabs, config: WinrateModelSeqConfig):
        super().__init__(vocabs, config)
        self.seq_config = config

        # Per-turn history encoders (same shapes as VGCTransformerV2Seq for
        # batch compatibility — uses prev_seq_* fields populated by the dataset)
        self.seq_action_embed = nn.Embedding(config.num_actions + 1, 16)
        self.seq_species_embed = nn.Embedding(len(vocabs.species), 16)

        per_turn_input = 16 * 4 + 16 * 4 + 4 + 3 + 2  # actions + species + hp + flags + speed
        self.per_turn_proj = nn.Linear(per_turn_input, 64)
        self.history_lstm = nn.LSTM(
            input_size=64,
            hidden_size=config.lstm_hidden,
            num_layers=1,
            batch_first=True,
        )
        self.history_proj = nn.Linear(config.lstm_hidden, config.d_model)

    def _encode_history(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        """Encode variable-length history through LSTM. Returns (B, d_model)."""
        B = batch["prev_seq_actions"].shape[0]

        actions = batch["prev_seq_actions"]
        species = batch["prev_seq_species"]
        hp = batch["prev_seq_hp"]
        flags = batch["prev_seq_flags"]
        seq_len = batch["prev_seq_len"]

        action_embs = self.seq_action_embed(actions)    # (B, T, 4, 16)
        species_embs = self.seq_species_embed(species)  # (B, T, 4, 16)
        T = actions.shape[1]
        action_flat = action_embs.reshape(B, T, -1)
        species_flat = species_embs.reshape(B, T, -1)

        speed = batch.get("prev_seq_speed",
                          torch.full((B, T, 2), 0.5, device=actions.device))

        per_turn = torch.cat([action_flat, species_flat, hp, flags, speed], dim=-1)
        per_turn_proj = self.per_turn_proj(per_turn)

        lengths = seq_len.clamp(min=1).cpu()
        packed = pack_padded_sequence(
            per_turn_proj, lengths, batch_first=True, enforce_sorted=False,
        )
        _, (h_n, _) = self.history_lstm(packed)
        return self.history_proj(h_n.squeeze(0))

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        # Same encoding as parent up through the 9-token transformer input
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

        tokens = torch.cat([pokemon_repr, global_repr], dim=1)
        positions = torch.arange(9, device=tokens.device)
        tokens = tokens + self.position_embed(positions)

        alive = batch["alive_flags"]
        alive_ext = torch.cat([alive, torch.ones(alive.shape[0], 1, device=alive.device)], dim=1)
        tokens = tokens * alive_ext.unsqueeze(-1)
        src_key_padding_mask = (alive_ext == 0)

        # Inject history into global token (same gating as VGCTransformerV2Seq)
        if "prev_seq_actions" in batch:
            history_token = self._encode_history(batch)
            mask = (batch["prev_seq_len"] > 0).float().unsqueeze(-1)
            tokens[:, 8] = tokens[:, 8] + history_token * mask

        encoded = self.transformer(tokens, src_key_padding_mask=src_key_padding_mask)

        global_token = encoded[:, 8]
        win_logit = self.win_head(global_token).squeeze(-1)
        return {"win_logit": win_logit}
