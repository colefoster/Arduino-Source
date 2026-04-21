#!/usr/bin/env python3
"""Run battles between VGC model players on a local Showdown server.

Prerequisites:
    1. Local Showdown server running (schtasks /Run /TN "ShowdownServer")
    2. Model checkpoint at data/checkpoints/best.pt

Usage:
    python scripts/run_battles.py --n 10
    python scripts/run_battles.py --n 10 --opponent model
    python scripts/run_battles.py --n 10 --team1 data/teams/team_cole_sun.txt
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

import torch

from vgc_model.data.vocab import Vocabs
from vgc_model.model.vgc_model import VGCTransformer, ModelConfig
from vgc_model.inference.model_player import VGCModelPlayer
from poke_env.player.random_player import RandomPlayer
from poke_env.ps_client.server_configuration import ServerConfiguration

DATA_DIR = project_root / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
TEAMS_DIR = DATA_DIR / "teams"


def load_team(path: Path) -> str:
    """Load a Showdown paste team from a text file."""
    return path.read_text().strip()


def get_all_teams() -> list[str]:
    """Load all team files from data/teams/."""
    teams = []
    if TEAMS_DIR.exists():
        for f in sorted(TEAMS_DIR.glob("*.txt")):
            teams.append(load_team(f))
    return teams


def load_model(checkpoint_path: Path, vocabs: Vocabs, device: torch.device):
    """Load a trained model from checkpoint."""
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


async def run_battles(
    n_battles: int = 10,
    opponent_type: str = "random",
    temperature: float = 0.0,
    checkpoint: str = "best.pt",
    server_url: str = "localhost:8000",
    battle_format: str = "gen9championsvgc2026regma",
    team1_path: str = "",
    team2_path: str = "",
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Load teams
    all_teams = get_all_teams()
    if not all_teams:
        print("ERROR: No teams found in data/teams/. Add .txt team files.")
        return

    team1 = load_team(Path(team1_path)) if team1_path else all_teams[0]
    team2 = load_team(Path(team2_path)) if team2_path else (all_teams[1] if len(all_teams) > 1 else all_teams[0])
    print(f"Team 1: {team1_path or 'default'}")
    print(f"Team 2: {team2_path or 'default'}")

    # Load vocabs and model
    vocabs = Vocabs.load(VOCAB_DIR)
    model = load_model(CHECKPOINT_DIR / checkpoint, vocabs, device)

    # Server config
    server_config = ServerConfiguration(server_url, "https://play.pokemonshowdown.com/action.php?")

    # Create players
    player = VGCModelPlayer(
        model=model,
        vocabs=vocabs,
        device=device,
        temperature=temperature,
        battle_format=battle_format,
        server_configuration=server_config,
        max_concurrent_battles=1,
        start_timer_on_battle_start=True,
    )
    player.update_team(team1)

    if opponent_type == "random":
        opponent = RandomPlayer(
            battle_format=battle_format,
            server_configuration=server_config,
            max_concurrent_battles=1,
        )
        opponent.update_team(team2)
        print(f"\nModel (temp={temperature}) vs Random — {n_battles} battles")
    elif opponent_type == "model":
        model2 = load_model(CHECKPOINT_DIR / checkpoint, vocabs, device)
        opponent = VGCModelPlayer(
            model=model2,
            vocabs=vocabs,
            device=device,
            temperature=max(temperature, 0.3),
            battle_format=battle_format,
            server_configuration=server_config,
            max_concurrent_battles=1,
        )
        opponent.update_team(team2)
        print(f"\nModel (temp={temperature}) vs Model (temp={max(temperature, 0.3)}) — {n_battles} battles")
    else:
        raise ValueError(f"Unknown opponent type: {opponent_type}")

    print(f"Format: {battle_format}")
    print(f"Teams: {len(all_teams)} available\n")

    # Run battles
    wins = 0
    losses = 0
    errors = 0

    for i in range(n_battles):
        try:
            # Swap teams periodically for variety
            if i > 0 and i % 5 == 0 and len(all_teams) > 1:
                t1 = random.choice(all_teams)
                t2 = random.choice(all_teams)
                player.update_team(t1)
                opponent.update_team(t2)

            # Alternate who challenges
            if i % 2 == 0:
                await player.battle_against(opponent, n_battles=1)
            else:
                await opponent.battle_against(player, n_battles=1)

            current_wins = player.n_won_battles
            current_total = player.n_finished_battles
            wins = current_wins
            losses = current_total - current_wins

            win_pct = wins / current_total * 100 if current_total > 0 else 0
            print(f"  Battle {i+1}/{n_battles}: {wins}W-{losses}L ({win_pct:.0f}%)", flush=True)

        except Exception as e:
            errors += 1
            print(f"  Battle {i+1}/{n_battles}: ERROR — {e}", flush=True)

    # Final report
    total = wins + losses
    print(f"\n{'='*50}")
    if total > 0:
        print(f"RESULTS: {wins}W - {losses}L ({wins/total*100:.1f}% winrate)")
    else:
        print("No battles completed")
    if errors > 0:
        print(f"Errors: {errors}")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="Run VGC model battles")
    parser.add_argument("--n", type=int, default=10, help="Number of battles")
    parser.add_argument("--opponent", choices=["random", "model"], default="random")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--checkpoint", default="best.pt")
    parser.add_argument("--server", default="localhost:8000")
    parser.add_argument("--format", default="gen9championsvgc2026regma")
    parser.add_argument("--team1", default="", help="Path to player's team file")
    parser.add_argument("--team2", default="", help="Path to opponent's team file")
    args = parser.parse_args()

    asyncio.run(run_battles(
        n_battles=args.n,
        opponent_type=args.opponent,
        temperature=args.temperature,
        checkpoint=args.checkpoint,
        server_url=args.server,
        battle_format=args.format,
        team1_path=args.team1,
        team2_path=args.team2,
    ))


if __name__ == "__main__":
    main()
