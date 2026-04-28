"""CLI tool for Lead Advisor inference.

Usage:
    python -m src.vgc_model.lead_advisor \
      --own "Incineroar,Whimsicott,Palafin,Dragapult,Tyranitar,Excadrill" \
      --opp "Talonflame,Garchomp,Sylveon,Kangaskhan,Aegislash,Rotom-Wash"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

from .data.feature_tables import FeatureTables
from .data.usage_stats import UsageStats
from .data.enriched_parser import CONF_USAGE, CONF_KNOWN, _base_species
from .model.lead_model import LeadAdvisorModel, LeadModelConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHECKPOINT_PATH = DATA_DIR / "checkpoints_lead" / "best.pt"


def _encode_pokemon(species: str, ft: FeatureTables, us: UsageStats,
                    confidence: float = CONF_USAGE) -> torch.Tensor:
    """Encode one Pokemon using feature tables + usage stats."""
    base = _base_species(species)
    species_feat = ft.to_tensor(ft.get_species_features(base), "species")

    moves = us.get_likely_moves(base, 4) if us else []
    move_tensors = []
    for i in range(4):
        if i < len(moves) and moves[i]:
            mfeat = ft.to_tensor(ft.get_move_features(moves[i]), "move")
        else:
            mfeat = torch.zeros(ft.to_tensor(ft.get_move_features(""), "move").shape)
        conf = confidence if (i < len(moves) and moves[i]) else 0.0
        move_tensors.append(torch.cat([mfeat, torch.tensor([conf])]))

    item = us.get_likely_item(base) if us else ""
    item_feat = ft.to_tensor(ft.get_item_features(item or ""), "item")
    item_conf = confidence if item else 0.0

    ability = us.get_likely_ability(base) if us else ""
    ability_feat = ft.to_tensor(ft.get_ability_features(ability or ""), "ability")
    ability_conf = confidence if ability else 0.0

    return torch.cat([
        species_feat,
        *move_tensors,
        item_feat, torch.tensor([item_conf]),
        ability_feat, torch.tensor([ability_conf]),
    ])


def advise(own_species: list[str], opp_species: list[str],
           checkpoint_path: Path = CHECKPOINT_PATH):
    """Run lead advisor and print recommendations."""
    if len(own_species) != 6:
        print(f"ERROR: Need exactly 6 own Pokemon, got {len(own_species)}")
        return
    if len(opp_species) != 6:
        print(f"ERROR: Need exactly 6 opponent Pokemon, got {len(opp_species)}")
        return

    # Load resources
    ft = FeatureTables()
    try:
        us = UsageStats()
    except Exception:
        us = None
        print("Warning: usage stats not available, encoding with zeros")

    if not checkpoint_path.exists():
        print(f"ERROR: No checkpoint at {checkpoint_path}")
        return

    # Load model
    device = torch.device("cpu")
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    config = ckpt.get("config", LeadModelConfig())
    model = LeadAdvisorModel(config).to(device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    # Encode teams
    own_features = torch.stack([
        _encode_pokemon(s, ft, us, CONF_KNOWN) for s in own_species
    ]).unsqueeze(0)  # (1, 6, 305)

    opp_features = torch.stack([
        _encode_pokemon(s, ft, us, CONF_USAGE) for s in opp_species
    ]).unsqueeze(0)  # (1, 6, 305)

    # Inference (no selected_indices -> uses top-4 from team_logits)
    with torch.no_grad():
        out = model({"own_features": own_features, "opp_features": opp_features})

    team_logits = out["team_logits"][0]   # (6,)
    lead_logits = out["lead_logits"][0]   # (4,)

    team_probs = torch.sigmoid(team_logits)
    lead_probs = torch.sigmoid(lead_logits)

    # Team selection: top 4
    team_ranked = sorted(range(6), key=lambda i: team_probs[i].item(), reverse=True)
    bring = team_ranked[:4]
    leave = team_ranked[4:]

    # Lead selection: top 2 from the selected 4
    # Map lead_logits back to the selected-4 indices
    sel_indices = team_logits.topk(4).indices.tolist()
    lead_ranked = sorted(range(4), key=lambda i: lead_probs[i].item(), reverse=True)
    lead_picks = [sel_indices[i] for i in lead_ranked[:2]]
    back_picks = [sel_indices[i] for i in lead_ranked[2:]]

    # Print
    print()
    print("=== Lead Advisor ===")
    print(f"Your team:  {', '.join(own_species)}")
    print(f"Opponent:   {', '.join(opp_species)}")
    print()
    print(f"Bring (4):  {', '.join(f'{own_species[i]} ({team_probs[i]:.0%})' for i in bring)}")
    print(f"Leave back: {', '.join(f'{own_species[i]} ({team_probs[i]:.0%})' for i in leave)}")
    print()
    print(f"Lead (2):   {', '.join(f'{own_species[lead_picks[i]]} ({lead_probs[lead_ranked[i]]:.0%})' for i in range(2))}")
    print(f"Back (2):   {', '.join(f'{own_species[back_picks[i]]} ({lead_probs[lead_ranked[2+i]]:.0%})' for i in range(2))}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Lead Advisor — VGC team/lead selection")
    parser.add_argument("--own", type=str, required=True,
                        help="Comma-separated list of 6 own Pokemon species")
    parser.add_argument("--opp", type=str, required=True,
                        help="Comma-separated list of 6 opponent Pokemon species")
    parser.add_argument("--checkpoint", type=str, default=str(CHECKPOINT_PATH))
    args = parser.parse_args()

    own = [s.strip() for s in args.own.split(",")]
    opp = [s.strip() for s in args.opp.split(",")]

    advise(own, opp, Path(args.checkpoint))


if __name__ == "__main__":
    main()
