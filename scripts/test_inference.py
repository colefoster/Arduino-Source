#!/usr/bin/env python3
"""Quick test of the inference server's predict + team-select endpoints."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vgc_model.inference.server import (
    load_model, predict, team_select,
    PredictRequest, PokemonState, FieldState, TeamSelectRequest,
)

ACTION_NAMES = []
for mi in range(4):
    for tn in ["opp_a", "opp_b", "ally"]:
        ACTION_NAMES.append(f"move{mi}_{tn}")
ACTION_NAMES += ["switch_0", "switch_1"]


def main():
    load_model("data/checkpoints/best.pt", "data/vocab")

    # --- Battle prediction ---
    req = PredictRequest(
        own_active=[
            PokemonState(species="Kingambit", hp=1.0,
                         moves=["Sucker Punch", "Iron Head", "Swords Dance", "Protect"]),
            PokemonState(species="Dragapult", hp=0.8,
                         moves=["Dragon Darts", "U-turn", "Dragon Dance", "Phantom Force"]),
        ],
        opp_active=[
            PokemonState(species="Hawlucha", hp=0.67),
            PokemonState(species="Hydreigon", hp=0.34),
        ],
        field=FieldState(turn=3),
    )

    result = predict(req)

    print("=== Battle Prediction ===")
    print(f"Slot A best: {ACTION_NAMES[result.slot_a.action]}")
    top3a = sorted(enumerate(result.slot_a.probs), key=lambda x: -x[1])[:3]
    for i, p in top3a:
        print(f"  {ACTION_NAMES[i]:20s} {p:.3f}")

    print(f"Slot B best: {ACTION_NAMES[result.slot_b.action]}")
    top3b = sorted(enumerate(result.slot_b.probs), key=lambda x: -x[1])[:3]
    for i, p in top3b:
        print(f"  {ACTION_NAMES[i]:20s} {p:.3f}")

    # --- Team selection ---
    ts = team_select(TeamSelectRequest(
        own_team=["Kingambit", "Dragapult", "Glimmora", "Rotom", "Sylveon", "Sinistcha"],
        opp_team=["Hawlucha", "Hydreigon", "Corviknight", "Gardevoir", "Azumarill", "Abomasnow"],
    ))

    own = ["Kingambit", "Dragapult", "Glimmora", "Rotom", "Sylveon", "Sinistcha"]
    print("\n=== Team Selection ===")
    print(f"Bring: {[own[i] for i in ts.bring]}")
    print(f"Lead:  {[own[ts.bring[i]] for i in ts.lead]}")
    print(f"Scores: {[round(s,2) for s in ts.bring_scores]}")


if __name__ == "__main__":
    main()
