#!/usr/bin/env python3
"""Play on the real Pokemon Showdown ladder.

Usage:
    python scripts/ladder.py --n 10
    python scripts/ladder.py --n 10 --team data/teams/team_cole_sun.txt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

import torch

from vgc_model.data.vocab import Vocabs
from vgc_model.model.vgc_model import VGCTransformer, ModelConfig
from vgc_model.inference.model_player import VGCModelPlayer
from poke_env.ps_client.server_configuration import ShowdownServerConfiguration
from poke_env.ps_client.account_configuration import AccountConfiguration

DATA_DIR = project_root / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
TEAMS_DIR = DATA_DIR / "teams"

# Showdown account
USERNAME = "pgvifs"
PASSWORD = "Asdf1029"


def load_model(checkpoint_path: Path, vocabs: Vocabs, device: torch.device):
    import importlib
    if "src" not in sys.modules:
        sys.modules["src"] = type(sys)("src")
        sys.modules["src.vgc_model"] = importlib.import_module("vgc_model")
        sys.modules["src.vgc_model.model"] = importlib.import_module("vgc_model.model")
        sys.modules["src.vgc_model.model.vgc_model"] = importlib.import_module("vgc_model.model.vgc_model")

    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    config = checkpoint.get("config", ModelConfig())
    model = VGCTransformer(vocabs, config)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()

    epoch = checkpoint.get("epoch", "?")
    val_loss = checkpoint.get("val_loss", 0)
    print(f"Loaded model from epoch {epoch} (val_loss={val_loss:.4f})")
    return model


def get_all_teams() -> list[str]:
    teams = []
    if TEAMS_DIR.exists():
        for f in sorted(TEAMS_DIR.glob("*.txt")):
            teams.append(f.read_text().strip())
    return teams


async def run_ladder(
    n_games: int = 10,
    temperature: float = 0.0,
    checkpoint: str = "best.pt",
    team_path: str = "",
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    print(f"Account: {USERNAME}")
    print(f"Server: sim3.psim.us (public ladder)")

    # Load
    vocabs = Vocabs.load(VOCAB_DIR)
    model = load_model(CHECKPOINT_DIR / checkpoint, vocabs, device)

    all_teams = get_all_teams()
    team = Path(team_path).read_text().strip() if team_path else (all_teams[0] if all_teams else None)
    if not team:
        print("ERROR: No team found")
        return

    # Create player with real account
    account = AccountConfiguration(USERNAME, PASSWORD)
    player = VGCModelPlayer(
        model=model,
        vocabs=vocabs,
        device=device,
        temperature=temperature,
        account_configuration=account,
        battle_format="gen9championsvgc2026regma",
        server_configuration=ShowdownServerConfiguration,
        max_concurrent_battles=1,
        start_timer_on_battle_start=True,
    )
    player.update_team(team)

    print(f"\nLaddering: {n_games} games, temp={temperature}")
    print(f"Team: {team_path or 'default'}\n")

    # Battle log
    battle_log_path = DATA_DIR / "checkpoints" / "battle_log.jsonl"

    for i in range(n_games):
        try:
            print(f"  Searching for game {i+1}/{n_games}...", flush=True)

            # Queue for a ladder game
            await player.ladder(1)

            # Wait for the battle to finish
            while player.n_finished_battles <= i:
                await asyncio.sleep(1)

            wins = player.n_won_battles
            total = player.n_finished_battles
            losses = total - wins
            win_pct = wins / total * 100

            # Log battle
            if player._battles:
                battle_tag = list(player._battles.keys())[-1]
                battle = player._battles[battle_tag]

                opp_name = "?"
                if hasattr(battle, '_opponent_username'):
                    opp_name = battle._opponent_username

                our_team = []
                for poke in battle.team.values():
                    our_team.append({
                        "species": poke.species,
                        "fainted": poke.fainted,
                        "hp": round(poke.current_hp_fraction, 2) if not poke.fainted else 0,
                    })

                opp_team = []
                for poke in (battle.opponent_team or {}).values():
                    opp_team.append({
                        "species": poke.species,
                        "fainted": poke.fainted,
                        "hp": round(poke.current_hp_fraction, 2) if not poke.fainted else 0,
                    })

                entry = {
                    "battle_num": i + 1,
                    "timestamp": time.time(),
                    "won": battle.won,
                    "turns": battle.turn,
                    "our_team": our_team,
                    "opp_team": opp_team,
                    "opponent": opp_name,
                    "ladder": True,
                    "battle_tag": battle_tag,
                }
                with open(battle_log_path, "a") as f:
                    json.dump(entry, f)
                    f.write("\n")

                result = "WIN" if battle.won else "LOSS"
                print(f"  Game {i+1}: {result} vs {opp_name} ({battle.turn}t) — {wins}W-{losses}L ({win_pct:.0f}%)", flush=True)

            # Swap team occasionally
            if i > 0 and i % 5 == 0 and len(all_teams) > 1:
                team = random.choice(all_teams)
                player.update_team(team)

        except Exception as e:
            print(f"  Game {i+1}: ERROR — {e}", flush=True)

    total = player.n_finished_battles
    wins = player.n_won_battles
    losses = total - wins
    print(f"\n{'='*50}")
    if total > 0:
        print(f"LADDER RESULTS: {wins}W - {losses}L ({wins/total*100:.1f}%)")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="Play on Showdown ladder")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--checkpoint", default="best.pt")
    parser.add_argument("--team", default="")
    args = parser.parse_args()

    asyncio.run(run_ladder(
        n_games=args.n,
        temperature=args.temperature,
        checkpoint=args.checkpoint,
        team_path=args.team,
    ))


if __name__ == "__main__":
    main()
