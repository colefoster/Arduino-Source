"""Layer 2 encoder: ParsedReplay -> per-decision tensor dicts.

Phase 4 of the pipeline redesign. Reads parsed parquet rows produced by
Layer 1 and produces flat lists of per-decision-point tensor dicts ready
for the new training loop.

Design choices:

- **Two modes**, ``meta-on`` and ``meta-off``, are first-class citizens.
  meta-on uses the ``prob`` field from Layer 1 as the model's confidence
  for each non-revealed slot. meta-off zeros out non-revealed slots
  entirely (PAD token + 0.0 confidence) — produces a "naive observer"
  model.
- **No augmentation**. Slot-swap augmentation is the trainer's job, on GPU,
  post-collate. The cache is augmentation-free so we never have to rebuild
  shards because a regularizer was tuned.
- **Confidence floats** are produced here from the ``prob`` field. If a
  later experiment wants different mappings (e.g. a sigmoid calibration
  on top of meta probs), bump the encoding version path segment and
  re-encode — Layer 1 stays untouched.

The 8-slot layout matches the existing model:
``[own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1]``.

This module is pure logic. The runner (``encode_runner.py``) handles I/O.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, Optional

import torch

from .vocab import Vocabs


N_SLOTS = 8
N_MOVES = 4

PAD_IDX = 0  # matches Vocabulary.PAD
NO_OP_TYPE = 0
MOVE_TYPE = 1
SWITCH_TYPE = 2

EncodeMode = Literal["meta-on", "meta-off"]


# ---------------------------------------------------------------------------
# Tensor builders
# ---------------------------------------------------------------------------

def _resolve_lookup(vocab, value: str, prob: float, source_type: str, mode: EncodeMode) -> tuple[int, float]:
    """Map a (value, source_type, prob) into (token_idx, confidence) per mode."""
    if source_type == "revealed":
        if not value:
            return (PAD_IDX, 0.0)
        return (vocab[value], 1.0)
    # source_type == "meta"
    if mode == "meta-off":
        return (PAD_IDX, 0.0)
    if not value:
        return (PAD_IDX, 0.0)
    return (vocab[value], float(prob))


def _encode_pokemon(slot, vocabs: Vocabs, mode: EncodeMode) -> dict:
    """Encode one revealed Pokémon slot into a flat dict of column -> scalar/list.

    `slot` is one entry from a turn's ``p1_revealed`` / ``p2_revealed`` array
    (as produced by ReplayParser, then JSON-serialized). After ``json.loads``
    it's a plain dict with the StatsField/RevealedPokemon shape.
    """
    item_v, item_c = _resolve_lookup(
        vocabs.items, slot["item"]["value"], slot["item"]["prob"],
        slot["item"]["source_type"], mode,
    )
    ability_v, ability_c = _resolve_lookup(
        vocabs.abilities, slot["ability"]["value"], slot["ability"]["prob"],
        slot["ability"]["source_type"], mode,
    )

    move_ids = []
    move_confs = []
    for m in slot["moves"][:N_MOVES]:
        v, c = _resolve_lookup(
            vocabs.moves, m["value"], m["prob"], m["source_type"], mode,
        )
        move_ids.append(v)
        move_confs.append(c)
    while len(move_ids) < N_MOVES:
        move_ids.append(PAD_IDX)
        move_confs.append(0.0)

    return {
        "species": vocabs.species[slot["species"]],
        "hp": float(slot["hp_frac"]),
        "status": vocabs.status[slot["status"] or "ok"],
        "alive": 0 if slot["fainted"] else 1,
        "item_id": item_v,
        "item_conf": item_c,
        "ability_id": ability_v,
        "ability_conf": ability_c,
        "move_ids": move_ids,
        "move_confs": move_confs,
    }


def _empty_pokemon() -> dict:
    return {
        "species": PAD_IDX, "hp": 0.0, "status": PAD_IDX, "alive": 0,
        "item_id": PAD_IDX, "item_conf": 0.0,
        "ability_id": PAD_IDX, "ability_conf": 0.0,
        "move_ids": [PAD_IDX] * N_MOVES, "move_confs": [0.0] * N_MOVES,
    }


def _split_revealed_to_4slot(revealed: list[dict]) -> list[Optional[dict]]:
    """Return ``[active_0, active_1, bench_0, bench_1]``.

    Slots without a real Pokémon are ``None`` (caller substitutes a padded
    empty dict). Active slots are entries with ``active_slot`` in (0, 1);
    everything else lands on the bench, capped at 2 entries.
    """
    out: list[Optional[dict]] = [None, None, None, None]
    bench: list[dict] = []
    for slot in revealed:
        idx = slot.get("active_slot", -1)
        if idx == 0 and out[0] is None:
            out[0] = slot
        elif idx == 1 and out[1] is None:
            out[1] = slot
        else:
            bench.append(slot)
    for i, s in enumerate(bench[:2]):
        out[2 + i] = s
    return out


def _encode_action(action: dict, vocabs: Vocabs) -> dict:
    """Encode one slot's action label."""
    t = action.get("type", "noop")
    if t == "move":
        action_type = MOVE_TYPE
        move_id = vocabs.moves[action.get("move", "")] if action.get("move") else PAD_IDX
        switch_id = PAD_IDX
    elif t == "switch":
        action_type = SWITCH_TYPE
        move_id = PAD_IDX
        switch_id = vocabs.species[action.get("switch_to", "")] if action.get("switch_to") else PAD_IDX
    else:
        action_type = NO_OP_TYPE
        move_id = PAD_IDX
        switch_id = PAD_IDX
    target = int(action.get("target", -2))
    if target < -2 or target > 1:
        target = -2
    return {
        "type": action_type,
        "move_id": move_id,
        "switch_to_id": switch_id,
        "target": target,
        "mega": int(bool(action.get("mega"))),
    }


