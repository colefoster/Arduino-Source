#!/usr/bin/env python3
"""Run battles between VGC model players on a local Showdown server.

Prerequisites:
    1. Local Showdown server running: cd C:/Dev/pokemon-showdown && node pokemon-showdown start --no-security
    2. Model checkpoint at data/checkpoints/best.pt

Usage:
    python scripts/run_battles.py --n 50                        # model vs random, 50 games
    python scripts/run_battles.py --n 50 --opponent model       # model vs model (self-play)
    python scripts/run_battles.py --n 50 --temperature 0.3      # model with sampling
"""

from __future__ import annotations

import argparse
import asyncio
import os
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

DATA_DIR = project_root / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"

# Sample VGC teams (packed Showdown format)
# These are common Champions VGC teams — replace with better ones as needed
SAMPLE_TEAMS = [
    # Team 1: Charizard-Y + Tyranitar core
    "|Charizard||charizarditey|SolarPower|HeatWave,SolarBeam,Protect,AirSlash|Timid|,,,252,4,252|||||]"
    "|Tyranitar||chopleberry|SandStream|RockSlide,Crunch,Protect,LowKick|Adamant|252,252,,,,4|||||]"
    "|Incineroar||sitrusberry|Intimidate|FakeOut,FlareBlitz,KnockOff,Protect|Adamant|252,252,,,,4|||||]"
    "|Sinistcha||focussash|Hospitality|MatchaGotcha,ShadowBall,Protect,TrickRoom|Quiet|252,,,252,4,|||||]"
    "|Garchomp||lifeorb|RoughSkin|Earthquake,DragonClaw,RockSlide,Protect|Jolly|,252,,,4,252|||||]"
    "|Rotom-Wash||sitrusberry|Levitate|HydroPump,Thunderbolt,WillOWisp,Protect|Modest|252,,,252,4,|||||]",

    # Team 2: Rain
    "|Pelipper||damprock|Drizzle|Scald,Hurricane,Tailwind,Protect|Bold|252,,252,,4,|||||]"
    "|Kingdra||choicespecs|SwiftSwim|MuddyWater,DragonPulse,IceBeam,HydroPump|Modest|,,,252,4,252|||||]"
    "|Rillaboom||miracleseed|GrassySurge|GrassyGlide,WoodHammer,FakeOut,Protect|Adamant|252,252,,,,4|||||]"
    "|Corviknight||leftovers|MirrorArmor|BraveBird,IronHead,Tailwind,Protect|Careful|252,,,,252,4|||||]"
    "|Sneasler||focussash|PoisonTouch|CloseCombat,DireClaw,FakeOut,Protect|Jolly|,252,,,4,252|||||]"
    "|Farigiraf||mentalherb|ArmorTail|Psychic,DazzlingGleam,TrickRoom,Protect|Quiet|252,,,252,4,|||||]",
]


def load_model(checkpoint_path: Path, vocabs: Vocabs, device: torch.device):
    """Load a trained model from checkpoint."""
    # Fix pickle path for checkpoints saved via `python -m src.vgc_model...`
    import importlib
    import sys
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
    n_battles: int = 50,
    opponent_type: str = "random",
    temperature: float = 0.0,
    checkpoint: str = "best.pt",
    server_url: str = "localhost:8000",
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Load vocabs and model
    vocabs = Vocabs.load(VOCAB_DIR)
    model = load_model(CHECKPOINT_DIR / checkpoint, vocabs, device)

    # Create players
    player = VGCModelPlayer(
        model=model,
        vocabs=vocabs,
        device=device,
        temperature=temperature,
        battle_format="gen9championsvgc2026regma",
        server_configuration={"server_url": server_url, "authentication_url": None},
        max_concurrent_battles=1,
        start_timer_on_battle_start=True,
    )
    player.update_team(SAMPLE_TEAMS[0])

    if opponent_type == "random":
        opponent = RandomPlayer(
            battle_format="gen9championsvgc2026regma",
            server_configuration={"server_url": server_url, "authentication_url": None},
            max_concurrent_battles=1,
        )
        opponent.update_team(SAMPLE_TEAMS[1])
        print(f"\nModel (temp={temperature}) vs Random — {n_battles} battles")
    elif opponent_type == "model":
        model2 = load_model(CHECKPOINT_DIR / checkpoint, vocabs, device)
        opponent = VGCModelPlayer(
            model=model2,
            vocabs=vocabs,
            device=device,
            temperature=max(temperature, 0.3),  # force some randomness for diversity
            battle_format="gen9championsvgc2026regma",
            server_configuration={"server_url": server_url, "authentication_url": None},
            max_concurrent_battles=1,
        )
        opponent.update_team(SAMPLE_TEAMS[1])
        print(f"\nModel (temp={temperature}) vs Model (temp={max(temperature, 0.3)}) — {n_battles} battles")
    else:
        raise ValueError(f"Unknown opponent type: {opponent_type}")

    # Run battles
    wins = 0
    losses = 0
    errors = 0

    for i in range(n_battles):
        try:
            # Alternate who challenges
            if i % 2 == 0:
                await player.battle_against(opponent, n_battles=1)
            else:
                await opponent.battle_against(player, n_battles=1)

            # Check result
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
    print(f"RESULTS: {wins}W - {losses}L ({wins/total*100:.1f}% winrate)" if total > 0 else "No battles completed")
    if errors > 0:
        print(f"Errors: {errors}")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="Run VGC model battles")
    parser.add_argument("--n", type=int, default=50, help="Number of battles")
    parser.add_argument("--opponent", choices=["random", "model"], default="random")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--checkpoint", default="best.pt")
    parser.add_argument("--server", default="localhost:8000")
    args = parser.parse_args()

    asyncio.run(run_battles(
        n_battles=args.n,
        opponent_type=args.opponent,
        temperature=args.temperature,
        checkpoint=args.checkpoint,
        server_url=args.server,
    ))


if __name__ == "__main__":
    main()
