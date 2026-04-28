"""Dataset for the standalone Lead Advisor model.

Parses replay logs and produces team-preview-only samples with:
  - Own team: full set encoding (species + moves + item + ability features + confidences)
  - Opponent team: species + usage-stat-inferred sets
  - Labels: which 4 selected, which 2 lead

Both players' selections are used (not winner-only) at rating >= 1400.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset

from .feature_tables import FeatureTables
from .log_parser import parse_battle, normalize_species, TeamPreview
from .enriched_parser import _pass1_extract, _base_species, CONF_KNOWN, CONF_USAGE
from .usage_stats import UsageStats


# Per-Pokemon feature dim: species(46) + 4*(move(56)+conf(1)) + item(13)+conf(1) + ability(16)+conf(1)
POKEMON_FEAT_DIM = 305


class LeadDataset(Dataset):
    """Dataset of team-preview samples for lead selection training."""

    def __init__(
        self,
        replay_dir: Path,
        feature_tables: FeatureTables,
        usage_stats: Optional[UsageStats] = None,
        min_rating: int = 1400,
        augment: bool = True,
    ):
        self.feature_tables = feature_tables
        self.usage_stats = usage_stats
        self.min_rating = min_rating
        self.augment = augment
        self.samples: list[dict] = []

        self._load_replays(replay_dir)

    def _load_replays(self, replay_dir: Path):
        """Parse all replays and extract team preview samples."""
        files = sorted(replay_dir.glob("*.json"))
        skipped = parsed = 0

        for f in files:
            if f.name == "index.json":
                continue
            try:
                data = json.loads(f.read_text(errors="replace"))
            except Exception:
                skipped += 1
                continue

            rating = data.get("rating") or 0
            if rating < self.min_rating:
                skipped += 1
                continue

            log = data.get("log", "")
            if not log:
                skipped += 1
                continue

            try:
                result = parse_battle(log, rating)
            except Exception:
                skipped += 1
                continue
            if result is None:
                skipped += 1
                continue

            tp = result.team_preview
            if not self._valid_preview(tp):
                skipped += 1
                continue

            # Extract full knowledge from the log (what was actually used)
            try:
                full_knowledge = _pass1_extract(log)
            except Exception:
                skipped += 1
                continue

            # Emit one sample per player
            for player in ("p1", "p2"):
                sample = self._build_sample(tp, player, full_knowledge, rating)
                if sample is not None:
                    self.samples.append(sample)

            parsed += 1

        print(f"LeadDataset: {parsed} replays -> {len(self.samples)} samples "
              f"(skipped {skipped})")

    @staticmethod
    def _valid_preview(tp: TeamPreview) -> bool:
        return (
            len(tp.p1_team) >= 6 and len(tp.p2_team) >= 6
            and len(tp.p1_selected) >= 4 and len(tp.p2_selected) >= 4
            and len(tp.p1_leads) >= 2 and len(tp.p2_leads) >= 2
        )

    def _build_sample(
        self, tp: TeamPreview, player: str,
        full_knowledge: dict, rating: int,
    ) -> Optional[dict]:
        """Build a single sample from one player's perspective."""
        own_team = tp.p1_team if player == "p1" else tp.p2_team
        opp_team = tp.p2_team if player == "p1" else tp.p1_team
        selected = tp.p1_selected if player == "p1" else tp.p2_selected
        leads = tp.p1_leads if player == "p1" else tp.p2_leads

        # Build own features using full log knowledge
        own_features = []
        for species in own_team[:6]:
            feat = self._encode_pokemon_known(species, player, full_knowledge)
            own_features.append(feat)

        # Build opponent features using usage stats only
        opp_features = []
        for species in opp_team[:6]:
            feat = self._encode_pokemon_usage(species)
            opp_features.append(feat)

        # Team selection labels: binary over 6 own Pokemon
        selected_set = set(selected[:4])
        team_labels = [1.0 if s in selected_set else 0.0 for s in own_team[:6]]

        # Selected indices: positions of the 4 selected within own_team
        selected_indices = []
        for s in selected[:4]:
            for i, t in enumerate(own_team[:6]):
                if t == s and i not in selected_indices:
                    selected_indices.append(i)
                    break
        if len(selected_indices) != 4:
            return None

        # Lead labels: binary over the 4 selected
        leads_set = set(leads[:2])
        selected_species = [own_team[i] for i in selected_indices]
        lead_labels = [1.0 if s in leads_set else 0.0 for s in selected_species]

        return {
            "own_features": torch.stack(own_features),           # (6, 305)
            "opp_features": torch.stack(opp_features),           # (6, 305)
            "team_select_labels": torch.tensor(team_labels),     # (6,)
            "lead_labels": torch.tensor(lead_labels),            # (4,)
            "selected_indices": torch.tensor(selected_indices, dtype=torch.long),  # (4,)
            "rating": rating,
        }

    def _encode_pokemon_known(
        self, species: str, player: str, full_knowledge: dict,
    ) -> torch.Tensor:
        """Encode a Pokemon with full log knowledge (own team)."""
        ft = self.feature_tables
        base = _base_species(species)
        key = f"{player}|{base}"
        knowledge = full_knowledge.get(key)

        # Species features
        species_feat = ft.to_tensor(ft.get_species_features(base), "species")

        # Moves: use log knowledge, fill gaps with usage stats
        known_moves = knowledge.moves if knowledge else []
        if self.usage_stats and len(known_moves) < 4:
            all_moves = self.usage_stats.infer_moveset(base, known_moves)
        else:
            all_moves = known_moves[:4]

        move_tensors = []
        for i in range(4):
            if i < len(all_moves) and all_moves[i]:
                mfeat = ft.to_tensor(ft.get_move_features(all_moves[i]), "move")
                conf = CONF_KNOWN if i < len(known_moves) else CONF_USAGE
            else:
                mfeat = torch.zeros(ft.to_tensor(ft.get_move_features(""), "move").shape)
                conf = 0.0
            move_tensors.append(torch.cat([mfeat, torch.tensor([conf])]))

        # Item
        known_item = knowledge.item if knowledge else ""
        if known_item:
            item_feat = ft.to_tensor(ft.get_item_features(known_item), "item")
            item_conf = CONF_KNOWN
        elif self.usage_stats:
            inferred = self.usage_stats.get_likely_item(base) or ""
            item_feat = ft.to_tensor(ft.get_item_features(inferred), "item")
            item_conf = CONF_USAGE if inferred else 0.0
        else:
            item_feat = ft.to_tensor(ft.get_item_features(""), "item")
            item_conf = 0.0

        # Ability
        known_ability = knowledge.ability if knowledge else ""
        if known_ability:
            ability_feat = ft.to_tensor(ft.get_ability_features(known_ability), "ability")
            ability_conf = CONF_KNOWN
        elif self.usage_stats:
            inferred = self.usage_stats.get_likely_ability(base) or ""
            ability_feat = ft.to_tensor(ft.get_ability_features(inferred), "ability")
            ability_conf = CONF_USAGE if inferred else 0.0
        else:
            ability_feat = ft.to_tensor(ft.get_ability_features(""), "ability")
            ability_conf = 0.0

        # Concat: species(46) + 4*(move(56)+1) + item(13)+1 + ability(16)+1 = 305
        return torch.cat([
            species_feat,
            *move_tensors,
            item_feat, torch.tensor([item_conf]),
            ability_feat, torch.tensor([ability_conf]),
        ])

    def _encode_pokemon_usage(self, species: str) -> torch.Tensor:
        """Encode a Pokemon with usage-stat inference only (opponent team)."""
        ft = self.feature_tables
        base = _base_species(species)

        # Species features
        species_feat = ft.to_tensor(ft.get_species_features(base), "species")

        # Moves from usage stats
        moves = self.usage_stats.get_likely_moves(base, 4) if self.usage_stats else []
        move_tensors = []
        for i in range(4):
            if i < len(moves) and moves[i]:
                mfeat = ft.to_tensor(ft.get_move_features(moves[i]), "move")
                conf = CONF_USAGE
            else:
                mfeat = torch.zeros(ft.to_tensor(ft.get_move_features(""), "move").shape)
                conf = 0.0
            move_tensors.append(torch.cat([mfeat, torch.tensor([conf])]))

        # Item from usage stats
        item_name = self.usage_stats.get_likely_item(base) if self.usage_stats else ""
        item_feat = ft.to_tensor(ft.get_item_features(item_name or ""), "item")
        item_conf = CONF_USAGE if item_name else 0.0

        # Ability from usage stats
        ability_name = self.usage_stats.get_likely_ability(base) if self.usage_stats else ""
        ability_feat = ft.to_tensor(ft.get_ability_features(ability_name or ""), "ability")
        ability_conf = CONF_USAGE if ability_name else 0.0

        return torch.cat([
            species_feat,
            *move_tensors,
            item_feat, torch.tensor([item_conf]),
            ability_feat, torch.tensor([ability_conf]),
        ])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        sample = self.samples[idx]

        if not self.augment:
            return {
                "own_features": sample["own_features"],
                "opp_features": sample["opp_features"],
                "team_select_labels": sample["team_select_labels"],
                "lead_labels": sample["lead_labels"],
                "selected_indices": sample["selected_indices"],
            }

        # Augment: shuffle order of own team and opponent team
        own_feat = sample["own_features"].clone()       # (6, 305)
        opp_feat = sample["opp_features"].clone()       # (6, 305)
        team_labels = sample["team_select_labels"].clone()  # (6,)
        sel_idx = sample["selected_indices"].clone()     # (4,)
        lead_labels = sample["lead_labels"].clone()      # (4,)

        # Shuffle own team order
        own_perm = torch.randperm(6)
        own_feat = own_feat[own_perm]
        team_labels = team_labels[own_perm]
        # Remap selected_indices through the permutation
        inv_perm = torch.zeros(6, dtype=torch.long)
        for new_pos, old_pos in enumerate(own_perm):
            inv_perm[old_pos] = new_pos
        sel_idx = inv_perm[sel_idx]

        # Shuffle opponent team order
        opp_perm = torch.randperm(6)
        opp_feat = opp_feat[opp_perm]

        return {
            "own_features": own_feat,
            "opp_features": opp_feat,
            "team_select_labels": team_labels,
            "lead_labels": lead_labels,
            "selected_indices": sel_idx,
        }