# ---------------------------------------------------------------------------
# Per-decision encoding
# ---------------------------------------------------------------------------

def _encode_one_decision(
    turn: dict,
    pov_player: str,
    vocabs: Vocabs,
    mode: EncodeMode,
) -> dict:
    """Encode one (turn, player) decision point as a tensor dict.

    POV is the player whose actions are the labels. The "own" Pokémon are that
    player's, "opp" Pokémon are the other player's.
    """
    if pov_player == "p1":
        own_revealed = turn["p1_revealed"]
        opp_revealed = turn["p2_revealed"]
        action_a = turn["p1_action_a"]
        action_b = turn["p1_action_b"]
    else:
        own_revealed = turn["p2_revealed"]
        opp_revealed = turn["p1_revealed"]
        action_a = turn["p2_action_a"]
        action_b = turn["p2_action_b"]

    own_4 = _split_revealed_to_4slot(own_revealed)
    opp_4 = _split_revealed_to_4slot(opp_revealed)

    encoded_slots = [
        _encode_pokemon(s, vocabs, mode) if s is not None else _empty_pokemon()
        for s in (own_4 + opp_4)
    ]

    a_enc = _encode_action(action_a, vocabs)
    b_enc = _encode_action(action_b, vocabs)

    return {
        # Slot tensors (length 8 unless noted)
        "species_ids": torch.tensor([s["species"] for s in encoded_slots], dtype=torch.long),
        "hp_values": torch.tensor([s["hp"] for s in encoded_slots], dtype=torch.float32),
        "status_ids": torch.tensor([s["status"] for s in encoded_slots], dtype=torch.long),
        "alive_flags": torch.tensor([s["alive"] for s in encoded_slots], dtype=torch.long),
        "item_ids": torch.tensor([s["item_id"] for s in encoded_slots], dtype=torch.long),
        "item_confidences": torch.tensor([s["item_conf"] for s in encoded_slots], dtype=torch.float32),
        "ability_ids": torch.tensor([s["ability_id"] for s in encoded_slots], dtype=torch.long),
        "ability_confidences": torch.tensor([s["ability_conf"] for s in encoded_slots], dtype=torch.float32),
        "move_ids": torch.tensor([s["move_ids"] for s in encoded_slots], dtype=torch.long),
        "move_confidences": torch.tensor([s["move_confs"] for s in encoded_slots], dtype=torch.float32),

        # Field
        "weather_id": torch.tensor(vocabs.weather[turn.get("weather") or "none"], dtype=torch.long),
        "terrain_id": torch.tensor(vocabs.terrain[turn.get("terrain") or "none"], dtype=torch.long),
        "trick_room": torch.tensor(int(bool(turn.get("trick_room"))), dtype=torch.long),

        # Action labels (one per active slot — 0=a, 1=b)
        "action_a_type": torch.tensor(a_enc["type"], dtype=torch.long),
        "action_a_move_id": torch.tensor(a_enc["move_id"], dtype=torch.long),
        "action_a_switch_id": torch.tensor(a_enc["switch_to_id"], dtype=torch.long),
        "action_a_target": torch.tensor(a_enc["target"], dtype=torch.long),
        "action_b_type": torch.tensor(b_enc["type"], dtype=torch.long),
        "action_b_move_id": torch.tensor(b_enc["move_id"], dtype=torch.long),
        "action_b_switch_id": torch.tensor(b_enc["switch_to_id"], dtype=torch.long),
        "action_b_target": torch.tensor(b_enc["target"], dtype=torch.long),
    }


# ---------------------------------------------------------------------------
# Encoder + per-replay output
# ---------------------------------------------------------------------------

@dataclass
class EncodedSample:
    """One per-decision sample, plus the metadata needed for filtering."""
    tensors: dict[str, torch.Tensor]
    replay_id: str
    bucket_hour: str
    rating: int
    pov_player: str   # "p1" or "p2"
    is_winner: bool
    turn_num: int


class Encoder:
    """Turn parsed parquet rows into per-decision tensor samples.

    Construct once with a configured ``Vocabs`` and a mode, reuse for many
    replays. The caller handles filesystem I/O.
    """

    def __init__(self, vocabs: Vocabs, mode: EncodeMode):
        if mode not in ("meta-on", "meta-off"):
            raise ValueError(f"unknown mode: {mode}")
        self.vocabs = vocabs
        self.mode: EncodeMode = mode

    def encode_row(self, row: dict) -> Iterator[EncodedSample]:
        """Encode one parquet row (one parsed replay) into per-decision samples.

        ``row`` is a dict with the Layer 1 schema: replay_id, p1_rating,
        winner, turns_json, etc. Yields one ``EncodedSample`` per (turn, player).
        """
        turns = json.loads(row["turns_json"])
        replay_id = row["replay_id"]
        bucket_hour = row.get("bucket_hour", "") or ""
        rating = max(int(row.get("p1_rating") or 0), int(row.get("p2_rating") or 0))
        winner = row.get("winner", "")

        for turn in turns:
            for pov in ("p1", "p2"):
                tensors = _encode_one_decision(turn, pov, self.vocabs, self.mode)
                yield EncodedSample(
                    tensors=tensors,
                    replay_id=replay_id,
                    bucket_hour=bucket_hour,
                    rating=rating,
                    pov_player=pov,
                    is_winner=(pov == winner),
                    turn_num=int(turn.get("turn_num", 0)),
                )
