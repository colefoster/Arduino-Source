"""Training loop for VGC battle model."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

from ..data.dataset import VGCDataset
from ..data.vocab import Vocabs
from ..model.vgc_model import VGCTransformer, ModelConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPLAY_DIR = DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"


def train(
    epochs: int = 80,
    batch_size: int = 128,
    lr: float = 3e-4,
    weight_decay: float = 1e-3,
    min_rating: int = 0,
    device_str: str = "auto",
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

    # Load dataset
    print(f"Loading dataset (min_rating={min_rating})...")
    dataset = VGCDataset(
        replay_dir=REPLAY_DIR,
        vocabs=vocabs,
        min_rating=min_rating,
        winner_only=True,
        min_turns=3,
    )
    print(f"Dataset: {len(dataset)} samples")

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
    config = ModelConfig()
    model = VGCTransformer(vocabs, config).to(device)
    print(f"Model parameters: {model.count_parameters():,}")

    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Loss with label smoothing
    criterion = nn.CrossEntropyLoss(reduction="none", label_smoothing=0.1)

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best_val_loss = float("inf")

    for epoch in range(1, epochs + 1):
        # Train
        model.train()
        train_loss = 0.0
        train_correct_a = 0
        train_correct_b = 0
        train_total = 0

        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}

            logits_a, logits_b = model(batch)

            loss_a = criterion(logits_a, batch["action_slot_a"])
            loss_b = criterion(logits_b, batch["action_slot_b"])

            # Weight by rating
            weights = batch["rating_weight"]
            loss = (weights * (loss_a + loss_b)).mean()

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            train_loss += loss.item() * len(batch["species_ids"])
            train_correct_a += (logits_a.argmax(-1) == batch["action_slot_a"]).sum().item()
            train_correct_b += (logits_b.argmax(-1) == batch["action_slot_b"]).sum().item()
            train_total += len(batch["species_ids"])

        scheduler.step()

        # Validate
        model.eval()
        val_loss = 0.0
        val_correct_a = 0
        val_correct_b = 0
        val_total = 0

        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                logits_a, logits_b = model(batch)

                loss_a = criterion(logits_a, batch["action_slot_a"])
                loss_b = criterion(logits_b, batch["action_slot_b"])
                weights = batch["rating_weight"]
                loss = (weights * (loss_a + loss_b)).mean()

                val_loss += loss.item() * len(batch["species_ids"])
                val_correct_a += (logits_a.argmax(-1) == batch["action_slot_a"]).sum().item()
                val_correct_b += (logits_b.argmax(-1) == batch["action_slot_b"]).sum().item()
                val_total += len(batch["species_ids"])

        avg_train_loss = train_loss / train_total
        avg_val_loss = val_loss / val_total
        train_acc_a = train_correct_a / train_total * 100
        train_acc_b = train_correct_b / train_total * 100
        val_acc_a = val_correct_a / val_total * 100
        val_acc_b = val_correct_b / val_total * 100

        print(
            f"Epoch {epoch:3d}/{epochs} | "
            f"Train loss: {avg_train_loss:.4f} acc_a: {train_acc_a:.1f}% acc_b: {train_acc_b:.1f}% | "
            f"Val loss: {avg_val_loss:.4f} acc_a: {val_acc_a:.1f}% acc_b: {val_acc_b:.1f}% | "
            f"LR: {scheduler.get_last_lr()[0]:.2e}"
        )

        # Save best
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": avg_val_loss,
                "val_acc_a": val_acc_a,
                "val_acc_b": val_acc_b,
                "config": config,
            }, CHECKPOINT_DIR / "best.pt")
            print(f"  -> Saved best model (val_loss={avg_val_loss:.4f})")

        # Periodic checkpoint
        if epoch % 10 == 0:
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": avg_val_loss,
                "config": config,
            }, CHECKPOINT_DIR / f"epoch_{epoch}.pt")

    print(f"\nTraining complete. Best val loss: {best_val_loss:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Train VGC battle model")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-3)
    parser.add_argument("--min-rating", type=int, default=0)
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    train(
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        min_rating=args.min_rating,
        device_str=args.device,
    )


if __name__ == "__main__":
    main()
