"""Consolidated training entry point (Phase 5 of the pipeline redesign).

Replaces ``train_v2.py``, ``train_winrate.py``, ``train_lead.py``. Reads
encoded ``.pt`` shards directly, applies row-level filters, runs an action
model with GPU-side slot-swap augmentation, logs per-epoch metrics.

Usage:
    python -m src.vgc_model.training.train --encoded data/encoded \\
        --format gen9championsvgc2026regma --version v3 --mode meta-on \\
        --min-rating 1200 --epochs 20 --num-workers 4
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import time
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

from ..data.training_dataset import TrainingDataset
from ..data.vocab import Vocabs
from ..model.action_model import ActionModel
from .gpu_slot_swap import swap_batch


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Number of distinct target slots in the action labels: -2..1 mapped to 0..3.
N_TARGETS = 4


def _shift_target(t: torch.Tensor) -> torch.Tensor:
    """Map target label range -2..1 to 0..3 for cross-entropy."""
    return (t + 2).clamp_(0, N_TARGETS - 1).long()


def _compute_loss(out: dict, batch: dict, mtl: dict[str, float]) -> tuple[torch.Tensor, dict]:
    """Cross-entropy across all 8 head outputs (4 per slot × 2 slots).

    The action_type head dominates by importance; ``mtl`` weights the others.
    """
    ce = nn.functional.cross_entropy

    type_a_loss = ce(out["type_a"], batch["action_a_type"].long())
    type_b_loss = ce(out["type_b"], batch["action_b_type"].long())

    a_is_move = batch["action_a_type"] == 1
    a_is_switch = batch["action_a_type"] == 2
    b_is_move = batch["action_b_type"] == 1
    b_is_switch = batch["action_b_type"] == 2

    def _masked_ce(logits: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        if not mask.any():
            return logits.new_zeros(())
        return ce(logits[mask], target[mask].long())

    move_a = _masked_ce(out["move_a"], batch["action_a_move_id"], a_is_move)
    move_b = _masked_ce(out["move_b"], batch["action_b_move_id"], b_is_move)
    target_a = _masked_ce(out["target_a"], _shift_target(batch["action_a_target"]), a_is_move)
    target_b = _masked_ce(out["target_b"], _shift_target(batch["action_b_target"]), b_is_move)
    switch_a = _masked_ce(out["switch_a"], batch["action_a_switch_id"], a_is_switch)
    switch_b = _masked_ce(out["switch_b"], batch["action_b_switch_id"], b_is_switch)

    total = (
        type_a_loss + type_b_loss
        + mtl["move"] * (move_a + move_b)
        + mtl["target"] * (target_a + target_b)
        + mtl["switch"] * (switch_a + switch_b)
    )
    return total, {}


def _run_epoch(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    *,
    mtl: dict[str, float],
    optimizer: Optional[torch.optim.Optimizer] = None,
    augment: bool = False,
) -> dict:
    is_train = optimizer is not None
    model.train(is_train)
    started = time.time()
    total_loss = 0.0
    total_n = 0
    type_a_hits = 0
    type_b_hits = 0
    n_batches = 0

    for batch in loader:
        batch = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
        if augment and is_train:
            batch = swap_batch(batch)

        if is_train:
            optimizer.zero_grad(set_to_none=True)
        out = model(batch)
        loss, _parts = _compute_loss(out, batch, mtl)

        if is_train:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        bs = batch["species_ids"].size(0)
        total_loss += float(loss) * bs
        total_n += bs
        type_a_hits += int((out["type_a"].argmax(-1) == batch["action_a_type"]).sum())
        type_b_hits += int((out["type_b"].argmax(-1) == batch["action_b_type"]).sum())
        n_batches += 1

    return {
        "loss": total_loss / max(total_n, 1),
        "type_a_acc": type_a_hits / max(total_n, 1),
        "type_b_acc": type_b_hits / max(total_n, 1),
        "samples": total_n,
        "batches": n_batches,
        "took_sec": round(time.time() - started, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoded", type=Path, default=PROJECT_ROOT / "data" / "encoded")
    ap.add_argument("--vocab-dir", type=Path, default=PROJECT_ROOT / "data" / "vocab")
    ap.add_argument("--checkpoint-dir", type=Path, default=PROJECT_ROOT / "data" / "checkpoints")
    ap.add_argument("--format", default="gen9championsvgc2026regma")
    ap.add_argument("--version", default="v3")
    ap.add_argument("--mode", default="meta-on", choices=["meta-on", "meta-off"])
    ap.add_argument("--min-rating", type=int, default=0)
    ap.add_argument("--since", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--until", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--weight-decay", type=float, default=1e-2)
    ap.add_argument("--num-workers", type=int, default=2)
    ap.add_argument("--no-augment", action="store_true")
    ap.add_argument("--run-id", type=str, default="")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--n-layers", type=int, default=4)
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--mtl-move", type=float, default=0.5)
    ap.add_argument("--mtl-target", type=float, default=0.3)
    ap.add_argument("--mtl-switch", type=float, default=0.5)
    ap.add_argument("--epoch-limit", type=int, default=None,
                    help="Stop training after N epochs.")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )

    device_str = args.device
    if device_str == "auto":
        if torch.cuda.is_available():
            device_str = "cuda"
        elif torch.backends.mps.is_available():
            device_str = "mps"
        else:
            device_str = "cpu"
    device = torch.device(device_str)
    print(f"machine={platform.node()} device={device}")

    vocabs = Vocabs.load(args.vocab_dir)
    print(
        f"vocabs: species={len(vocabs.species)} moves={len(vocabs.moves)} "
        f"items={len(vocabs.items)} abilities={len(vocabs.abilities)} "
        f"status={len(vocabs.status)} weather={len(vocabs.weather)} "
        f"terrain={len(vocabs.terrain)}"
    )

    dataset = TrainingDataset(
        encoded_root=args.encoded,
        fmt=args.format,
        encoding_version=args.version,
        mode=args.mode,
        min_rating=args.min_rating,
        since=args.since,
        until=args.until,
    )
    print(
        f"dataset: kept={len(dataset)} (of {dataset.total_seen}) "
        f"shards={dataset.shard_count}"
    )

    val_size = max(1, int(0.05 * len(dataset)))
    train_size = len(dataset) - val_size
    train_set, val_set = random_split(
        dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42),
    )

    train_loader = DataLoader(
        train_set, batch_size=args.batch_size, shuffle=True,
        num_workers=args.num_workers, pin_memory=device.type == "cuda",
        persistent_workers=args.num_workers > 0,
    )
    val_loader = DataLoader(
        val_set, batch_size=args.batch_size, shuffle=False,
        num_workers=args.num_workers, pin_memory=device.type == "cuda",
        persistent_workers=args.num_workers > 0,
    )

    model = ActionModel(
        n_species=len(vocabs.species), n_moves=len(vocabs.moves),
        n_items=len(vocabs.items), n_abilities=len(vocabs.abilities),
        n_status=len(vocabs.status),
        n_weather=len(vocabs.weather), n_terrain=len(vocabs.terrain),
        d_model=args.d_model, n_layers=args.n_layers,
    ).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"model params: {n_params:,}")

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.lr, weight_decay=args.weight_decay,
    )
    mtl = {"move": args.mtl_move, "target": args.mtl_target, "switch": args.mtl_switch}

    run_id = args.run_id or f"{args.version}_{args.mode}_r{args.min_rating}_{int(time.time())}"
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.checkpoint_dir / f"{run_id}.jsonl"

    best_val_loss = float("inf")
    target_epochs = args.epochs if args.epoch_limit is None else min(args.epochs, args.epoch_limit)
    for epoch in range(1, target_epochs + 1):
        train_metrics = _run_epoch(
            model, train_loader, device, mtl=mtl,
            optimizer=optimizer, augment=not args.no_augment,
        )
        with torch.no_grad():
            val_metrics = _run_epoch(model, val_loader, device, mtl=mtl)

        line = {
            "run_id": run_id, "epoch": epoch,
            "train_loss": round(train_metrics["loss"], 4),
            "val_loss": round(val_metrics["loss"], 4),
            "train_type_a_acc": round(train_metrics["type_a_acc"], 4),
            "val_type_a_acc": round(val_metrics["type_a_acc"], 4),
            "train_took_sec": train_metrics["took_sec"],
            "val_took_sec": val_metrics["took_sec"],
            "samples": train_metrics["samples"],
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(line) + "\n")
        print(json.dumps(line))

        if val_metrics["loss"] < best_val_loss:
            best_val_loss = val_metrics["loss"]
            ckpt_path = args.checkpoint_dir / f"{run_id}.best.pt"
            torch.save({
                "epoch": epoch,
                "state_dict": model.state_dict(),
                "args": vars(args),
                "val_loss": val_metrics["loss"],
            }, ckpt_path)


if __name__ == "__main__":
    main()
