"""Unit tests for `ReplayParser`.

Uses real replay JSONs from the test_images / data dirs as fixtures. Asserts
on schema invariants (counts, types) plus a few specific values that should
hold for any structurally-valid VGC replay. Avoids asserting on implementation
details that drift (specific move probs, etc).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from src.vgc_model.data.replay_parser import (
    ParsedReplay,
    ReplayParser,
    StatsField,
)
from src.vgc_model.data.stats_source import PikalyticsStatsSource


@pytest.fixture(scope="module")
def stats_source():
    try:
        return PikalyticsStatsSource()
    except FileNotFoundError:
        pytest.skip("Pikalytics snapshot not present")


@pytest.fixture(scope="module")
def parser(stats_source):
    return ReplayParser(stats_source)


@pytest.fixture(scope="module")
def replay_files():
    """Find a handful of bucketed replays to use as fixtures."""
    root = PROJECT_ROOT / "data" / "replays" / "gen9championsvgc2026regma"
    if not root.exists():
        pytest.skip("No bucketed replays available")
    files = []
    for day in sorted(root.iterdir()):
        if not day.is_dir():
            continue
        for hour in sorted(day.iterdir()):
            if not hour.is_dir():
                continue
            for f in sorted(hour.iterdir()):
                if f.suffix == ".json":
                    files.append(f)
                    if len(files) >= 5:
                        return files
    return files


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_parses_a_real_replay(parser, replay_files):
    if not replay_files:
        pytest.skip("No replays to test against")
    parsed = parser.parse(_load(replay_files[0]))
    assert isinstance(parsed, ParsedReplay)
    assert parsed.replay_id  # non-empty
    assert parsed.format
    assert parsed.winner in ("p1", "p2")
    assert len(parsed.turns) > 0
    assert parsed.bucket_hour  # YYYY-MM-DD-HH


def test_team_size_is_six(parser, replay_files):
    if not replay_files:
        pytest.skip("No replays")
    parsed = parser.parse(_load(replay_files[0]))
    assert len(parsed.p1_team) == 6
    assert len(parsed.p2_team) == 6


def test_turns_have_both_players_actions(parser, replay_files):
    if not replay_files:
        pytest.skip("No replays")
    parsed = parser.parse(_load(replay_files[0]))
    for t in parsed.turns:
        # Action structs are always present (may be type="noop")
        for a in (t.p1_action_a, t.p1_action_b, t.p2_action_a, t.p2_action_b):
            assert a.type in {"move", "switch", "team_select", "noop"}


def test_revealed_pokemon_have_4_move_slots(parser, replay_files):
    if not replay_files:
        pytest.skip("No replays")
    parsed = parser.parse(_load(replay_files[0]))
    for turn in parsed.turns:
        for revealed in turn.p1_revealed + turn.p2_revealed:
            assert len(revealed.moves) == 4
            for m in revealed.moves:
                assert isinstance(m, StatsField)
                assert m.source_type in {"revealed", "meta"}
                if m.source_type == "revealed":
                    assert m.prob == 1.0


def test_meta_source_id_matches_stats_source(parser, replay_files, stats_source):
    if not replay_files:
        pytest.skip("No replays")
    parsed = parser.parse(_load(replay_files[0]))
    found_meta = False
    for turn in parsed.turns[:3]:  # only need to scan a few turns
        for revealed in turn.p1_revealed + turn.p2_revealed:
            for m in revealed.moves:
                if m.source_type == "meta" and m.value:
                    assert m.stats_source_id == stats_source.source_id
                    found_meta = True
    # Almost certain to find at least one meta-fill (no replay reveals all 4 moves
    # on every Pokemon). If we don't, that itself is suspect.
    assert found_meta, "expected at least one meta-source move slot"


def test_revealed_item_has_prob_one(parser, replay_files):
    if not replay_files:
        pytest.skip("No replays")
    parsed = parser.parse(_load(replay_files[0]))
    for turn in parsed.turns:
        for revealed in turn.p1_revealed + turn.p2_revealed:
            if revealed.item.source_type == "revealed":
                assert revealed.item.prob == 1.0


def test_returns_none_on_empty_log(parser):
    assert parser.parse({"id": "x", "log": ""}) is None


def test_returns_none_on_garbage_log(parser):
    assert parser.parse({"id": "x", "log": "this is not a battle log"}) is None
