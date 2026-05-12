#!/usr/bin/env python3
"""Regenerate Resources/PokemonChampions/OpponentSetPrior.json from a
Smogon usage-stats dump.

The prior is consumed by `BattleStateTracker::pokemon_to_json` (C++ side)
to fill in opponent `item` / `ability` / `moves` when the live trace
hasn't observed a reveal yet — closes the train/inference distribution
shift on opp info. See memory `project_opp_set_prior.md`.

Usage:
    tools/generate_opp_set_prior.py
    tools/generate_opp_set_prior.py --format gen9championsvgc2026regmb
    tools/generate_opp_set_prior.py --src data/usage_stats/foo.json --out Resources/.../Bar.json

Refresh cadence: pull a fresh chaos dump from Smogon when the regulation
shifts (Reg M-A → Reg M-B, etc.), drop it under `data/usage_stats/` with
the matching format slug, run this. The C++ loader is lazy-init via
std::call_once — restart any running SerialPrograms after writing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FORMAT = "gen9championsvgc2026regma"
DEFAULT_SRC = REPO_ROOT / "data" / "usage_stats" / f"{DEFAULT_FORMAT}.json"
DEFAULT_OUT = REPO_ROOT / "switch_bot" / "Resources" / "PokemonChampions" / "OpponentSetPrior.json"

#  How many top moves to keep per species. Set to 4 to match a Pokemon's
#  4-move-slot UI; the prior's job is to fill the slot, not predict the
#  full move pool.
TOP_MOVES = 4


def slugify(name: str) -> str:
    """Mirror the slugification used by the C++ tracker / encoder.

    Lowercase, swap any run of non-[a-z0-9] for a single hyphen, strip
    leading/trailing hyphens. Empty input -> "".
    """
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def top1(d: dict[str, float] | None) -> str:
    """Most-used entry by percent. Empty -> "" (will trigger the C++
    side's fall-through-to-blank behavior for that field)."""
    if not d:
        return ""
    name, _ = max(d.items(), key=lambda kv: kv[1])
    return slugify(name)


def topN(d: dict[str, float] | None, n: int) -> list[str]:
    """Top-N most-used entries, slugified. Pads with empty strings to
    length n so every species has a fixed-shape moves list (the C++
    side iterates a known count)."""
    if not d:
        return [""] * n
    ranked = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
    out = [slugify(name) for name, _ in ranked[:n]]
    out += [""] * (n - len(out))
    return out


def build_priors(src_path: Path) -> dict[str, dict]:
    raw = json.loads(src_path.read_text())
    out: dict[str, dict] = {}
    for species, info in raw.items():
        if not isinstance(info, dict):
            continue
        key = slugify(species)
        if not key:
            continue
        out[key] = {
            "item": top1(info.get("items")),
            "ability": top1(info.get("abilities")),
            "moves": topN(info.get("moves"), TOP_MOVES),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--format", default=DEFAULT_FORMAT,
                    help=f"format slug (default: {DEFAULT_FORMAT})")
    ap.add_argument("--src", type=Path, default=None,
                    help=f"source JSON (default: data/usage_stats/<format>.json)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"output path (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})")
    args = ap.parse_args()

    src = args.src or (REPO_ROOT / "data" / "usage_stats" / f"{args.format}.json")
    if not src.exists():
        print(f"error: source not found: {src}", file=sys.stderr)
        return 2

    priors = build_priors(src)
    payload = {
        "format": args.format,
        "source": "smogon-chaos-cut1500",
        "priors": priors,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    try:
        display = args.out.relative_to(REPO_ROOT)
    except ValueError:
        display = args.out
    print(f"wrote {display}: {len(priors)} species")
    return 0


if __name__ == "__main__":
    sys.exit(main())
