"""Hybrid Lead Advisor — lookup table primary, neural model fallback.

Strategy:
  - Run the LeadLookup first.
  - If lookup hits tier1/tier2/tier3 (~89% of val), use it for both team selection
    and lead pair recommendations. Lookup top-3 lead pairs are masked to the
    top-1 brought-4 set so we never suggest a pair for a mon we're not bringing.
  - If lookup falls through ("none" tier ~11%), fall back to the trained model.
    The model masks lead_logits to its own team-head's top-4 brought prediction.
  - Output is unified: brought-4 + ranked lead pairs + provenance.

Usage:
  python -m src.vgc_model.lead.advisor \
      --own "Sneasler,Incineroar,Garchomp,Sinistcha,Kingambit,Whimsicott" \
      --opp "Floette-Mega,Charizard-Mega-Y,Pelipper,Sneasler,Aerodactyl,Whimsicott"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .constants import PAIRS_6
from .lookup import LeadLookup

if TYPE_CHECKING:
    import torch
    from .features import FeatureBuilder
    from .model import LeadAdvisorModel


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_LOOKUP = PROJECT_ROOT / "data" / "checkpoints_lead" / "lookup_train_v2.pkl"
DEFAULT_MODEL = PROJECT_ROOT / "data" / "checkpoints_lead" / "v3_masked" / "best.pt"


def load_model(ckpt_path: Path, builder: "FeatureBuilder", device: "torch.device") -> "LeadAdvisorModel":
    import torch
    from .model import LeadAdvisorModel
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    args = ckpt.get("args", {})
    model = LeadAdvisorModel(
        n_species=builder.species_size,
        n_items=builder.item_size,
        n_abilities=builder.ability_size,
        n_moves=builder.move_size,
        d_model=args.get("d_model", 128),
        n_layers=args.get("n_layers", 2),
        n_heads=args.get("n_heads", 4),
    ).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model


def _model_recommend(
    model: "LeadAdvisorModel",
    builder: "FeatureBuilder",
    own: list[str],
    opp: list[str],
    device: "torch.device",
    top_k_pairs: int,
) -> dict:
    import torch
    own_feat = builder.encode_team(own)
    opp_feat = builder.encode_team(opp)
    own_b = {k: torch.from_numpy(v[None]).to(device) for k, v in own_feat.items()}
    opp_b = {k: torch.from_numpy(v[None]).to(device) for k, v in opp_feat.items()}

    with torch.no_grad():
        # First pass: get team_top4 predictions
        out = model(own_b, opp_b)
        team_logits = out["team_logits"][0]
        team_top4 = team_logits.topk(4).indices
        # Build mask for second pass
        mask = torch.zeros(1, 6, device=device)
        mask[0, team_top4] = 1.0
        out = model(own_b, opp_b, team_mask=mask)

    team_logits = out["team_logits"][0]
    team_probs = torch.sigmoid(team_logits).cpu().tolist()
    lead_logits = out["lead_logits"][0]
    lead_probs = torch.softmax(lead_logits, dim=-1).cpu().tolist()

    brought_idx = sorted(team_top4.cpu().tolist())
    brought_species = [own[i] for i in brought_idx if i < len(own)]

    pair_ranking = sorted(
        ((PAIRS_6[i], lead_probs[i]) for i in range(15)),
        key=lambda x: -x[1],
    )
    lead_pairs = [
        {
            "pair": (own[i] if i < len(own) else "<PAD>",
                     own[j] if j < len(own) else "<PAD>"),
            "prob": round(p, 4),
        }
        for (i, j), p in pair_ranking[:top_k_pairs]
        if p > 0
    ]

    return {
        "brought": {
            "set": brought_species,
            "scores": [(own[i] if i < len(own) else "<PAD>", round(team_probs[i], 4)) for i in range(6)],
        },
        "leads": lead_pairs,
        "source": "model",
    }


def _lookup_recommend(
    lookup: LeadLookup,
    own: list[str],
    opp: list[str],
    top_k_sets: int,
    top_k_pairs: int,
) -> dict | None:
    team_rec = lookup.recommend_team(own, opp, top_k_sets=top_k_sets)
    pair_rec = lookup.recommend(own, opp, top_k=top_k_pairs * 2)  # extra for filtering

    if team_rec["tier"] == "none":
        return None

    # Top brought set drives the lead-pair mask.
    if team_rec["top_brought_sets"]:
        brought_set = set(team_rec["top_brought_sets"][0]["set"])
    else:
        brought_set = set(own[:4])

    leads = [
        {"pair": p["pair"], "prob": p["share_w"], "count": p["count"]}
        for p in pair_rec["pairs"]
        if set(p["pair"]).issubset(brought_set)
    ][:top_k_pairs]

    return {
        "brought": {
            "set": sorted(brought_set),
            "candidates": [
                {"set": list(d["set"]), "share": d["share_w"], "count": d["count"]}
                for d in team_rec["top_brought_sets"]
            ],
            "member_scores": [
                {"species": sp, "share": share}
                for sp, share, _ in team_rec.get("top_members", [])
            ],
        },
        "leads": leads,
        "source": f"lookup:{team_rec['tier']}",
        "support": {"team_n": team_rec["n"], "lead_n": pair_rec["n"]},
    }


def recommend(
    own: list[str],
    opp: list[str],
    *,
    lookup: LeadLookup | None,
    model: "LeadAdvisorModel | None",
    builder: "FeatureBuilder | None",
    device: "torch.device | None",
    top_k_sets: int = 3,
    top_k_pairs: int = 5,
) -> dict:
    """Try lookup first; fall back to model if lookup has no coverage."""
    if lookup is not None:
        rec = _lookup_recommend(lookup, own, opp, top_k_sets, top_k_pairs)
        if rec is not None and rec["leads"]:
            return rec
    if model is None or builder is None:
        return {
            "brought": {"set": own[:4], "candidates": []},
            "leads": [],
            "source": "fallback_default",
        }
    return _model_recommend(model, builder, own, opp, device, top_k_pairs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--own", required=True, help="Comma-separated 6 species (own team)")
    p.add_argument("--opp", required=True, help="Comma-separated 6 species (opp team)")
    p.add_argument("--lookup", default=str(DEFAULT_LOOKUP), type=Path)
    p.add_argument("--model", default=str(DEFAULT_MODEL), type=Path)
    p.add_argument("--top-k-sets", type=int, default=3)
    p.add_argument("--top-k-pairs", type=int, default=5)
    p.add_argument("--no-model", action="store_true",
                   help="Skip neural model fallback; only use lookup")
    p.add_argument("--device", default="cpu")
    p.add_argument("--json", action="store_true",
                   help="Emit raw JSON instead of formatted text")
    args = p.parse_args()

    own = [s.strip() for s in args.own.split(",")]
    opp = [s.strip() for s in args.opp.split(",")]
    if len(own) != 6 or len(opp) != 6:
        raise SystemExit("Need exactly 6 species for both --own and --opp")

    import torch
    from .features import FeatureBuilder
    device = torch.device(args.device)
    lookup = LeadLookup.load(args.lookup) if args.lookup.exists() else None
    builder = None
    model = None
    if not args.no_model and args.model.exists():
        builder = FeatureBuilder()
        model = load_model(args.model, builder, device)

    rec = recommend(
        own, opp,
        lookup=lookup, model=model, builder=builder, device=device,
        top_k_sets=args.top_k_sets, top_k_pairs=args.top_k_pairs,
    )

    if args.json:
        print(json.dumps(rec, indent=2))
        return

    print(f"Source: {rec['source']}")
    if "support" in rec:
        print(f"Support: team_n={rec['support']['team_n']}  lead_n={rec['support']['lead_n']}")
    print()
    print("Bring (4 of 6):")
    print("  " + " · ".join(rec["brought"]["set"]))
    if rec["brought"].get("candidates"):
        print("\n  Top alternative brought sets:")
        for c in rec["brought"]["candidates"][:args.top_k_sets]:
            mons = ", ".join(c["set"])
            print(f"   {c['share']*100:5.1f}%  ({c['count']:>4} battles)  {mons}")
    elif "member_scores" in rec["brought"]:
        print("\n  Member scores:")
        for m in rec["brought"]["member_scores"]:
            print(f"   {m['share']*100:5.1f}%  {m['species']}")
    print()
    print(f"Lead pairs (top {args.top_k_pairs}):")
    for p in rec["leads"]:
        a, b = p["pair"]
        prob = p.get("prob", 0)
        cnt = p.get("count", "")
        cnt_s = f"  ({cnt} battles)" if cnt != "" else ""
        print(f"   {prob*100:5.1f}%{cnt_s}  {a:<20} + {b}")


if __name__ == "__main__":
    main()
