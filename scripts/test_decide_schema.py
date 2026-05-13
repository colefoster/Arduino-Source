#!/usr/bin/env python3
"""Schema round-trip smoke test for the /decide endpoint.

Builds a representative PredictRequest (everything the C++ tracker
emits in to_predict_json), POSTs it to a /decide endpoint, and asserts
the response parses cleanly into DecideResponse.

Two modes:

  $ python3 scripts/test_decide_schema.py
        Local — validates the request schema by round-tripping through
        Pydantic models. Does NOT hit a server. Useful in CI / pre-commit.

  $ python3 scripts/test_decide_schema.py --url http://localhost:8265
        Live — POSTs the request to the given server. Asserts a 200 and
        a parsable DecideResponse. Requires the server to be running.

The request below mirrors the C++ to_predict_json shape: per-mon slots
with volatiles / confidences / move_pp / nature / evs, field state with
hazards / side_timers / last_move, history entries, legal_actions masks.
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Add ml/ to sys.path so we can import the schema.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ml"))

from vgc_model.inference.server import (
    PredictRequest, PokemonState, FieldState, HistoryEntry,
    HazardsState, SideTimers, DecideResponse,
)


def build_representative_request() -> PredictRequest:
    own_a = PokemonState(
        species="garchomp", hp=0.85, status="", alive=True,
        moves=["earthquake", "dragon-claw", "swords-dance", "protect"],
        item="choice-scarf", ability="rough-skin",
        boosts=[2, 0, 0, 0, 1, 0, 0],          # 7-D: atk+2, spe+1
        is_mega=False,
        volatile_statuses=["LOCKEDMOVE"],
        substitute_hp_frac=0.0,
        item_confidence=1.0, ability_confidence=1.0,
        move_confidences=[1.0, 0.0, 0.0, 0.0],
        sleep_turns_remaining=0, toxic_counter=0,
        locked_to_move="earthquake",
        last_move="earthquake",
        nature="Jolly", evs=[0, 252, 0, 0, 4, 252],
        move_pp=[[7, 8], [15, 15], [20, 20], [10, 10]],
    )
    own_b = PokemonState(
        species="rillaboom", hp=1.0, alive=True,
        moves=["grassy-glide", "wood-hammer", "u-turn", "fake-out"],
        item="loaded-dice", ability="grassy-surge",
        boosts=[0]*7,
        item_confidence=1.0, ability_confidence=1.0,
        move_confidences=[1.0, 1.0, 1.0, 1.0],
    )
    opp_a = PokemonState(
        species="incineroar", hp=0.6, status="brn", alive=True,
        moves=["fake-out", "knock-off"], item="safety-goggles",
        ability="intimidate", boosts=[-1, 0, 0, 0, 0, 0, 0],
        volatile_statuses=[],
        item_confidence=1.0, ability_confidence=1.0,
        move_confidences=[1.0, 1.0, 0.0, 0.0],
        last_move="fake-out",
    )
    opp_b = PokemonState(
        species="urshifu", hp=0.95, alive=True,
        moves=[], item="", ability="", boosts=[0]*7,
        item_confidence=0.0, ability_confidence=0.0,
        move_confidences=[0.0]*4,
    )

    field = FieldState(
        weather="", terrain="grassy", trick_room=False,
        tailwind_own=True, tailwind_opp=False,
        screens_own=[False, False, False],
        screens_opp=[True, False, False],   # opp light_screen up
        turn=4,
        hazards_own=HazardsState(stealth_rock=True, spikes=1),
        hazards_opp=HazardsState(),
        side_timers_own=SideTimers(tailwind=3),
        side_timers_opp=SideTimers(light_screen=4),
        last_move_own="earthquake", last_move_opp="fake-out",
    )

    history = [
        HistoryEntry(
            active_species=["garchomp", "rillaboom", "incineroar", "urshifu"],
            active_hp=[1.0, 1.0, 1.0, 1.0],
            action_types=["move", "move", "move", "move"],
            action_moves=["earthquake", "fake-out", "fake-out", "wicked-blow"],
            weather="", terrain="grassy", trick_room=False,
            move_order=[2, 0, 1, 3],
        ),
        HistoryEntry(
            active_species=["garchomp", "rillaboom", "incineroar", "urshifu"],
            active_hp=[0.95, 1.0, 0.7, 1.0],
            action_types=["move", "move", "move", "move"],
            action_moves=["earthquake", "grassy-glide", "knock-off", "u-turn"],
            weather="", terrain="grassy", trick_room=False,
            move_order=[2, 0, 3, 1],
        ),
    ]

    return PredictRequest(
        own_active=[own_a, own_b],
        own_bench=[],
        opp_active=[opp_a, opp_b],
        opp_bench=[],
        field=field,
        legal_actions_a=[
            # Choice-locked into earthquake (slot 0). Only the 3 target
            # rows for move 0 + the 2 switch rows are legal. The other
            # 9 move rows are masked.
            True, True, False,   # move 0 -> opp_a, opp_b, ally
            False, False, False, # move 1
            False, False, False, # move 2
            False, False, False, # move 3
            True, True,          # switch_0, switch_1
        ],
        legal_actions_b=[True]*14,
        history=history,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="Live server URL (empty = local-only schema test)")
    args = ap.parse_args()

    req = build_representative_request()
    body = req.model_dump_json()
    print(f"Built representative PredictRequest: {len(body)} bytes")

    # Always validate the request shape locally first.
    parsed = PredictRequest.model_validate_json(body)
    assert parsed.own_active[0].species == "garchomp"
    assert parsed.own_active[0].locked_to_move == "earthquake"
    assert parsed.field.hazards_own.stealth_rock is True
    assert len(parsed.history) == 2
    print("  [OK] PredictRequest round-trips via Pydantic.")

    if not args.url:
        print("Schema-only mode (no --url). Done.")
        return 0

    # Live mode — POST and validate response.
    target = args.url.rstrip("/") + "/decide"
    print(f"Posting to {target} ...")
    req_obj = urllib.request.Request(
        target,
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_obj, timeout=10) as resp:
        if resp.status != 200:
            print(f"  [FAIL] HTTP {resp.status}: {resp.read()!r}")
            return 1
        raw = resp.read().decode("utf-8")
    resp_obj = DecideResponse.model_validate_json(raw)
    print(f"  [OK] DecideResponse parsed.")
    print(f"  slot_a: action={resp_obj.slot_a.action} p={resp_obj.slot_a.probs[resp_obj.slot_a.action]:.3f}")
    print(f"  slot_b: action={resp_obj.slot_b.action} p={resp_obj.slot_b.probs[resp_obj.slot_b.action]:.3f}")
    if resp_obj.win_pct is not None:
        print(f"  win_pct: {resp_obj.win_pct:.3f}")
    print(f"  meta: model={resp_obj.meta.model_version} impl={resp_obj.meta.endpoint_impl} latency={resp_obj.meta.latency_ms:.1f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
