"""VGC Model Inference Server.

FastAPI service that wraps the trained VGCTransformer for real-time
battle decisions. The C++ SerialPrograms calls this over HTTP.

Endpoints:
    POST /predict       — Given game state JSON, return action predictions
    POST /team-select   — Given both teams' species, return team + lead picks
    GET  /health        — Check if model is loaded and ready

Usage:
    python -m src.vgc_model.inference.server [--port 8Pokemon] [--checkpoint PATH]

Or:
    uvicorn src.vgc_model.inference.server:app --port 8265
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.vgc_model.data.vocab import Vocabs
from src.vgc_model.data.dataset import MAX_ACTIONS, BOOST_STATS
from src.vgc_model.model.vgc_model import VGCTransformer, ModelConfig


# ── Request / Response schemas ────────────────────────────────────

class PokemonState(BaseModel):
    species: str = ""
    hp: float = 1.0           # 0.0-1.0 normalized
    status: str = ""          # brn, par, psn, slp, frz, tox, or ""
    moves: list[str] = Field(default_factory=list)   # up to 4 move names
    item: str = ""
    ability: str = ""
    boosts: list[int] = Field(default_factory=lambda: [0]*6)  # atk,def,spa,spd,spe,eva
    is_mega: bool = False
    alive: bool = True


class FieldState(BaseModel):
    weather: str = ""         # SunnyDay, RainDance, Sandstorm, Snow
    terrain: str = ""         # Electric, Grassy, Psychic, Misty
    trick_room: bool = False
    tailwind_own: bool = False
    tailwind_opp: bool = False
    screens_own: list[bool] = Field(default_factory=lambda: [False]*3)  # LS, Reflect, AV
    screens_opp: list[bool] = Field(default_factory=lambda: [False]*3)
    turn: int = 1


class PredictRequest(BaseModel):
    """Game state for a battle action prediction.

    Slots: own_active[0-1], own_bench[0-1], opp_active[0-1], opp_bench[0-1]
    For singles, only index 0 of each pair is used.
    """
    own_active: list[PokemonState] = Field(default_factory=list)    # 1-2 mons
    own_bench: list[PokemonState] = Field(default_factory=list)     # 0-2 mons
    opp_active: list[PokemonState] = Field(default_factory=list)    # 1-2 mons
    opp_bench: list[PokemonState] = Field(default_factory=list)     # 0-2 mons
    field: FieldState = Field(default_factory=FieldState)
    legal_actions_a: Optional[List[bool]] = None   # 14-element mask, or None = all legal
    legal_actions_b: Optional[List[bool]] = None


class ActionResult(BaseModel):
    action: int                 # best action index (0-13)
    probs: list[float]          # probability for each of 14 actions


class PredictResponse(BaseModel):
    slot_a: ActionResult
    slot_b: ActionResult


class TeamSelectRequest(BaseModel):
    own_team: list[str]         # 6 species names
    opp_team: list[str]         # 6 species names


class TeamSelectResponse(BaseModel):
    bring: list[int]            # 4 indices (0-5) of Pokemon to bring
    lead: list[int]             # 2 indices (into the bring list) to lead with
    bring_scores: list[float]   # 6 scores (one per team member)
    lead_scores: list[float]    # 4 scores (one per selected)


class SearchResponse(BaseModel):
    slot_a: ActionResult
    slot_b: ActionResult
    win_pct: float
    opp_slot_a: Optional[ActionResult] = None
    opp_slot_b: Optional[ActionResult] = None
    n_rollouts: int = 0


# ── Model loading ─────────────────────────────────────────────────

_model: VGCTransformer | None = None
_vocabs: Vocabs | None = None
_device: torch.device = torch.device("cpu")
_search_engine = None  # SearchEngine instance (loaded on demand)


def load_model(checkpoint_path: str, vocab_dir: str,
               v2_checkpoint: str = "", winrate_checkpoint: str = ""):
    global _model, _vocabs, _device, _search_engine

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Load vocabularies
    _vocabs = Vocabs.load(Path(vocab_dir))
    _vocabs.freeze_all()

    # Create v1 model
    config = ModelConfig()
    _model = VGCTransformer(_vocabs, config)

    # Load checkpoint
    checkpoint = torch.load(checkpoint_path, map_location=_device, weights_only=False)
    if "model_state_dict" in checkpoint:
        _model.load_state_dict(checkpoint["model_state_dict"])
    else:
        _model.load_state_dict(checkpoint)

    _model.to(_device)
    _model.eval()

    param_count = _model.count_parameters()
    print(f"Model loaded: {param_count:,} parameters on {_device}")
    print(f"Vocabs: {len(_vocabs.species)} species, {len(_vocabs.moves)} moves")

    # Load search engine (v2_seq action model + winrate model)
    if v2_checkpoint and winrate_checkpoint:
        _load_search_engine(v2_checkpoint, winrate_checkpoint)


def _load_search_engine(v2_checkpoint: str, winrate_checkpoint: str):
    global _search_engine

    from .search import SearchEngine
    from ..model.vgc_model_v2_seq import VGCTransformerV2Seq, ModelConfigV2Seq
    from ..model.winrate_model import WinrateModel, WinrateModelConfig
    from ..data.feature_tables import FeatureTables
    from ..data.usage_stats import UsageStats

    print("Loading search engine...")

    ft = FeatureTables()
    try:
        us = UsageStats()
    except Exception:
        us = None
        print("  Warning: usage stats not available")

    # Load v2_seq action model
    v2_ckpt = torch.load(v2_checkpoint, map_location=_device, weights_only=False)
    v2_config = v2_ckpt.get("config", ModelConfigV2Seq())
    action_model = VGCTransformerV2Seq(_vocabs, v2_config).to(_device)
    action_model.load_state_dict(v2_ckpt["model_state_dict"])
    action_model.eval()
    print(f"  Action model (v2_seq): {action_model.count_parameters():,} params")

    # Load winrate model
    wr_ckpt = torch.load(winrate_checkpoint, map_location=_device, weights_only=False)
    wr_config = wr_ckpt.get("config", WinrateModelConfig())
    winrate_model = WinrateModel(_vocabs, wr_config).to(_device)
    winrate_model.load_state_dict(wr_ckpt["model_state_dict"])
    winrate_model.eval()
    print(f"  Winrate model: {winrate_model.count_parameters():,} params")

    _search_engine = SearchEngine(
        action_model=action_model,
        winrate_model=winrate_model,
        vocabs=_vocabs,
        feature_tables=ft,
        usage_stats=us,
        device=_device,
    )
    print("Search engine ready.")


# ── Encoding ──────────────────────────────────────────────────────

def _encode_pokemon_slot(poke: PokemonState) -> dict:
    """Encode a single Pokemon into vocab indices."""
    species_id = _vocabs.species[poke.species] if poke.species else 0
    status_id = _vocabs.status[poke.status] if poke.status else 0
    item_id = _vocabs.items[poke.item] if poke.item else 0
    ability_id = _vocabs.abilities[poke.ability] if poke.ability else 0

    move_ids = []
    for m in poke.moves[:4]:
        move_ids.append(_vocabs.moves[m] if m else 0)
    move_ids += [0] * (4 - len(move_ids))

    boosts = (poke.boosts + [0]*6)[:6]

    return {
        "species_id": species_id,
        "hp": poke.hp if poke.alive else 0.0,
        "status_id": status_id,
        "move_ids": move_ids,
        "item_id": item_id,
        "ability_id": ability_id,
        "boosts": boosts,
        "mega": 1 if poke.is_mega else 0,
        "alive": 1 if poke.alive and poke.species else 0,
    }


def _build_batch(req: PredictRequest) -> dict[str, torch.Tensor]:
    """Convert a PredictRequest into the model's tensor format."""
    empty = PokemonState()

    # Pad to exactly 2 per category
    own_active = (req.own_active + [empty, empty])[:2]
    own_bench = (req.own_bench + [empty, empty])[:2]
    opp_active = (req.opp_active + [empty, empty])[:2]
    opp_bench = (req.opp_bench + [empty, empty])[:2]

    # 8 slots: own_a, own_b, own_bench0, own_bench1, opp_a, opp_b, opp_bench0, opp_bench1
    all_pokemon = own_active + own_bench + opp_active + opp_bench
    encoded = [_encode_pokemon_slot(p) for p in all_pokemon]

    species_ids = [e["species_id"] for e in encoded]
    hp_values = [e["hp"] for e in encoded]
    status_ids = [e["status_id"] for e in encoded]
    boost_values = [e["boosts"] for e in encoded]
    item_ids = [e["item_id"] for e in encoded]
    ability_ids = [e["ability_id"] for e in encoded]
    mega_flags = [e["mega"] for e in encoded]
    alive_flags = [e["alive"] for e in encoded]
    move_ids = [e["move_ids"] for e in encoded]

    # Field
    f = req.field
    weather_id = _vocabs.weather[f.weather] if f.weather else 0
    terrain_id = _vocabs.terrain[f.terrain] if f.terrain else 0

    # Action masks
    if req.legal_actions_a is not None:
        mask_a = req.legal_actions_a[:MAX_ACTIONS]
        mask_a += [False] * (MAX_ACTIONS - len(mask_a))
    else:
        mask_a = [True] * MAX_ACTIONS

    if req.legal_actions_b is not None:
        mask_b = req.legal_actions_b[:MAX_ACTIONS]
        mask_b += [False] * (MAX_ACTIONS - len(mask_b))
    else:
        mask_b = [True] * MAX_ACTIONS

    batch = {
        "species_ids": torch.tensor([species_ids], dtype=torch.long, device=_device),
        "hp_values": torch.tensor([hp_values], dtype=torch.float, device=_device),
        "status_ids": torch.tensor([status_ids], dtype=torch.long, device=_device),
        "boost_values": torch.tensor([boost_values], dtype=torch.float, device=_device),
        "item_ids": torch.tensor([item_ids], dtype=torch.long, device=_device),
        "ability_ids": torch.tensor([ability_ids], dtype=torch.long, device=_device),
        "mega_flags": torch.tensor([mega_flags], dtype=torch.float, device=_device),
        "alive_flags": torch.tensor([alive_flags], dtype=torch.float, device=_device),
        "move_ids": torch.tensor([move_ids], dtype=torch.long, device=_device),
        "weather_id": torch.tensor([weather_id], dtype=torch.long, device=_device),
        "terrain_id": torch.tensor([terrain_id], dtype=torch.long, device=_device),
        "trick_room": torch.tensor([1.0 if f.trick_room else 0.0], dtype=torch.float, device=_device),
        "tailwind_own": torch.tensor([1.0 if f.tailwind_own else 0.0], dtype=torch.float, device=_device),
        "tailwind_opp": torch.tensor([1.0 if f.tailwind_opp else 0.0], dtype=torch.float, device=_device),
        "screens_own": torch.tensor([[1.0 if s else 0.0 for s in f.screens_own[:3]]], dtype=torch.float, device=_device),
        "screens_opp": torch.tensor([[1.0 if s else 0.0 for s in f.screens_opp[:3]]], dtype=torch.float, device=_device),
        "turn": torch.tensor([min(f.turn, 30)], dtype=torch.float, device=_device),
        "action_mask_a": torch.tensor([mask_a], dtype=torch.bool, device=_device),
        "action_mask_b": torch.tensor([mask_b], dtype=torch.bool, device=_device),
    }

    return batch


