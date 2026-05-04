#!/usr/bin/env python3
"""
Mark labeled own-side mons as shiny across all test_images/ manifests.

Background: the user's competitive team is fully shiny. The BattleHUD pill
icon and TeamPreview own-side icons render as shiny variants in-game, so
sprite-match ground truth needs to know whether each labeled species
should be matched against the normal or shiny atlas.

Strategy: ground-truth species labels stay as plain slugs (text OCR truth).
Add a parallel boolean array `own_species_shiny` per reader entry, true
where the labeled species is in the user's shiny list.

  BattleHUDReader.own_species: ["incineroar", "charizard"]
  BattleHUDReader.own_species_shiny: [true, true]

  TeamPreviewReader.own_species: ["charizard", "sneasler", ..., "venusaur"]
  TeamPreviewReader.own_species_shiny: [true, true, false, false, ..., true]

Usage:
  python3 tools/mark_shiny_species.py charizard venusaur garchomp sneasler \\
      incineroar meganium delphox basculegion archaludon
  python3 tools/mark_shiny_species.py --dry-run <slug...>
"""

import json
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
TEST_IMAGES = REPO_ROOT / "test_images"

#  Readers we care about: own-side species labels that should be matched
#  against shiny atlas when the species is in the shiny set.
TARGETS = [
    ("BattleHUDReader",   "own_species", "own_species_shiny"),
    ("TeamPreviewReader", "own_species", "own_species_shiny"),
]


def update_manifest(path: Path, shiny_set: set[str], dry_run: bool) -> tuple[int, int]:
    """Returns (entries_inspected, entries_modified)."""
    try:
        manifest = json.loads(path.read_text())
    except Exception as e:
        print(f"  SKIP {path}: {e}")
        return 0, 0

    inspected = modified = 0
    for fname, labels in manifest.items():
        for reader, sp_key, shiny_key in TARGETS:
            entry = labels.get(reader)
            if not isinstance(entry, dict):
                continue
            species = entry.get(sp_key)
            if not isinstance(species, list) or not species:
                continue
            inspected += 1
            new_shiny = [bool(s) and s in shiny_set for s in species]
            old_shiny = entry.get(shiny_key)
            if old_shiny == new_shiny:
                continue
            entry[shiny_key] = new_shiny
            modified += 1

    if modified and not dry_run:
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return inspected, modified


def main():
    args = sys.argv[1:]
    dry_run = False
    if "--dry-run" in args:
        dry_run = True
        args.remove("--dry-run")
    if not args:
        print(__doc__.strip())
        sys.exit(1)

    shiny_set = {s.strip().lower() for s in args}
    print(f"Shiny species ({len(shiny_set)}): {sorted(shiny_set)}")
    print(f"Mode: {'DRY RUN' if dry_run else 'WRITE'}\n")

    total_inspected = total_modified = 0
    for manifest_path in sorted(TEST_IMAGES.glob("*/manifest.json")):
        rel = manifest_path.relative_to(REPO_ROOT)
        ins, mod = update_manifest(manifest_path, shiny_set, dry_run)
        total_inspected += ins
        total_modified += mod
        if ins or mod:
            mark = "*" if mod else " "
            print(f"  {mark} {rel}  inspected={ins} modified={mod}")

    print()
    print(f"Total entries inspected: {total_inspected}")
    print(f"Total entries modified:  {total_modified}")
    if dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
