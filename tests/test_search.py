"""Tests for the MCTS search engine with mock models."""

import pytest
import torch
import torch.nn as nn
from unittest.mock import MagicMock
from collections import Counter

from src.vgc_model.sim.battle_sim import SimPokemon, SimState, SimField


# ── Mock Models ──────────────────────────────────────────────────

class MockActionModel(nn.Module):
    """Returns fixed logits for both slots."""

    def __init__(self, logits_a=None, logits_b=None):
        super().__init__()
        # Default: heavily favor action 0 for slot A, action 3 for slot B
        self._logits_a = logits_a if logits_a is not None else torch.tensor(
            [5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        )
        self._logits_b = logits_b if logits_b is not None else torch.tensor(
            [0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        )

    def forward(self, batch):
        B = batch["species_ids"].shape[0]
        return {
            "logits_a": self._logits_a.unsqueeze(0).expand(B, -1),
            "logits_b": self._logits_b.unsqueeze(0).expand(B, -1),
        }

    def count_parameters(self):
        return 0


class MockWinrateModel(nn.Module):
    """Returns a fixed win probability for all states."""

    def __init__(self, win_logit=0.5):
        super().__init__()
        self._logit = win_logit  # raw logit, not probability

    def forward(self, batch):
        B = batch["species_ids"].shape[0]
        return {"win_logit": torch.full((B,), self._logit)}

    def count_parameters(self):
        return 0


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mock_vocabs():
    """Create a minimal mock vocabs object."""
    from src.vgc_model.data.vocab import Vocabs
    vocab_dir = pytest.importorskip("pathlib").Path(__file__).parent.parent / "data" / "vocab"
    if not vocab_dir.exists():
        pytest.skip("Vocab dir not available")
    return Vocabs.load(vocab_dir)


@pytest.fixture
def search_engine_factory(feature_tables, mock_vocabs):
    """Factory to create SearchEngine with mock models."""
    from src.vgc_model.inference.search import SearchEngine

    def _make(action_logits_a=None, action_logits_b=None, win_logit=0.5):
        action_model = MockActionModel(action_logits_a, action_logits_b)
        winrate_model = MockWinrateModel(win_logit)
        return SearchEngine(
            action_model=action_model,
            winrate_model=winrate_model,
            vocabs=mock_vocabs,
            feature_tables=feature_tables,
            usage_stats=None,
            device=torch.device("cpu"),
        )
    return _make


@pytest.fixture
def sample_request():
    """A minimal PredictRequest-style dict."""
    return {
        "own_active": [
            {"species": "Garchomp", "hp": 1.0, "status": "", "alive": True,
             "moves": ["Earthquake", "Rock Slide", "Protect", "Dragon Claw"],
             "item": "", "ability": "", "boosts": [0]*6, "is_mega": False},
            {"species": "Rillaboom", "hp": 1.0, "status": "", "alive": True,
             "moves": ["Grassy Glide", "Wood Hammer", "Fake Out", "U-turn"],
             "item": "", "ability": "", "boosts": [0]*6, "is_mega": False},
        ],
        "own_bench": [],
        "opp_active": [
            {"species": "Incineroar", "hp": 1.0, "status": "", "alive": True,
             "moves": ["Flare Blitz", "Knock Off", "Fake Out", "Protect"],
             "item": "", "ability": "", "boosts": [0]*6, "is_mega": False},
            {"species": "Flutter Mane", "hp": 1.0, "status": "", "alive": True,
             "moves": ["Moonblast", "Shadow Ball", "Dazzling Gleam", "Protect"],
             "item": "", "ability": "", "boosts": [0]*6, "is_mega": False},
        ],
        "opp_bench": [],
        "field": {"weather": "", "terrain": "", "trick_room": False,
                  "tailwind_own": False, "tailwind_opp": False,
                  "screens_own": [False]*3, "screens_opp": [False]*3, "turn": 1},
    }


# ── Tests ────────────────────────────────────────────────────────

class TestSearchBasic:
    def test_returns_result(self, search_engine_factory, sample_request):
        engine = search_engine_factory()
        result = engine.search(sample_request, n_rollouts=20)
        assert 0 <= result.action_a < 14
        assert 0 <= result.action_b < 14
        assert 0.0 <= result.win_pct <= 1.0
        assert result.n_rollouts > 0

    def test_peaked_model_picks_favored_action(self, search_engine_factory, sample_request):
        """When action model heavily favors action 0, search should pick it."""
        peaked_a = torch.tensor([10.0] + [0.0]*13)
        peaked_b = torch.tensor([0.0, 0.0, 0.0, 10.0] + [0.0]*10)
        engine = search_engine_factory(action_logits_a=peaked_a, action_logits_b=peaked_b)

        result = engine.search(sample_request, n_rollouts=50)
        assert result.action_a == 0
        assert result.action_b == 3

    def test_uniform_model_explores(self, search_engine_factory, sample_request):
        """With uniform probs, search should sample diverse action pairs."""
        uniform = torch.zeros(14)
        engine = search_engine_factory(action_logits_a=uniform, action_logits_b=uniform)

        result = engine.search(sample_request, n_rollouts=100)
        # Should have multiple distinct action pairs
        assert len(result.pair_scores) > 1

    def test_rollout_count(self, search_engine_factory, sample_request):
        engine = search_engine_factory()
        result = engine.search(sample_request, n_rollouts=50)
        assert result.n_rollouts <= 50
        assert result.n_rollouts > 0

    def test_probs_returned(self, search_engine_factory, sample_request):
        engine = search_engine_factory()
        result = engine.search(sample_request, n_rollouts=20)
        assert len(result.own_probs_a) == 14
        assert len(result.own_probs_b) == 14
        assert len(result.opp_probs_a) == 14
        assert len(result.opp_probs_b) == 14
        assert abs(sum(result.own_probs_a) - 1.0) < 0.01


class TestPerspectiveSwap:
    def test_swap_reverses_sides(self, search_engine_factory):
        from src.vgc_model.inference.search import SearchEngine
        req = {
            "own_active": [{"species": "Garchomp"}],
            "opp_active": [{"species": "Incineroar"}],
            "own_bench": [], "opp_bench": [],
            "field": {"tailwind_own": True, "tailwind_opp": False,
                      "screens_own": [True, False, False], "screens_opp": [False, True, False]},
        }
        swapped = SearchEngine._swap_perspective(req)
        assert swapped["own_active"][0]["species"] == "Incineroar"
        assert swapped["opp_active"][0]["species"] == "Garchomp"
        assert swapped["field"]["tailwind_own"] == False
        assert swapped["field"]["tailwind_opp"] == True
        assert swapped["field"]["screens_own"] == [False, True, False]
        assert swapped["field"]["screens_opp"] == [True, False, False]


class TestSearchWinrate:
    def test_high_winrate_reflected(self, search_engine_factory, sample_request):
        """When winrate model always says 0.9, search win_pct should be ~0.9."""
        # logit for sigmoid(x) = 0.9 -> x = ln(0.9/0.1) ≈ 2.197
        engine = search_engine_factory(win_logit=2.197)
        result = engine.search(sample_request, n_rollouts=50)
        assert result.win_pct > 0.8

    def test_low_winrate_reflected(self, search_engine_factory, sample_request):
        """When winrate model always says 0.1, search win_pct should be ~0.1."""
        engine = search_engine_factory(win_logit=-2.197)
        result = engine.search(sample_request, n_rollouts=50)
        assert result.win_pct < 0.2