# ── Action decoding ───────────────────────────────────────────────

ACTION_NAMES = []
for move_i in range(4):
    for target_j, target_name in enumerate(["opp_a", "opp_b", "ally"]):
        ACTION_NAMES.append(f"move{move_i}_{target_name}")
ACTION_NAMES.append("switch_0")
ACTION_NAMES.append("switch_1")


# ── FastAPI app ───────────────────────────────────────────────────

app = FastAPI(title="VGC Inference Server", version="1.0")


@app.get("/health")
def health():
    return {
        "status": "ok" if _model is not None else "not_loaded",
        "device": str(_device),
        "species_count": len(_vocabs.species) if _vocabs else 0,
        "moves_count": len(_vocabs.moves) if _vocabs else 0,
        "parameters": _model.count_parameters() if _model else 0,
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    batch = _build_batch(req)

    with torch.no_grad():
        out = _model(batch)

    logits_a = out["logits_a"].squeeze(0)  # (14,)
    logits_b = out["logits_b"].squeeze(0)  # (14,)

    probs_a = torch.softmax(logits_a, dim=-1).cpu().tolist()
    probs_b = torch.softmax(logits_b, dim=-1).cpu().tolist()

    return PredictResponse(
        slot_a=ActionResult(
            action=int(logits_a.argmax().item()),
            probs=probs_a,
        ),
        slot_b=ActionResult(
            action=int(logits_b.argmax().item()),
            probs=probs_b,
        ),
    )


@app.post("/team-select", response_model=TeamSelectResponse)
def team_select(req: TeamSelectRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    own_ids = torch.tensor(
        [[_vocabs.species[s] for s in req.own_team[:6]]], dtype=torch.long, device=_device
    )
    opp_ids = torch.tensor(
        [[_vocabs.species[s] for s in req.opp_team[:6]]], dtype=torch.long, device=_device
    )

    with torch.no_grad():
        # Team selection: score all 6
        team_logits = _model.team_head(own_ids, opp_ids).squeeze(0)  # (6,)
        team_scores = team_logits.cpu().tolist()
        _, top4 = team_logits.topk(4)
        bring = sorted(top4.tolist())

        # Lead selection: score the 4 selected
        selected_ids = torch.tensor(
            [[_vocabs.species[req.own_team[i]] for i in bring]], dtype=torch.long, device=_device
        )
        lead_logits = _model.lead_head(selected_ids, opp_ids).squeeze(0)  # (4,)
        lead_scores = lead_logits.cpu().tolist()
        _, top2 = lead_logits.topk(2)
        lead = sorted(top2.tolist())

    return TeamSelectResponse(
        bring=bring,
        lead=lead,
        bring_scores=team_scores,
        lead_scores=lead_scores,
    )


@app.post("/search", response_model=SearchResponse)
def search(req: PredictRequest):
    """1-ply MCTS search using action model + battle sim + winrate model."""
    if _search_engine is None:
        raise HTTPException(status_code=503, detail="Search engine not loaded. "
                            "Start with --v2-checkpoint and --winrate-checkpoint.")

    result = _search_engine.search(req.model_dump(), n_rollouts=100)

    return SearchResponse(
        slot_a=ActionResult(action=result.action_a, probs=result.own_probs_a),
        slot_b=ActionResult(action=result.action_b, probs=result.own_probs_b),
        win_pct=result.win_pct,
        opp_slot_a=ActionResult(
            action=int(max(range(len(result.opp_probs_a)),
                           key=lambda i: result.opp_probs_a[i])),
            probs=result.opp_probs_a,
        ) if result.opp_probs_a else None,
        opp_slot_b=ActionResult(
            action=int(max(range(len(result.opp_probs_b)),
                           key=lambda i: result.opp_probs_b[i])),
            probs=result.opp_probs_b,
        ) if result.opp_probs_b else None,
        n_rollouts=result.n_rollouts,
    )


# ── CLI entrypoint ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VGC Inference Server")
    parser.add_argument("--checkpoint", type=str, default="data/checkpoints/best.pt",
                        help="Path to v1 model checkpoint")
    parser.add_argument("--vocab-dir", type=str, default="data/vocab",
                        help="Path to vocabulary directory")
    parser.add_argument("--v2-checkpoint", type=str, default="",
                        help="Path to v2_seq action model (enables /search)")
    parser.add_argument("--winrate-checkpoint", type=str, default="",
                        help="Path to winrate model (enables /search)")
    parser.add_argument("--port", type=int, default=8265,
                        help="Port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Host to bind to")
    args = parser.parse_args()

    load_model(args.checkpoint, args.vocab_dir,
               v2_checkpoint=args.v2_checkpoint,
               winrate_checkpoint=args.winrate_checkpoint)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
