#!/usr/bin/env python3
"""
Migrate test images from old CommandLineTests/PokemonChampions/ structure
to the new test_images/ screen-based structure with manifest.json files.

Old structure: CommandLineTests/PokemonChampions/<DetectorName>/<filename_with_label>.png
New structure: test_images/<screen_name>/manifest.json + <timestamp>.png

Usage:
    python3 tools/migrate_test_images.py [--dry-run]
"""

import os
import sys
import json
import hashlib
import shutil
import argparse
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OLD_ROOT = PROJECT_ROOT / "CommandLineTests" / "PokemonChampions"
NEW_ROOT = PROJECT_ROOT / "test_images"

# ── Mapping from old detector directories to new screen directories ──

# Bool detectors: directory name -> new screen name
# Images labeled _True go to the screen; _False are negatives (handled implicitly).
BOOL_DETECTOR_TO_SCREEN = {
    "ActionMenuDetector": "action_menu_singles",
    "MoveSelectDetector": "move_select_singles",
    "MainMenuDetector": "main_menu",
    "TeamPreviewDetector": "team_preview_selecting",
    "PostMatchScreenDetector": "post_match",
    "TeamSelectDetector": "team_select",
    "MovesMoreDetector": "moves_and_more",
    "PreparingForBattleDetector": "team_preview_locked_in",
    "ResultScreenDetector": "result_screen",
}

# Reader directories: these images already exist in bool detector dirs (shared hashes).
# We map them to screens to attach reader labels.
READER_TO_SCREEN = {
    "MoveNameReader": "move_select_singles",
    "MoveSelectCursorSlot": "move_select_singles",
    "SpeciesReader": "move_select_singles",         # singles opponent species
    "SpeciesReader_Doubles": "move_select_doubles",  # doubles opponent species
    "OpponentHPReader": "move_select_singles",
    "OpponentHPReader_Doubles": "move_select_doubles",
    "BattleLogReader": "_overlays/battle_log",
    "TeamSelectReader": "team_select",
    "TeamSummaryReader": "moves_and_more",
}

# Conflict resolution: when an image is True for multiple detectors,
# pick the most specific screen. Priority (first match wins).
CONFLICT_PRIORITY = [
    "PreparingForBattleDetector",  # team_preview_locked_in (most specific)
    "MoveSelectDetector",          # move_select_singles
    "ActionMenuDetector",          # action_menu_singles
    "PostMatchScreenDetector",     # post_match
    "TeamSelectDetector",          # team_select
    "TeamPreviewDetector",         # team_preview_selecting
    "ResultScreenDetector",        # result_screen
    "MainMenuDetector",            # main_menu
    "MovesMoreDetector",           # moves_and_more
]

# Images that are False for all detectors — classify by filename patterns
UNCLASSIFIED_PATTERNS = {
    "battle_log": ["battle_log_", "dialog_", "battle_dialog_"],
    "battle_animation": ["battle_animation_", "mid_animation_"],
    "doubles": ["doubles_"],
}


