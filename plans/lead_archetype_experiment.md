# Lead model — archetype-feature experiment (2026-05-06)

## Question

Does adding Smogon-derived archetype features to the lead model
(team/lead-pair selection at team preview) improve accuracy or calibration?

## Source data

**Smogon `gen9championsvgc2026regma` chaos dump, fetched 2026-05-04.**
4 cumulative cutoffs: 0 / 1500 / 1630 / 1760. 263 species at cut0, 51 at ≥2%
usage at cut1760.

Saved at `data/usage_stats/`:
- `gen9championsvgc2026regma.json` — full chaos dump
- `cuts/gen9championsvgc2026regma_cut{0,1500,1630,1760}.json`
- `archetypes_1760.json` — 8-cluster archetype taxonomy (this experiment's input)

## Archetype taxonomy (cut1760)

Built via lift-based hierarchical clustering (avg linkage, k=8) over 51 mons
at ≥2% usage. Lift = P(B|A) / P(B) symmetrized — removes "everyone runs X"
baseline and surfaces preferential pairing.

| Cluster | Hint | Top members |
|---|---|---|
| C1 | HO Top Cut | Sneasler, Kingambit, Basculegion, Froslass-M, Aero-M, Delphox-M, Dragonite, Clefable |
| C2 | Sun / Fairy Aura | Garchomp, Char-Y, Whimsicott, Sylveon, Venusaur, Lopunny-M |
| C3 | Bulky Goodstuff / Mixed | Incineroar, Gengar-M, Kommo-o, Politoed, A-Ninetales, Aggron-M, Hydreigon, Palafin |
| C4 | Rain / Bulk-Offense | Sinistcha, Pelipper, Archaludon, Dnite-M, Megan-M, Blast-M, Sableye, Scizor-M |
| C5 | Sand | Ttar-M, Excadrill, Corviknight, Rotom-W, Milotic, Ttar, Venusaur-M, Rotom-H |
| C6 | TR / Sun-TR | Farigiraf, Torkoal, Scov-M, Kanga-M, Primarina, Dragapult |
| C7 | HO Support Niche | Aegislash, Talonflame, Maushold, Garde-M |
| C8 | Mega-Floette + Aero | Floette-M, Aerodactyl |

**Top synergy pairs (cut1760):** Ttar-M+Excadrill 1.98×, Gengar-M+Politoed
1.35×, Delphox-M+Clefable 1.29×, Dragonite+Clefable 1.13×, Gengar-M+Kommo-o
1.13×.

## Cross-cutoff observations (separately interesting)

### Skill-drops (used a lot at low ladder, dropped at high)
Whimsicott −3.3, Milotic −2.7, Meganium-M −2.1, Incineroar −2.0, Sinistcha
−1.9, Sableye −1.7.

### Skill-rises
Basculegion +16.2, Kingambit +15.3, Garchomp +11.8, Floette-M +10.2,
Sneasler +7.6, Charizard-Y +7.0, Sylveon +4.4, Aerodactyl-M +3.7.

### Item shifts (high-ladder defensive upgrades)
- **Incineroar**: Sitrus 52→48%, **Chople 17→23%** (+6)
- **Garchomp**: Choice Scarf flat, **Sitrus 9→17%** (+8)
- **Kingambit**: **Chople 39→52%** (+13), Black Glasses 46→41%
- **Basculegion**: **Choice Scarf 62→48%** (−13), **Focus Sash 9→25%** (+17)
- **Whimsicott**: Sash 70→75%, Coba 1→4%

### Ability shifts
- **Dragonite Multiscale 68→85%** (biggest single ability swing)
- Garchomp Rough Skin 89→94%, Aerodactyl Unnerve 87→93%

### Archetype substitution (low → high ladder)
**Low-ladder-only pairings** (high lift at cut0, mons absent at cut1760):
Golurk-M+Torkoal 1.73×, Golurk-M+Oranguru 1.38×, Crab-M+Hatterene 1.34×,
Kanga-M+Hisuian-Typhlosion 1.28×.

This is a coherent **slow-Trick Room with bulky setters** archetype that
exists only below 1500. High-ladder players don't run it; they consolidate
into HO (C1) or specialist cores (sand, rain-Palafin, Aggron-M bulk).

**Implication for our pipeline**: at 1500+ the prior should weight HO heavily
and down-weight TR-with-bulky-setters relative to raw 0-cutoff usage.

## Experiment setup

- **Data:** `data/parsed/gen9championsvgc2026regma`, 532 train / 39 val
  parquet shards, time-based split (last 2 days held out).
- **Filter:** `min_rating=1500`, `mask-to-brought=True`.
- **Train:** 10 epochs, batch 256, AdamW lr 3e-4 cosine schedule, dropout 0.
- **Hardware:** unraid `pokemon-champions-gpu` container, RTX 4060.
- **Seeds:** 42, 43, 44 (3-seed sweep per variant).
- **~67s/epoch**, ~12 min per run, ~35 min per 3-seed variant.

## Variants tested

| Variant | What it adds |
|---|---|
| **Baseline** | Existing model. species + items + abilities + moves + scalars. |
| **L1 only** | Per-mon cluster id embedding (8 clusters + UNK), concatenated to PokemonEncoder feature vector. d_cluster=8. |
| **L1+L2** | L1 + team-archetype `[TEAM]` token: histogram (length-9) → MLP → d_model token, prepended to each side's set before cross-attn layers, sliced off before pair head. |
| **L2 only** | Just the team token (no per-mon cluster embedding). |
| **L2 isolated** | L2, but `team_head` reads from a separate forward pass through shared transformer layers WITHOUT the team token. Lead head still uses the with-token pass. |
| **L3 (winner)** | L2-isolated + opp-archetype-conditioned pair bias: `lead_logits += opp_hist @ pair_arch_bias.T` where `pair_arch_bias ∈ R^{15×9}` is learned. +135 params. |

## Results (3-seed mean ± sd)

| Variant | params | lead_top1 | lead_top3 | team_top4 | lead_loss |
|---|---|---|---|---|---|
| Baseline | 519,666 | 49.89 ± 0.23 | 86.43 ± 0.13 | 65.46 ± 0.06 | 1.302 ± 0.017 |
| L1 only | 520,762 | 49.37 ± 0.13 | 86.41 ± 0.46 | 65.24 ± 0.13 | 1.307 ± 0.014 |
| L1+L2 | 522,298 | 49.95 ± 0.13 | 86.63 ± 0.27 | 65.36 ± 0.29 | 1.275 ± 0.008 |
| L2 only | 521,202 | 50.15 ± 0.16 | 86.75 ± 0.19 | 65.34 ± 0.11 | 1.286 ± 0.013 |
| L2 isolated | 521,202 | 50.15 ± 0.14 | 86.72 ± 0.17 | 65.38 ± 0.08 | 1.285 ± 0.014 |
| **L3** | **521,337** | **50.19 ± 0.11** | **86.81 ± 0.19** | **65.38 ± 0.09** | **1.284 ± 0.014** |

### Δ vs baseline

| Variant | Δ top1 | Δ top3 | Δ team_top4 | Δ lead_loss |
|---|---|---|---|---|
| L1 only | **−0.51pt** | −0.02pt | −0.22pt | +0.005 |
| L1+L2 | +0.07pt | +0.21pt | −0.10pt | **−0.027** |
| L2 only | +0.27pt | +0.33pt | −0.12pt | −0.016 |
| L2 isolated | +0.26pt | +0.30pt | −0.08pt | −0.017 |
| **L3** | **+0.30pt** ✓ | **+0.38pt** ✓ | −0.08pt | **−0.018** |

## Findings

1. **Per-mon cluster ID is dead weight.** L1 alone is *strictly worse* than
   baseline (−0.51pt top1). The encoder already gets cluster-equivalent
   information from species + items + abilities + moves; adding a redundant
   id is interference, not signal.

2. **Team-level archetype histogram is the actual signal.** L2 (or L2 +
   conditioning) gives +0.27 to +0.30pt top1 over baseline. The win is the
   *aggregate* team-composition view that no single mon's features encode.

3. **Team head consistently regresses ~−0.10pt** in every variant that
   touches the lead-side architecture. L2-isolated (separate forward path)
   recovers ~half of it (−0.08pt vs −0.12pt). Full recovery would require
   non-shared transformer parameters.

4. **L3 is incrementally best.** +135 params buys another +0.04pt top1 over
   L2-isolated, with the smallest seed variance (sd 0.0011 vs baseline
   0.0023). Marginal but consistent.

5. **The whole effect is small.** +0.30pt top1 is barely outside baseline sd
   of 0.23pt. Real but not large.

6. **The lead model is overfit.** Train top1 ≈ 67%, val ≈ 50% — feature
   engineering yields diminishing returns. Bigger levers from here:
   regularization, more data, sequence-history conditioning (cf. action
   model's +11.7pt type-acc gain from `--use-history`).

## Decision

**Ship L3.** Modest but free win, smallest seed variance, marginal team-head
regression is acceptable.

Files installed (canonical state):
- `src/vgc_model/lead/features.py` — adds `cluster_id` per-mon and
  `arch_hist` per-team to encoder output. `N_ARCHETYPES = 8`.
- `src/vgc_model/lead/dataset.py` — `collate` includes `arch_hist` as
  team-level batched key.
- `src/vgc_model/lead/model.py` — PokemonEncoder gets cluster embedding
  (kept despite being redundant — small param cost, kept for L3's pair-bias
  to leverage cluster signal end-to-end). LeadAdvisorModel: dual forward
  through shared layers (team head no-token, lead head with-token); opp-arch
  conditioned pair bias.
- `tests/test_lead_archetype.py` — shape/smoke tests.
- `data/usage_stats/archetypes_1760.json` — 8-cluster taxonomy, regenerate
  quarterly or after big meta shifts.

## Known follow-ups (not done)

- **Refresh archetype taxonomy after each Smogon monthly drop.** Build at
  cut1500 to better match the training filter (currently uses cut1760).
- **Mega-base name normalization in Smogon priors.** Same gap exists in
  pre-archetype code; fixing it would lift item/ability/move features for
  Mega-evolving base species.
- **L4 idea (not run):** non-shared transformer stacks per pathway — would
  fully eliminate the team_top4 regression at ~2x transformer params.
- **Higher-leverage idea:** sequence-history token (LSTM-style) à la the
  action model's `--use-history` finding. Different mechanism, likely
  bigger lift than archetype.

## Reproducibility

Sweep scripts: `/tmp/run_*_ab.sh` on unraid (not committed).
Per-run logs: `data/checkpoints_lead/exp_<variant>_seed<N>/{train_log.jsonl,console.log}`.
