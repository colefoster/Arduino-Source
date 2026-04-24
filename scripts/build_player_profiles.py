#!/usr/bin/env python3
"""Build per-player team profiles from replay JSONs.

Scans all VGC replay JSONs, groups by player name, and accumulates
per-species move/item/ability counts with timestamps. Output is used
by the model's enrichment pipeline to backfill own-team unknowns.

Usage:
    python scripts/build_player_profiles.py
    python scripts/build_player_profiles.py --dir /path/to/replays
    python scripts/build_player_profiles.py --format gen9championsvgc2026regma
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Reuse the log parser from reconstruct_teams
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.reconstruct_teams import reconstruct_from_log


DEFAULT_FORMAT = "gen9championsvgc2026regma"
MAX_SINGLE_FILE_MB = 200


def build_profiles(replay_files: list[Path], verbose: bool = False) -> dict:
    """Scan replays and build per-player profiles.

    Returns:
        {player_name: {"games": int, "pokemon": {species: {...}}}}
    """
    profiles: dict[str, dict] = {}
    processed = 0
    errors = 0

    for i, f in enumerate(replay_files):
        try:
            data = json.loads(f.read_text(errors="replace"))
        except Exception:
            errors += 1
            continue

        log = data.get("log", "")
        players = data.get("players", [])
        upload_time = data.get("uploadtime", 0)

        if len(players) != 2 or not log:
            errors += 1
            continue

        result = reconstruct_from_log(log)
        if result is None:
            errors += 1
            continue

        p1_team, p2_team = result

        for player_name, team in zip(players, [p1_team, p2_team]):
            # Normalize player name to lowercase for consistent matching
            name_key = player_name.lower().strip()
            if not name_key:
                continue

            if name_key not in profiles:
                profiles[name_key] = {
                    "games": 0,
                    "display_name": player_name,
                    "pokemon": {},
                }

            profile = profiles[name_key]
            profile["games"] += 1
            # Keep the most recent display name
            if upload_time > 0:
                profile["display_name"] = player_name

            for species, poke in team.pokemon.items():
                if species not in profile["pokemon"]:
                    profile["pokemon"][species] = {
                        "games_used": 0,
                        "moves": {},
                        "items": {},
                        "abilities": {},
                        "last_seen": 0,
                    }
                sp = profile["pokemon"][species]
                sp["games_used"] += 1
                if upload_time > sp["last_seen"]:
                    sp["last_seen"] = upload_time

                for move in poke.moves:
                    sp["moves"][move] = sp["moves"].get(move, 0) + 1

                if poke.item:
                    sp["items"][poke.item] = sp["items"].get(poke.item, 0) + 1

                if poke.ability:
                    sp["abilities"][poke.ability] = sp["abilities"].get(poke.ability, 0) + 1

        processed += 1
        if verbose and (i + 1) % 5000 == 0:
            print(f"  {i+1}/{len(replay_files)} processed...")

    return profiles


def write_profiles(profiles: dict, output_dir: Path, format_name: str):
    """Write profiles to JSON, sharding by first letter if too large.

    If total size exceeds MAX_SINGLE_FILE_MB, splits into per-letter files
    with an index.json pointing to them.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try single file first — estimate size
    full_json = json.dumps(profiles, separators=(",", ":"))
    size_mb = len(full_json.encode()) / (1024 * 1024)

    if size_mb <= MAX_SINGLE_FILE_MB:
        out_path = output_dir / f"{format_name}.json"
        out_path.write_text(json.dumps(profiles, indent=1))
        print(f"Wrote {len(profiles)} player profiles to {out_path} ({size_mb:.1f} MB)")
        return

    # Shard by first letter
    print(f"Total size {size_mb:.1f} MB exceeds {MAX_SINGLE_FILE_MB} MB — sharding by letter")
    shards: dict[str, dict] = defaultdict(dict)
    for name, profile in profiles.items():
        letter = name[0] if name else "_"
        if not letter.isalpha():
            letter = "_"
        shards[letter][name] = profile

    index = {}
    for letter, shard_profiles in sorted(shards.items()):
        shard_file = f"{format_name}_{letter}.json"
        shard_path = output_dir / shard_file
        shard_path.write_text(json.dumps(shard_profiles, indent=1))
        index[letter] = {
            "file": shard_file,
            "players": len(shard_profiles),
        }
        shard_size = shard_path.stat().st_size / (1024 * 1024)
        print(f"  {letter}: {len(shard_profiles)} players ({shard_size:.1f} MB)")

    index_path = output_dir / f"{format_name}_index.json"
    index_path.write_text(json.dumps(index, indent=2))
    print(f"Wrote index to {index_path}")


def main():
    parser = argparse.ArgumentParser(description="Build per-player team profiles from replays")
    parser.add_argument("--dir", type=str, default=None, help="Replay directory (overrides auto-detect)")
    parser.add_argument("--format", type=str, default=DEFAULT_FORMAT, help="Format name")
    parser.add_argument("--limit", type=int, default=0, help="Max replays (0 = all)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    replay_base = project_root / "data" / "showdown_replays"

    # Find replay directories
    search_dirs = [
        replay_base / args.format,
        replay_base / "spectated" / args.format,
        replay_base / "downloaded" / args.format,
    ]
    if args.dir:
        search_dirs = [Path(args.dir)]

    replay_files = []
    for d in search_dirs:
        if d.exists():
            replay_files.extend(f for f in d.glob("*.json") if f.name != "index.json")

    if not replay_files:
        print(f"No replay files found in: {[str(d) for d in search_dirs]}")
        print("Run this on a machine with replay data (e.g. ColePC or ash).")
        sys.exit(1)

    print(f"Found {len(replay_files)} replay files")
    if args.limit > 0:
        replay_files = replay_files[:args.limit]
        print(f"Processing first {args.limit}")

    profiles = build_profiles(replay_files, verbose=args.verbose)

    # Stats
    total_players = len(profiles)
    games_list = [p["games"] for p in profiles.values()]
    single_game = sum(1 for g in games_list if g == 1)
    multi_game = total_players - single_game
    max_games = max(games_list) if games_list else 0

    print(f"\n{'='*60}")
    print(f"PLAYER PROFILE STATS")
    print(f"{'='*60}")
    print(f"Total players: {total_players:,}")
    print(f"  Single-game: {single_game:,} ({single_game/total_players*100:.1f}%)")
    print(f"  Multi-game:  {multi_game:,} ({multi_game/total_players*100:.1f}%)")
    print(f"  Max games:   {max_games}")

    # Species coverage for multi-game players
    if multi_game > 0:
        total_species = 0
        total_moves = 0
        full_movesets = 0
        total_pokemon = 0
        for p in profiles.values():
            if p["games"] < 2:
                continue
            for sp_data in p["pokemon"].values():
                total_pokemon += 1
                total_species += 1
                n_moves = len(sp_data["moves"])
                total_moves += n_moves
                if n_moves >= 4:
                    full_movesets += 1

        avg_moves = total_moves / total_pokemon if total_pokemon else 0
        full_pct = full_movesets / total_pokemon * 100 if total_pokemon else 0
        print(f"\nMulti-game player coverage:")
        print(f"  Avg moves per species: {avg_moves:.2f}")
        print(f"  Full movesets (4+):    {full_movesets:,}/{total_pokemon:,} ({full_pct:.1f}%)")

    output_dir = project_root / "data" / "player_profiles"
    write_profiles(profiles, output_dir, args.format)


if __name__ == "__main__":
    main()
