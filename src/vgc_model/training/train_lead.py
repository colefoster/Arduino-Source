"""Training loop for the standalone Lead Advisor model."""

from __future__ import annotations

import argparse
import json
import platform
import time
import urllib.request
import urllib.error
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

from ..data.lead_dataset import LeadDataset
from ..data.feature_tables import FeatureTables
from ..data.usage_stats import UsageStats
from ..model.lead_model import LeadAdvisorModel, LeadModelConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHECKPOINT_DIR = DATA_DIR / "checkpoints_lead"

REPLAY_SEARCH_DIRS = [
    DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma",
    DATA_DIR / "spectated",
    DATA_DIR / "downloaded",
]


def _find_replay_dir() -> Path:
    for d in REPLAY_SEARCH_DIRS:
        if d.exists() and any(d.glob("*.json")):
            return d
    return REPLAY_SEARCH_DIRS[0]


def _report_to_dashboard(url: str, payload: dict):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/api/training/report",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "vgc-trainer/1.0"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def train(
    epochs: int = 100,
    batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-2,
    min_rating: int = 1400,
    device_str: str = "auto",
    patience: int = 15,
    run_id: str = "",
    replay_dir: str = "",
    dashboard_url: str = "",
    dropout: float = 0.2,
):
    machine_name = platform.node() or "unknown"

    if device_str == "auto":
        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        device = torch.device(device_str)
    print(f"Device: {device}")

    # Load feature tables and usage stats
    print("Loading feature tables...")
    feature_tables = FeatureTables()

    usage_stats = None
    try:
        usage_stats = UsageStats()
        print(f"Loaded usage stats: {len(usage_stats.species_list)} species")
    except Exception as e:
        print(f"Usage stats not available: {e}")

    # Find replay directory
    rdir = Path(replay_dir) if replay_dir else _find_replay_dir()
    print(f"Replay directory: {rdir}")

    # Load dataset
    print(f"Loading lead dataset (min_rating={min_rating})...")
    dataset = LeadDataset(
        replay_dir=rdir,
        feature_tables=feature_tables,
        usage_stats=usage_stats,
        min_rating=min_rating,
        augment=True,
    )

    if len(dataset) == 0:
        print("ERROR: No samples loaded.")
        return

    # Train/val split (90/10)
    val_size = max(1, len(dataset) // 10)
    train_size = len(dataset) - val_size
    train_dataset, val_dataset = random_split(
        dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42),
    )
    print(f"Train: {len(train_dataset)}, Val: {len(val_dataset)}")

    train_loader = DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True,
        num_workers=0, pin_memory=(device.type != "cpu"),
    )
    val_loader = DataLoader(
        val_dataset, batch_size=batch_size, shuffle=False,
        num_workers=0, pin_memory=(device.type != "cpu"),
    )

    # Model
    config = LeadModelConfig(dropout=dropout)
    model = LeadAdvisorModel(config).to(device)
    print(f"Lead Advisor parameters: {model.count_parameters():,}")

    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Loss
    team_criterion = nn.BCEWithLogitsLoss()
    lead_criterion = nn.BCEWithLogitsLoss()

    if not run_id:
        run_id = f"lead_run_{int(time.time())}"
    training_log_path = CHECKPOINT_DIR / "training_log.jsonl"
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, epochs + 1):
        # Train
        model.train()
        train_metrics = _run_epoch(
            model, train_loader, device, team_criterion, lead_criterion,
            optimizer=optimizer,
        )
        scheduler.step()

        # Validate
        model.eval()
        with torch.no_grad():
            val_metrics = _run_epoch(
                model, val_loader, device, team_criterion, lead_criterion,
            )

        m, v = train_metrics, val_metrics
        line = (
            f"Epoch {epoch:3d}/{epochs} | "
            f"Train loss: {m['loss']:.4f} | "
            f"Val loss: {v['loss']:.4f} | "
            f"Team: {v['team_acc']:.1f}% (exact {v['team_exact']:.1f}%) | "
            f"Lead: {v['lead_acc']:.1f}% (exact {v['lead_exact']:.1f}%) | "
            f"LR: {scheduler.get_last_lr()[0]:.2e}"
        )
        print(line, flush=True)

        # JSONL log
        log_entry = {
            "run_id": run_id, "epoch": epoch, "total_epochs": epochs,
            "timestamp": time.time(),
            "train_loss": round(m["loss"], 4),
            "val_loss": round(v["loss"], 4),
            "team_acc": round(v["team_acc"], 2),
            "team_exact": round(v["team_exact"], 2),
            "lead_acc": round(v["lead_acc"], 2),
            "lead_exact": round(v["lead_exact"], 2),
            "lr": scheduler.get_last_lr()[0],
            "best_val_loss": round(min(best_val_loss, v["loss"]), 4),
        }
        with open(training_log_path, "a") as f:
            json.dump(log_entry, f)
            f.write("\n")

        # Dashboard
        if dashboard_url:
            _report_to_dashboard(dashboard_url, {
                "session_id": run_id,
                "machine": machine_name,
                "model_version": "lead_advisor",
                "epoch": epoch,
                "total_epochs": epochs,
                "timestamp": time.time(),
                "train_loss": round(m["loss"], 4),
                "val_loss": round(v["loss"], 4),
                "val_top1": round(v["team_acc"], 2),   # reuse dashboard field
                "val_top3": round(v["lead_acc"], 2),    # reuse dashboard field
                "team_acc": round(v["team_acc"], 2),
                "lead_acc": round(v["lead_acc"], 2),
                "lr": scheduler.get_last_lr()[0],
                "best_val_loss": round(min(best_val_loss, v["loss"]), 4),
                "config": {
                    "batch_size": batch_size,
                    "lr": lr,
                    "min_rating": min_rating,
                    "device": str(device),
                    "params": model.count_parameters(),
                    "dataset_size": len(dataset),
                },
            })

        # Save best + early stopping
        if v["loss"] < best_val_loss:
            best_val_loss = v["loss"]
            patience_counter = 0
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "val_loss": v["loss"],
                "team_acc": v["team_acc"],
                "lead_acc": v["lead_acc"],
                "team_exact": v["team_exact"],
                "lead_exact": v["lead_exact"],
                "config": config,
            }, CHECKPOINT_DIR / "best.pt")
            print(f"  -> Saved best model (val_loss={v['loss']:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"  -> Early stopping: no improvement for {patience} epochs")
                break

        # Periodic checkpoint
        if epoch % 10 == 0:
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "val_loss": v["loss"],
                "config": config,
            }, CHECKPOINT_DIR / f"epoch_{epoch}.pt")

    print(f"\nTraining complete. Best val loss: {best_val_loss:.4f}")


