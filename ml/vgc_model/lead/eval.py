"""Evaluate the Lead Advisor checkpoint and a few baselines on a held-out split.

Baselines:
  smogon-modal — pick the most-frequent lead pair across all training-corpus replays
                 of teams that share K species with the own team (cheap k-NN).
  random       — uniform over 15 pairs (sanity floor).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from .dataset import iter_samples_from_dir, iter_samples_from_parquet
from .features import FeatureBuilder
from .lookup import LeadLookup
from .model import PAIRS_6, LeadAdvisorModel, lead_pair_to_index


def _val_samples(parsed_dir: Path, val_days: int, min_rating: int):
    """Yield samples ONLY from the last `val_days` calendar dirs."""
    day_dirs = sorted([p for p in parsed_dir.iterdir() if p.is_dir()])
    val_dirs = day_dirs[-val_days:] if val_days > 0 else day_dirs
    for d in val_dirs:
        for shard in sorted(d.glob("*.parquet")):
            yield from iter_samples_from_parquet(shard, min_rating=min_rating)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CKPT = PROJECT_ROOT / "data" / "checkpoints_lead" / "v2_smogon" / "best.pt"


def topk_correct(logits: np.ndarray, target: int, k: int) -> bool:
    topk = np.argsort(-logits)[:k]
    return target in topk


def evaluate_model(
    ckpt_path: Path, parsed_dir: Path, *, min_rating: int, max_samples: int | None,
    val_days: int = 2, mask_to_brought: bool = True,
) -> dict:
    builder = FeatureBuilder()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
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

    n = 0
    hits = {1: 0, 3: 0, 5: 0}
    team_top4_hits = 0.0
    rating_buckets: dict[str, dict] = {}

    samples = _val_samples(parsed_dir, val_days, min_rating=min_rating)
    with torch.no_grad():
        for s in samples:
            from .dataset import collate
            np_batch = collate([s], builder)
            own = {k.replace("own_", ""): torch.from_numpy(v).to(device)
                   for k, v in np_batch.items() if k.startswith("own_")}
            opp = {k.replace("opp_", ""): torch.from_numpy(v).to(device)
                   for k, v in np_batch.items() if k.startswith("opp_")}
            mask = torch.from_numpy(np_batch["team_label"]).to(device) if mask_to_brought else None
            out = model(own, opp, team_mask=mask)
            lead_logits = out["lead_logits"][0].cpu().numpy()
            ia, ib = np_batch["lead_index"][0]
            target = lead_pair_to_index(int(ia), int(ib))
            for k in (1, 3, 5):
                if topk_correct(lead_logits, target, k):
                    hits[k] += 1

            team_logits = out["team_logits"][0].cpu().numpy()
            top4 = np.argsort(-team_logits)[:4]
            team_label = np_batch["team_label"][0]
            team_top4_hits += float(team_label[top4].mean())

            bucket = "1500" if s.rating < 1630 else ("1630" if s.rating < 1760 else "1760+")
            b = rating_buckets.setdefault(bucket, {"n": 0, "h1": 0, "h3": 0})
            b["n"] += 1
            if topk_correct(lead_logits, target, 1):
                b["h1"] += 1
            if topk_correct(lead_logits, target, 3):
                b["h3"] += 1

            n += 1
            if max_samples and n >= max_samples:
                break

    if n == 0:
        return {"n": 0}

    return {
        "n": n,
        "lead_top1": hits[1] / n,
        "lead_top3": hits[3] / n,
        "lead_top5": hits[5] / n,
        "team_top4_recall": team_top4_hits / n,
        "by_rating": {
            k: {"n": v["n"], "top1": v["h1"] / v["n"], "top3": v["h3"] / v["n"]}
            for k, v in rating_buckets.items()
        },
    }


def evaluate_hybrid(
    lookup_path: Path,
    ckpt_path: Path,
    parsed_dir: Path,
    *,
    min_rating: int,
    max_samples: int | None,
    val_days: int = 2,
) -> dict:
    """End-to-end hybrid: lookup primary, model fallback for 'none' tier.

    Reports unified top-K lead acc + team_top4_recall, and how often each
    fallback fired.
    """
    from .advisor import _lookup_recommend, _model_recommend, load_model
    from .features import FeatureBuilder

    lookup = LeadLookup.load(lookup_path)
    builder = FeatureBuilder()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(ckpt_path, builder, device)

    samples = list(_val_samples(parsed_dir, val_days, min_rating=min_rating))
    if max_samples:
        samples = samples[:max_samples]

    n = 0
    src_count = {"lookup": 0, "model": 0}
    lead_hits = {1: 0, 3: 0, 5: 0}
    team_top4_recall_sum = 0.0
    team_n = 0

    for s in samples:
        n += 1
        rec = _lookup_recommend(lookup, s.own_team, s.opp_team, top_k_sets=3, top_k_pairs=5)
        if rec is None or not rec["leads"]:
            rec = _model_recommend(model, builder, s.own_team, s.opp_team, device, top_k_pairs=5)
            src_count["model"] += 1
        else:
            src_count["lookup"] += 1

        truth_pair = tuple(sorted(s.own_leads))
        ranked_pairs = [tuple(sorted(p["pair"])) for p in rec["leads"]]
        for k in (1, 3, 5):
            if truth_pair in ranked_pairs[:k]:
                lead_hits[k] += 1

        if len(s.own_brought) == 4:
            truth_set = set(s.own_brought)
            brought = set(rec["brought"]["set"])
            recall = len(truth_set & brought) / 4
            team_top4_recall_sum += recall
            team_n += 1

    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "source_share": {k: round(v / n, 4) for k, v in src_count.items()},
        "lead_top1": lead_hits[1] / n,
        "lead_top3": lead_hits[3] / n,
        "lead_top5": lead_hits[5] / n,
        "team_top4_recall": team_top4_recall_sum / team_n if team_n else 0.0,
        "team_n_with_full_brought": team_n,
    }


def evaluate_smogon_modal(parsed_dir: Path, *, min_rating: int, max_samples: int | None, val_days: int = 2) -> dict:
    """Cheap k-NN baseline: predict the modal lead-pair (by team-sheet slot indices)
    across all samples whose own-team Jaccard overlap is >= 5/6 with the query.
    """
    builder = FeatureBuilder()
    samples = list(iter_samples_from_dir(parsed_dir, min_rating=min_rating))
    if max_samples:
        samples = samples[: max_samples * 2]

    pair_count_global: Counter = Counter()
    for s in samples:
        ia, ib = s.lead_index_in_team6()
        if ia >= 0 and ib >= 0:
            pair_count_global[lead_pair_to_index(ia, ib)] += 1
    modal_global = pair_count_global.most_common(1)[0][0] if pair_count_global else 0

    hits = {1: 0, 3: 0, 5: 0}
    n = 0
    for s in samples:
        ia, ib = s.lead_index_in_team6()
        if ia < 0 or ib < 0:
            continue
        target = lead_pair_to_index(ia, ib)

        # Match other samples that share >= 5 of own_team species
        own_set = set(s.own_team)
        local: Counter = Counter()
        for s2 in samples:
            if s2 is s:
                continue
            overlap = len(own_set & set(s2.own_team))
            if overlap >= 5:
                ia2, ib2 = s2.lead_index_in_team6()
                if ia2 >= 0 and ib2 >= 0:
                    local[lead_pair_to_index(ia2, ib2)] += 1

        if local:
            ranked = [p for p, _ in local.most_common()]
        else:
            ranked = [modal_global]
        for k in (1, 3, 5):
            if target in ranked[:k]:
                hits[k] += 1
        n += 1
        if max_samples and n >= max_samples:
            break

    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "lead_top1": hits[1] / n,
        "lead_top3": hits[3] / n,
        "lead_top5": hits[5] / n,
    }


def evaluate_lookup(
    lookup_path: Path, parsed_dir: Path, *, min_rating: int, max_samples: int | None,
    val_days: int = 2,
) -> dict:
    """Evaluate the LeadLookup table on parsed_dir as val.

    Scores both lead pair (top-K) AND team selection:
      - team_set_top1/3: did the modal brought-set match truth?
      - team_top4_recall: of the top-4 ranked individual mons, fraction brought.
    """
    lookup = LeadLookup.load(lookup_path)
    samples = list(_val_samples(parsed_dir, val_days, min_rating=min_rating))
    if max_samples:
        samples = samples[:max_samples]

    lead_overall = {1: 0, 3: 0, 5: 0}
    team_set_top = {1: 0, 3: 0}
    team_top4_recall_sum = 0.0
    team_n = 0
    n = 0
    by_tier: dict[str, dict] = {}

    for s in samples:
        n += 1
        # Lead recommendation
        rec = lookup.recommend(s.own_team, s.opp_team)
        tier = rec["tier"]
        ranked_pairs = [tuple(sorted(p["pair"])) for p in rec["pairs"]]
        truth_pair = tuple(sorted(s.own_leads))

        b = by_tier.setdefault(tier, {"n": 0, 1: 0, 3: 0, 5: 0,
                                       "team_set1": 0, "team_set3": 0,
                                       "team_top4_sum": 0.0, "team_n": 0})
        b["n"] += 1
        for k in (1, 3, 5):
            if truth_pair in ranked_pairs[:k]:
                lead_overall[k] += 1
                b[k] += 1

        # Team-selection — only when ground truth has full brought-4
        if len(s.own_brought) == 4:
            truth_set = frozenset(s.own_brought)
            trec = lookup.recommend_team(s.own_team, s.opp_team)
            top_sets = [frozenset(d["set"]) for d in trec["top_brought_sets"]]
            for k in (1, 3):
                if truth_set in top_sets[:k]:
                    team_set_top[k] += 1
                    b[f"team_set{k}"] += 1
            # Top-4 by per-member share, restricted to own_team slots
            top4_members = [sp for sp, _, _ in trec["top_members"][:4]]
            recall = sum(1 for sp in top4_members if sp in truth_set) / 4
            team_top4_recall_sum += recall
            b["team_top4_sum"] += recall
            team_n += 1
            b["team_n"] += 1

    if n == 0:
        return {"n": 0}
    out = {
        "n": n,
        "lead_top1": lead_overall[1] / n,
        "lead_top3": lead_overall[3] / n,
        "lead_top5": lead_overall[5] / n,
        "team_n_with_full_brought": team_n,
        "team_set_top1": team_set_top[1] / team_n if team_n else 0.0,
        "team_set_top3": team_set_top[3] / team_n if team_n else 0.0,
        "team_top4_recall": team_top4_recall_sum / team_n if team_n else 0.0,
        "by_tier": {
            tier: {
                "n": b["n"],
                "share": round(b["n"] / n, 4),
                "lead_top1": round(b[1] / b["n"], 4) if b["n"] else 0.0,
                "lead_top3": round(b[3] / b["n"], 4) if b["n"] else 0.0,
                "lead_top5": round(b[5] / b["n"], 4) if b["n"] else 0.0,
                "team_set_top1": round(b["team_set1"] / b["team_n"], 4) if b["team_n"] else 0.0,
                "team_set_top3": round(b["team_set3"] / b["team_n"], 4) if b["team_n"] else 0.0,
                "team_top4_recall": round(b["team_top4_sum"] / b["team_n"], 4) if b["team_n"] else 0.0,
            }
            for tier, b in by_tier.items()
        },
    }
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default=str(DEFAULT_CKPT), type=Path)
    p.add_argument("--parsed-dir", required=True, type=Path)
    p.add_argument("--lookup-path", default=None, type=Path,
                   help="Path to LeadLookup.pkl produced by lookup.py")
    p.add_argument("--min-rating", type=int, default=1500)
    p.add_argument("--max-samples", type=int, default=None)
    p.add_argument("--baseline-only", action="store_true")
    p.add_argument("--model-only", action="store_true")
    p.add_argument("--lookup-only", action="store_true")
    p.add_argument("--hybrid", action="store_true",
                   help="Score the lookup-primary + model-fallback pipeline end-to-end")
    p.add_argument("--val-days", type=int, default=2)
    p.add_argument("--mask-to-brought", action="store_true",
                   help="Mask model lead_logits to brought-4 (matches training)")
    args = p.parse_args()

    out = {}
    if args.hybrid and args.lookup_path is not None:
        out["hybrid"] = evaluate_hybrid(
            args.lookup_path, args.ckpt, args.parsed_dir,
            min_rating=args.min_rating, max_samples=args.max_samples,
            val_days=args.val_days,
        )
    if not args.hybrid and not args.lookup_only and not args.baseline_only:
        out["model"] = evaluate_model(
            args.ckpt, args.parsed_dir,
            min_rating=args.min_rating, max_samples=args.max_samples,
            val_days=args.val_days, mask_to_brought=args.mask_to_brought,
        )
    if args.lookup_path is not None:
        out["lookup"] = evaluate_lookup(
            args.lookup_path, args.parsed_dir,
            min_rating=args.min_rating, max_samples=args.max_samples,
            val_days=args.val_days,
        )
    if not args.model_only and not args.lookup_only and args.lookup_path is None:
        out["smogon_modal"] = evaluate_smogon_modal(
            args.parsed_dir,
            min_rating=args.min_rating, max_samples=args.max_samples,
            val_days=args.val_days,
        )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
