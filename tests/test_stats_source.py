"""Unit tests for `PikalyticsStatsSource`.

Uses the live snapshot at data/usage_stats/gen9championsvgc2026regma.json as
a fixture. The values here are stable across re-scrapes only at the level of
"Aegislash uses King's Shield as its top move" — exact percentages will drift,
so assertions check structure + sanity ranges, not specific floats.
"""
from __future__ import annotations

import pytest

from src.vgc_model.data.stats_source import (
    PikalyticsStatsSource,
    StatsLookup,
)


@pytest.fixture(scope="module")
def stats():
    try:
        return PikalyticsStatsSource()
    except FileNotFoundError:
        pytest.skip("Pikalytics snapshot not present")


def test_source_id_format(stats):
    sid = stats.source_id
    assert sid.startswith("pikalytics-")
    # YYYY-MM-DD suffix
    assert len(sid.split("-", 1)[1]) == 10


def test_lookup_item_returns_normalized_prob(stats):
    if not stats.has_species("Aegislash"):
        pytest.skip("Aegislash not in snapshot")
    r = stats.lookup_item("Aegislash")
    assert isinstance(r, StatsLookup)
    assert r.value != ""
    assert 0.0 < r.prob <= 1.0  # normalized from %; should not be raw 0..100
    assert r.source_id == stats.source_id


def test_lookup_ability_returns_normalized_prob(stats):
    if not stats.has_species("Aegislash"):
        pytest.skip("Aegislash not in snapshot")
    r = stats.lookup_ability("Aegislash")
    assert r.value == "Stance Change"  # only legal ability for Aegislash
    assert r.prob == pytest.approx(1.0, abs=0.01)


def test_lookup_moves_returns_n_results_with_probs(stats):
    if not stats.has_species("Aegislash"):
        pytest.skip("Aegislash not in snapshot")
    moves = stats.lookup_moves("Aegislash", n=4)
    assert 1 <= len(moves) <= 4
    for m in moves:
        assert isinstance(m, StatsLookup)
        assert m.value != ""
        assert 0.0 < m.prob <= 1.0
        assert m.source_id == stats.source_id
    # Probabilities should be in descending order (top-n = most-used first)
    probs = [m.prob for m in moves]
    assert probs == sorted(probs, reverse=True)


def test_unknown_species_returns_empty_lookup(stats):
    r = stats.lookup_item("NotARealPokemon-9999")
    assert r.value == ""
    assert r.prob == 0.0
    assert r.source_id == stats.source_id


def test_unknown_species_has_zero_coverage(stats):
    assert stats.coverage_score("NotARealPokemon-9999") == 0.0


def test_known_species_has_nonzero_coverage(stats):
    if not stats.has_species("Aegislash"):
        pytest.skip("Aegislash not in snapshot")
    assert stats.coverage_score("Aegislash") > 0.5


def test_unknown_species_returns_empty_moves_list(stats):
    assert stats.lookup_moves("NotARealPokemon-9999") == []
