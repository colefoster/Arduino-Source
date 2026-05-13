#!/usr/bin/env python3
"""Build per-species usage statistics for Champions VGC format.

Source: Smogon chaos JSON (https://www.smogon.com/stats/{month}/chaos/).
Replaces the legacy Pikalytics scrape — Smogon publishes the official ladder
stats for `gen9championsvgc2026regma` every month, with full per-species
distributions (moves, items, abilities, tera, spreads, teammates, checks).

Output: see data/usage_stats/SCHEMA.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import io
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MAIN_REPO = Path(os.environ.get("REPO_ROOT", PROJECT_ROOT))

FORMAT_ID = "gen9championsvgc2026regma"
DEFAULT_CUT = 1500
ALL_CUTS = [0, 1500, 1630, 1760]

OUTPUT_DIR = PROJECT_ROOT / "data" / "usage_stats"
CUTS_DIR = OUTPUT_DIR / "cuts"
DEFAULT_OUT = OUTPUT_DIR / f"{FORMAT_ID}.json"
DEFAULT_META = OUTPUT_DIR / f"{FORMAT_ID}.meta.json"
SUMMARY_FILE = OUTPUT_DIR / "summary.txt"

PS_DATA_DIR = _MAIN_REPO / "data" / "ps_data"
MOVES_FILE = PS_DATA_DIR / "moves.json"
ITEMS_FILE = PS_DATA_DIR / "items.json"
ABILITIES_FILE = PS_DATA_DIR / "abilities.json"

# Spreads: keep top N with pct >= threshold to bound file size.
SPREADS_MAX = 30
SPREADS_MIN_PCT = 0.5

# User-Agent matters: Smogon's nginx returns 405 to default urllib UA.
# Accept-Encoding: gzip is also required.
HTTP_HEADERS = {
    "User-Agent": "mimikyu-usage-stats/2.0",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}


# ---------------------------------------------------------------------------
# id -> display name maps (built from ps_data)
# ---------------------------------------------------------------------------

def _load_name_map(path: Path) -> dict[str, str]:
    """Load ps_data/{moves,items,abilities}.json and return id -> display name."""
    with open(path) as f:
        d = json.load(f)
    out = {}
    for key, entry in d.items():
        name = entry.get("name") if isinstance(entry, dict) else None
        if name:
            out[key] = name
    return out


def _load_ps_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    return (
        _load_name_map(MOVES_FILE),
        _load_name_map(ITEMS_FILE),
        _load_name_map(ABILITIES_FILE),
    )


def _humanize(name_id: str, name_map: dict[str, str]) -> str:
    """Convert chaos-JSON id (e.g. 'closecombat') to display name ('Close Combat').

    Falls back to the raw id if not found (rare items like new DLC moves not yet
    in ps_data — caller can decide whether to include or skip).
    """
    return name_map.get(name_id, name_id)


# ---------------------------------------------------------------------------
# Smogon fetch
# ---------------------------------------------------------------------------

def fetch_chaos(month: str, cut: int) -> dict:
    """Download and parse the chaos JSON for one (month, cut)."""
    url = f"https://www.smogon.com/stats/{month}/chaos/{FORMAT_ID}-{cut}.json"
    req = Request(url, headers=HTTP_HEADERS)
    with urlopen(req, timeout=60) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def latest_available_month() -> str:
    """Smogon publishes month N around the 1st of month N+1.

    We optimistically try last month first; the caller can fall back further.
    """
    today = _dt.date.today()
    first = today.replace(day=1)
    last_month = first - _dt.timedelta(days=1)
    return f"{last_month.year:04d}-{last_month.month:02d}"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _to_pct(weighted: dict[str, float]) -> dict[str, float]:
    """Normalize a chaos-JSON weighted-count dict to percentages summing to ~100."""
    total = sum(v for v in weighted.values() if v > 0)
    if total <= 0:
        return {}
    return {k: round(v / total * 100, 4) for k, v in weighted.items() if v > 0}


def _humanize_pct_dict(
    weighted: dict[str, float], name_map: dict[str, str]
) -> dict[str, float]:
    """Normalize + map ids to display names + sort desc."""
    pct = _to_pct(weighted)
    renamed: dict[str, float] = {}
    for key, val in pct.items():
        display = _humanize(key, name_map)
        # Two ids could collide post-display (rare); sum if so.
        renamed[display] = renamed.get(display, 0.0) + val
    return dict(sorted(renamed.items(), key=lambda x: -x[1]))


def _normalize_spreads(weighted: dict[str, float]) -> list[dict]:
    """Convert chaos 'Nature:HP/Atk/Def/SpA/SpD/Spe' weights to a sorted list."""
    pct = _to_pct(weighted)
    rows: list[dict] = []
    for spread, p in sorted(pct.items(), key=lambda x: -x[1]):
        if p < SPREADS_MIN_PCT:
            break
        if ":" not in spread:
            continue
        nature, evs = spread.split(":", 1)
        rows.append({"nature": nature, "evs": evs, "pct": p})
        if len(rows) >= SPREADS_MAX:
            break
    return rows


def _normalize_teammates(weighted: dict[str, float]) -> dict[str, float]:
    """Teammate names are already PS display names (e.g. 'Rotom-Wash')."""
    pct = _to_pct(weighted)
    return dict(sorted(pct.items(), key=lambda x: -x[1]))


def _normalize_checks(checks: dict) -> dict[str, float]:
    """chaos `Checks and Counters` values are [n, score, stddev] — keep `score`."""
    out: dict[str, float] = {}
    for name, val in checks.items():
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            out[name] = round(float(val[1]), 4)
        elif isinstance(val, (int, float)):
            out[name] = round(float(val), 4)
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def transform_species(
    raw: dict,
    moves_map: dict[str, str],
    items_map: dict[str, str],
    abilities_map: dict[str, str],
) -> dict:
    """Transform one chaos-JSON species entry into our schema."""
    out = OrderedDict()
    out["source"] = "smogon"
    out["usage_pct"] = round(raw.get("usage", 0.0) * 100, 4)
    out["raw_count"] = int(raw.get("Raw count", 0))
    vc = raw.get("Viability Ceiling")
    if isinstance(vc, list):
        out["viability_ceiling"] = vc

    out["moves"] = _humanize_pct_dict(raw.get("Moves", {}), moves_map)
    out["items"] = _humanize_pct_dict(raw.get("Items", {}), items_map)
    out["abilities"] = _humanize_pct_dict(raw.get("Abilities", {}), abilities_map)
    out["spreads"] = _normalize_spreads(raw.get("Spreads", {}))
    out["teammates"] = _normalize_teammates(raw.get("Teammates", {}))

    cc = raw.get("Checks and Counters") or {}
    if cc:
        out["checks_and_counters"] = _normalize_checks(cc)

    return out


def transform_all(chaos: dict) -> tuple[dict, dict]:
    """Return (species_data, meta) tuples in schema-compliant shape."""
    moves_map, items_map, abilities_map = _load_ps_maps()

    species_out: dict[str, dict] = {}
    for name, entry in chaos.get("data", {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("usage", 0.0) <= 0:
            continue
        species_out[name] = transform_species(
            entry, moves_map, items_map, abilities_map
        )

    species_out = dict(
        sorted(species_out.items(), key=lambda x: -x[1].get("usage_pct", 0.0))
    )

    info = chaos.get("info", {})
    meta = {
        "format": info.get("metagame", FORMAT_ID),
        "cutoff": info.get("cutoff"),
        "battles": info.get("number of battles"),
        "source": "smogon-chaos",
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "species_count": len(species_out),
    }
    return species_out, meta


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def generate_summary(stats: dict, meta: dict) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("Champions VGC 2026 Reg M-A — Usage Statistics (Smogon)")
    lines.append("=" * 70)
    lines.append(f"Format:        {meta.get('format')}")
    lines.append(f"Month/cutoff:  {meta.get('cutoff')}")
    lines.append(f"Battles:       {meta.get('battles'):,}")
    lines.append(f"Species seen:  {meta.get('species_count')}")
    lines.append(f"Fetched at:    {meta.get('fetched_at')}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("TOP 20 BY USAGE")
    lines.append("-" * 70)
    for i, (name, data) in enumerate(list(stats.items())[:20], 1):
        top_move = next(iter(data.get("moves") or {}), "—")
        top_item = next(iter(data.get("items") or {}), "—")
        top_ability = next(iter(data.get("abilities") or {}), "—")
        lines.append(
            f"{i:>2}. {name:<22} "
            f"usage={data.get('usage_pct', 0):>5.2f}%  "
            f"item={top_item:<18} "
            f"ability={top_ability:<14} "
            f"top-move={top_move}"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_cut(month: str, cut: int, verbose: bool = True) -> tuple[dict, dict]:
    if verbose:
        print(f"  Fetching {month} cut {cut}...", end=" ", flush=True)
    try:
        chaos = fetch_chaos(month, cut)
    except (HTTPError, URLError) as e:
        if verbose:
            print(f"FAILED: {e}")
        raise
    species, meta = transform_all(chaos)
    if verbose:
        print(f"OK ({len(species)} species, {meta['battles']:,} battles)")

    CUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CUTS_DIR / f"{FORMAT_ID}_cut{cut}.json"
    meta_path = CUTS_DIR / f"{FORMAT_ID}_cut{cut}.meta.json"
    with open(out_path, "w") as f:
        json.dump(species, f, indent=2)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    return species, meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month", default=None,
        help="YYYY-MM (default: latest fully-published month)"
    )
    parser.add_argument(
        "--cut", type=int, default=DEFAULT_CUT,
        help=f"ELO cut to write as the default flat file (default {DEFAULT_CUT})"
    )
    parser.add_argument(
        "--all-cuts", action="store_true",
        help="Also fetch/write 0, 1500, 1630, 1760 to cuts/"
    )
    parser.add_argument(
        "--quiet", action="store_true"
    )
    args = parser.parse_args()
    verbose = not args.quiet

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    month = args.month or latest_available_month()
    if verbose:
        print(f"Source: Smogon chaos JSON for {FORMAT_ID}, month {month}")

    cuts_to_fetch = ALL_CUTS if args.all_cuts else [args.cut]
    if args.cut not in cuts_to_fetch:
        cuts_to_fetch.append(args.cut)

    default_species: dict | None = None
    default_meta: dict | None = None

    for cut in cuts_to_fetch:
        try:
            species, meta = write_cut(month, cut, verbose=verbose)
        except (HTTPError, URLError) as e:
            print(
                f"ERROR fetching cut {cut} for {month}: {e}\n"
                f"  Try --month with an earlier YYYY-MM if month not yet published.",
                file=sys.stderr,
            )
            if cut == args.cut:
                sys.exit(2)
            continue
        if cut == args.cut:
            default_species = species
            default_meta = meta

    if default_species is None or default_meta is None:
        print("ERROR: requested default cut was not fetched", file=sys.stderr)
        sys.exit(2)

    with open(DEFAULT_OUT, "w") as f:
        json.dump(default_species, f, indent=2)
    with open(DEFAULT_META, "w") as f:
        json.dump(default_meta, f, indent=2)
    if verbose:
        print(f"Wrote {DEFAULT_OUT} ({len(default_species)} species)")
        print(f"Wrote {DEFAULT_META}")

    summary = generate_summary(default_species, default_meta)
    with open(SUMMARY_FILE, "w") as f:
        f.write(summary)
    if verbose:
        print(f"Wrote {SUMMARY_FILE}")
        print()
        print(summary)


if __name__ == "__main__":
    main()
