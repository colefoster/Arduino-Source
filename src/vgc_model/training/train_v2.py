"""Training loop for VGC battle model v2 (enriched features)."""

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

from ..data.enriched_dataset import EnrichedDataset, CachedDataset
from ..data.feature_tables import FeatureTables
from ..data.usage_stats import UsageStats
from ..data.player_profiles import PlayerProfiles
from ..data.vocab import Vocabs
from ..model.vgc_model_v2 import VGCTransformerV2, ModelConfigV2
from ..model.vgc_model_v2_window import VGCTransformerV2Window, ModelConfigV2Window
from ..model.vgc_model_v2_seq import VGCTransformerV2Seq, ModelConfigV2Seq

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


def _report_to_dashboard(url: str, payload: dict):
    """POST training metrics to the dashboard. Fire-and-forget."""
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
        pass  # non-critical — don't interrupt training


def top_k_accuracy(logits: torch.Tensor, targets: torch.Tensor, k: int) -> int:
    """Count how many targets are in the top-k predictions."""
    _, top_k_preds = logits.topk(k, dim=-1)
    return (top_k_preds == targets.unsqueeze(-1)).any(dim=-1).sum().item()


class MTLUncertainty(nn.Module):
    """Kendall, Gal & Cipolla 2018 — homoscedastic uncertainty MTL weighting.

    Replaces hand-tuned task weights with learnable log-σ per task. For each
    task: L_total = (1/2σ²) * L_task + log σ. Implemented with log_sigma to
    keep σ > 0 and improve stability.
    """

    def __init__(self):
        super().__init__()
        self.log_sigma_action = nn.Parameter(torch.zeros(1))
        self.log_sigma_team = nn.Parameter(torch.zeros(1))
        self.log_sigma_lead = nn.Parameter(torch.zeros(1))

    def weight(self, log_sigma: torch.Tensor, loss: torch.Tensor) -> torch.Tensor:
        precision = torch.exp(-2.0 * log_sigma)
        return precision * loss + log_sigma.squeeze()


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
    dashboard_url: str = "",
    cache_path: str = "",
    dropout: float = 0.25,
    n_layers: int = 4,
    d_ff: int = 256,
    n_heads: int = 4,
    model_variant: str = "v2",
    resume_path: str = "",
    winner_only: bool = False,
    mtl_kendall: bool = True,
):
    machine_name = platform.node() or "unknown"

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

    # Map model variant to history mode
    history_mode_map = {"v2": "single", "v2_window": "window", "v2_seq": "sequence"}
    history_mode = history_mode_map[model_variant]

    # Load dataset — from cache or parse from scratch
    if cache_path and Path(cache_path).exists():
        cp = Path(cache_path)
        if cp.is_dir():
            from ..data.sharded_cache import ShardedCachedDataset
            dataset = ShardedCachedDataset(cp, augment=True)
        else:
            dataset = CachedDataset(cp, augment=True)
    else:
        print(f"Loading enriched dataset (min_rating={min_rating}, history_mode={history_mode})...")
        dataset = EnrichedDataset(
            replay_dir=rdir,
            vocabs=vocabs,
            feature_tables=feature_tables,
            usage_stats=usage_stats,
            player_profiles=player_profiles,
            min_rating=min_rating,
            winner_only=winner_only,
            min_turns=3,
            history_mode=history_mode,
        )
        print(f"Dataset: {len(dataset)} samples "
              f"({len(dataset.samples)} battle turns, {len(dataset.team_previews)} team previews)")

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
    if model_variant == "v2_window":
        config = ModelConfigV2Window(
            dropout=dropout, n_layers=n_layers, d_ff=d_ff, n_heads=n_heads,
        )
        model = VGCTransformerV2Window(vocabs, config).to(device)
    elif model_variant == "v2_seq":
        config = ModelConfigV2Seq(
            dropout=dropout, n_layers=n_layers, d_ff=d_ff, n_heads=n_heads,
        )
        model = VGCTransformerV2Seq(vocabs, config).to(device)
    else:
        config = ModelConfigV2(
            dropout=dropout, n_layers=n_layers, d_ff=d_ff, n_heads=n_heads,
        )
        model = VGCTransformerV2(vocabs, config).to(device)
    print(f"Model {model_variant} parameters: {model.count_parameters():,}")

    # MTL weighting (Kendall homoscedastic uncertainty) or fixed 0.3 fallback
    mtl = MTLUncertainty().to(device) if mtl_kendall else None
    if mtl is not None:
        print("MTL: Kendall homoscedastic uncertainty weighting (learned log-sigma per task)")

    # Optimizer
    opt_params = list(model.parameters())
    if mtl is not None:
        opt_params += list(mtl.parameters())
    optimizer = torch.optim.AdamW(opt_params, lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Losses
    action_criterion = nn.CrossEntropyLoss(reduction="none", label_smoothing=0.1)
    team_criterion = nn.BCEWithLogitsLoss(reduction="none")

    # JSONL training log
    if not run_id:
        run_id = f"{model_variant}_run_{int(time.time())}"
    training_log_path = CHECKPOINT_DIR / "training_log.jsonl"

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best_val_loss = float("inf")
    patience_counter = 0
    start_epoch = 1

    # Resume from checkpoint if provided
    if resume_path and Path(resume_path).exists():
        print(f"Resuming from {resume_path}...")
        # Handle pickle path mismatches (vgc_model vs src.vgc_model)
        import importlib
        import sys as _sys
        for mod_name in ["vgc_model", "vgc_model.model", "vgc_model.model.vgc_model_v2",
                         "vgc_model.model.vgc_model_v2_seq", "vgc_model.model.vgc_model_v2_window"]:
            src_name = f"src.{mod_name}"
            if src_name in _sys.modules and mod_name not in _sys.modules:
                _sys.modules[mod_name] = _sys.modules[src_name]
            elif mod_name in _sys.modules and src_name not in _sys.modules:
                _sys.modules[src_name] = _sys.modules[mod_name]
        ckpt = torch.load(resume_path, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"])
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if "scheduler_state_dict" in ckpt:
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        else:
            # Step scheduler forward to match resumed epoch
            for _ in range(ckpt["epoch"]):
                scheduler.step()
        start_epoch = ckpt["epoch"] + 1
        best_val_loss = ckpt.get("val_loss", float("inf"))
        print(f"  Resumed at epoch {start_epoch}, best_val_loss={best_val_loss:.4f}")

    for epoch in range(start_epoch, epochs + 1):
        # ---- Train ----
        model.train()
        if mtl is not None:
            mtl.train()
        metrics = _run_epoch(model, train_loader, device, action_criterion, team_criterion,
                             optimizer=optimizer, mtl=mtl)
        scheduler.step()

        # ---- Validate ----
        model.eval()
        if mtl is not None:
            mtl.eval()
        with torch.no_grad():
            val_metrics = _run_epoch(model, val_loader, device, action_criterion, team_criterion,
                                     mtl=mtl)

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

        # Report to dashboard
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
                "train_top1": round(m["top1"], 2),
                "val_top1": round(v["top1"], 2),
                "train_top3": round(m["top3"], 2),
                "val_top3": round(v["top3"], 2),
                "team_acc": round(v["team_acc"], 2) if v["team_acc"] is not None else None,
                "lead_acc": round(v["lead_acc"], 2) if v["lead_acc"] is not None else None,
                "lr": scheduler.get_last_lr()[0],
                "best_val_loss": round(min(best_val_loss, v["loss"]), 4),
                "config": {
                    "batch_size": batch_size,
                    "lr": lr,
                    "min_rating": min_rating,
                    "device": str(device),
                    "params": model.count_parameters(),
                    "dataset_size": len(dataset),
                    "winner_only": winner_only,
                    "history_mode": history_mode,
                    "mtl": "kendall" if mtl is not None else "fixed_0.3",
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
                "mtl_state_dict": mtl.state_dict() if mtl is not None else None,
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
                "scheduler_state_dict": scheduler.state_dict(),
                "val_loss": v["loss"],
                "config": config,
            }, CHECKPOINT_DIR / f"epoch_{epoch}.pt")

    print(f"\nTraining complete. Best val loss: {best_val_loss:.4f}")


def _run_epoch(
    model, loader, device, action_criterion, team_criterion, optimizer=None, mtl=None
) -> dict:
    """Run one epoch (train or eval). Returns metrics dict.

    `mtl` (optional MTLUncertainty): if provided, total backprop loss uses
    Kendall homoscedastic uncertainty weighting across action/team/lead.
    Reported `loss` is always the rating-weighted action loss alone — comparable
    across runs regardless of MTL scheme.
    """
    total_action_loss = 0.0  # rating-weighted action loss only (for reporting)
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

        # Action loss (rating-weighted)
        loss_a = action_criterion(logits_a, batch["action_slot_a"])
        loss_b = action_criterion(logits_b, batch["action_slot_b"])
        weights = batch["rating_weight"]
        action_loss = (weights * (loss_a + loss_b)).mean()

        # Build total backprop loss
        if mtl is not None:
            total_loss = mtl.weight(mtl.log_sigma_action, action_loss)
        else:
            total_loss = action_loss

        # Team selection loss
        if "team_logits" in out:
            tp_mask = batch["has_team_preview"]
            if tp_mask.any():
                team_logits = out["team_logits"][tp_mask]
                team_labels = batch["team_select_labels"][tp_mask]
                team_loss = team_criterion(team_logits, team_labels).mean()
                if mtl is not None:
                    total_loss = total_loss + mtl.weight(mtl.log_sigma_team, team_loss)
                else:
                    total_loss = total_loss + 0.3 * team_loss

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
                if mtl is not None:
                    total_loss = total_loss + mtl.weight(mtl.log_sigma_lead, lead_loss)
                else:
                    total_loss = total_loss + 0.3 * lead_loss

                lead_preds = lead_logits.topk(2, dim=-1).indices
                lead_truth = lead_labels.bool()
                for i in range(lead_preds.shape[0]):
                    pred_set = set(lead_preds[i].tolist())
                    truth_set = set(j for j in range(4) if lead_truth[i, j])
                    total_lead_correct += len(pred_set & truth_set)
                    total_lead_samples += 2

        if optimizer:
            optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        n = len(batch["species_ids"])
        total_action_loss += action_loss.item() * n

        total_correct_top1 += (logits_a.argmax(-1) == batch["action_slot_a"]).sum().item()
        total_correct_top1 += (logits_b.argmax(-1) == batch["action_slot_b"]).sum().item()
        total_correct_top3 += top_k_accuracy(logits_a, batch["action_slot_a"], 3)
        total_correct_top3 += top_k_accuracy(logits_b, batch["action_slot_b"], 3)
        total_actions += n * 2

    return {
        "loss": total_action_loss / (total_actions // 2) if total_actions else 0,
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
    parser.add_argument("--cache", type=str, default="",
                        help="Pre-parsed dataset: either a directory (sharded cache from "
                             "preparse_dataset.py) or a legacy single .pt file")
    parser.add_argument("--dashboard", type=str, default="http://100.113.157.128:8421",
                        help="Dashboard URL for live training progress (empty to disable)")
    parser.add_argument("--dropout", type=float, default=0.25)
    parser.add_argument("--n-layers", type=int, default=4)
    parser.add_argument("--d-ff", type=int, default=256)
    parser.add_argument("--n-heads", type=int, default=4)
    parser.add_argument("--model", type=str, default="v2",
                        choices=["v2", "v2_window", "v2_seq"],
                        help="Model variant: v2 (default), v2_window (3-turn), v2_seq (LSTM)")
    parser.add_argument("--winner-only", action="store_true",
                        help="Filter dataset to winning-side actions only (default: include both players)")
    parser.add_argument("--no-mtl", action="store_true",
                        help="Disable Kendall MTL uncertainty weighting; use fixed 0.3 aux weights instead")
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
        cache_path=args.cache,
        dashboard_url=args.dashboard,
        dropout=args.dropout,
        n_layers=args.n_layers,
        d_ff=args.d_ff,
        n_heads=args.n_heads,
        model_variant=args.model,
        resume_path=args.resume,
        winner_only=args.winner_only,
        mtl_kendall=not args.no_mtl,
    )


if __name__ == "__main__":
    main()
