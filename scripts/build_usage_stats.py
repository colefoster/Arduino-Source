#!/usr/bin/env python3
"""Build per-species usage statistics for Champions VGC format.

Two data sources, used in priority order:
  1. Pikalytics tournament data (top 50 species) — team-sheet-derived percentages
  2. Local replay corpus (fallback for rare species) — raw counts from battle logs

Output:
  data/usage_stats/gen9championsvgc2026regma.json
  data/usage_stats/summary.txt
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# In a git worktree, data/ may not exist — resolve to the main repo
_MAIN_REPO = Path(os.environ.get("REPO_ROOT", PROJECT_ROOT))
PIKALYTICS_BASE = "https://www.pikalytics.com/ai/pokedex/championstournaments"
_REPLAY_BASE = _MAIN_REPO / "data" / "showdown_replays"
REPLAY_DIRS = [
    _REPLAY_BASE / "gen9championsvgc2026regma",
    _REPLAY_BASE / "spectated" / "gen9championsvgc2026regma",
    _REPLAY_BASE / "downloaded" / "gen9championsvgc2026regma",
]
OUTPUT_DIR = PROJECT_ROOT / "data" / "usage_stats"
OUTPUT_FILE = OUTPUT_DIR / "gen9championsvgc2026regma.json"
SUMMARY_FILE = OUTPUT_DIR / "summary.txt"

RATE_LIMIT_SECS = 1.0


# ---------------------------------------------------------------------------
# Pikalytics fetching
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> str:
    """Fetch URL content as string with a polite User-Agent."""
    req = Request(url, headers={"User-Agent": "pokemon-champions-usage-stats/1.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_pikalytics_index(markdown: str) -> list[str]:
    """Extract species names from the Pikalytics index page markdown."""
    species = []
    # Match rows like: | 1 | **Incineroar** | 51.19% | ...
    for m in re.finditer(r'\|\s*\d+\s*\|\s*\*\*(.+?)\*\*\s*\|', markdown):
        name = m.group(1).strip()
        if name not in species:
            species.append(name)
    return species


def parse_bullet_list(text: str, section_header: str) -> dict[str, float]:
    """Parse a markdown section with bullet items like '- **Name**: 99.05%'."""
    result = {}
    pattern = re.compile(
        r'^##\s+' + re.escape(section_header) + r'\s*$',
        re.MULTILINE
    )
    match = pattern.search(text)
    if not match:
        return result

    # Get text from this section header to the next ## header
    start = match.end()
    next_section = re.search(r'^##\s+', text[start:], re.MULTILINE)
    section_text = text[start:start + next_section.start()] if next_section else text[start:]

    for item in re.finditer(r'-\s+\*\*(.+?)\*\*:\s*([\d.]+)%', section_text):
        name = item.group(1).strip()
        pct = float(item.group(2))
        result[name] = pct
    return result


def parse_teammates(text: str) -> dict[str, float]:
    """Parse Common Teammates section."""
    return parse_bullet_list(text, "Common Teammates")


def parse_featured_teams(text: str) -> list[dict]:
    """Parse Featured Teams section into sample sets."""
    sets = []
    # Split on team headers like "### Team 1 by ..."
    team_blocks = re.split(r'###\s+Team\s+\d+\s+by\s+', text)
    for block in team_blocks[1:]:  # skip text before first team
        sample = {}
        # Ability
        ability_m = re.search(r'\*\*Ability\*\*:\s*(.+)', block)
        if ability_m:
            sample["ability"] = ability_m.group(1).strip()
        # Item
        item_m = re.search(r'\*\*Item\*\*:\s*(.+)', block)
        if item_m:
            sample["item"] = item_m.group(1).strip()
        # Moves — "**Moves**: Move1, Move2, Move3, Move4"
        moves_m = re.search(r'\*\*Moves\*\*:\s*(.+)', block)
        if moves_m:
            moves = [m.strip() for m in moves_m.group(1).split(",")]
            sample["moves"] = moves

        if sample.get("moves"):
            sets.append(sample)
    return sets


def fetch_species_data(species: str) -> dict:
    """Fetch and parse a single species page from Pikalytics."""
    url = f"{PIKALYTICS_BASE}/{species}"
    md = fetch_url(url)

    data = {
        "source": "pikalytics",
        "moves": parse_bullet_list(md, "Common Moves"),
        "items": parse_bullet_list(md, "Common Items"),
        "abilities": parse_bullet_list(md, "Common Abilities"),
        "teammates": parse_teammates(md),
        "sample_sets": parse_featured_teams(md),
    }

    # Spreads — Pikalytics may or may not have them
    spreads = parse_spreads(md)
    if spreads:
        data["spreads"] = spreads

    return data


def parse_spreads(text: str) -> list[dict]:
    """Parse EV spread data if available. Currently Pikalytics doesn't provide this."""
    # Placeholder — Pikalytics says "No EV spread or nature data available"
    return []


