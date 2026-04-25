#!/usr/bin/env python3
"""Evaluate v1 model with and without spread move correction.

Measures how much of v1's "errors" were just spread move target mismatches.
Loads the v1 checkpoint, runs on validation data, scores both ways.

Usage:
    python scripts/eval_v1_spread.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for pickled 'src.vgc_model...'

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, random_split

from vgc_model.data.dataset import VGCDataset
from vgc_model.data.vocab import Vocabs
from vgc_model.data.feature_tables import FeatureTables
from vgc_model.model.vgc_model import VGCTransformer, ModelConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_PATH = DATA_DIR / "checkpoints" / "best.pt"

# Replay dirs to search
REPLAY_DIRS = [
    DATA_DIR / "showdown_replays" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "spectated" / "gen9championsvgc2026regma",
    DATA_DIR / "showdown_replays" / "downloaded" / "gen9championsvgc2026regma",
]

# Spread moves — target doesn't matter for these
SPREAD_MOVES = {
    "Earthquake", "Rock Slide", "Heat Wave", "Blizzard", "Hyper Voice",
    "Dazzling Gleam", "Icy Wind", "Eruption", "Water Spout", "Discharge",
    "Sludge Wave", "Surf", "Muddy Water", "Lava Plume", "Electroweb",
    "Struggle Bug", "Breaking Swipe", "Bulldoze", "Glacial Lance",
    "Astral Barrage", "Matcha Gotcha", "Make It Rain",
}


def is_spread_action(action_idx: int, pokemon_moves: list[str]) -> bool:
    """Check if an action index corresponds to a spread move."""
    if action_idx >= 12:  # switch
        return False
    move_idx = action_idx // 3
    if move_idx < len(pokemon_moves):
        return pokemon_moves[move_idx] in SPREAD_MOVES
    return False


def main():
    # Device
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
    print(f"Device: {device}")

    # Load vocabs
    vocabs = Vocabs.load(VOCAB_DIR)

    # Find replay dir
    replay_dir = None
    for d in REPLAY_DIRS:
        if d.exists() and any(d.glob("*.json")):
            replay_dir = d
            break
    if replay_dir is None:
        print("No replay directory found")
        return
    print(f"Replay dir: {replay_dir}")

    # Load v1 dataset (same as training)
    dataset = VGCDataset(
        replay_dir=replay_dir,
        vocabs=vocabs,
        min_rating=1200,
        winner_only=True,
        min_turns=3,
        augment=False,  # no augmentation for eval
    )
    print(f"Dataset: {len(dataset)} samples")

    # Same split as training (seed=42)
    val_size = max(1, len(dataset) // 10)
    train_size = len(dataset) - val_size
    _, val_dataset = random_split(
        dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42),
    )
    print(f"Validation set: {len(val_dataset)} samples")

    val_loader = DataLoader(val_dataset, batch_size=128, shuffle=False, num_workers=0)

    # Load v1 model
    print(f"Loading checkpoint from {CHECKPOINT_PATH}...")
    checkpoint = torch.load(CHECKPOINT_PATH, map_location=device, weights_only=False)
    config = checkpoint.get("config", ModelConfig())
    model = VGCTransformer(vocabs, config).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    print(f"Model params: {model.count_parameters():,}")
    print(f"Checkpoint epoch: {checkpoint.get('epoch')}, "
          f"reported val_top1: {checkpoint.get('val_top1', '?')}")

    # Evaluate
    original_correct = 0
    spread_corrected_correct = 0
    total_actions = 0
    spread_actions = 0
    spread_originally_wrong = 0
    spread_now_correct = 0

    # We also need move names to check spread. The v1 dataset encodes moves
    # but we need the original sample data. We'll re-derive from the batch.
    # Since v1 uses move_ids, we need the reverse vocab mapping.
    idx_to_move = {v: k for k, v in vocabs.moves._token_to_idx.items()}

    with torch.no_grad():
        for batch in val_loader:
            batch_dev = {k: v.to(device) for k, v in batch.items()}
            out = model(batch_dev)

            for slot_key, logits_key in [("action_slot_a", "logits_a"),
                                          ("action_slot_b", "logits_b")]:
                logits = out[logits_key]
                targets = batch[slot_key].to(device)
                preds = logits.argmax(dim=-1)
                n = targets.shape[0]

                # Get move names for each sample in batch
                # move_ids shape: (B, 8, 4) — slot 0 = own_a, slot 1 = own_b
                move_ids = batch["move_ids"]
                slot_idx = 0 if slot_key == "action_slot_a" else 1

                for i in range(n):
                    target = targets[i].item()
                    pred = preds[i].item()
                    total_actions += 1

                    # Get move names for this pokemon's slot
                    pokemon_move_ids = move_ids[i, slot_idx].tolist()
                    pokemon_moves = [idx_to_move.get(mid, "") for mid in pokemon_move_ids]

                    # Original accuracy
                    if pred == target:
                        original_correct += 1
                        spread_corrected_correct += 1
                    else:
                        # Check if this is a spread move mismatch
                        target_move_idx = target // 3 if target < 12 else -1
                        pred_move_idx = pred // 3 if pred < 12 else -1

                        is_target_spread = target < 12 and is_spread_action(target, pokemon_moves)
                        is_pred_spread = pred < 12 and is_spread_action(pred, pokemon_moves)

                        if (is_target_spread and is_pred_spread and
                                target_move_idx == pred_move_idx and
                                target_move_idx >= 0):
                            # Same spread move, different target — should count as correct
                            spread_corrected_correct += 1
                            spread_now_correct += 1

                    if target < 12 and is_spread_action(target, pokemon_moves):
                        spread_actions += 1

    print(f"\n{'='*60}")
    print(f"V1 MODEL EVALUATION — SPREAD MOVE IMPACT")
    print(f"{'='*60}")
    print(f"Total actions evaluated: {total_actions:,}")
    print(f"Spread move actions:     {spread_actions:,} ({spread_actions/total_actions*100:.1f}%)")
    print()
    print(f"Original accuracy:       {original_correct/total_actions*100:.2f}%  ({original_correct:,}/{total_actions:,})")
    print(f"Spread-corrected:        {spread_corrected_correct/total_actions*100:.2f}%  ({spread_corrected_correct:,}/{total_actions:,})")
    print(f"Difference:              +{(spread_corrected_correct-original_correct)/total_actions*100:.2f}%")
    print()
    print(f"Spread mismatches fixed: {spread_now_correct:,}")
    print(f"  (same move, different target — previously counted as wrong)")


if __name__ == "__main__":
    main()
