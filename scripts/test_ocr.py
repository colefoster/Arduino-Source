#!/usr/bin/env python3
"""
Headless OCR test against reference frame screenshots.

Crops the same regions that the C++ readers use, runs Tesseract,
and fuzzy-matches against the move/species dictionaries.
This validates that:
  1. The crop coordinates are correct
  2. Tesseract can read the text
  3. Dictionary matching finds the right entry

Usage:
    python scripts/test_ocr.py [frame_path ...]

If no paths given, runs against all known test frames in ref_frames/1/.
"""

import json
import os
import sys
from pathlib import Path
from difflib import get_close_matches

try:
    import pytesseract
    from PIL import Image
except ImportError:
    print("ERROR: pip install pytesseract Pillow")
    sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
REF_FRAMES = REPO / "SerialPrograms/Source/PokemonChampions/ref_frames/1"

# Load dictionaries
def load_dict(path):
    with open(path) as f:
        data = json.load(f)
    eng = data.get("eng", {})
    # slug -> display name
    return {slug: names[0] for slug, names in eng.items()}

MOVES_DICT = load_dict(REPO / "Resources/PokemonChampions/PokemonMovesOCR.json")
SPECIES_DICT = load_dict(REPO / "Resources/PokemonChampions/PokemonSpeciesOCR.json")

# All display names for fuzzy matching
MOVE_NAMES = list(MOVES_DICT.values())
SPECIES_NAMES = list(SPECIES_DICT.values())

# Reverse lookup: display name -> slug
MOVE_NAME_TO_SLUG = {v: k for k, v in MOVES_DICT.items()}
SPECIES_NAME_TO_SLUG = {v: k for k, v in SPECIES_DICT.items()}


# ── Crop regions (normalized 0-1, matching C++ code) ──────────────
# Measured from ref_frames/1/frame_00080.jpg (1920x1080)

# Move name text boxes — shifted right to exclude type icon
MOVE_NAME_BOXES = [
    (0.7760, 0.5093, 0.1510, 0.0463),  # slot 0  (px: 1490,550 -> 1780,600)
    (0.7760, 0.6296, 0.1510, 0.0463),  # slot 1  (px: 1490,680 -> 1780,730)
    (0.7760, 0.7500, 0.1510, 0.0463),  # slot 2  (px: 1490,810 -> 1780,860)
    (0.7760, 0.8704, 0.1510, 0.0463),  # slot 3  (px: 1490,940 -> 1780,990)
]

# Opponent species name — pink/red badge top-right
OPPONENT_NAME_BOX = (0.8333, 0.0417, 0.1302, 0.0324)  # px: 1600,45 -> 1850,80

# Opponent HP % — below/right of name badge
OPPONENT_HP_BOX = (0.9635, 0.0574, 0.0339, 0.0306)  # px: 1850,62 -> 1915,95

# Own HP current/max — bottom-left, below HP bar
OWN_HP_BOX = (0.1328, 0.9444, 0.0781, 0.0417)  # px: 255,1020 -> 405,1065

# PP boxes — right edge of each move pill
PP_BOXES = [
    (0.9271, 0.5000, 0.0573, 0.0509),  # slot 0  (px: 1780,540 -> 1890,595)
    (0.9271, 0.6204, 0.0573, 0.0509),  # slot 1
    (0.9271, 0.7407, 0.0573, 0.0509),  # slot 2
    (0.9271, 0.8611, 0.0573, 0.0509),  # slot 3
]

# Battle log text bar — bottom-center during animations
BATTLE_LOG_BOX = (0.1042, 0.7454, 0.7292, 0.0417)  # px: 200,805 -> 1600,850


def crop_box(img, box):
    """Crop an image using a normalized (x, y, w, h) box."""
    w, h = img.size
    x1 = int(box[0] * w)
    y1 = int(box[1] * h)
    x2 = int((box[0] + box[2]) * w)
    y2 = int((box[1] + box[3]) * h)
    return img.crop((x1, y1, x2, y2))


def ocr_text(crop, psm=7):
    """Run Tesseract on a PIL image crop. psm=7 = single line."""
    config = f"--psm {psm}"
    text = pytesseract.image_to_string(crop, config=config).strip()
    return text


def fuzzy_match(text, candidates, name_to_slug, n=3, cutoff=0.4):
    """Fuzzy match OCR text against a dictionary of display names."""
    if not text:
        return []
    matches = get_close_matches(text, candidates, n=n, cutoff=cutoff)
    return [(m, name_to_slug.get(m, "?")) for m in matches]