def fetch_all_pikalytics(species_list: list[str], verbose: bool = True) -> dict:
    """Fetch data for all Pikalytics species with rate limiting."""
    results = {}
    total = len(species_list)
    for i, species in enumerate(species_list):
        if verbose:
            print(f"  [{i+1}/{total}] Fetching {species}...", end=" ", flush=True)
        try:
            data = fetch_species_data(species)
            results[species] = data
            if verbose:
                print(f"OK ({len(data['moves'])} moves, {len(data['items'])} items)")
        except (HTTPError, URLError) as e:
            if verbose:
                print(f"FAILED: {e}")
        if i < total - 1:
            time.sleep(RATE_LIMIT_SECS)
    return results


# ---------------------------------------------------------------------------
# Replay corpus parsing (fallback)
# ---------------------------------------------------------------------------

def normalize_species(raw: str) -> str:
    """Normalize species name from PS log format.

    e.g. 'Rotom-Wash, L50, F' -> 'Rotom-Wash'
         'Kangaskhan-Mega, L50, F' -> 'Kangaskhan-Mega'
    """
    # Strip everything after the first comma
    name = raw.split(",")[0].strip()
    return name


def parse_replay_log(log: str) -> dict[str, dict]:
    """Parse a PS battle log and extract per-species usage data.

    Returns {species: {"moves": set, "items": set, "abilities": set}}
    """
    species_data = defaultdict(lambda: {"moves": set(), "items": set(), "abilities": set()})

    # Map slot identifiers (e.g. "p1a: Incineroar") to species
    slot_to_species = {}

    for line in log.split("\n"):
        parts = line.split("|")
        if len(parts) < 3:
            continue

        cmd = parts[1].strip()

        if cmd == "poke":
            # |poke|p1|Incineroar, L50, F|
            if len(parts) >= 4:
                species = normalize_species(parts[3])
                # Don't map slot yet — that happens on switch
        elif cmd == "switch" or cmd == "drag":
            # |switch|p1a: Incineroar|Incineroar, L50, F|100/100
            if len(parts) >= 4:
                slot = parts[2].strip()
                species = normalize_species(parts[3])
                slot_to_species[slot] = species
        elif cmd == "detailschange":
            # |detailschange|p2b: Kangaskhan|Kangaskhan-Mega, L50, F
            # Update slot mapping to mega form
            if len(parts) >= 4:
                slot = parts[2].strip()
                species = normalize_species(parts[3])
                slot_to_species[slot] = species
        elif cmd == "move":
            # |move|p1a: Incineroar|Fake Out|p2b: Kangaskhan
            if len(parts) >= 4:
                slot = parts[2].strip()
                move = parts[3].strip()
                species = slot_to_species.get(slot)
                if species:
                    species_data[species]["moves"].add(move)
        elif cmd == "-ability":
            # |-ability|p1a: Incineroar|Intimidate|...
            if len(parts) >= 4:
                slot = parts[2].strip()
                ability = parts[3].strip()
                species = slot_to_species.get(slot)
                if species:
                    species_data[species]["abilities"].add(ability)
        elif cmd in ("-item", "-enditem"):
            # |-item|p1a: Incineroar|Sitrus Berry|...
            # |-enditem|p1b: Whimsicott|Focus Sash|...
            if len(parts) >= 4:
                slot = parts[2].strip()
                item = parts[3].strip()
                # Filter out items that are just move effects
                if item and not item.startswith("["):
                    species = slot_to_species.get(slot)
                    if species:
                        species_data[species]["items"].add(item)
        elif cmd == "-mega":
            # |-mega|p2b: Kangaskhan|Kangaskhan|Kangaskhanite
            if len(parts) >= 5:
                slot = parts[2].strip()
                stone = parts[4].strip()
                species = slot_to_species.get(slot)
                if species:
                    species_data[species]["items"].add(stone)

    return dict(species_data)


