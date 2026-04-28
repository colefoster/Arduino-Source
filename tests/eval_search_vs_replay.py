"""Layer 4: Full replay evaluation — search vs raw model vs ground truth.

Evaluates whether the search engine picks better moves than the raw
action model by comparing both against what the winning player actually did.

Usage:
    python -m tests.eval_search_vs_replay [--n-games 100] [--min-rating 1400]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.vgc_model.data.log_parser import parse_battle, normalize_species
from src.vgc_model.data.enriched_parser import (
    EnrichedBattleParser, _pass1_extract, _base_species,
    CONF_KNOWN, CONF_USAGE,
)
from src.vgc_model.data.feature_tables import FeatureTables
from src.vgc_model.data.usage_stats import UsageStats
from src.vgc_model.data.vocab import Vocabs
from src.vgc_model.data.dataset import MAX_ACTIONS, BOOST_STATS

REPLAY_DIR = PROJECT_ROOT / "data" / "showdown_replays" / "gen9championsvgc2026regma"
VOCAB_DIR = PROJECT_ROOT / "data" / "vocab"
V2_CHECKPOINT = PROJECT_ROOT / "data" / "checkpoints_v2" / "best.pt"
WINRATE_CHECKPOINT = PROJECT_ROOT / "data" / "checkpoints_winrate" / "best.pt"


def _action_to_index(action, slot_idx, own_active, own_bench, player,
                     full_knowledge=None):
    """Convert a log_parser Action to a flat action index (0-13).

    Uses full_knowledge (from _pass1_extract) to know the full moveset,
    not just progressively revealed moves_known.
    Returns -1 if the action can't be encoded.
    """
    if action is None:
        return -1
    if action.type == "switch":
        for i, p in enumerate(own_bench):
            base = lambda s: s.split("-Mega")[0] if "-Mega" in s else s
            if p.species == action.switch_to or base(p.species) == base(action.switch_to):
                return 12 + min(i, 1)
        return -1
    if action.type == "move":
        if slot_idx >= len(own_active):
            return -1
        poke = own_active[slot_idx]

        # Build full moveset: start with moves_known, add from full_knowledge
        moves = list(poke.moves_known)
        if full_knowledge:
            base_sp = _base_species(poke.species)
            key = f"{player}|{base_sp}"
            fk = full_knowledge.get(key)
            if fk:
                for m in fk.moves:
                    if m not in moves:
                        moves.append(m)

        if action.move in moves:
            mi = moves.index(action.move)
        else:
            return -1
        if mi >= 4:
            return -1  # Can only encode first 4 moves

        # Target encoding: spread moves always target 0
        SPREAD_MOVES = {
            "Earthquake", "Rock Slide", "Heat Wave", "Blizzard", "Hyper Voice",
            "Dazzling Gleam", "Icy Wind", "Eruption", "Water Spout", "Discharge",
            "Sludge Wave", "Surf", "Muddy Water", "Lava Plume", "Electroweb",
            "Struggle Bug", "Breaking Swipe", "Bulldoze", "Matcha Gotcha",
            "Make It Rain",
        }
        ti = 0
        if action.move not in SPREAD_MOVES and action.target:
            tp, ts = action.target[:2], action.target[2]
            ti = 2 if tp == player else (0 if ts == "a" else 1)
        return min(mi, 3) * 3 + min(ti, 2)
    return -1


def _build_predict_request(sample, tp, full_knowledge, ft, us):
    """Convert an enriched sample to a PredictRequest-style dict."""
    player = sample.player
    state = sample.state

    if player == "p1":
        own_active, own_bench = state.p1_active, state.p1_bench
        opp_active, opp_bench = state.p2_active, state.p2_bench
        tw_own = state.field.tailwind_p1
        tw_opp = state.field.tailwind_p2
        sc_own = [state.field.light_screen_p1, state.field.reflect_p1, state.field.aurora_veil_p1]
        sc_opp = [state.field.light_screen_p2, state.field.reflect_p2, state.field.aurora_veil_p2]
    else:
        own_active, own_bench = state.p2_active, state.p2_bench
        opp_active, opp_bench = state.p1_active, state.p1_bench
        tw_own = state.field.tailwind_p2
        tw_opp = state.field.tailwind_p1
        sc_own = [state.field.light_screen_p2, state.field.reflect_p2, state.field.aurora_veil_p2]
        sc_opp = [state.field.light_screen_p1, state.field.reflect_p1, state.field.aurora_veil_p1]

    def _poke_dict(poke, is_own=True):
        if poke is None:
            return {"species": "", "hp": 0.0, "alive": False, "moves": [],
                    "item": "", "ability": "", "boosts": [0]*6, "status": "", "is_mega": False}
        moves = list(poke.moves_known[:4])
        if is_own:
            # Fill from full knowledge
            key = f"{player}|{_base_species(poke.species)}"
            fk = full_knowledge.get(key)
            if fk:
                for m in fk.moves:
                    if m not in moves and len(moves) < 4:
                        moves.append(m)
        elif us and len(moves) < 4:
            moves = us.infer_moveset(poke.species, moves)
        return {
            "species": poke.species, "hp": poke.hp, "alive": not poke.fainted,
            "moves": moves,
            "item": poke.item, "ability": poke.ability,
            "boosts": [poke.boosts.get(s, 0) for s in BOOST_STATS],
            "status": poke.status, "is_mega": poke.mega,
        }

    own_a = [_poke_dict(p, True) for p in own_active[:2]]
    own_b = [_poke_dict(p, True) for p in own_bench[:2]]
    opp_a = [_poke_dict(p, False) for p in opp_active[:2]]
    opp_b = [_poke_dict(p, False) for p in opp_bench[:2]]

    return {
        "own_active": own_a, "own_bench": own_b,
        "opp_active": opp_a, "opp_bench": opp_b,
        "field": {
            "weather": state.field.weather, "terrain": state.field.terrain,
            "trick_room": state.field.trick_room,
            "tailwind_own": tw_own, "tailwind_opp": tw_opp,
            "screens_own": sc_own, "screens_opp": sc_opp,
            "turn": state.turn,
        },
    }


def evaluate(n_games=100, min_rating=1400, n_rollouts=50):
    """Run evaluation and print results."""
    print(f"Loading models...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    vocabs = Vocabs.load(VOCAB_DIR)
    ft = FeatureTables()
    try:
        us = UsageStats()
    except Exception:
        us = None

    # Load search engine
    from src.vgc_model.inference.search import SearchEngine
    from src.vgc_model.model.vgc_model_v2_seq import VGCTransformerV2Seq, ModelConfigV2Seq
    from src.vgc_model.model.winrate_model import WinrateModel, WinrateModelConfig

    if not V2_CHECKPOINT.exists():
        print(f"ERROR: No v2 checkpoint at {V2_CHECKPOINT}")
        return
    if not WINRATE_CHECKPOINT.exists():
        print(f"ERROR: No winrate checkpoint at {WINRATE_CHECKPOINT}")
        return

    v2_ckpt = torch.load(V2_CHECKPOINT, map_location=device, weights_only=False)
    v2_config = v2_ckpt.get("config", ModelConfigV2Seq())
    action_model = VGCTransformerV2Seq(vocabs, v2_config).to(device)
    action_model.load_state_dict(v2_ckpt["model_state_dict"])
    action_model.eval()

    wr_ckpt = torch.load(WINRATE_CHECKPOINT, map_location=device, weights_only=False)
    wr_config = wr_ckpt.get("config", WinrateModelConfig())
    winrate_model = WinrateModel(vocabs, wr_config).to(device)
    winrate_model.load_state_dict(wr_ckpt["model_state_dict"])
    winrate_model.eval()

    engine = SearchEngine(action_model, winrate_model, vocabs, ft, us, device)
    print(f"Models loaded. Device: {device}")

    # Find replay files
    files = sorted(REPLAY_DIR.glob("*.json"))
    random.seed(42)
    random.shuffle(files)

    # Metrics
    model_match_a = model_match_b = 0
    search_match_a = search_match_b = 0
    total_a = total_b = 0
    search_winpcts_correct = []
    search_winpcts_incorrect = []
    games_processed = 0
    turns_processed = 0

    print(f"Evaluating {n_games} games at min_rating={min_rating}...")
    t0 = time.time()

    for f in files:
        if games_processed >= n_games:
            break

        try:
            data = json.loads(f.read_text(errors="replace"))
        except Exception:
            continue

        rating = data.get("rating") or 0
        if rating < min_rating:
            continue

        log = data.get("log", "")
        if not log:
            continue

        try:
            result = parse_battle(log, rating)
        except Exception:
            continue
        if result is None:
            continue

        tp = result.team_preview
        try:
            full_knowledge = _pass1_extract(log)
        except Exception:
            continue

        # Process winner's turns only
        winner_samples = [s for s in result.samples if s.is_winner]

        for sample in winner_samples:
            player = sample.player
            state = sample.state
            own_active = state.p1_active if player == "p1" else state.p2_active
            own_bench = state.p1_bench if player == "p1" else state.p2_bench

            # Encode ground truth actions (using full knowledge for moveset)
            gt_a = _action_to_index(sample.actions.slot_a, 0, own_active, own_bench, player,
                                    full_knowledge)
            gt_b = _action_to_index(sample.actions.slot_b, 1, own_active, own_bench, player,
                                    full_knowledge)

            if gt_a < 0 and gt_b < 0:
                continue

            # Build request
            try:
                req = _build_predict_request(sample, tp, full_knowledge, ft, us)
            except Exception:
                continue

            # Raw model prediction
            try:
                batch = engine._build_v2_batch(req, perspective="own")
                with torch.no_grad():
                    out = action_model(batch)
                model_a = out["logits_a"].squeeze(0).argmax().item()
                model_b = out["logits_b"].squeeze(0).argmax().item()
            except Exception:
                continue

            # Search prediction
            try:
                search_result = engine.search(req, n_rollouts=n_rollouts)
                search_a = search_result.action_a
                search_b = search_result.action_b
            except Exception:
                search_a = model_a
                search_b = model_b

            # Score
            if gt_a >= 0:
                total_a += 1
                if model_a == gt_a:
                    model_match_a += 1
                if search_a == gt_a:
                    search_match_a += 1
                    search_winpcts_correct.append(search_result.win_pct)
                else:
                    search_winpcts_incorrect.append(search_result.win_pct)

            if gt_b >= 0:
                total_b += 1
                if model_b == gt_b:
                    model_match_b += 1
                if search_b == gt_b:
                    search_match_b += 1

            turns_processed += 1

        games_processed += 1
        if games_processed % 10 == 0:
            elapsed = time.time() - t0
            print(f"  {games_processed}/{n_games} games, {turns_processed} turns, {elapsed:.0f}s")

    elapsed = time.time() - t0

    # Results
    total = total_a + total_b
    model_match = model_match_a + model_match_b
    search_match = search_match_a + search_match_b

    model_acc = model_match / total * 100 if total else 0
    search_acc = search_match / total * 100 if total else 0
    lift = search_acc - model_acc

    print(f"\n{'='*60}")
    print(f"EVALUATION RESULTS ({games_processed} games, {turns_processed} turns)")
    print(f"{'='*60}")
    print(f"  Rating: >= {min_rating}")
    print(f"  Rollouts: {n_rollouts}")
    print(f"  Time: {elapsed:.0f}s ({elapsed/max(turns_processed,1):.2f}s/turn)")
    print(f"")
    print(f"  Raw model top-1:  {model_acc:.1f}% ({model_match}/{total})")
    print(f"  Search top-1:     {search_acc:.1f}% ({search_match}/{total})")
    print(f"  Search lift:      {lift:+.1f}%")
    print(f"")
    if search_winpcts_correct:
        print(f"  Avg win% when search agrees with winner:    {sum(search_winpcts_correct)/len(search_winpcts_correct):.3f}")
    if search_winpcts_incorrect:
        print(f"  Avg win% when search disagrees with winner: {sum(search_winpcts_incorrect)/len(search_winpcts_incorrect):.3f}")
    print(f"{'='*60}")

    # Save results
    results = {
        "meta": {
            "n_games": games_processed, "n_turns": turns_processed,
            "min_rating": min_rating, "n_rollouts": n_rollouts,
            "elapsed_sec": round(elapsed, 1),
        },
        "model_top1": round(model_acc, 2),
        "search_top1": round(search_acc, 2),
        "search_lift": round(lift, 2),
    }

    out_path = PROJECT_ROOT / "data" / "eval_results"
    out_path.mkdir(exist_ok=True)
    out_file = out_path / f"search_eval_{int(time.time())}.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {out_file}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate search engine vs raw model")
    parser.add_argument("--n-games", type=int, default=100)
    parser.add_argument("--min-rating", type=int, default=1400)
    parser.add_argument("--n-rollouts", type=int, default=50)
    args = parser.parse_args()
    evaluate(n_games=args.n_games, min_rating=args.min_rating, n_rollouts=args.n_rollouts)


if __name__ == "__main__":
    main()
