"""Unit tests for `Encoder` (Layer 2).

Tests both modes against a real ParsedReplay. Asserts on per-column shapes,
dtypes after stacking, and the meta-on/off divergence.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from src.vgc_model.data.encoder import Encoder, PAD_IDX, RawSample
from src.vgc_model.data.encode_runner import _stack_samples
from src.vgc_model.data.replay_parser import ReplayParser
from src.vgc_model.data.stats_source import PikalyticsStatsSource
from src.vgc_model.data.vocab import Vocabs


@pytest.fixture(scope="module")
def stats_source():
    try:
        return PikalyticsStatsSource()
    except FileNotFoundError:
        pytest.skip("Pikalytics snapshot not present")


@pytest.fixture(scope="module")
def parsed_replay(stats_source):
    root = PROJECT_ROOT / "data" / "replays" / "gen9championsvgc2026regma"
    if not root.exists():
        pytest.skip("No bucketed replays available")
    for day in sorted(root.iterdir()):
        if not day.is_dir():
            continue
        for hour in sorted(day.iterdir()):
            if not hour.is_dir():
                continue
            for f in sorted(hour.iterdir()):
                if f.suffix != ".json":
                    continue
                replay = json.loads(f.read_text(encoding="utf-8"))
                parsed = ReplayParser(stats_source).parse(replay)
                if parsed is not None and len(parsed.turns) >= 2:
                    return parsed
    pytest.skip("No parseable replay")


@pytest.fixture(scope="module")
def row(parsed_replay):
    from dataclasses import asdict
    return {
        "replay_id": parsed_replay.replay_id,
        "format": parsed_replay.format,
        "bucket_hour": parsed_replay.bucket_hour,
        "p1_rating": parsed_replay.p1_rating,
        "p2_rating": parsed_replay.p2_rating,
        "winner": parsed_replay.winner,
        "turns_json": json.dumps([asdict(t) for t in parsed_replay.turns]),
    }


@pytest.fixture(scope="module")
def vocabs(parsed_replay):
    v = Vocabs()
    v.weather.add("none"); v.terrain.add("none"); v.status.add("ok")
    for t in parsed_replay.turns:
        v.weather.add(t.weather or "none")
        v.terrain.add(t.terrain or "none")
        for revealed in t.p1_revealed + t.p2_revealed:
            v.species.add(revealed.species)
            v.status.add(revealed.status or "ok")
            if revealed.item.value:
                v.items.add(revealed.item.value)
            if revealed.ability.value:
                v.abilities.add(revealed.ability.value)
            for m in revealed.moves:
                if m.value:
                    v.moves.add(m.value)
        for action in (t.p1_action_a, t.p1_action_b, t.p2_action_a, t.p2_action_b):
            if action.move:
                v.moves.add(action.move)
            if action.switch_to:
                v.species.add(action.switch_to)
    v.freeze_all()
    return v


def test_raw_sample_has_per_column_lists(vocabs, row):
    e = Encoder(vocabs, mode="meta-on")
    sample = next(iter(e.encode_row(row)))
    assert isinstance(sample, RawSample)
    assert isinstance(sample.fields["species_ids"], list)
    assert len(sample.fields["species_ids"]) == 8
    assert len(sample.fields["move_ids"]) == 8
    assert len(sample.fields["move_ids"][0]) == 4


def test_meta_off_zeros_unrevealed_slots(vocabs, row):
    """Across all samples, meta-off must constrain confidences to {0, 1};
    meta-on must produce at least one fractional confidence."""
    e_on = Encoder(vocabs, mode="meta-on")
    e_off = Encoder(vocabs, mode="meta-off")

    found_diff = False
    for on_sample, off_sample in zip(e_on.encode_row(row), e_off.encode_row(row)):
        for k in ("item_confidences", "ability_confidences"):
            on_v = np.asarray(on_sample.fields[k])
            off_v = np.asarray(off_sample.fields[k])
            assert np.all((off_v == 0.0) | (off_v == 1.0))
            if not np.allclose(on_v, off_v):
                found_diff = True
        # move_confidences is 8x4
        on_m = np.asarray(on_sample.fields["move_confidences"])
        off_m = np.asarray(off_sample.fields["move_confidences"])
        assert np.all((off_m == 0.0) | (off_m == 1.0))
        if not np.allclose(on_m, off_m):
            found_diff = True
    assert found_diff


def test_revealed_slots_match_in_both_modes(vocabs, row):
    e_on = Encoder(vocabs, mode="meta-on")
    e_off = Encoder(vocabs, mode="meta-off")
    for on_s, off_s in zip(e_on.encode_row(row), e_off.encode_row(row)):
        on_c = np.asarray(on_s.fields["item_confidences"])
        off_c = np.asarray(off_s.fields["item_confidences"])
        revealed_mask = on_c == 1.0
        if revealed_mask.any():
            assert np.all(off_c[revealed_mask] == 1.0)


def test_encode_row_yields_two_per_turn(vocabs, row):
    e = Encoder(vocabs, mode="meta-on")
    samples = list(e.encode_row(row))
    turns = json.loads(row["turns_json"])
    assert len(samples) == 2 * len(turns)
    povs = {s.pov_player for s in samples}
    assert povs == {"p1", "p2"}


def test_stacked_columns_have_correct_shapes(vocabs, row):
    """End-to-end: encoder + stacker produce arrays the trainer expects."""
    e = Encoder(vocabs, mode="meta-on")
    samples = list(e.encode_row(row))
    stacked = _stack_samples(samples)

    n = len(samples)
    assert stacked["species_ids"].shape == (n, 8)
    assert stacked["species_ids"].dtype == np.int32
    assert stacked["hp_values"].shape == (n, 8)
    assert stacked["hp_values"].dtype == np.float32
    assert stacked["move_ids"].shape == (n, 8, 4)
    assert stacked["move_confidences"].shape == (n, 8, 4)
    assert stacked["action_a_type"].shape == (n,)
    assert stacked["_meta_rating"].shape == (n,)


def test_stacked_metadata_matches_samples(vocabs, row):
    e = Encoder(vocabs, mode="meta-on")
    samples = list(e.encode_row(row))
    stacked = _stack_samples(samples)
    assert stacked["_meta_replay_id"][0] == samples[0].replay_id
    assert stacked["_meta_pov_player"][0] == samples[0].pov_player
    assert int(stacked["_meta_turn_num"][0]) == samples[0].turn_num