def scan_replays(replay_dirs: list[Path], verbose: bool = True) -> dict:
    """Scan all replay JSONs and aggregate per-species usage counts.

    Returns {species: {"source": "replays", "count": N,
                       "moves": {move: count}, "items": {item: count},
                       "abilities": {ability: count}}}
    """
    species_moves = defaultdict(lambda: defaultdict(int))
    species_items = defaultdict(lambda: defaultdict(int))
    species_abilities = defaultdict(lambda: defaultdict(int))
    species_count = defaultdict(int)

    total_replays = 0
    seen_files = set()

    for replay_dir in replay_dirs:
        if not replay_dir.exists():
            if verbose:
                print(f"  Skipping {replay_dir} (not found)")
            continue
        files = list(replay_dir.glob("*.json"))
        if verbose:
            print(f"  Scanning {replay_dir.name}: {len(files)} files")
        for f in files:
            # Deduplicate across ELO-sliced dirs (same replay may appear in multiple)
            replay_id = f.stem
            if replay_id in seen_files:
                continue
            seen_files.add(replay_id)

            try:
                with open(f) as fh:
                    data = json.load(fh)
                log = data.get("log", "")
                if not log:
                    continue
                parsed = parse_replay_log(log)
                total_replays += 1
                for species, info in parsed.items():
                    species_count[species] += 1
                    for move in info["moves"]:
                        species_moves[species][move] += 1
                    for item in info["items"]:
                        species_items[species][item] += 1
                    for ability in info["abilities"]:
                        species_abilities[species][ability] += 1
            except (json.JSONDecodeError, KeyError):
                continue

    if verbose:
        print(f"  Parsed {total_replays} unique replays, found {len(species_count)} species")

    results = {}
    for species in species_count:
        results[species] = {
            "source": "replays",
            "count": species_count[species],
            "moves": dict(sorted(species_moves[species].items(), key=lambda x: -x[1])),
            "items": dict(sorted(species_items[species].items(), key=lambda x: -x[1])),
            "abilities": dict(sorted(species_abilities[species].items(), key=lambda x: -x[1])),
        }
    return results


# ---------------------------------------------------------------------------
# Merge & output
# ---------------------------------------------------------------------------

def normalize_for_lookup(name: str) -> str:
    """Normalize a species name for matching across sources.

    Strips mega suffixes, lowercases, etc.
    """
    return name.lower().replace(" ", "").replace("-", "")


def merge_sources(pikalytics: dict, replays: dict) -> dict:
    """Merge Pikalytics (primary) and replay (fallback) data.

    Pikalytics species take priority. Replay data fills in uncovered species.
    For Pikalytics species that also appear in replays with mega forms,
    the mega forms get their own replay-sourced entries.
    """
    merged = dict(pikalytics)

    # Build a set of normalized Pikalytics species names for dedup
    pikalytics_normalized = set()
    for name in pikalytics:
        pikalytics_normalized.add(normalize_for_lookup(name))

    for species, data in replays.items():
        norm = normalize_for_lookup(species)
        if norm not in pikalytics_normalized:
            merged[species] = data

    # Sort by source (pikalytics first) then alphabetically
    def sort_key(item):
        name, data = item
        return (0 if data["source"] == "pikalytics" else 1, name.lower())

    return dict(sorted(merged.items(), key=sort_key))


