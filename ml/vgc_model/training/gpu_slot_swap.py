"""Vectorized slot-swap augmentation, applied post-collate on GPU.

Replaces the per-sample CPU ``_swap_slots`` that lived in three places. One
``swap_batch`` call per training step swaps slots A↔B for randomly-selected
samples in the batch — model learns slot-symmetry without paying for ~40
``tensor.clone()`` calls per CPU sample.

Slot layout (8 slots): ``[own_a, own_b, own_bench0, own_bench1,
                          opp_a, opp_b, opp_bench0, opp_bench1]``.

Augmentation swaps:
- own active: indices 0 ↔ 1
- opp active: indices 4 ↔ 5

Bench slots aren't swapped because bench order isn't meaningful in the same
way (positions 2,3 are arbitrary leftovers).

The action labels for slot-A and slot-B also swap when own-active is swapped,
keeping the (state, label) pair internally consistent.
"""
from __future__ import annotations

import torch


# Tensors that index slots — these are the ones that need swapping.
# Keys must match those in ``training_dataset.SAMPLE_COLUMNS``.
_SLOT_KEYS_1D = (
    "species_ids", "hp_values", "status_ids", "alive_flags",
    "item_ids", "item_confidences",
    "ability_ids", "ability_confidences",
)
_SLOT_KEYS_2D = ("move_ids", "move_confidences")  # shape (B, 8, 4)
_OWN_PAIR = (0, 1)
_OPP_PAIR = (4, 5)


def swap_batch(
    batch: dict[str, torch.Tensor],
    *,
    p_own: float = 0.5,
    p_opp: float = 0.5,
    generator: torch.Generator | None = None,
) -> dict[str, torch.Tensor]:
    """Apply slot-swap to a batch in-place. Returns the same dict.

    Independent random masks for own-side swap and opp-side swap. When
    own-side swaps, the per-slot action labels (a/b) swap too.
    """
    if "species_ids" not in batch:
        return batch
    bsz = batch["species_ids"].shape[0]
    device = batch["species_ids"].device

    own_mask = (
        torch.rand(bsz, generator=generator, device=device) < p_own
    )
    opp_mask = (
        torch.rand(bsz, generator=generator, device=device) < p_opp
    )

    if own_mask.any():
        _swap_slot_pair(batch, own_mask, _OWN_PAIR)
        _swap_action_labels(batch, own_mask)
    if opp_mask.any():
        _swap_slot_pair(batch, opp_mask, _OPP_PAIR)

    return batch


def _swap_slot_pair(batch, mask: torch.Tensor, pair: tuple[int, int]) -> None:
    """Swap ``slot[pair[0]] ↔ slot[pair[1]]`` for samples where mask is True."""
    a, b = pair
    rows = mask.nonzero(as_tuple=True)[0]
    if rows.numel() == 0:
        return
    for k in _SLOT_KEYS_1D:
        t = batch.get(k)
        if t is None:
            continue
        # t shape (B, 8). Swap two columns at the masked rows.
        col_a = t[rows, a].clone()
        t[rows, a] = t[rows, b]
        t[rows, b] = col_a
    for k in _SLOT_KEYS_2D:
        t = batch.get(k)
        if t is None:
            continue
        # t shape (B, 8, 4). Same trick on dim 1.
        col_a = t[rows, a].clone()
        t[rows, a] = t[rows, b]
        t[rows, b] = col_a


def _swap_action_labels(batch, mask: torch.Tensor) -> None:
    """Swap ``action_a_*`` ↔ ``action_b_*`` rows where mask is True."""
    for suffix in ("type", "move_id", "switch_id", "target", "mega"):
        a_key = f"action_a_{suffix}"
        b_key = f"action_b_{suffix}"
        a = batch.get(a_key)
        b = batch.get(b_key)
        if a is None or b is None:
            continue
        rows = mask.nonzero(as_tuple=True)[0]
        if rows.numel() == 0:
            return
        a_vals = a[rows].clone()
        a[rows] = b[rows]
        b[rows] = a_vals
