#!/usr/bin/env python3
"""Scan all replays to build vocabulary files (species, moves, items, abilities, etc.)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vgc_model.data.vocab import Vocabs
from vgc_model.data.log_parser import parse_battle

REPLAY_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
VOCAB_DIR = Path(__file__).resolve().parent.parent / "data" / "vocab"


def main():
    vocabs = Vocabs()

    # Pre-populate weather/terrain/status with known values
    for w in ["SunnyDay", "RainDance", "Sandstorm", "Snow"]:
        vocabs.weather.add(w)
    for t in ["Electric", "Grassy", "Psychic", "Misty"]:
        vocabs.terrain.add(t)
    for s in ["brn", "par", "slp", "frz", "psn", "tox"]:
        vocabs.status.add(s)

    # Scan replay directories
    formats = ["gen9championsvgc2026regma", "gen9championsbssregma"]
    total = 0
    parsed = 0

    for fmt in formats:
        fmt_dir = REPLAY_DIR / fmt
        if not fmt_dir.exists():
            continue

        files = list(fmt_dir.glob("*.json"))
        print(f"{fmt}: {len(files)} files")

        for f in files:
            total += 1
            try:
                data = json.loads(f.read_text())
                log = data.get("log", "")
                rating = data.get("rating", 0)
                result = parse_battle(log, rating)
            except Exception as e:
                continue

            if result is None:
                continue
            parsed += 1

            # Collect species from team preview
            for species in result.team_preview.p1_team + result.team_preview.p2_team:
                vocabs.species.add(species)

            # Collect from samples
            for sample in result.samples:
                for poke_list in (sample.state.p1_active, sample.state.p1_bench,
                                  sample.state.p2_active, sample.state.p2_bench):
                    for poke in poke_list:
                        vocabs.species.add(poke.species)
                        if poke.item:
                            vocabs.items.add(poke.item)
                        if poke.ability:
                            vocabs.abilities.add(poke.ability)
                        for move in poke.moves_known:
                            vocabs.moves.add(move)

                # Collect moves from actions
                if sample.actions.slot_a and sample.actions.slot_a.type == "move":
                    vocabs.moves.add(sample.actions.slot_a.move)
                if sample.actions.slot_b and sample.actions.slot_b.type == "move":
                    vocabs.moves.add(sample.actions.slot_b.move)

            if total % 1000 == 0:
                print(f"  Processed {total} files ({parsed} parsed)...", flush=True)

    # Save
    vocabs.freeze_all()
    vocabs.save(VOCAB_DIR)

    print(f"\nDone! Processed {total} files, parsed {parsed} battles.")
    print(f"Vocabularies saved to {VOCAB_DIR}/")
    print(f"  Species: {len(vocabs.species)}")
    print(f"  Moves: {len(vocabs.moves)}")
    print(f"  Items: {len(vocabs.items)}")
    print(f"  Abilities: {len(vocabs.abilities)}")
    print(f"  Weather: {len(vocabs.weather)}")
    print(f"  Terrain: {len(vocabs.terrain)}")
    print(f"  Status: {len(vocabs.status)}")


if __name__ == "__main__":
    main()
