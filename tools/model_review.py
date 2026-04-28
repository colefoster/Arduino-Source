#!/usr/bin/env python3
"""Model Review Dashboard — turn-by-turn replay analysis.

Loads VGC replay JSONs, runs the trained model on each turn,
and shows predicted vs actual actions in a web UI.

Usage:
    python tools/model_review.py [--port 8421] [--replays 10] [--device auto]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup — import from src/vgc_model/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import torch
import torch.nn.functional as F
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from vgc_model.data.log_parser import (
    parse_battle, BattleParser, ParsedBattle, TrainingSample,
    GameState, Pokemon, Action, TurnActions, FieldState,
)
from vgc_model.data.dataset import VGCDataset, EncodedSample, MAX_ACTIONS, BOOST_STATS
from vgc_model.data.vocab import Vocabs, Vocabulary
from vgc_model.model.vgc_model import VGCTransformer, ModelConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_DIR = DATA_DIR / "vocab"
CHECKPOINT_PATH = DATA_DIR / "checkpoints" / "best.pt"

# Replay directories — search multiple layouts (local flat + ash spectated/downloaded)
REPLAY_BASE = DATA_DIR / "showdown_replays"
VGC_FMT = "gen9championsvgc2026regma"
REPLAY_SEARCH_DIRS = [
    REPLAY_BASE / VGC_FMT,                    # local flat layout
    REPLAY_BASE / "spectated" / VGC_FMT,      # ash spectated
    REPLAY_BASE / "downloaded" / VGC_FMT,     # ash downloaded
]

# ---------------------------------------------------------------------------
# Global state (loaded at startup)
# ---------------------------------------------------------------------------
vocabs: Optional[Vocabs] = None
model: Optional[VGCTransformer] = None
device: torch.device = torch.device("cpu")
replay_cache: dict[str, dict] = {}  # replay_id -> analysis result


# ---------------------------------------------------------------------------
# Encoding helper (adapted from VGCDataset._encode_sample)
# ---------------------------------------------------------------------------

def encode_sample_standalone(
    sample: TrainingSample, battle: ParsedBattle, v: Vocabs
) -> dict[str, torch.Tensor]:
    """Encode a single TrainingSample into model input tensors (batch size 1)."""
    player = sample.player
    state = sample.state

    if player == "p1":
        own_active = state.p1_active
        own_bench = state.p1_bench
        opp_active = state.p2_active
        opp_bench = state.p2_bench
        tailwind_own = state.field.tailwind_p1
        tailwind_opp = state.field.tailwind_p2
        screens_own = [
            int(state.field.light_screen_p1),
            int(state.field.reflect_p1),
            int(state.field.aurora_veil_p1),
        ]
        screens_opp = [
            int(state.field.light_screen_p2),
            int(state.field.reflect_p2),
            int(state.field.aurora_veil_p2),
        ]
    else:
        own_active = state.p2_active
        own_bench = state.p2_bench
        opp_active = state.p1_active
        opp_bench = state.p1_bench
        tailwind_own = state.field.tailwind_p2
        tailwind_opp = state.field.tailwind_p1
        screens_own = [
            int(state.field.light_screen_p2),
            int(state.field.reflect_p2),
            int(state.field.aurora_veil_p2),
        ]
        screens_opp = [
            int(state.field.light_screen_p1),
            int(state.field.reflect_p1),
            int(state.field.aurora_veil_p1),
        ]

    # 8 slots: own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1
    all_pokemon: list[Optional[Pokemon]] = [None] * 8
    if len(own_active) > 0: all_pokemon[0] = own_active[0]
    if len(own_active) > 1: all_pokemon[1] = own_active[1]
    if len(own_bench) > 0:  all_pokemon[2] = own_bench[0]
    if len(own_bench) > 1:  all_pokemon[3] = own_bench[1]
    if len(opp_active) > 0: all_pokemon[4] = opp_active[0]
    if len(opp_active) > 1: all_pokemon[5] = opp_active[1]
    if len(opp_bench) > 0:  all_pokemon[6] = opp_bench[0]
    if len(opp_bench) > 1:  all_pokemon[7] = opp_bench[1]

    species_ids = []
    hp_values = []
    status_ids = []
    boost_values = []
    item_ids = []
    ability_ids = []
    mega_flags = []
    alive_flags = []
    move_ids = []

    for poke in all_pokemon:
        if poke is None:
            species_ids.append(0)
            hp_values.append(0.0)
            status_ids.append(0)
            boost_values.append([0] * 6)
            item_ids.append(0)
            ability_ids.append(0)
            mega_flags.append(0)
            alive_flags.append(0)
            move_ids.append([0, 0, 0, 0])
        else:
            species_ids.append(v.species[poke.species])
            hp_values.append(poke.hp)
            status_ids.append(v.status[poke.status] if poke.status else 0)
            boosts = [poke.boosts.get(s, 0) for s in BOOST_STATS]
            boost_values.append(boosts)
            item_ids.append(v.items[poke.item] if poke.item else 0)
            ability_ids.append(v.abilities[poke.ability] if poke.ability else 0)
            mega_flags.append(int(poke.mega))
            alive_flags.append(1)
            moves = poke.moves_known[:4]
            midx = [v.moves[m] for m in moves]
            midx += [0] * (4 - len(midx))
            move_ids.append(midx)

    mask_a = [1] * MAX_ACTIONS
    mask_b = [1] * MAX_ACTIONS

    # Team preview data
    tp = battle.team_preview
    own_team = tp.p1_team if player == "p1" else tp.p2_team
    opp_team = tp.p2_team if player == "p1" else tp.p1_team
    selected = (tp.p1_selected if player == "p1" else tp.p2_selected)[:4]

    own_team_ids = [v.species[s] for s in own_team[:6]]
    own_team_ids += [0] * (6 - len(own_team_ids))
    opp_team_ids = [v.species[s] for s in opp_team[:6]]
    opp_team_ids += [0] * (6 - len(opp_team_ids))
    selected_ids = [v.species[s] for s in selected[:4]]
    selected_ids += [0] * (4 - len(selected_ids))

    # Build tensor dict (batch dim = 1)
    return {
        "species_ids": torch.tensor([species_ids], dtype=torch.long),
        "hp_values": torch.tensor([hp_values], dtype=torch.float),
        "status_ids": torch.tensor([status_ids], dtype=torch.long),
        "boost_values": torch.tensor([boost_values], dtype=torch.float),
        "item_ids": torch.tensor([item_ids], dtype=torch.long),
        "ability_ids": torch.tensor([ability_ids], dtype=torch.long),
        "mega_flags": torch.tensor([mega_flags], dtype=torch.float),
        "alive_flags": torch.tensor([alive_flags], dtype=torch.float),
        "move_ids": torch.tensor([move_ids], dtype=torch.long),
        "weather_id": torch.tensor([v.weather[state.field.weather] if state.field.weather else 0], dtype=torch.long),
        "terrain_id": torch.tensor([v.terrain[state.field.terrain] if state.field.terrain else 0], dtype=torch.long),
        "trick_room": torch.tensor([int(state.field.trick_room)], dtype=torch.float),
        "tailwind_own": torch.tensor([int(tailwind_own)], dtype=torch.float),
        "tailwind_opp": torch.tensor([int(tailwind_opp)], dtype=torch.float),
        "screens_own": torch.tensor([screens_own], dtype=torch.float),
        "screens_opp": torch.tensor([screens_opp], dtype=torch.float),
        "turn": torch.tensor([min(state.turn, 30)], dtype=torch.float),
        "action_mask_a": torch.tensor([mask_a], dtype=torch.bool),
        "action_mask_b": torch.tensor([mask_b], dtype=torch.bool),
        "own_team_ids": torch.tensor([own_team_ids], dtype=torch.long),
        "opp_team_ids": torch.tensor([opp_team_ids], dtype=torch.long),
        "selected_ids": torch.tensor([selected_ids], dtype=torch.long),
        "has_team_preview": torch.tensor([True], dtype=torch.bool),
    }


# ---------------------------------------------------------------------------
# Action decoding
# ---------------------------------------------------------------------------

TARGET_NAMES = ["opp_a", "opp_b", "ally"]


def decode_action(
    action_idx: int,
    own_active: list[Pokemon],
    own_bench: list[Pokemon],
    slot_idx: int,
) -> str:
    """Decode action index to human-readable string."""
    if action_idx >= 12:
        bench_idx = action_idx - 12
        if bench_idx < len(own_bench):
            return f"Switch → {own_bench[bench_idx].species}"
        return f"Switch → bench[{bench_idx}]"

    move_idx = action_idx // 3
    target_idx = action_idx % 3

    move_name = "?"
    if slot_idx < len(own_active):
        poke = own_active[slot_idx]
        if move_idx < len(poke.moves_known):
            move_name = poke.moves_known[move_idx]
        else:
            move_name = f"move[{move_idx}]"

    target = TARGET_NAMES[target_idx]
    return f"{move_name} → {target}"


def encode_action_from_log(
    action: Optional[Action],
    slot_idx: int,
    own_active: list[Pokemon],
    own_bench: list[Pokemon],
    player: str,
) -> int:
    """Re-encode a log Action to an action index (mirrors VGCDataset._encode_action)."""
    if action is None:
        return 0

    if action.type == "switch":
        for i, poke in enumerate(own_bench):
            base = lambda s: s.split("-Mega")[0] if "-Mega" in s else s
            if poke.species == action.switch_to or base(poke.species) == base(action.switch_to):
                return 12 + min(i, 1)
        return 12

    if action.type == "move":
        move_idx = 0
        if slot_idx < len(own_active):
            poke = own_active[slot_idx]
            if action.move in poke.moves_known:
                move_idx = poke.moves_known.index(action.move)

        target_idx = 0
        if action.target:
            target_player = action.target[:2]
            target_slot = action.target[2]
            if target_player == player:
                target_idx = 2
            else:
                target_idx = 0 if target_slot == "a" else 1

        return min(move_idx, 3) * 3 + min(target_idx, 2)

    return 0


def describe_action_from_log(action: Optional[Action]) -> str:
    """Human-readable description of a log Action."""
    if action is None:
        return "—"
    if action.type == "switch":
        return f"Switch → {action.switch_to}"
    if action.type == "move":
        target = f" → {action.target}" if action.target else ""
        mega = " (Mega)" if action.mega else ""
        return f"{action.move}{target}{mega}"
    return "?"


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------

def analyze_replay(replay_path: Path) -> Optional[dict]:
    """Parse a replay and run the model on each turn. Returns analysis dict."""
    try:
        data = json.loads(replay_path.read_text())
        log = data.get("log", "")
        rating = data.get("rating", 0)
    except Exception:
        return None

    result = parse_battle(log, rating)
    if result is None:
        return None

    # Filter to winner samples only
    winner_samples = [s for s in result.samples if s.is_winner]
    if not winner_samples:
        return None

    turns = []
    match_count_a = 0
    match_count_b = 0
    total_a = 0
    total_b = 0

    for sample in winner_samples:
        player = sample.player
        state = sample.state

        if player == "p1":
            own_active = state.p1_active
            own_bench = state.p1_bench
            opp_active = state.p2_active
            opp_bench = state.p2_bench
        else:
            own_active = state.p2_active
            own_bench = state.p2_bench
            opp_active = state.p1_active
            opp_bench = state.p1_bench

        # Encode and run model
        try:
            batch = encode_sample_standalone(sample, result, vocabs)
            batch_dev = {k: v.to(device) for k, v in batch.items()}

            with torch.no_grad():
                out = model(batch_dev)

            probs_a = F.softmax(out["logits_a"][0], dim=-1).cpu()
            probs_b = F.softmax(out["logits_b"][0], dim=-1).cpu()
        except Exception as e:
            continue

        # Top 3 predictions for each slot
        def top3(probs, own_act, own_bn, slot_idx):
            vals, idxs = probs.topk(min(3, len(probs)))
            return [
                {"action": decode_action(idx.item(), own_act, own_bn, slot_idx),
                 "prob": round(val.item() * 100, 1),
                 "idx": idx.item()}
                for val, idx in zip(vals, idxs)
            ]

        preds_a = top3(probs_a, own_active, own_bench, 0)
        preds_b = top3(probs_b, own_active, own_bench, 1)

        # Actual actions
        actual_a = sample.actions.slot_a
        actual_b = sample.actions.slot_b

        actual_a_idx = encode_action_from_log(actual_a, 0, own_active, own_bench, player)
        actual_b_idx = encode_action_from_log(actual_b, 1, own_active, own_bench, player)

        match_a = preds_a[0]["idx"] == actual_a_idx if preds_a else False
        match_b = preds_b[0]["idx"] == actual_b_idx if preds_b else False

        if actual_a is not None:
            total_a += 1
            if match_a:
                match_count_a += 1
        if actual_b is not None:
            total_b += 1
            if match_b:
                match_count_b += 1

        # Field conditions
        field_conds = []
        if state.field.weather:
            field_conds.append(state.field.weather)
        if state.field.terrain:
            field_conds.append(f"{state.field.terrain} Terrain")
        if state.field.trick_room:
            field_conds.append("Trick Room")
        tw_own = state.field.tailwind_p1 if player == "p1" else state.field.tailwind_p2
        tw_opp = state.field.tailwind_p2 if player == "p1" else state.field.tailwind_p1
        if tw_own:
            field_conds.append("Own Tailwind")
        if tw_opp:
            field_conds.append("Opp Tailwind")

        turn_data = {
            "turn": state.turn,
            "own_active": [
                {"species": p.species, "hp": round(p.hp * 100, 1), "status": p.status}
                for p in own_active
            ],
            "opp_active": [
                {"species": p.species, "hp": round(p.hp * 100, 1), "status": p.status}
                for p in opp_active
            ],
            "own_bench": [
                {"species": p.species, "hp": round(p.hp * 100, 1)}
                for p in own_bench
            ],
            "opp_bench": [
                {"species": p.species, "hp": round(p.hp * 100, 1)}
                for p in opp_bench
            ],
            "field": field_conds,
            "slot_a": {
                "actual": describe_action_from_log(actual_a),
                "actual_idx": actual_a_idx,
                "predictions": preds_a,
                "match": match_a,
            },
            "slot_b": {
                "actual": describe_action_from_log(actual_b),
                "actual_idx": actual_b_idx,
                "predictions": preds_b,
                "match": match_b,
            },
        }
        turns.append(turn_data)

    total = total_a + total_b
    matches = match_count_a + match_count_b

    return {
        "id": data.get("id", replay_path.stem),
        "players": data.get("players", []),
        "rating": rating,
        "winner": result.winner,
        "total_turns": len(turns),
        "accuracy": round(matches / total * 100, 1) if total > 0 else 0,
        "matches": matches,
        "total_actions": total,
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="VGC Model Review")


@app.get("/api/replays")
async def list_replays():
    return [
        {"id": rid, "accuracy": r["accuracy"], "rating": r["rating"],
         "players": r["players"], "total_turns": r["total_turns"],
         "winner": r["winner"]}
        for rid, r in replay_cache.items()
    ]


@app.get("/api/replay/{replay_id}")
async def get_replay(replay_id: str):
    if replay_id in replay_cache:
        return replay_cache[replay_id]
    return JSONResponse({"error": "Replay not found"}, status_code=404)


@app.get("/api/summary")
async def summary():
    if not replay_cache:
        return {"total_replays": 0, "avg_accuracy": 0, "total_turns": 0}
    total_matches = sum(r["matches"] for r in replay_cache.values())
    total_actions = sum(r["total_actions"] for r in replay_cache.values())
    return {
        "total_replays": len(replay_cache),
        "avg_accuracy": round(total_matches / total_actions * 100, 1) if total_actions > 0 else 0,
        "total_turns": sum(r["total_turns"] for r in replay_cache.values()),
        "total_matches": total_matches,
        "total_actions": total_actions,
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML_PAGE)


# ---------------------------------------------------------------------------
# HTML (embedded)
# ---------------------------------------------------------------------------

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VGC Model Review</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --text-bright: #f0f6fc;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --blue: #58a6ff; --purple: #bc8cff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.5; padding: 20px; max-width: 1200px; margin: 0 auto; }
  h1 { color: var(--text-bright); font-size: 24px; margin-bottom: 4px; }
  .subtitle { color: var(--text-dim); margin-bottom: 20px; }

  /* Summary bar */
  .summary { display: flex; gap: 24px; padding: 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 20px; flex-wrap: wrap; }
  .stat { text-align: center; }
  .stat .val { font-size: 28px; font-weight: 700; color: var(--text-bright); }
  .stat .lbl { font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }

  /* Selector */
  .controls { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; flex-wrap: wrap; }
  select { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 14px; min-width: 300px; }
  select:focus { outline: none; border-color: var(--blue); }

  /* Turn card */
  .turn-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .turn-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  .turn-num { font-size: 16px; font-weight: 700; color: var(--text-bright); }
  .field-tags { display: flex; gap: 6px; flex-wrap: wrap; }
  .tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; background: #1f2937; color: var(--purple); border: 1px solid var(--purple); }

  /* Pokemon row */
  .pokemon-row { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .side { flex: 1; min-width: 200px; }
  .side-label { font-size: 11px; text-transform: uppercase; color: var(--text-dim); letter-spacing: 0.5px; margin-bottom: 4px; }
  .poke { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: #1f2937; border-radius: 4px; margin-right: 6px; margin-bottom: 4px; }
  .poke .name { font-weight: 600; color: var(--text-bright); }
  .hp-bar { width: 50px; height: 6px; background: #21262d; border-radius: 3px; overflow: hidden; display: inline-block; }
  .hp-bar .fill { height: 100%; border-radius: 3px; }
  .hp-green { background: var(--green); }
  .hp-yellow { background: var(--yellow); }
  .hp-red { background: var(--red); }
  .status-badge { font-size: 10px; padding: 1px 4px; border-radius: 2px; background: var(--yellow); color: #000; font-weight: 700; }

  /* Slots */
  .slots { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .slot { padding: 12px; border-radius: 6px; border: 1px solid var(--border); }
  .slot-label { font-size: 12px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; margin-bottom: 8px; }
  .actual { margin-bottom: 8px; }
  .actual-label { font-size: 11px; color: var(--text-dim); }
  .actual-action { font-weight: 600; font-size: 15px; }
  .pred-label { font-size: 11px; color: var(--text-dim); margin-bottom: 4px; }
  .pred-row { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
  .pred-rank { font-size: 11px; color: var(--text-dim); width: 16px; }
  .pred-action { flex: 1; }
  .pred-prob { font-size: 12px; font-weight: 600; color: var(--blue); min-width: 50px; text-align: right; }
  .pred-bar { width: 60px; height: 4px; background: #21262d; border-radius: 2px; overflow: hidden; }
  .pred-bar .fill { height: 100%; background: var(--blue); border-radius: 2px; }

  .match-yes { border-left: 3px solid var(--green); }
  .match-no { border-left: 3px solid var(--red); }
  .match-badge { font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 3px; }
  .match-badge.yes { background: rgba(63,185,80,0.15); color: var(--green); }
  .match-badge.no { background: rgba(248,81,73,0.15); color: var(--red); }
  .match-badge.na { background: rgba(139,148,158,0.15); color: var(--text-dim); }

  .loading { text-align: center; padding: 60px; color: var(--text-dim); }
  .error { background: rgba(248,81,73,0.1); border: 1px solid var(--red); border-radius: 8px; padding: 16px; color: var(--red); }

  @media (max-width: 768px) {
    .slots { grid-template-columns: 1fr; }
    .summary { gap: 16px; }
    select { min-width: unset; width: 100%; }
  }
</style>
</head>
<body>

<h1>VGC Model Review</h1>
<p class="subtitle">Turn-by-turn model prediction vs actual winner actions</p>

<div class="summary" id="summary">
  <div class="stat"><div class="val" id="s-replays">—</div><div class="lbl">Replays</div></div>
  <div class="stat"><div class="val" id="s-accuracy">—</div><div class="lbl">Top-1 Accuracy</div></div>
  <div class="stat"><div class="val" id="s-turns">—</div><div class="lbl">Turns Analyzed</div></div>
  <div class="stat"><div class="val" id="s-matches">—</div><div class="lbl">Correct / Total</div></div>
</div>

<div class="controls">
  <select id="replay-select">
    <option value="">Select a replay...</option>
  </select>
</div>

<div id="content">
  <div class="loading">Loading replays...</div>
</div>

<script>
const $ = s => document.querySelector(s);

async function init() {
  const [summaryRes, replaysRes] = await Promise.all([
    fetch('/api/summary').then(r => r.json()),
    fetch('/api/replays').then(r => r.json()),
  ]);

  $('#s-replays').textContent = summaryRes.total_replays;
  $('#s-accuracy').textContent = summaryRes.avg_accuracy + '%';
  $('#s-turns').textContent = summaryRes.total_turns;
  $('#s-matches').textContent = summaryRes.total_matches + ' / ' + summaryRes.total_actions;

  const sel = $('#replay-select');
  replaysRes.sort((a, b) => b.rating - a.rating);
  replaysRes.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.id;
    const p = r.players.join(' vs ');
    opt.textContent = `[${r.rating || '?'}] ${p} — ${r.accuracy}% (${r.total_turns}t)`;
    sel.appendChild(opt);
  });

  sel.addEventListener('change', () => {
    if (sel.value) loadReplay(sel.value);
  });

  // Auto-load first replay
  if (replaysRes.length > 0) {
    sel.value = replaysRes[0].id;
    loadReplay(replaysRes[0].id);
  } else {
    $('#content').innerHTML = '<div class="loading">No replays loaded.</div>';
  }
}

async function loadReplay(id) {
  $('#content').innerHTML = '<div class="loading">Loading...</div>';
  const data = await fetch('/api/replay/' + encodeURIComponent(id)).then(r => r.json());

  if (data.error) {
    $('#content').innerHTML = '<div class="error">' + data.error + '</div>';
    return;
  }

  let html = '';
  for (const turn of data.turns) {
    html += renderTurn(turn);
  }
  $('#content').innerHTML = html;
}

function hpColor(hp) {
  if (hp > 50) return 'hp-green';
  if (hp > 20) return 'hp-yellow';
  return 'hp-red';
}

function renderPoke(p) {
  const statusHtml = p.status ? ` <span class="status-badge">${p.status.toUpperCase()}</span>` : '';
  return `<span class="poke">
    <span class="name">${p.species}</span>
    <span class="hp-bar"><span class="fill ${hpColor(p.hp)}" style="width:${p.hp}%"></span></span>
    <span style="font-size:11px;color:var(--text-dim)">${p.hp}%</span>
    ${statusHtml}
  </span>`;
}

function renderSlot(slot, label) {
  const isNone = slot.actual === '\\u2014' || slot.actual === '—';
  const matchClass = isNone ? '' : (slot.match ? 'match-yes' : 'match-no');
  const badgeClass = isNone ? 'na' : (slot.match ? 'yes' : 'no');
  const badgeText = isNone ? 'N/A' : (slot.match ? 'MATCH' : 'MISS');

  let predsHtml = '';
  slot.predictions.forEach((p, i) => {
    const isCorrect = p.idx === slot.actual_idx;
    const highlight = isCorrect ? 'color:var(--green);font-weight:600' : '';
    predsHtml += `<div class="pred-row">
      <span class="pred-rank">#${i+1}</span>
      <span class="pred-action" style="${highlight}">${p.action}</span>
      <span class="pred-prob">${p.prob}%</span>
      <span class="pred-bar"><span class="fill" style="width:${p.prob}%"></span></span>
    </div>`;
  });

  return `<div class="slot ${matchClass}">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span class="slot-label">${label}</span>
      <span class="match-badge ${badgeClass}">${badgeText}</span>
    </div>
    <div class="actual">
      <div class="actual-label">Actual action</div>
      <div class="actual-action">${slot.actual}</div>
    </div>
    <div class="pred-label">Model predictions</div>
    ${predsHtml}
  </div>`;
}

function renderTurn(turn) {
  const fieldHtml = turn.field.map(f => `<span class="tag">${f}</span>`).join('');

  const ownHtml = turn.own_active.map(renderPoke).join('');
  const oppHtml = turn.opp_active.map(renderPoke).join('');
  const ownBenchHtml = turn.own_bench.length > 0
    ? '<span style="color:var(--text-dim);font-size:11px;margin-left:8px">bench:</span> ' + turn.own_bench.map(renderPoke).join('')
    : '';
  const oppBenchHtml = turn.opp_bench.length > 0
    ? '<span style="color:var(--text-dim);font-size:11px;margin-left:8px">bench:</span> ' + turn.opp_bench.map(renderPoke).join('')
    : '';

  return `<div class="turn-card">
    <div class="turn-header">
      <span class="turn-num">Turn ${turn.turn}</span>
      <div class="field-tags">${fieldHtml}</div>
    </div>
    <div class="pokemon-row">
      <div class="side">
        <div class="side-label">Winner</div>
        ${ownHtml}${ownBenchHtml}
      </div>
      <div class="side">
        <div class="side-label">Opponent</div>
        ${oppHtml}${oppBenchHtml}
      </div>
    </div>
    <div class="slots">
      ${renderSlot(turn.slot_a, 'Slot A')}
      ${renderSlot(turn.slot_b, 'Slot B')}
    </div>
  </div>`;
}

init();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def load_model_and_data(num_replays: int, device_str: str):
    """Load vocabs, model, and analyze replays."""
    global vocabs, model, device, replay_cache

    # Device
    if device_str == "auto":
        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    else:
        device = torch.device(device_str)
    print(f"Device: {device}")

    # Vocabs
    print("Loading vocabularies...")
    vocabs = Vocabs.load(VOCAB_DIR)

    # Model
    if not CHECKPOINT_PATH.exists():
        print(f"ERROR: Checkpoint not found at {CHECKPOINT_PATH}")
        print("Run training first: python -m vgc_model.training.train")
        return

    print(f"Loading model from {CHECKPOINT_PATH}...")
    checkpoint = torch.load(CHECKPOINT_PATH, map_location=device, weights_only=False)
    config = checkpoint.get("config", ModelConfig())
    model = VGCTransformer(vocabs, config).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    print(f"Model loaded ({model.count_parameters():,} params)")
    if "val_top1" in checkpoint:
        print(f"  Checkpoint val_top1: {checkpoint['val_top1']:.1f}%, val_top3: {checkpoint['val_top3']:.1f}%")

    # Find replay files across all search directories
    replay_files = []
    for d in REPLAY_SEARCH_DIRS:
        if d.exists():
            replay_files.extend(f for f in d.glob("*.json") if f.name != "index.json")
    replay_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    print(f"Found {len(replay_files)} replay files")

    if num_replays < len(replay_files):
        replay_files = random.sample(replay_files, num_replays)
    print(f"Analyzing {len(replay_files)} replays...")

    success = 0
    for i, f in enumerate(replay_files):
        result = analyze_replay(f)
        if result:
            replay_cache[result["id"]] = result
            success += 1
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(replay_files)} processed ({success} successful)")

    total_matches = sum(r["matches"] for r in replay_cache.values())
    total_actions = sum(r["total_actions"] for r in replay_cache.values())
    acc = round(total_matches / total_actions * 100, 1) if total_actions > 0 else 0
    print(f"\nDone: {success} replays, {total_actions} actions, {acc}% top-1 accuracy")


def main():
    parser = argparse.ArgumentParser(description="VGC Model Review Dashboard")
    parser.add_argument("--port", type=int, default=8421)
    parser.add_argument("--replays", type=int, default=10, help="Number of replays to analyze")
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    load_model_and_data(args.replays, args.device)
    print(f"\nStarting server at http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