def _run_epoch(
    model, loader, device, team_criterion, lead_criterion, optimizer=None,
) -> dict:
    total_loss = 0.0
    total_samples = 0

    # Team accuracy (per-slot)
    team_correct = 0
    team_total = 0
    # Team exact match
    team_exact_correct = 0
    # Lead accuracy (per-slot)
    lead_correct = 0
    lead_total = 0
    # Lead exact match
    lead_exact_correct = 0

    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        B = batch["own_features"].shape[0]

        out = model(batch)

        team_loss = team_criterion(out["team_logits"], batch["team_select_labels"])
        lead_loss = lead_criterion(out["lead_logits"], batch["lead_labels"])
        loss = team_loss + lead_loss

        if optimizer:
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        total_loss += loss.item() * B
        total_samples += B

        # Team accuracy: top-4 predicted vs actual selected
        team_pred = out["team_logits"].topk(4, dim=-1).indices  # (B, 4)
        team_truth = batch["team_select_labels"].bool()          # (B, 6)
        for i in range(B):
            pred_set = set(team_pred[i].tolist())
            truth_set = set(j for j in range(6) if team_truth[i, j])
            overlap = len(pred_set & truth_set)
            team_correct += overlap
            team_total += 4
            if overlap == 4:
                team_exact_correct += 1

        # Lead accuracy: top-2 predicted vs actual leads
        lead_pred = out["lead_logits"].topk(2, dim=-1).indices  # (B, 2)
        lead_truth = batch["lead_labels"].bool()                 # (B, 4)
        for i in range(B):
            pred_set = set(lead_pred[i].tolist())
            truth_set = set(j for j in range(4) if lead_truth[i, j])
            overlap = len(pred_set & truth_set)
            lead_correct += overlap
            lead_total += 2
            if overlap == 2:
                lead_exact_correct += 1

    return {
        "loss": total_loss / total_samples if total_samples else 0,
        "team_acc": team_correct / team_total * 100 if team_total else 0,
        "team_exact": team_exact_correct / total_samples * 100 if total_samples else 0,
        "lead_acc": lead_correct / lead_total * 100 if lead_total else 0,
        "lead_exact": lead_exact_correct / total_samples * 100 if total_samples else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Train Lead Advisor model")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-2)
    parser.add_argument("--min-rating", type=int, default=1400)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--replay-dir", type=str, default="")
    parser.add_argument("--dashboard", type=str, default="http://100.113.157.128:8421",
                        help="Dashboard URL (empty to disable)")
    parser.add_argument("--dropout", type=float, default=0.2)
    args = parser.parse_args()

    train(
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        min_rating=args.min_rating,
        device_str=args.device,
        patience=args.patience,
        run_id=args.run_id,
        replay_dir=args.replay_dir,
        dashboard_url=args.dashboard,
        dropout=args.dropout,
    )


if __name__ == "__main__":
    main()
