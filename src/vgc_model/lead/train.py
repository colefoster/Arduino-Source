"""Train the Lead Advisor model.

Usage (locally for smoke):
  python -m src.vgc_model.lead.train --parsed-dir data/parsed/gen9championsvgc2026regma \
      --epochs 1 --batch-size 64 --device cpu

Usage (unraid GPU container):
  python -m src.vgc_model.lead.train --parsed-dir /workspace/data/parsed/gen9championsvgc2026regma \
      --epochs 30 --batch-size 256 --device cuda --min-rating 1500

Train/val split is time-based: latest 2 days of buckets are held out as val.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from .dataset import LeadSample, collate, iter_samples_from_parquet
from .features import FeatureBuilder
from .model import PAIRS_6, LeadAdvisorModel, lead_pair_to_index, num_params


# ---------------------------------------------------------------------------
# Data plumbing
# ---------------------------------------------------------------------------

def list_shards(parsed_dir: Path, val_days: int) -> tuple[list[Path], list[Path]]:
    """Time-based split: last `val_days` calendar dirs go to val."""
    day_dirs = sorted([p for p in parsed_dir.iterdir() if p.is_dir()])
    if len(day_dirs) <= val_days:
        raise SystemExit(f"Not enough day buckets in {parsed_dir} (need > {val_days})")
    train_days = day_dirs[:-val_days]
    val_days_dirs = day_dirs[-val_days:]
    train = [p for d in train_days for p in sorted(d.glob("*.parquet"))]
    val = [p for d in val_days_dirs for p in sorted(d.glob("*.parquet"))]
    return train, val


def stream_batches(
    shards: list[Path],
    builder: FeatureBuilder,
    *,
    batch_size: int,
    min_rating: int,
    loser_weight: float,
    shuffle: bool = True,
    seed: int = 0,
    require_full_brought: bool = False,
) -> Iterable[dict]:
    """Yield batched numpy dicts. Loads one shard at a time, shuffles within shard."""
    rng = np.random.default_rng(seed)
    order = list(range(len(shards)))
    if shuffle:
        rng.shuffle(order)

    buf: list[LeadSample] = []
    for idx in order:
        shard = shards[idx]
        samples = list(iter_samples_from_parquet(
            shard, min_rating=min_rating, loser_weight=loser_weight,
            require_full_brought=require_full_brought,
        ))
        if shuffle:
            rng.shuffle(samples)
        buf.extend(samples)
        while len(buf) >= batch_size:
            chunk = buf[:batch_size]
            buf = buf[batch_size:]
            yield collate(chunk, builder)
    if buf:
        yield collate(buf, builder)


def to_torch_batch(np_batch: dict, device: torch.device) -> tuple[dict, dict, dict]:
    own = {}
    opp = {}
    extras = {}
    for k, v in np_batch.items():
        t = torch.from_numpy(v).to(device, non_blocking=True)
        if k.startswith("own_"):
            own[k[len("own_"):]] = t
        elif k.startswith("opp_"):
            opp[k[len("opp_"):]] = t
        else:
            extras[k] = t
    return own, opp, extras


# ---------------------------------------------------------------------------
# Loss
# ---------------------------------------------------------------------------

def lead_target_index(lead_index: torch.Tensor) -> torch.Tensor:
    """[B, 2] -> [B] index over PAIRS_6 (15)."""
    pair_lookup = {p: i for i, p in enumerate(PAIRS_6)}
    out = torch.zeros(lead_index.shape[0], dtype=torch.long, device=lead_index.device)
    li = lead_index.cpu().numpy()
    for b, (a, c) in enumerate(li):
        a, c = sorted((int(a), int(c)))
        out[b] = pair_lookup[(a, c)]
    return out


def compute_loss(
    output: dict[str, torch.Tensor],
    extras: dict[str, torch.Tensor],
    *,
    team_weight: float = 1.0,
    lead_weight: float = 1.0,
) -> tuple[torch.Tensor, dict]:
    weight = extras["weight"]                       # [B]
    team_label = extras["team_label"]               # [B, 6]
    lead_idx_2d = extras["lead_index"].long()       # [B, 2]

    # Team head: weighted BCE per element, mean over batch+slots
    bce = F.binary_cross_entropy_with_logits(
        output["team_logits"], team_label, reduction="none"
    )                                                # [B, 6]
    team_loss = (bce.mean(dim=1) * weight).sum() / weight.sum().clamp(min=1e-6)

    # Lead head: weighted CE over 15 pair classes
    target_pair_idx = lead_target_index(lead_idx_2d)
    ce = F.cross_entropy(output["lead_logits"], target_pair_idx, reduction="none")  # [B]
    lead_loss = (ce * weight).sum() / weight.sum().clamp(min=1e-6)

    loss = team_weight * team_loss + lead_weight * lead_loss

    with torch.no_grad():
        # Top-K pair accuracy (unweighted, for interpretability)
        ranked = output["lead_logits"].argsort(dim=-1, descending=True)
        top1 = (ranked[:, 0] == target_pair_idx).float().mean().item()
        top3 = (ranked[:, :3] == target_pair_idx[:, None]).any(dim=-1).float().mean().item()
        top5 = (ranked[:, :5] == target_pair_idx[:, None]).any(dim=-1).float().mean().item()
        # Team head: top-4 by logit, fraction-of-true-positives
        team_top4 = output["team_logits"].topk(4, dim=-1).indices  # [B, 4]
        gathered = team_label.gather(1, team_top4)                  # [B, 4]
        team_acc = gathered.mean().item()

    return loss, {
        "team_loss": team_loss.item(),
        "lead_loss": lead_loss.item(),
        "lead_top1": top1,
        "lead_top3": top3,
        "lead_top5": top5,
        "team_top4_recall": team_acc,
    }


# ---------------------------------------------------------------------------
# Train / eval loops
# ---------------------------------------------------------------------------

def evaluate(
    model: LeadAdvisorModel,
    builder: FeatureBuilder,
    val_shards: list[Path],
    *,
    batch_size: int,
    min_rating: int,
    device: torch.device,
    mask_to_brought: bool = False,
    require_full_brought: bool = False,
) -> dict:
    model.eval()
    agg = {"n": 0, "team_loss": 0.0, "lead_loss": 0.0,
           "lead_top1": 0.0, "lead_top3": 0.0, "lead_top5": 0.0, "team_top4_recall": 0.0}
    with torch.no_grad():
        for nb in stream_batches(val_shards, builder, batch_size=batch_size,
                                 min_rating=min_rating, loser_weight=0.5, shuffle=False,
                                 require_full_brought=require_full_brought):
            own, opp, extras = to_torch_batch(nb, device)
            mask = extras["team_label"] if mask_to_brought else None
            out = model(own, opp, team_mask=mask)
            _, m = compute_loss(out, extras)
            B = nb["weight"].shape[0]
            for k in m:
                agg[k] += m[k] * B
            agg["n"] += B
    if agg["n"] == 0:
        return {k: float("nan") for k in agg if k != "n"}
    return {k: agg[k] / agg["n"] for k in agg if k != "n"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parsed-dir", required=True, type=Path)
    p.add_argument("--out-dir", default=Path("data/checkpoints_lead"), type=Path)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--d-model", type=int, default=128)
    p.add_argument("--n-layers", type=int, default=2)
    p.add_argument("--n-heads", type=int, default=4)
    p.add_argument("--dropout", type=float, default=0.0)
    p.add_argument("--mask-to-brought", action="store_true",
                   help="Mask lead-pair softmax to pairs within the brought-4 (matches v1 task)")
    p.add_argument("--require-full-brought", action="store_true",
                   help="Drop samples where fewer than 4 own-mons went active (label cleanup)")
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--wd", type=float, default=1e-4)
    p.add_argument("--min-rating", type=int, default=1500)
    p.add_argument("--loser-weight", type=float, default=0.5)
    p.add_argument("--team-weight", type=float, default=1.0)
    p.add_argument("--lead-weight", type=float, default=1.0)
    p.add_argument("--val-days", type=int, default=2,
                   help="Most-recent N day-buckets used as val")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-train-shards", type=int, default=None,
                   help="Cap shards per epoch (smoke testing)")
    args = p.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device = torch.device(args.device)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    builder = FeatureBuilder()
    train_shards, val_shards = list_shards(args.parsed_dir, args.val_days)
    if args.max_train_shards:
        train_shards = train_shards[: args.max_train_shards]
    print(f"train shards: {len(train_shards)}  val shards: {len(val_shards)}")

    model = LeadAdvisorModel(
        n_species=builder.species_size,
        n_items=builder.item_size,
        n_abilities=builder.ability_size,
        n_moves=builder.move_size,
        d_model=args.d_model,
        n_layers=args.n_layers,
        n_heads=args.n_heads,
        dropout=args.dropout,
    ).to(device)
    print(f"params: {num_params(model):,}")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    best_top1 = -1.0
    best_path = args.out_dir / "best.pt"
    log_path = args.out_dir / "train_log.jsonl"

    for epoch in range(1, args.epochs + 1):
        model.train()
        t0 = time.time()
        agg = {"n": 0, "loss": 0.0, "team_loss": 0.0, "lead_loss": 0.0,
               "lead_top1": 0.0, "lead_top3": 0.0, "team_top4_recall": 0.0}
        for nb in stream_batches(
            train_shards, builder,
            batch_size=args.batch_size,
            min_rating=args.min_rating,
            loser_weight=args.loser_weight,
            shuffle=True,
            seed=args.seed + epoch,
            require_full_brought=args.require_full_brought,
        ):
            own, opp, extras = to_torch_batch(nb, device)
            mask = extras["team_label"] if args.mask_to_brought else None
            out = model(own, opp, team_mask=mask)
            loss, m = compute_loss(out, extras,
                                   team_weight=args.team_weight,
                                   lead_weight=args.lead_weight)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            B = nb["weight"].shape[0]
            agg["n"] += B
            agg["loss"] += loss.item() * B
            for k in ("team_loss", "lead_loss", "lead_top1", "lead_top3", "team_top4_recall"):
                agg[k] += m[k] * B
        sched.step()

        train_metrics = {k: agg[k] / max(agg["n"], 1) for k in agg if k != "n"}
        val_metrics = evaluate(model, builder, val_shards,
                               batch_size=args.batch_size,
                               min_rating=args.min_rating,
                               device=device,
                               mask_to_brought=args.mask_to_brought,
                               require_full_brought=args.require_full_brought)
        elapsed = time.time() - t0

        log = {
            "epoch": epoch,
            "lr": opt.param_groups[0]["lr"],
            "elapsed_sec": round(elapsed, 1),
            "train": {k: round(v, 4) for k, v in train_metrics.items()},
            "val": {k: round(v, 4) for k, v in val_metrics.items()},
            "n_train": agg["n"],
        }
        print(json.dumps(log))
        with open(log_path, "a") as f:
            f.write(json.dumps(log) + "\n")

        if val_metrics["lead_top1"] > best_top1:
            best_top1 = val_metrics["lead_top1"]
            torch.save({
                "epoch": epoch,
                "model_state": model.state_dict(),
                "args": vars(args) | {"parsed_dir": str(args.parsed_dir),
                                       "out_dir": str(args.out_dir)},
                "val": val_metrics,
            }, best_path)
            print(f"  -> saved best (lead_top1={best_top1:.4f})")


if __name__ == "__main__":
    main()
