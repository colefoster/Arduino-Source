"""Training loop for the Win Probability model."""

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

from ..data.winrate_dataset import WinrateDataset
from ..data.feature_tables import FeatureTables
from ..data.usage_stats import UsageStats
from ..data.player_profiles import PlayerProfiles
from ..data.vocab import Vocabs
from ..model.winrate_model import WinrateModel, WinrateModelConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_DIR = DATA_DIR / "checkpoints_winrate"

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
    epochs: int = 40,
    batch_size: int = 256,
    lr: float = 3e-4,
    weight_decay: float = 5e-3,
    min_rating: int = 1200,
    device_str: str = "auto",
    patience: int = 8,
    run_id: str = "",
    replay_dir: str = "",
    dashboard_url: str = "",
    dropout: float = 0.25,
    n_layers: int = 4,
    label_smoothing: float = 0.05,
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

    # Load vocabs + feature tables
    print("Loading vocabularies...")
    vocabs = Vocabs.load(VOCAB_DIR)

    print("Loading feature tables...")
    feature_tables = FeatureTables()

    usage_stats = None
    try:
        usage_stats = UsageStats()
        print(f"Loaded usage stats: {len(usage_stats.species_list)} species")
    except Exception as e:
        print(f"Usage stats not available: {e}")

    player_profiles = None
    try:
        player_profiles = PlayerProfiles()
        print(f"Loaded player profiles: {player_profiles}")
    except Exception as e:
        print(f"Player profiles not available: {e}")

    # Replay directory
    rdir = Path(replay_dir) if replay_dir else _find_replay_dir()
    print(f"Replay directory: {rdir}")

    # Load dataset
    print(f"Loading winrate dataset (min_rating={min_rating})...")
    dataset = WinrateDataset(
        replay_dir=rdir,
        vocabs=vocabs,
        feature_tables=feature_tables,
        usage_stats=usage_stats,
        player_profiles=player_profiles,
        min_rating=min_rating,
    )

    if len(dataset) == 0:
        print("ERROR: No samples loaded.")
        return

    # Train/val split
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
    config = WinrateModelConfig(dropout=dropout, n_layers=n_layers)
    model = WinrateModel(vocabs, config).to(device)
    print(f"Winrate model parameters: {model.count_parameters():,}")

    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Loss with label smoothing (0/1 -> 0.05/0.95 to handle noisy games)
    criterion = nn.BCEWithLogitsLoss(reduction="none")

    if not run_id:
        run_id = f"winrate_run_{int(time.time())}"
    training_log_path = CHECKPOINT_DIR / "training_log.jsonl"
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, epochs + 1):
        # Train
        model.train()
        train_metrics = _run_epoch(
            model, train_loader, device, criterion,
            label_smoothing=label_smoothing, optimizer=optimizer,
        )
        scheduler.step()

        # Validate
        model.eval()
        with torch.no_grad():
            val_metrics = _run_epoch(
                model, val_loader, device, criterion,
                label_smoothing=label_smoothing,
            )

        m, v = train_metrics, val_metrics
        line = (
            f"Epoch {epoch:3d}/{epochs} | "
            f"Train loss: {m['loss']:.4f} acc: {m['accuracy']:.1f}% | "
            f"Val loss: {v['loss']:.4f} acc: {v['accuracy']:.1f}% | "
            f"Cal: win={v['cal_win']:.3f} loss={v['cal_loss']:.3f} | "
            f"LR: {scheduler.get_last_lr()[0]:.2e}"
        )
        print(line, flush=True)

        # JSONL log
        log_entry = {
            "run_id": run_id, "epoch": epoch, "total_epochs": epochs,
            "timestamp": time.time(),
            "train_loss": round(m["loss"], 4),
            "val_loss": round(v["loss"], 4),
            "train_acc": round(m["accuracy"], 2),
            "val_acc": round(v["accuracy"], 2),
            "cal_win": round(v["cal_win"], 4),
            "cal_loss": round(v["cal_loss"], 4),
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
                "model_version": "winrate",
                "epoch": epoch,
                "total_epochs": epochs,
                "timestamp": time.time(),
                "train_loss": round(m["loss"], 4),
                "val_loss": round(v["loss"], 4),
                "val_top1": round(v["accuracy"], 2),  # reuse dashboard field
                "train_top1": round(m["accuracy"], 2),
                "lr": scheduler.get_last_lr()[0],
                "best_val_loss": round(min(best_val_loss, v["loss"]), 4),
                "config": {
                    "batch_size": batch_size,
                    "lr": lr,
                    "min_rating": min_rating,
                    "device": str(device),
                    "params": model.count_parameters(),
                    "dataset_size": len(dataset),
                    "label_smoothing": label_smoothing,
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
                "val_acc": v["accuracy"],
                "config": config,
            }, CHECKPOINT_DIR / "best.pt")
            print(f"  -> Saved best model (val_loss={v['loss']:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"  -> Early stopping: no improvement for {patience} epochs")
                break

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
    model, loader, device, criterion, label_smoothing=0.05, optimizer=None,
) -> dict:
    total_loss = 0.0
    total_correct = 0
    total_samples = 0
    # Calibration: track mean predicted prob for wins vs losses
    sum_pred_win = 0.0
    count_win = 0
    sum_pred_loss = 0.0
    count_loss = 0

    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        B = batch["species_ids"].shape[0]

        out = model(batch)
        logits = out["win_logit"]  # (B,)
        labels = batch["win_label"]  # (B,)

        # Apply label smoothing
        smoothed = labels * (1 - label_smoothing) + (1 - labels) * label_smoothing

        # Weighted loss
        weights = batch["rating_weight"]
        loss = (criterion(logits, smoothed) * weights).mean()

        if optimizer:
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        total_loss += loss.item() * B
        total_samples += B

        # Accuracy
        preds = (logits > 0).float()
        total_correct += (preds == labels).sum().item()

        # Calibration
        probs = torch.sigmoid(logits).detach()
        win_mask = labels == 1.0
        loss_mask = labels == 0.0
        sum_pred_win += probs[win_mask].sum().item()
        count_win += win_mask.sum().item()
        sum_pred_loss += probs[loss_mask].sum().item()
        count_loss += loss_mask.sum().item()

    return {
        "loss": total_loss / total_samples if total_samples else 0,
        "accuracy": total_correct / total_samples * 100 if total_samples else 0,
        "cal_win": sum_pred_win / count_win if count_win else 0,
        "cal_loss": sum_pred_loss / count_loss if count_loss else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Train Win Probability model")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=5e-3)
    parser.add_argument("--min-rating", type=int, default=1200)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--replay-dir", type=str, default="")
    parser.add_argument("--dashboard", type=str, default="http://100.113.157.128:8421",
                        help="Dashboard URL (empty to disable)")
    parser.add_argument("--dropout", type=float, default=0.25)
    parser.add_argument("--n-layers", type=int, default=4)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
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
        n_layers=args.n_layers,
        label_smoothing=args.label_smoothing,
    )


if __name__ == "__main__":
    main()