def md5_file(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def parse_bool_label(filename):
    """Extract True/False from filename like '20260423-145950387380_False.png'."""
    stem = Path(filename).stem
    if stem.endswith("_True"):
        return True
    elif stem.endswith("_False"):
        return False
    return None


def parse_reader_label(reader_name, filename):
    """Parse reader-specific labels from filename. Returns dict of fields or None."""
    stem = Path(filename).stem
    parts = stem.split("_")

    if reader_name == "MoveNameReader":
        # <prefix>_<move0>_<move1>_<move2>_<move3>.png
        if len(parts) < 4:
            return None
        moves = parts[-4:]
        return {"moves": [None if m == "NONE" else m for m in moves]}

    elif reader_name == "MoveSelectCursorSlot":
        # <prefix>_<slot>.png
        try:
            slot = int(parts[-1])
            return {"slot": slot}
        except ValueError:
            return None

    elif reader_name == "SpeciesReader":
        # <prefix>_<species>.png (may start with _)
        if not parts:
            return None
        species = parts[-1]
        return {"opponent_species": species}

    elif reader_name == "SpeciesReader_Doubles":
        # <prefix>_s<slot>_<species>.png
        if len(parts) < 2:
            return None
        slot_str = parts[-2]
        species = parts[-1]
        slot = 0 if slot_str == "s0" else 1 if slot_str == "s1" else -1
        if slot < 0:
            return None
        return {"slot": slot, "opponent_species": species}

    elif reader_name == "OpponentHPReader":
        # <prefix>_<hp>.png
        try:
            hp = int(parts[-1])
            return {"opponent_hp_pct": hp}
        except ValueError:
            return None

    elif reader_name == "OpponentHPReader_Doubles":
        # <prefix>_s<slot>_<hp>.png
        if len(parts) < 2:
            return None
        slot_str = parts[-2]
        hp_str = parts[-1]
        slot = 0 if slot_str == "s0" else 1 if slot_str == "s1" else -1
        if slot < 0:
            return None
        try:
            hp = int(hp_str)
        except ValueError:
            return None
        return {"slot": slot, "opponent_hp_pct": hp}

    elif reader_name == "BattleLogReader":
        # <prefix>_<EVENT_TYPE>.png — uppercase words joined with _
        upper_parts = []
        for p in parts:
            if p and p[0].isupper():
                upper_parts.append(p)
            elif upper_parts:
                upper_parts.append(p)
        event_type = "_".join(upper_parts) if upper_parts else parts[-1]
        return {"event_type": event_type}

    elif reader_name == "TeamSelectReader":
        # <prefix>_<sp0>_<sp1>_..._<sp5>.png
        if len(parts) < 6:
            return None
        species = parts[-6:]
        return {"species": [None if s == "NONE" else s for s in species]}

    elif reader_name == "TeamSummaryReader":
        # <prefix>_<sp0>_<sp1>_..._<sp5>.png
        if len(parts) < 6:
            return None
        species = parts[-6:]
        return {"species": [None if s == "NONE" else s for s in species]}

    return None


def classify_unclassified(filename):
    """For images that are False for all detectors, try to classify by name."""
    lower = filename.lower()
    if any(lower.startswith(p) or f"_{p}" in lower for p in UNCLASSIFIED_PATTERNS["battle_log"]):
        return "_overlays/battle_log"
    if any(lower.startswith(p) for p in UNCLASSIFIED_PATTERNS["doubles"]):
        if "action_menu" in lower:
            return "action_menu_doubles"
        if "move_select" in lower:
            return "move_select_doubles"
        return "action_menu_doubles"  # default doubles
    # battle animation, screenshots with no clear screen — put in inbox
    return "_inbox"


def run_migration(dry_run=False):
    if not OLD_ROOT.exists():
        print(f"Error: {OLD_ROOT} does not exist")
        sys.exit(1)

    # ── Step 1: Hash all images, build maps ──

    print("Scanning existing test images...")

    # hash -> {detector: label} for bool detectors
    hash_true_detectors = defaultdict(set)
    hash_false_detectors = defaultdict(set)
    # hash -> first (dir, filename, full_path)
    hash_to_source = {}
    # hash -> {reader: parsed_label} for reader dirs
    hash_reader_labels = defaultdict(dict)

    # Scan bool detector directories
    for det_name, screen_name in BOOL_DETECTOR_TO_SCREEN.items():
        det_dir = OLD_ROOT / det_name
        if not det_dir.exists():
            continue
        for fname in sorted(det_dir.iterdir()):
            if not fname.suffix.lower() == ".png":
                continue
            h = md5_file(fname)
            if h not in hash_to_source:
                hash_to_source[h] = (det_name, fname.name, fname)

            label = parse_bool_label(fname.name)
            if label is True:
                hash_true_detectors[h].add(det_name)
            elif label is False:
                hash_false_detectors[h].add(det_name)

    # Scan reader directories
    for reader_name, screen_name in READER_TO_SCREEN.items():
        reader_dir = OLD_ROOT / reader_name
        if not reader_dir.exists():
            continue
        for fname in sorted(reader_dir.iterdir()):
            if not fname.suffix.lower() == ".png":
                continue
            h = md5_file(fname)
            if h not in hash_to_source:
                hash_to_source[h] = (reader_name, fname.name, fname)

            parsed = parse_reader_label(reader_name, fname.name)
            if parsed is not None:
                hash_reader_labels[h][reader_name] = parsed

    # OCRDump images — put in inbox (dev/debug, no labels)
    ocr_dump_dir = OLD_ROOT / "OCRDump"
    if ocr_dump_dir.exists():
        for fname in sorted(ocr_dump_dir.iterdir()):
            if not fname.suffix.lower() == ".png":
                continue
            h = md5_file(fname)
            if h not in hash_to_source:
                hash_to_source[h] = ("OCRDump", fname.name, fname)

    total_unique = len(hash_to_source)
    print(f"Found {total_unique} unique images")

    # ── Step 2: Determine screen assignment for each unique image ──

    # hash -> screen_name
    assignments = {}

    for h in hash_to_source:
        true_dets = hash_true_detectors.get(h, set())

        if len(true_dets) == 0:
            # No detector says True — classify by filename or put in inbox
            _, fname, _ = hash_to_source[h]
            assignments[h] = classify_unclassified(fname)

        elif len(true_dets) == 1:
            det = next(iter(true_dets))
            assignments[h] = BOOL_DETECTOR_TO_SCREEN[det]

        else:
            # Multiple True detectors — resolve conflict by priority
            for det in CONFLICT_PRIORITY:
                if det in true_dets:
                    assignments[h] = BOOL_DETECTOR_TO_SCREEN[det]
                    break
            else:
                # Shouldn't happen, but fall back
                det = sorted(true_dets)[0]
                assignments[h] = BOOL_DETECTOR_TO_SCREEN[det]

    # Override: images from reader-only dirs that have no bool detector match
    # and are in a doubles reader dir → assign to doubles screen
    for h, readers in hash_reader_labels.items():
        if "SpeciesReader_Doubles" in readers or "OpponentHPReader_Doubles" in readers:
            # If currently assigned to a singles screen, override to doubles
            current = assignments.get(h, "")
            if current in ("move_select_singles", "action_menu_singles"):
                assignments[h] = "move_select_doubles"

    # ── Step 3: Print summary ──

    screen_counts = defaultdict(int)
    for h, screen in assignments.items():
        screen_counts[screen] += 1

    print("\nScreen assignments:")
    for screen in sorted(screen_counts.keys()):
        print(f"  {screen}: {screen_counts[screen]} images")

    # ── Step 4: Create directories and copy images ──

    # Collect per-screen: list of (hash, new_filename, reader_labels)
    screen_images = defaultdict(list)

    for h, screen in assignments.items():
        _, orig_fname, orig_path = hash_to_source[h]
        # Strip old label suffixes to get a clean timestamp name
        stem = Path(orig_fname).stem
        # Remove _True/_False suffix
        for suffix in ("_True", "_False"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        # If it starts with _, strip that too (hidden file prefix)
        if stem.startswith("_"):
            stem = stem[1:]

        new_fname = f"{stem}.png"
        reader_labels = hash_reader_labels.get(h, {})
        screen_images[screen].append((h, new_fname, orig_path, reader_labels))

    if dry_run:
        print("\n[DRY RUN] Would create:")
        for screen, images in sorted(screen_images.items()):
            screen_dir = NEW_ROOT / screen
            print(f"\n  {screen_dir}/  ({len(images)} images)")
            for _, fname, _, labels in images[:3]:
                label_str = f" labels={list(labels.keys())}" if labels else ""
                print(f"    {fname}{label_str}")
            if len(images) > 3:
                print(f"    ... and {len(images) - 3} more")
        return

    # Create directories and copy
    for screen, images in sorted(screen_images.items()):
        screen_dir = NEW_ROOT / screen
        screen_dir.mkdir(parents=True, exist_ok=True)

        manifest = {}
        dupes = set()

        for h, new_fname, orig_path, reader_labels in images:
            # Handle duplicate filenames within same screen
            if new_fname in dupes:
                base, ext = os.path.splitext(new_fname)
                new_fname = f"{base}_{h[:6]}{ext}"
            dupes.add(new_fname)

            dest = screen_dir / new_fname
            shutil.copy2(orig_path, dest)

            # Build manifest entry (only reader labels, not detector bools)
            if reader_labels:
                entry = {}
                for reader_name, fields in reader_labels.items():
                    entry[reader_name] = fields
                manifest[new_fname] = entry

        # Write manifest.json
        manifest_path = screen_dir / "manifest.json"
        if manifest_path.exists():
            # Merge with existing
            existing = json.loads(manifest_path.read_text())
            existing.update(manifest)
            manifest = existing

        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"  Created {screen}: {len(images)} images, {len(manifest)} labeled")

    # Also create empty manifests for screens with no images yet
    all_screens = [
        "team_select", "searching_for_battle", "team_preview_selecting",
        "team_preview_locked_in", "action_menu_singles", "action_menu_doubles",
        "move_select_singles", "move_select_doubles", "pokemon_switch_singles",
        "pokemon_switch_doubles", "communicating", "result_screen", "post_match",
        "main_menu", "moves_and_more", "_overlays/battle_log",
    ]
    for screen in all_screens:
        screen_dir = NEW_ROOT / screen
        screen_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = screen_dir / "manifest.json"
        if not manifest_path.exists():
            manifest_path.write_text("{}\n")
            print(f"  Created {screen}: empty (no images yet)")

    print(f"\nMigration complete. {total_unique} unique images placed.")
    print(f"Old directory: {OLD_ROOT}")
    print(f"New directory: {NEW_ROOT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate test images to new structure")
    parser.add_argument("--dry-run", action="store_true", help="Preview without copying")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)
