# Usage stats — file layout & schema

Source: **Smogon chaos JSON** for `gen9championsvgc2026regma`, refreshed monthly.
Replaces the legacy Pikalytics scrape (top-50 species → species %).

## Files

- `gen9championsvgc2026regma.json` — flat `{species: stats}` map at the **1500 cut** (matches our 1400+ training slice). This is what `UsageStats` and downstream code load.
- `gen9championsvgc2026regma.meta.json` — sidecar with format id, month, cutoff, battle count, source URL.
- `cuts/gen9championsvgc2026regma_cut{0,1500,1630,1760}.json` — same shape, one file per ELO bracket. For ELO-stratified priors (e.g. blend `1500` for live spectator vs. `1760` for tournament search eval).
- `cuts/gen9championsvgc2026regma_cut{N}.meta.json` — sidecar for each cut.
- `summary.txt` — human-readable top species + sample fields.

## Per-species schema

```jsonc
{
  "Sneasler": {
    "source": "smogon",
    "usage_pct": 40.03,                  // % of teams that include this mon
    "raw_count": 2262250,                // raw weighted appearance count
    "viability_ceiling": [84712, 85, 74, 62],  // [battles, GXE max, avg, min]

    "moves":    {"Close Combat": 28.4, "Dire Claw": 27.8, ...},   // pct of slots-used
    "items":    {"White Herb": 79.4, "Focus Sash": 16.7, ...},
    "abilities":{"Unburden": 90.2, "Poison Touch": 7.7, ...},

    "spreads": [                         // top spreads, pct >= 0.5%, capped at 30
      {"nature": "Jolly",   "evs": "2/32/0/0/0/32", "pct": 28.6},
      {"nature": "Adamant", "evs": "2/32/0/0/0/32", "pct": 20.3}
    ],

    "teammates": {"Garchomp": 37.2, "Incineroar": 34.3, ...},  // pct of this mon's teams
    "checks_and_counters": {"Garchomp": 0.74, ...}             // KO+switch-out rate vs this mon
  }
}
```

### Field semantics

- **`usage_pct`** is doubled by Smogon for VGC (a team has 6 mons but ~1.5 unique species per appearance accounted via weights). Use as a relative ranking; do not assume column-sum = 100%.
- **`moves` / `items` / `abilities`** are normalized so each dict sums to ~100% per species. Names are PS **display names** (e.g. `"Close Combat"`, `"White Herb"`), converted from Smogon's id form via `data/ps_data/{moves,items,abilities}.json`.
- **Tera and Happiness are intentionally dropped** — Champions format does not use Terastallization, and Happiness has no in-battle effect in this format. Smogon's chaos JSON includes both fields but they carry no signal here.
- **`spreads`** is a list of objects, not a dict, because the same nature+EV string is unique. Truncated at 30 entries and 0.5% to keep file size sane (Sneasler alone has 7,051 raw spreads).
- **`teammates`** is normalized within the species (sums to ~500% for a 6-mon format → divide by 5 if you want fraction-of-teams). Smogon convention.
- **`checks_and_counters`** is often empty in VGC chaos JSON; treat as advisory.

### Backward compatibility

`UsageStats` (`src/vgc_model/data/usage_stats.py`) reads only `moves`, `items`, `abilities`, `teammates`, `sample_sets`, `source`, `count`. Smogon source omits `sample_sets` and `count`; consumers handle missing keys gracefully.

The old per-species `"source": "pikalytics" | "replays"` field is replaced by `"source": "smogon"`. No code branches on this string today.

## Refresh cadence

Smogon publishes monthly stats around the 1st of the following month. Run:

```bash
python3 scripts/build_usage_stats.py            # default: latest month, cut 1500
python3 scripts/build_usage_stats.py --month 2026-04 --all-cuts
```
