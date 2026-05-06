"""Shape + smoke test for the archetype-aware lead model."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")


def test_feature_builder_has_cluster_id():
    from vgc_model.lead.features import FeatureBuilder, N_ARCHETYPES

    b = FeatureBuilder()
    f = b.encode_pokemon("Sneasler")
    assert "cluster_id" in f
    # Sneasler is in the HO Top Cut cluster (id 1 in archetypes_1760.json)
    assert int(f["cluster_id"]) >= 1
    assert int(f["cluster_id"]) <= N_ARCHETYPES

    pad = b.encode_pokemon("<PAD>")
    assert int(pad["cluster_id"]) == 0  # unknown bucket


def test_encode_team_archetype_histogram():
    from vgc_model.lead.features import FeatureBuilder, N_ARCHETYPES

    b = FeatureBuilder()
    team = ["Sneasler", "Kingambit", "Basculegion", "Garchomp", "Floette-Mega", "Incineroar"]
    out = b.encode_team(team)
    assert "arch_hist" in out
    assert out["arch_hist"].shape == (N_ARCHETYPES + 1,)
    assert abs(out["arch_hist"].sum() - 1.0) < 1e-5  # normalized

    # Mostly HO Top Cut + bulky goodstuff — at least 2 clusters represented.
    assert (out["arch_hist"] > 0).sum() >= 2


def test_model_forward_with_archetype():
    from vgc_model.lead.features import FeatureBuilder
    from vgc_model.lead.model import LeadAdvisorModel

    b = FeatureBuilder()
    team = ["Sneasler", "Kingambit", "Basculegion", "Garchomp", "Floette-Mega", "Incineroar"]
    opp = ["Charizard-Mega-Y", "Venusaur", "Whimsicott", "Garchomp", "Aerodactyl", "Sinistcha"]

    own_feat = b.encode_team(team)
    opp_feat = b.encode_team(opp)
    own_t = {k: torch.from_numpy(v[None]) for k, v in own_feat.items()}
    opp_t = {k: torch.from_numpy(v[None]) for k, v in opp_feat.items()}

    model = LeadAdvisorModel(
        n_species=b.species_size,
        n_items=b.item_size,
        n_abilities=b.ability_size,
        n_moves=b.move_size,
        d_model=64,
        n_layers=2,
    )
    model.eval()
    with torch.no_grad():
        out = model(own_t, opp_t)
    assert out["team_logits"].shape == (1, 6)
    assert out["lead_logits"].shape == (1, 15)
    assert torch.isfinite(out["team_logits"]).all()
    assert torch.isfinite(out["lead_logits"]).all()
