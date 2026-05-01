"""Tests for GpuSlotSwap.

Verifies that with all-True swap masks, slot pairs (0,1) and (4,5) are
correctly exchanged across all per-slot tensors AND the action labels swap
when own-side swaps. Idempotent under double-swap.
"""
from __future__ import annotations

import torch

from src.vgc_model.training.gpu_slot_swap import swap_batch


def _make_batch(b: int = 3) -> dict[str, torch.Tensor]:
    return {
        "species_ids": torch.arange(b * 8).view(b, 8).long(),
        "hp_values": (torch.arange(b * 8) / 100.0).view(b, 8).float(),
        "status_ids": torch.zeros(b, 8, dtype=torch.long),
        "alive_flags": torch.ones(b, 8, dtype=torch.long),
        "item_ids": torch.arange(b * 8).view(b, 8).long() + 1000,
        "item_confidences": torch.full((b, 8), 0.5),
        "ability_ids": torch.arange(b * 8).view(b, 8).long() + 2000,
        "ability_confidences": torch.full((b, 8), 0.7),
        "move_ids": torch.arange(b * 8 * 4).view(b, 8, 4).long(),
        "move_confidences": torch.full((b, 8, 4), 0.3),
        "action_a_type": torch.tensor([1] * b),
        "action_a_move_id": torch.tensor([10, 20, 30][:b]),
        "action_a_switch_id": torch.tensor([0] * b),
        "action_a_target": torch.tensor([0] * b),
        "action_a_mega": torch.tensor([0] * b),
        "action_b_type": torch.tensor([2] * b),
        "action_b_move_id": torch.tensor([0] * b),
        "action_b_switch_id": torch.tensor([100, 200, 300][:b]),
        "action_b_target": torch.tensor([-2] * b),
        "action_b_mega": torch.tensor([0] * b),
    }


def test_swap_with_all_ones_swaps_own_actives():
    batch = _make_batch(b=2)
    expected_b0 = batch["species_ids"][0, 1].item()
    expected_b1 = batch["species_ids"][1, 1].item()
    out = swap_batch(batch, p_own=1.0, p_opp=0.0)
    assert out["species_ids"][0, 0].item() == expected_b0
    assert out["species_ids"][1, 0].item() == expected_b1


def test_swap_swaps_action_labels_when_own_swaps():
    batch = _make_batch(b=1)
    a_move = batch["action_a_move_id"][0].item()
    b_switch = batch["action_b_switch_id"][0].item()
    swap_batch(batch, p_own=1.0, p_opp=0.0)
    # After own swap, action_b_move should be a's old, action_a_switch should be b's old.
    assert batch["action_b_move_id"][0].item() == a_move
    assert batch["action_a_switch_id"][0].item() == b_switch


def test_double_swap_is_identity_for_own_pair():
    batch = _make_batch(b=2)
    species_before = batch["species_ids"].clone()
    moves_before = batch["move_ids"].clone()
    swap_batch(batch, p_own=1.0, p_opp=0.0)
    swap_batch(batch, p_own=1.0, p_opp=0.0)
    assert torch.equal(batch["species_ids"], species_before)
    assert torch.equal(batch["move_ids"], moves_before)


def test_swap_zero_prob_is_noop():
    batch = _make_batch(b=2)
    species_before = batch["species_ids"].clone()
    swap_batch(batch, p_own=0.0, p_opp=0.0)
    assert torch.equal(batch["species_ids"], species_before)


def test_swap_handles_2d_move_tensors():
    batch = _make_batch(b=2)
    moves_b1 = batch["move_ids"][1, 1].clone()
    swap_batch(batch, p_own=1.0, p_opp=0.0)
    assert torch.equal(batch["move_ids"][1, 0], moves_b1)


def test_swap_swaps_opp_actives_independently():
    batch = _make_batch(b=2)
    # Distinct values at opp positions
    expected = batch["species_ids"][:, 5].clone()
    swap_batch(batch, p_own=0.0, p_opp=1.0)
    assert torch.equal(batch["species_ids"][:, 4], expected)