def test_move_select(img, label=""):
    """Test OCR on a move-select screen."""
    print(f"\n{'='*60}")
    print(f"  MOVE SELECT SCREEN  {label}")
    print(f"{'='*60}")

    # Move names
    print("\n  Move Names:")
    for i, box in enumerate(MOVE_NAME_BOXES):
        crop = crop_box(img, box)
        raw = ocr_text(crop)
        matches = fuzzy_match(raw, MOVE_NAMES, MOVE_NAME_TO_SLUG)
        match_str = matches[0] if matches else ("NO MATCH", "")
        status = "OK" if matches else "FAIL"
        print(f"    Slot {i}: raw={raw!r:25s}  -> {match_str[0]:20s} [{match_str[1]}]  {status}")

    # Opponent species
    print("\n  Opponent Species:")
    crop = crop_box(img, OPPONENT_NAME_BOX)
    raw = ocr_text(crop)
    matches = fuzzy_match(raw, SPECIES_NAMES, SPECIES_NAME_TO_SLUG)
    match_str = matches[0] if matches else ("NO MATCH", "")
    print(f"    raw={raw!r:25s}  -> {match_str[0]:20s} [{match_str[1]}]")

    # Opponent HP%
    print("\n  Opponent HP%:")
    crop = crop_box(img, OPPONENT_HP_BOX)
    raw = ocr_text(crop)
    print(f"    raw={raw!r}")

    # Own HP
    print("\n  Own HP:")
    crop = crop_box(img, OWN_HP_BOX)
    raw = ocr_text(crop)
    print(f"    raw={raw!r}")

    # PP counts
    print("\n  PP Counts:")
    for i, box in enumerate(PP_BOXES):
        crop = crop_box(img, box)
        raw = ocr_text(crop)
        print(f"    Slot {i}: raw={raw!r}")


def test_battle_log(img, label=""):
    """Test OCR on a battle animation frame's text bar."""
    print(f"\n{'='*60}")
    print(f"  BATTLE LOG  {label}")
    print(f"{'='*60}")

    crop = crop_box(img, BATTLE_LOG_BOX)
    raw = ocr_text(crop, psm=7)
    print(f"    raw={raw!r}")

    # Try to parse with the same regex patterns as BattleLogReader
    import re

    # Super effective (check first since OCR can mangle the rest)
    if "super" in raw.lower() and ("effective" in raw.lower() or "etrective" in raw.lower()):
        print(f"    PARSED: SUPER EFFECTIVE")
        return

    # Move used — lenient: allow trailing junk after move name
    m = re.search(r"(?:The opposing |the opposing )?(.+?) used (.+?)(?:!|$)", raw, re.IGNORECASE)
    if m:
        opp = "opposing" in raw.lower()
        print(f"    PARSED: {'OPP' if opp else 'OWN'} {m.group(1)} used {m.group(2)}")
        return

    # Stat change — lenient: allow "rose" variants even with OCR noise
    m = re.search(r"(?:The opposing |the opposing )?(.+?).s (.+?) (rose|fell)", raw, re.IGNORECASE)
    if m:
        opp = "opposing" in raw.lower()
        print(f"    PARSED: {'OPP' if opp else 'OWN'} {m.group(1)} {m.group(2)} {m.group(3)}")
        return

    # Switch in
    m = re.search(r"(.+?) sent out (.+?)!", raw, re.IGNORECASE)
    if m:
        print(f"    PARSED: SWITCH_IN {m.group(2)} (by {m.group(1)})")
        return

    # Fainted
    m = re.search(r"(.+?) fainted", raw, re.IGNORECASE)
    if m:
        print(f"    PARSED: FAINTED {m.group(1)}")
        return

    print(f"    PARSED: (no pattern matched)")


# ── Known test frames ─────────────────────────────────────────────

KNOWN_FRAMES = {
    "move_select": [
        ("frame_00078.jpg", "Victreebel vs Greninja - Sucker Punch selected"),
        ("frame_00080.jpg", "Victreebel vs Greninja - Sucker Punch selected (2)"),
        ("frame_00119.jpg", "Garchomp vs Volcarona - Rock Tomb selected"),
        ("frame_00120.jpg", "Garchomp vs Volcarona - Rock Tomb selected (2)"),
    ],
    "battle_log": [
        ("frame_00060.jpg", "Victreebelite reacting to Omni Ring"),
        ("frame_00070.jpg", "It's super effective!"),
        ("frame_00100.jpg", "The opposing Volcarona used Fiery Dance!"),
        ("frame_00115.jpg", "Volcarona's stats rose"),
    ],
}


def main():
    if len(sys.argv) > 1:
        # Test specific files
        for path in sys.argv[1:]:
            img = Image.open(path)
            # Guess type from image content - try both
            test_move_select(img, label=path)
            test_battle_log(img, label=path)
        return

    # Run known test frames
    print("Pokemon Champions OCR Test")
    print(f"Tesseract: {pytesseract.get_tesseract_version()}")
    print(f"Ref frames dir: {REF_FRAMES}")
    print(f"Moves dictionary: {len(MOVES_DICT)} entries")
    print(f"Species dictionary: {len(SPECIES_DICT)} entries")

    if not REF_FRAMES.exists():
        print(f"\nERROR: ref_frames not found at {REF_FRAMES}")
        print("Copy some frames there or pass image paths as arguments.")
        sys.exit(1)

    for fname, desc in KNOWN_FRAMES["move_select"]:
        path = REF_FRAMES / fname
        if path.exists():
            img = Image.open(path)
            test_move_select(img, label=f"{fname} ({desc})")

    for fname, desc in KNOWN_FRAMES["battle_log"]:
        path = REF_FRAMES / fname
        if path.exists():
            img = Image.open(path)
            test_battle_log(img, label=f"{fname} ({desc})")

    print(f"\n{'='*60}")
    print("  DONE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
