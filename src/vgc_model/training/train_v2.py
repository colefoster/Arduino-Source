"""Training loop for VGC battle model v2 (enriched features)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

from ..data.enriched_dataset import EnrichedDataset
from ..data.feature_tables import FeatureTables
from ..data.usage_stats import UsageStats
from ..data.player_profiles import PlayerProfiles
from ..data.vocab import Vocabs
from ..model.vgc_model_v2 import VGCTransformerV2, ModelConfigV2

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_DIR = DATA_DIR / "checkpoints_v2"

# Search for replays in multiple directories
REPLAY_SEARCH_DIRS = [
    DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma",
    DATA_DIR / "spectated",
    DATA_DIR / "downloaded",
]


def _find_replay_dir() -> Path:
    """Find the first existing replay directory."""
    for d in REPLAY_SEARCH_DIRS:
        if d.exists() and any(d.glob("*.json")):
            return d
    # Fallback to the standard location even if empty
    return REPLAY_SEARCH_DIRS[0]


def top_k_accuracy(logits: torch.Tensor, targets: torch.Tensor, k: int) -> int:
    """Count how many targets are in the top-k predictions."""
    _, top_k_preds = logits.topk(k, dim=-1)
    return (top_k_preds == targets.unsqueeze(-1)).any(dim=-1).sum().item()


def train(
    epochs: int = 80,
    batch_size: int = 128,
    lr: float = 3e-4,
    weight_decay: float = 5e-3,
    min_rating: int = 0,
    device_str: str = "auto",
    patience: int = 10,
    run_id: str = "",
    replay_dir: str = "",
):
    # Device selection
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

    # Load vocabs
    print("Loading vocabularies...")
    vocabs = Vocabs.load(VOCAB_DIR)

    # Load feature tables
    print("Loading feature tables...")
    feature_tables = FeatureTables()

    # Load usage stats (optional)
    usage_stats = None
    try:
        usage_stats = UsageStats()
        print(f"Loaded usage stats: {len(usage_stats.species_list)} species")
    except Exception as e:
        print(f"Usage stats not available: {e}")

    # Load player profiles (optional)
    player_profiles = None
    try:
        player_profiles = PlayerProfiles()
        print(f"Loaded player profiles: {player_profiles}")
    except Exception as e:
        print(f"Player profiles not available: {e}")

    # Find replay directory
    if replay_dir:
        rdir = Path(replay_dir)
    else:
        rdir = _find_replay_dir()
    print(f"Replay directory: {rdir}")

    # Load dataset
    print(f"Loading enriched dataset (min_rating={min_rating})...")
    dataset = EnrichedDataset(
        replay_dir=rdir,
        vocabs=vocabs,
        feature_tables=feature_tables,
        usage_stats=usage_stats,
        player_profiles=player_profiles,
        min_rating=min_rating,
        winner_only=True,
        min_turns=3,
    )
    print(f"Dataset: {len(dataset)} samples ({len(dataset.samples)} battle turns, "
          f"{len(dataset.team_previews)} team previews)")

    if len(dataset) == 0:
        print("ERROR: No samples loaded. Check replay directory and data files.")
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
    config = ModelConfigV2()
    model = VGCTransformerV2(vocabs, config).to(device)
    print(f"Model v2 parameters: {model.count_parameters():,}")

    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Losses
    action_criterion = nn.CrossEntropyLoss(reduction="none", label_smoothing=0.1)
    team_criterion = nn.BCEWithLogitsLoss(reduction="none")

    # JSONL training log
    if not run_id:
        run_id = f"v2_run_{int(time.time())}"
    training_log_path = CHECKPOINT_DIR / "training_log.jsonl"

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(1, epochs + 1):
        # ---- Train ----
        model.train()
        metrics = _run_epoch(model, train_loader, device, action_criterion, team_criterion,
                             optimizer=optimizer)
        scheduler.step()

        # ---- Validate ----
        model.eval()
        with torch.no_grad():
            val_metrics = _run_epoch(model, val_loader, device, action_criterion, team_criterion)

        # Print
        m, v = metrics, val_metrics
        line = (
            f"Epoch {epoch:3d}/{epochs} | "
            f"Train loss: {m['loss']:.4f} top1: {m['top1']:.1f}% top3: {m['top3']:.1f}% | "
            f"Val loss: {v['loss']:.4f} top1: {v['top1']:.1f}% top3: {v['top3']:.1f}%"
        )
        if v["team_acc"] is not None:
            line += f" | team: {v['team_acc']:.1f}% lead: {v['lead_acc']:.1f}%"
        line += f" | LR: {scheduler.get_last_lr()[0]:.2e}"
        print(line, flush=True)

        # Append to JSONL
        with open(training_log_path, "a") as f:
            json.dump({
                "run_id": run_id,
                "epoch": epoch,
                "total_epochs": epochs,
                "timestamp": time.time(),
                "train_loss": round(m["loss"], 4),
                "val_loss": round(v["loss"], 4),
                "train_top1": round(m["top1"], 2),
                "val_top1": round(v["top1"], 2),
                "train_top3": round(m["top3"], 2),
                "val_top3": round(v["top3"], 2),
                "team_acc": round(v["team_acc"], 2) if v["team_acc"] is not None else None,
                "lead_acc": round(v["lead_acc"], 2) if v["lead_acc"] is not None else None,
                "lr": scheduler.get_last_lr()[0],
                "best_val_loss": round(min(best_val_loss, v["loss"]), 4),
            }, f)
            f.write("\n")

        # Save best + early stopping
        if v["loss"] < best_val_loss:
            best_val_loss = v["loss"]
            patience_counter = 0
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": v["loss"],
                "val_top1": v["top1"],
                "val_top3": v["top3"],
                "val_team_acc": v["team_acc"],
                "val_lead_acc": v["lead_acc"],
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
                "val_loss": v["loss"],
                "config": config,
            }, CHECKPOINT_DIR / f"epoch_{epoch}.pt")

    print(f"\nTraining complete. Best val loss: {best_val_loss:.4f}")


def _run_epoch(
    model, loader, device, action_criterion, team_criterion, optimizer=None
) -> dict:
    """Run one epoch (train or eval). Returns metrics dict."""
    total_loss = 0.0
    total_correct_top1 = 0
    total_correct_top3 = 0
    total_actions = 0
    total_team_correct = 0
    total_team_samples = 0
    total_lead_correct = 0
    total_lead_samples = 0

    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}

        out = model(batch)
        logits_a = out["logits_a"]
        logits_b = out["logits_b"]

        # Action loss
        loss_a = action_criterion(logits_a, batch["action_slot_a"])
        loss_b = action_criterion(logits_b, batch["action_slot_b"])
        weights = batch["rating_weight"]
        loss = (weights * (loss_a + loss_b)).mean()

        # Team selection loss
        if "team_logits" in out:
            tp_mask = batch["has_team_preview"]
            if tp_mask.any():
                team_logits = out["team_logits"][tp_mask]
                team_labels = batch["team_select_labels"][tp_mask]
                team_loss = team_criterion(team_logits, team_labels).mean()
                loss = loss + 0.3 * team_loss

                team_preds = team_logits.topk(4, dim=-1).indices
                team_truth = team_labels.bool()
                for i in range(team_preds.shape[0]):
                    pred_set = set(team_preds[i].tolist())
                    truth_set = set(j for j in range(6) if team_truth[i, j])
                    total_team_correct += len(pred_set & truth_set)
                    total_team_samples += 4

        # Lead selection loss
        if "lead_logits" in out:
            tp_mask = batch["has_team_preview"]
            if tp_mask.any():
                lead_logits = out["lead_logits"][tp_mask]
                lead_labels = batch["lead_labels"][tp_mask]
                lead_loss = team_criterion(lead_logits, lead_labels).mean()
                loss = loss + 0.3 * lead_loss

                lead_preds = lead_logits.topk(2, dim=-1).indices
                lead_truth = lead_labels.bool()
                for i in range(lead_preds.shape[0]):
                    pred_set = set(lead_preds[i].tolist())
                    truth_set = set(j for j in range(4) if lead_truth[i, j])
                    total_lead_correct += len(pred_set & truth_set)
                    total_lead_samples += 2

        if optimizer:
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        n = len(batch["species_ids"])
        total_loss += loss.item() * n

        total_correct_top1 += (logits_a.argmax(-1) == batch["action_slot_a"]).sum().item()
        total_correct_top1 += (logits_b.argmax(-1) == batch["action_slot_b"]).sum().item()
        total_correct_top3 += top_k_accuracy(logits_a, batch["action_slot_a"], 3)
        total_correct_top3 += top_k_accuracy(logits_b, batch["action_slot_b"], 3)
        total_actions += n * 2

    return {
        "loss": total_loss / (total_actions // 2) if total_actions else 0,
        "top1": total_correct_top1 / total_actions * 100 if total_actions else 0,
        "top3": total_correct_top3 / total_actions * 100 if total_actions else 0,
        "team_acc": total_team_correct / total_team_samples * 100 if total_team_samples else None,
        "lead_acc": total_lead_correct / total_lead_samples * 100 if total_lead_samples else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Train VGC battle model v2 (enriched)")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=5e-3)
    parser.add_argument("--min-rating", type=int, default=0)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--replay-dir", type=str, default="")
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
    )


if __name__ == "__main__":
    main()
