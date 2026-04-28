"""Dataset for the Win Probability model.

Wraps EnrichedDataset with winner_only=False and adds binary win labels.
Every turn from both players' perspectives becomes a sample.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset

from .enriched_dataset import EnrichedDataset
from .feature_tables import FeatureTables
from .usage_stats import UsageStats
from .player_profiles import PlayerProfiles
from .vocab import Vocabs


class WinrateDataset(Dataset):
    """Wraps EnrichedDataset to produce (state, win_label) pairs."""

    def __init__(
        self,
        replay_dir: Path,
        vocabs: Vocabs,
        feature_tables: FeatureTables,
        usage_stats: Optional[UsageStats] = None,
        player_profiles: Optional[PlayerProfiles] = None,
        min_rating: int = 1200,
        min_turns: int = 3,
        history_mode: str = "single",
    ):
        # Build the enriched dataset with BOTH players (not winner-only)
        self._inner = EnrichedDataset(
            replay_dir=replay_dir,
            vocabs=vocabs,
            feature_tables=feature_tables,
            usage_stats=usage_stats,
            player_profiles=player_profiles,
            min_rating=min_rating,
            winner_only=False,   # Both players — this is the key difference
            min_turns=min_turns,
            history_mode=history_mode,
            augment=True,
        )

        # Only use battle-turn samples, not team preview samples
        self._num_battle_samples = len(self._inner.samples)

        # Extract win labels from the stored samples
        self._win_labels = []
        for sample, tp, prev_own, prev_opp in self._inner.samples:
            self._win_labels.append(1.0 if sample.is_winner else 0.0)

        print(f"WinrateDataset: {self._num_battle_samples} battle samples "
              f"({sum(self._win_labels):.0f} wins, "
              f"{self._num_battle_samples - sum(self._win_labels):.0f} losses)")

    def __len__(self) -> int:
        return self._num_battle_samples

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        # Get the encoded sample from the inner dataset
        # (this calls _encode_sample + augmentation)
        tensors = self._inner[idx]

        # Add win label
        tensors["win_label"] = torch.tensor(self._win_labels[idx], dtype=torch.float)

        return tensors