def generate_summary(stats: dict) -> str:
    """Generate a human-readable summary report."""
    lines = []
    lines.append("=" * 70)
    lines.append("Champions VGC 2026 Reg M-A — Usage Statistics Summary")
    lines.append("=" * 70)
    lines.append("")

    pikalytics_species = [s for s, d in stats.items() if d["source"] == "pikalytics"]
    replay_species = [s for s, d in stats.items() if d["source"] == "replays"]

    lines.append(f"Total species: {len(stats)}")
    lines.append(f"  From Pikalytics: {len(pikalytics_species)}")
    lines.append(f"  From replays:    {len(replay_species)}")
    lines.append("")

    # Top Pikalytics species
    lines.append("-" * 70)
    lines.append("TOP PIKALYTICS SPECIES (by move count)")
    lines.append("-" * 70)
    for species in pikalytics_species[:10]:
        data = stats[species]
        top_moves = list(data["moves"].keys())[:4]
        top_item = next(iter(data["items"]), "???")
        top_ability = next(iter(data["abilities"]), "???")
        lines.append(f"\n  {species}")
        lines.append(f"    Moves: {', '.join(top_moves)}")
        lines.append(f"    Item:  {top_item} ({data['items'].get(top_item, 0):.1f}%)")
        lines.append(f"    Ability: {top_ability} ({data['abilities'].get(top_ability, 0):.1f}%)")
        if data.get("sample_sets"):
            lines.append(f"    Sample sets: {len(data['sample_sets'])}")

    # Top replay-only species
    if replay_species:
        lines.append("")
        lines.append("-" * 70)
        lines.append("TOP REPLAY-ONLY SPECIES (by appearance count)")
        lines.append("-" * 70)
        sorted_replay = sorted(replay_species, key=lambda s: stats[s]["count"], reverse=True)
        for species in sorted_replay[:20]:
            data = stats[species]
            top_moves = list(data["moves"].keys())[:4]
            lines.append(f"\n  {species} (seen {data['count']} times)")
            lines.append(f"    Moves: {', '.join(top_moves)}")
            if data["items"]:
                lines.append(f"    Items: {', '.join(list(data['items'].keys())[:3])}")
            if data["abilities"]:
                lines.append(f"    Abilities: {', '.join(list(data['abilities'].keys())[:3])}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pikalytics-only", action="store_true",
                        help="Only fetch Pikalytics data, skip replay scanning")
    parser.add_argument("--replays-only", action="store_true",
                        help="Only scan replays, skip Pikalytics fetching")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    verbose = not args.quiet
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pikalytics_data = {}
    replay_data = {}

    # --- Source 1: Pikalytics ---
    if not args.replays_only:
        if verbose:
            print("Fetching Pikalytics index...")
        try:
            index_md = fetch_url(PIKALYTICS_BASE)
            species_list = parse_pikalytics_index(index_md)
            if verbose:
                print(f"Found {len(species_list)} species on Pikalytics")
            pikalytics_data = fetch_all_pikalytics(species_list, verbose=verbose)
        except (HTTPError, URLError) as e:
            print(f"ERROR: Could not fetch Pikalytics index: {e}", file=sys.stderr)
            if not args.pikalytics_only:
                print("Falling back to replay-only mode", file=sys.stderr)

    # --- Source 2: Replay corpus ---
    if not args.pikalytics_only:
        if verbose:
            print("\nScanning replay corpus...")
        replay_data = scan_replays(REPLAY_DIRS, verbose=verbose)

    # --- Merge ---
    if verbose:
        print("\nMerging sources...")
    merged = merge_sources(pikalytics_data, replay_data)

    # --- Write output ---
    with open(OUTPUT_FILE, "w") as f:
        json.dump(merged, f, indent=2)
    if verbose:
        print(f"Wrote {OUTPUT_FILE} ({len(merged)} species)")

    summary = generate_summary(merged)
    with open(SUMMARY_FILE, "w") as f:
        f.write(summary)
    if verbose:
        print(f"Wrote {SUMMARY_FILE}")
        print("\n" + summary)


if __name__ == "__main__":
    main()
