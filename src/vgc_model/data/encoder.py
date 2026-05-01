"""Layer 2 encoder: ParsedReplay -> per-decision raw samples.

Phase 4 of the pipeline redesign, optimized in Phase 5. Reads parsed parquet
rows produced by Layer 1 and produces flat lists of per-decision-point dicts
of Python primitives. The encode runner stacks these into per-column numpy
arrays once per shard — orders of magnitude faster than ``torch.tensor()``
called ~25 times per sample.

Two modes:
- ``meta-on``: uses Layer 1's ``prob`` for non-revealed slots.
- ``meta-off``: zeros out non-revealed slots (PAD + 0.0 confidence).

8-slot layout: ``[own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1]``.

Pure logic. The runner (``encode_runner.py``) handles I/O.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, Literal, Optional

from .vocab import Vocabs


N_SLOTS = 8
N_MOVES = 4
PAD_IDX = 0  # matches Vocabulary.PAD
NO_OP_TYPE = 0
MOVE_TYPE = 1
SWITCH_TYPE = 2

EncodeMode = Literal["meta-on", "meta-off"]


# Empty-Pokémon slot template (returned cheaply for missing positions).
# Caller must NOT mutate; we share the same lists.
_EMPTY_MOVES = [PAD_IDX] * N_MOVES
_EMPTY_CONFS = [0.0] * N_MOVES


def _resolve_lookup(
    vocab, value: str, prob: float, source_type: str, mode: EncodeMode,
) -> tuple[int, float]:
    if source_type == "revealed":
        if not value:
            return (PAD_IDX, 0.0)
        return (vocab[value], 1.0)
    # source_type == "meta"
    if mode == "meta-off" or not value:
        return (PAD_IDX, 0.0)
    return (vocab[value], float(prob))


def _encode_pokemon(slot: dict, vocabs: Vocabs, mode: EncodeMode) -> dict:
    item_v, item_c = _resolve_lookup(
        vocabs.items, slot["item"]["value"], slot["item"]["prob"],
        slot["item"]["source_type"], mode,
    )
    ability_v, ability_c = _resolve_lookup(
        vocabs.abilities, slot["ability"]["value"], slot["ability"]["prob"],
        slot["ability"]["source_type"], mode,
    )

    move_ids: list[int] = []
    move_confs: list[float] = []
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
        "move_ids": list(_EMPTY_MOVES), "move_confs": list(_EMPTY_CONFS),
    }


def _split_revealed_to_4slot(revealed: list[dict]) -> list[Optional[dict]]:
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


def _encode_action(action: dict, vocabs: Vocabs) -> tuple[int, int, int, int, int]:
    """Returns (action_type, move_id, switch_to_id, target, mega)."""
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
    return (action_type, move_id, switch_id, target, int(bool(action.get("mega"))))


def _encode_one_decision_raw(
    turn: dict, pov_player: str, vocabs: Vocabs, mode: EncodeMode,
) -> dict:
    """Encode one (turn, player) decision into a dict of plain Python primitives.

    No torch involvement. The shard runner stacks these into numpy arrays in
    one pass at write time.
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

    encoded_slots: list[dict] = [
        _encode_pokemon(s, vocabs, mode) if s is not None else _empty_pokemon()
        for s in (own_4 + opp_4)
    ]

    a_type, a_move, a_switch, a_target, a_mega = _encode_action(action_a, vocabs)
    b_type, b_move, b_switch, b_target, b_mega = _encode_action(action_b, vocabs)

    return {
        "species_ids": [s["species"] for s in encoded_slots],
        "hp_values": [s["hp"] for s in encoded_slots],
        "status_ids": [s["status"] for s in encoded_slots],
        "alive_flags": [s["alive"] for s in encoded_slots],
        "item_ids": [s["item_id"] for s in encoded_slots],
        "item_confidences": [s["item_conf"] for s in encoded_slots],
        "ability_ids": [s["ability_id"] for s in encoded_slots],
        "ability_confidences": [s["ability_conf"] for s in encoded_slots],
        "move_ids": [s["move_ids"] for s in encoded_slots],          # 8 x 4
        "move_confidences": [s["move_confs"] for s in encoded_slots],

        "weather_id": vocabs.weather[turn.get("weather") or "none"],
        "terrain_id": vocabs.terrain[turn.get("terrain") or "none"],
        "trick_room": int(bool(turn.get("trick_room"))),

        "action_a_type": a_type,
        "action_a_move_id": a_move,
        "action_a_switch_id": a_switch,
        "action_a_target": a_target,
        "action_a_mega": a_mega,
        "action_b_type": b_type,
        "action_b_move_id": b_move,
        "action_b_switch_id": b_switch,
        "action_b_target": b_target,
        "action_b_mega": b_mega,
    }


@dataclass
class RawSample:
    """One per-decision sample (Python primitives only) plus metadata."""
    fields: dict          # the per-column lists/scalars from _encode_one_decision_raw
    replay_id: str
    bucket_hour: str
    rating: int
    pov_player: str
    is_winner: bool
    turn_num: int


class Encoder:
    """Turn parsed parquet rows into per-decision raw samples.

    Encoder is pure: no I/O. Construct once with a configured ``Vocabs`` and a
    mode, reuse for many replays. Use ``encode_row`` to iterate samples; the
    runner stacks them into numpy arrays per shard.
    """

    def __init__(self, vocabs: Vocabs, mode: EncodeMode):
        if mode not in ("meta-on", "meta-off"):
            raise ValueError(f"unknown mode: {mode}")
        self.vocabs = vocabs
        self.mode: EncodeMode = mode

    def encode_row(self, row: dict) -> Iterator[RawSample]:
        turns = json.loads(row["turns_json"])
        replay_id = row["replay_id"]
        bucket_hour = row.get("bucket_hour", "") or ""
        rating = max(int(row.get("p1_rating") or 0), int(row.get("p2_rating") or 0))
        winner = row.get("winner", "")

        for turn in turns:
            for pov in ("p1", "p2"):
                fields = _encode_one_decision_raw(turn, pov, self.vocabs, self.mode)
                yield RawSample(
                    fields=fields,
                    replay_id=replay_id,
                    bucket_hour=bucket_hour,
                    rating=rating,
                    pov_player=pov,
                    is_winner=(pov == winner),
                    turn_num=int(turn.get("turn_num", 0)),
                )
