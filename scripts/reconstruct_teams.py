#!/usr/bin/env python3
"""Reconstruct full team info from spectated battle logs.

Parses complete replay logs to extract everything revealed about each
player's team: species, moves, items, abilities. Since spectated logs
are third-party POV, some info is never revealed (e.g. a bench Pokemon's
moves if it never switches in, or an item that never triggers).

This script measures how much of each player's team data we can recover
from the full log, and writes enriched replay JSONs with a `teams` field.

Usage:
    python scripts/reconstruct_teams.py                          # scan local
    python scripts/reconstruct_teams.py --dir /path/to/replays   # custom dir
    python scripts/reconstruct_teams.py --enrich                 # write teams back to JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReconstructedPokemon:
    species: str
    moves: list[str] = field(default_factory=list)
    item: str = ""
    ability: str = ""
    mega: bool = False
    brought: bool = False  # was this Pokemon selected for battle?
    switched_in: bool = False  # did it ever appear on the field?


@dataclass
class ReconstructedTeam:
    pokemon: dict[str, ReconstructedPokemon] = field(default_factory=dict)  # species -> info


def reconstruct_from_log(log: str) -> tuple[ReconstructedTeam, ReconstructedTeam] | None:
    """Parse a full battle log and extract all revealed team info.

    Returns (p1_team, p2_team) or None if the log is invalid.
    """
    p1 = ReconstructedTeam()
    p2 = ReconstructedTeam()
    teams = {"p1": p1, "p2": p2}

    # Nickname -> species mapping
    nick_to_species: dict[str, str] = {}  # "p1: Nickname" -> species
    # Active slot -> nickname key
    active_slots: dict[str, str] = {}  # "p1a" -> "p1: Nickname"

    has_preview = False

    for line in log.strip().split("\n"):
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        cmd = parts[1]

        # Team preview
        if cmd == "poke" and len(parts) >= 4:
            player = parts[2]
            species = parts[3].split(",")[0].strip()
            team = teams[player]
            if species not in team.pokemon:
                team.pokemon[species] = ReconstructedPokemon(species=species)
            has_preview = True

        # Switch — reveals species, marks as brought + switched in
        elif cmd in ("switch", "drag") and len(parts) >= 5:
            slot_info = parts[2]
            species = parts[3].split(",")[0].strip()
            slot = slot_info[:3]  # "p1a"
            player = slot[:2]
            nickname = slot_info.split(": ", 1)[1] if ": " in slot_info else slot_info[5:]
            key = f"{player}: {nickname}"

            nick_to_species[key] = species
            active_slots[slot] = key

            team = teams[player]
            # Handle mega forms — map back to base species for the team entry
            base = species.split("-Mega")[0] if "-Mega" in species else species
            if base not in team.pokemon:
                team.pokemon[base] = ReconstructedPokemon(species=base)
            poke = team.pokemon[base]
            poke.brought = True
            poke.switched_in = True
            # Update species if mega
            if "-Mega" in species:
                poke.mega = True

        # Move — reveals a move for the active Pokemon
        elif cmd == "move" and len(parts) >= 4:
            slot_info = parts[2]
            move_name = parts[3]
            slot = slot_info[:3]
            player = slot[:2]
            rest = "|".join(parts[4:])

            # Skip forced/copied moves
            if "[from]" in rest:
                continue

            key = active_slots.get(slot)
            if not key:
                continue
            species = nick_to_species.get(key, "")
            base = species.split("-Mega")[0] if "-Mega" in species else species

            team = teams[player]
            if base in team.pokemon:
                poke = team.pokemon[base]
                if move_name not in poke.moves:
                    poke.moves.append(move_name)

        # Ability revealed
        elif cmd == "-ability" and len(parts) >= 4:
            slot_info = parts[2]
            ability = parts[3]
            slot = slot_info[:3]
            player = slot[:2]

            key = active_slots.get(slot)
            if not key:
                continue
            species = nick_to_species.get(key, "")
            base = species.split("-Mega")[0] if "-Mega" in species else species

            team = teams[player]
            if base in team.pokemon:
                team.pokemon[base].ability = ability

        # Item revealed (consumed)
        elif cmd == "-enditem" and len(parts) >= 4:
            slot_info = parts[2]
            item = parts[3]
            slot = slot_info[:3]
            player = slot[:2]

            key = active_slots.get(slot)
            if not key:
                continue
            species = nick_to_species.get(key, "")
            base = species.split("-Mega")[0] if "-Mega" in species else species

            team = teams[player]
            if base in team.pokemon:
                team.pokemon[base].item = item

        # Item revealed (shown/gained)
        elif cmd == "-item" and len(parts) >= 4:
            slot_info = parts[2]
            item = parts[3]
            slot = slot_info[:3]
            player = slot[:2]

            key = active_slots.get(slot)
            if not key:
                continue
            species = nick_to_species.get(key, "")
            base = species.split("-Mega")[0] if "-Mega" in species else species

            team = teams[player]
            if base in team.pokemon:
                team.pokemon[base].item = item

        # Mega evolution
        elif cmd == "-mega" and len(parts) >= 4:
            slot_info = parts[2]
            slot = slot_info[:3]
            player = slot[:2]

            key = active_slots.get(slot)
            if not key:
                continue
            species = nick_to_species.get(key, "")
            base = species.split("-Mega")[0] if "-Mega" in species else species

            team = teams[player]
            if base in team.pokemon:
                team.pokemon[base].mega = True
                # Mega stone = item
                if len(parts) >= 5 and parts[4]:
                    team.pokemon[base].item = parts[4]

        # Details change (mega evolution form)
        elif cmd == "detailschange" and len(parts) >= 4:
            slot_info = parts[2]
            new_species = parts[3].split(",")[0].strip()
            slot = slot_info[:3]
            player = slot[:2]

            key = active_slots.get(slot)
            if key:
                nick_to_species[key] = new_species

    if not has_preview:
        return None

    # Mark brought Pokemon that were selected but never switched in
    # (they appear in preview but not in switch commands — we only know species)

    return p1, p2


def analyze_replay(replay_path: Path) -> dict | None:
    """Analyze one replay file and return coverage stats."""
    try:
        data = json.loads(replay_path.read_text(errors="replace"))
        log = data.get("log", "")
        rating = data.get("rating", 0)
    except Exception:
        return None

    result = reconstruct_from_log(log)
    if result is None:
        return None

    p1_team, p2_team = result

    stats = {"rating": rating, "id": data.get("id", replay_path.stem)}

    for label, team in [("p1", p1_team), ("p2", p2_team)]:
        total_pokemon = len(team.pokemon)
        brought = sum(1 for p in team.pokemon.values() if p.brought)
        switched_in = sum(1 for p in team.pokemon.values() if p.switched_in)
        moves_known = sum(len(p.moves) for p in team.pokemon.values())
        max_moves = brought * 4  # each brought Pokemon has 4 moves
        items_known = sum(1 for p in team.pokemon.values() if p.item and p.brought)
        abilities_known = sum(1 for p in team.pokemon.values() if p.ability and p.brought)

        stats[label] = {
            "total": total_pokemon,
            "brought": brought,
            "switched_in": switched_in,
            "moves_found": moves_known,
            "moves_max": max_moves,
            "moves_pct": round(moves_known / max_moves * 100, 1) if max_moves > 0 else 0,
            "items_found": items_known,
            "items_pct": round(items_known / brought * 100, 1) if brought > 0 else 0,
            "abilities_found": abilities_known,
            "abilities_pct": round(abilities_known / brought * 100, 1) if brought > 0 else 0,
        }

    return stats


def team_to_dict(team: ReconstructedTeam) -> list[dict]:
    """Serialize a ReconstructedTeam for JSON output."""
    return [
        {
            "species": p.species,
            "moves": p.moves,
            "item": p.item,
            "ability": p.ability,
            "mega": p.mega,
            "brought": p.brought,
            "switched_in": p.switched_in,
        }
        for p in team.pokemon.values()
    ]


def main():
    parser = argparse.ArgumentParser(description="Reconstruct team data from battle logs")
    parser.add_argument("--dir", type=str, default=None,
                        help="Directory of replay JSONs (default: auto-detect)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max replays to process (0 = all)")
    parser.add_argument("--enrich", action="store_true",
                        help="Write reconstructed teams back into replay JSONs")
    parser.add_argument("--min-rating", type=int, default=0)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    replay_base = project_root / "data" / "showdown_replays"
    fmt = "gen9championsvgc2026regma"

    # Find replay directories
    search_dirs = [
        replay_base / fmt,
        replay_base / "spectated" / fmt,
        replay_base / "downloaded" / fmt,
    ]
    if args.dir:
        search_dirs = [Path(args.dir)]

    replay_files = []
    for d in search_dirs:
        if d.exists():
            replay_files.extend(f for f in d.glob("*.json") if f.name != "index.json")

    if not replay_files:
        print("No replay files found.")
        return

    print(f"Found {len(replay_files)} replay files")

    if args.limit > 0:
        replay_files = replay_files[:args.limit]
        print(f"Processing first {args.limit}")

    # Aggregate stats
    total = 0
    errors = 0
    skipped_rating = 0

    # Per-player coverage aggregates (treating each player as a "own team" simulation)
    agg_moves_found = 0
    agg_moves_max = 0
    agg_items_found = 0
    agg_items_max = 0
    agg_abilities_found = 0
    agg_abilities_max = 0
    agg_switched_in = 0
    agg_brought = 0

    # Move count distribution: how many of 4 moves do we find per brought Pokemon?
    moves_per_pokemon: Counter = Counter()  # {0: N, 1: N, 2: N, 3: N, 4: N}
    enriched = 0

    for i, f in enumerate(replay_files):
        if args.min_rating > 0:
            try:
                d = json.loads(f.read_text(errors="replace"))
                if (d.get("rating") or 0) < args.min_rating:
                    skipped_rating += 1
                    continue
            except Exception:
                errors += 1
                continue

        stats = analyze_replay(f)
        if stats is None:
            errors += 1
            continue

        total += 1

        # Aggregate both players (either could be "us")
        for label in ("p1", "p2"):
            s = stats[label]
            agg_moves_found += s["moves_found"]
            agg_moves_max += s["moves_max"]
            agg_items_found += s["items_found"]
            agg_items_max += s["brought"]
            agg_abilities_found += s["abilities_found"]
            agg_abilities_max += s["brought"]
            agg_switched_in += s["switched_in"]
            agg_brought += s["brought"]

        # Per-Pokemon move counts
        if args.enrich or True:  # always compute for stats
            try:
                data = json.loads(f.read_text(errors="replace"))
                result = reconstruct_from_log(data.get("log", ""))
                if result:
                    p1t, p2t = result
                    for team in (p1t, p2t):
                        for poke in team.pokemon.values():
                            if poke.brought:
                                moves_per_pokemon[len(poke.moves)] += 1

                    if args.enrich:
                        data["teams"] = {
                            "p1": team_to_dict(p1t),
                            "p2": team_to_dict(p2t),
                        }
                        f.write_text(json.dumps(data, indent=2))
                        enriched += 1
            except Exception:
                pass

        if (i + 1) % 5000 == 0:
            print(f"  {i+1}/{len(replay_files)} processed...")

    # Report
    print(f"\n{'='*60}")
    print(f"RECONSTRUCTION COVERAGE REPORT")
    print(f"{'='*60}")
    print(f"Replays processed: {total}  (errors: {errors}, skipped: {skipped_rating})")
    print()

    print(f"Per-player averages (each player = simulated 'own team'):")
    print(f"  Brought to battle: {agg_brought / (total*2):.1f} / 6 Pokemon")  # should be ~4
    print(f"  Switched in:       {agg_switched_in / (total*2):.1f} / {agg_brought / (total*2):.1f} brought")
    print()

    moves_pct = round(agg_moves_found / agg_moves_max * 100, 1) if agg_moves_max else 0
    items_pct = round(agg_items_found / agg_items_max * 100, 1) if agg_items_max else 0
    abilities_pct = round(agg_abilities_found / agg_abilities_max * 100, 1) if agg_abilities_max else 0

    print(f"  Moves:     {agg_moves_found:,} / {agg_moves_max:,}  ({moves_pct}%)")
    print(f"  Items:     {agg_items_found:,} / {agg_items_max:,}  ({items_pct}%)")
    print(f"  Abilities: {agg_abilities_found:,} / {agg_abilities_max:,}  ({abilities_pct}%)")
    print()

    total_brought = sum(moves_per_pokemon.values())
    print(f"Moves known per brought Pokemon:")
    for n in range(5):
        count = moves_per_pokemon.get(n, 0)
        pct = round(count / total_brought * 100, 1) if total_brought else 0
        bar = "█" * int(pct / 2)
        print(f"  {n} moves: {count:>7,}  ({pct:>5.1f}%)  {bar}")

    if args.enrich:
        print(f"\nEnriched {enriched} replay files with `teams` field.")


if __name__ == "__main__":
    main()
