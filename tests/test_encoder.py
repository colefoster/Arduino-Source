"""Unit tests for `Encoder` (Layer 2).

Tests both modes against a small in-memory ParsedReplay built from a real
replay JSON. Asserts on tensor shapes, dtypes, and the meta-on vs meta-off
divergence.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from src.vgc_model.data.encoder import Encoder, PAD_IDX
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
    """Parse one real replay into a ParsedReplay -> row dict."""
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
    """Convert ParsedReplay to the row dict shape Encoder.encode_row expects."""
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
    """Build a tiny vocab from this one replay's content."""
    from dataclasses import asdict
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


def test_meta_on_produces_correct_shapes(vocabs, row):
    e = Encoder(vocabs, mode="meta-on")
    sample = next(iter(e.encode_row(row)))
    t = sample.tensors
    assert t["species_ids"].shape == (8,)
    assert t["species_ids"].dtype == torch.long
    assert t["hp_values"].shape == (8,)
    assert t["hp_values"].dtype == torch.float32
    assert t["move_ids"].shape == (8, 4)
    assert t["move_confidences"].shape == (8, 4)


def test_meta_off_zeros_unrevealed_slots(vocabs, row):
    e_on = Encoder(vocabs, mode="meta-on")
    e_off = Encoder(vocabs, mode="meta-off")
    on_sample = next(iter(e_on.encode_row(row)))
    off_sample = next(iter(e_off.encode_row(row)))

    # In meta-off, every confidence is either 0.0 (meta-source) or 1.0 (revealed).
    # In meta-on, meta-source confidences are arbitrary 0..1.
    on_confs = on_sample.tensors["item_confidences"]
    off_confs = off_sample.tensors["item_confidences"]
    assert torch.all((off_confs == 0.0) | (off_confs == 1.0))
    # The two should differ on at least one slot — Aegislash etc. usually have
    # a meta-guessed item with prob != 0/1.
    assert not torch.allclose(on_confs, off_confs)


def test_meta_off_preserves_revealed_slots(vocabs, row):
    """Revealed-source slots must be identical between modes."""
    e_on = Encoder(vocabs, mode="meta-on")
    e_off = Encoder(vocabs, mode="meta-off")
    on_sample = next(iter(e_on.encode_row(row)))
    off_sample = next(iter(e_off.encode_row(row)))

    on_conf = on_sample.tensors["item_confidences"]
    off_conf = off_sample.tensors["item_confidences"]
    # Slots where on=1.0 (revealed) must also be 1.0 in off.
    revealed_mask = (on_conf == 1.0)
    if revealed_mask.any():
        assert torch.all(off_conf[revealed_mask] == 1.0)


def test_action_labels_are_long_tensors(vocabs, row):
    e = Encoder(vocabs, mode="meta-on")
    sample = next(iter(e.encode_row(row)))
    for k in ("action_a_type", "action_a_move_id", "action_b_type", "action_b_target"):
        assert sample.tensors[k].dtype == torch.long
        # Scalar tensors
        assert sample.tensors[k].shape == ()


def test_encode_row_yields_two_per_turn(vocabs, row):
    """Each turn should produce one sample per player POV."""
    e = Encoder(vocabs, mode="meta-on")
    samples = list(e.encode_row(row))
    turns = json.loads(row["turns_json"])
    assert len(samples) == 2 * len(turns)
    povs = {s.pov_player for s in samples}
    assert povs == {"p1", "p2"}
