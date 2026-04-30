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
from ..model.winrate_model_seq import WinrateModelSeq, WinrateModelSeqConfig

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
    model_variant: str = "winrate_seq",
    turn_weight: bool = False,
    resume_path: str = "",
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
    history_mode = "sequence" if model_variant == "winrate_seq" else "single"
    print(f"Loading winrate dataset (min_rating={min_rating}, history_mode={history_mode})...")
    dataset = WinrateDataset(
        replay_dir=rdir,
        vocabs=vocabs,
        feature_tables=feature_tables,
        usage_stats=usage_stats,
        player_profiles=player_profiles,
        min_rating=min_rating,
        history_mode=history_mode,
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
    if model_variant == "winrate_seq":
        config = WinrateModelSeqConfig(dropout=dropout, n_layers=n_layers)
        model = WinrateModelSeq(vocabs, config).to(device)
    else:
        config = WinrateModelConfig(dropout=dropout, n_layers=n_layers)
        model = WinrateModel(vocabs, config).to(device)
    print(f"Winrate model ({model_variant}) parameters: {model.count_parameters():,}")
    if turn_weight:
        print("Turn weighting enabled: per-sample loss multiplied by 1/sqrt(turn+1)")

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
    start_epoch = 1

    # Resume from checkpoint if requested
    if resume_path and Path(resume_path).exists():
        print(f"Resuming from {resume_path}...")
        ckpt = torch.load(resume_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"])
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if "scheduler_state_dict" in ckpt:
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        else:
            for _ in range(ckpt["epoch"]):
                scheduler.step()
        start_epoch = ckpt["epoch"] + 1
        best_val_loss = ckpt.get("val_loss", float("inf"))
        print(f"  Resumed at epoch {start_epoch}, best_val_loss={best_val_loss:.4f}")

    for epoch in range(start_epoch, epochs + 1):
        # Train
        model.train()
        train_metrics = _run_epoch(
            model, train_loader, device, criterion,
            label_smoothing=label_smoothing, optimizer=optimizer,
            turn_weight=turn_weight,
        )
        scheduler.step()

        # Validate
        model.eval()
        with torch.no_grad():
            val_metrics = _run_epoch(
                model, val_loader, device, criterion,
                label_smoothing=label_smoothing,
                turn_weight=turn_weight,
            )

        m, v = train_metrics, val_metrics
        line = (
            f"Epoch {epoch:3d}/{epochs} | "
            f"Train loss: {m['loss']:.4f} acc: {m['accuracy']:.1f}% | "
            f"Val loss: {v['loss']:.4f} acc: {v['accuracy']:.1f}% | "
            f"Cal: win={v['cal_win']:.3f} loss={v['cal_loss']:.3f} ECE={v['ece']:.3f} | "
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
            "ece": round(v["ece"], 4),
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
                "model_version": model_variant,
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
                    "model_variant": model_variant,
                    "history_mode": history_mode,
                    "turn_weight": turn_weight,
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
    turn_weight: bool = False,
) -> dict:
    total_loss = 0.0
    total_correct = 0
    total_samples = 0
    sum_pred_win = 0.0
    count_win = 0
    sum_pred_loss = 0.0
    count_loss = 0

    # Reliability buckets for ECE: 10 equal-width bins over [0,1]
    n_bins = 10
    bin_conf_sum = [0.0] * n_bins   # sum of predicted probs in bin
    bin_acc_sum = [0.0] * n_bins    # sum of correct predictions in bin
    bin_count = [0] * n_bins

    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        B = batch["species_ids"].shape[0]

        out = model(batch)
        logits = out["win_logit"]
        labels = batch["win_label"]

        smoothed = labels * (1 - label_smoothing) + (1 - labels) * label_smoothing

        weights = batch["rating_weight"]
        if turn_weight:
            # Downweight late-game turns where the outcome is more obvious; turn
            # comes in as float (1..30 cap). 1/sqrt(turn+1) gives turn 1: 0.71,
            # turn 5: 0.41, turn 20: 0.22.
            tw = 1.0 / torch.sqrt(batch["turn"] + 1.0)
            weights = weights * tw

        loss = (criterion(logits, smoothed) * weights).mean()

        if optimizer:
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        total_loss += loss.item() * B
        total_samples += B

        probs = torch.sigmoid(logits).detach()
        preds = (logits > 0).float()
        correct = (preds == labels).float()
        total_correct += correct.sum().item()

        # Per-class predicted-prob means
        win_mask = labels == 1.0
        loss_mask = labels == 0.0
        sum_pred_win += probs[win_mask].sum().item()
        count_win += win_mask.sum().item()
        sum_pred_loss += probs[loss_mask].sum().item()
        count_loss += loss_mask.sum().item()

        # ECE bucketing — confidence = max(p, 1-p), accuracy uses hard label.
        # Note: for binary, ECE on raw p and on confidence are equivalent.
        probs_cpu = probs.cpu().numpy()
        correct_cpu = correct.cpu().numpy()
        for i in range(B):
            p = float(probs_cpu[i])
            b = min(int(p * n_bins), n_bins - 1)
            bin_conf_sum[b] += p
            bin_acc_sum[b] += float(correct_cpu[i])
            bin_count[b] += 1

    # Expected Calibration Error: weighted |conf - acc| per bin
    ece = 0.0
    if total_samples:
        for b in range(n_bins):
            if bin_count[b]:
                conf = bin_conf_sum[b] / bin_count[b]
                acc = bin_acc_sum[b] / bin_count[b]
                ece += (bin_count[b] / total_samples) * abs(conf - acc)

    return {
        "loss": total_loss / total_samples if total_samples else 0,
        "accuracy": total_correct / total_samples * 100 if total_samples else 0,
        "cal_win": sum_pred_win / count_win if count_win else 0,
        "cal_loss": sum_pred_loss / count_loss if count_loss else 0,
        "ece": ece,
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
    parser.add_argument("--model", type=str, default="winrate_seq",
                        choices=["winrate", "winrate_seq"],
                        help="Model variant: winrate (stateless, default historical) or winrate_seq (LSTM history, new)")
    parser.add_argument("--turn-weight", action="store_true",
                        help="Downweight late-game turns by 1/sqrt(turn+1) so easy late positions don't dominate the loss")
    parser.add_argument("--resume", type=str, default="",
                        help="Path to checkpoint to resume training from")
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
        model_variant=args.model,
        turn_weight=args.turn_weight,
        resume_path=args.resume,
    )


if __name__ == "__main__":
    main()
