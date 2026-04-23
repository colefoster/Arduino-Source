#!/usr/bin/env python3
"""
Extract labeled Pokemon sprites from a Moves & More screenshot.

The Moves & More tab shows 6 Pokemon in a 2x3 grid. Each card has a
sprite at a known position within the card. Given a screenshot and the
6 species slugs (in grid order), this script crops each sprite and
saves it to data/sprite_cache/<slug>.png.

Grid order is:
    slot 0 = top-left     slot 1 = top-right
    slot 2 = mid-left     slot 3 = mid-right
    slot 4 = bot-left     slot 5 = bot-right

Coordinates are loaded from tools/box_definitions.json (moves_more/sprite_0)
combined with the already-known col/row offsets measured for species_*.

Usage:
  python3 tools/extract_movesmore_sprites.py <screenshot.png> \\
      <slot0> <slot1> <slot2> <slot3> <slot4> <slot5>

Example:
  python3 tools/extract_movesmore_sprites.py \\
      screenshots/screenshot-20260422-160514341816.png \\
      garchomp venusaur charizard sneasler kingambit incineroar

Use "-" or "SKIP" for a slot to skip saving that sprite (e.g. for an
already-captured species).
"""

import json
import os
import sys
from PIL import Image


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
BOX_DEFS_PATH = os.path.join(SCRIPT_DIR, "box_definitions.json")
SPRITE_CACHE = os.path.join(REPO_ROOT, "data", "sprite_cache")


def get_box(data, name):
    for b in data["boxes"]:
        if b["name"] == name and b.get("status") == "confirmed" and b.get("box"):
            return b["box"]
    raise ValueError(f"Box '{name}' not found or not confirmed in {BOX_DEFS_PATH}")


def main():
    if len(sys.argv) < 2 + 6:
        print(__doc__)
        sys.exit(1)

    screenshot_path = sys.argv[1]
    slot_slugs = [s.strip().lower() for s in sys.argv[2:8]]

    if not os.path.exists(screenshot_path):
        print(f"Error: screenshot not found: {screenshot_path}")
        sys.exit(1)

    with open(BOX_DEFS_PATH) as f:
        data = json.load(f)

    # Anchor: sprite_0 is in card 0 (top-left).
    sprite_0 = get_box(data, "moves_more/sprite_0")
    sx, sy, sw, sh = sprite_0

    # Derive col / row offsets from the already-measured species boxes.
    sp0 = get_box(data, "moves_more/species_0")  # top-left
    sp1 = get_box(data, "moves_more/species_1")  # top-right
    sp2 = get_box(data, "moves_more/species_2")  # mid-left

    col_offset = sp1[0] - sp0[0]    # dx between left and right columns
    row_offset = sp2[1] - sp0[1]    # dy between rows 0 and 1

    img = Image.open(screenshot_path).convert("RGBA")
    W, H = img.size

    os.makedirs(SPRITE_CACHE, exist_ok=True)

    #  Slot layout: slot = row*2 + col
    print(f"Image: {W}x{H}  col_offset={col_offset:.4f}  row_offset={row_offset:.4f}")
    print(f"Cache: {SPRITE_CACHE}")
    print()

    saved = 0
    skipped = 0
    for slot in range(6):
        row = slot // 2
        col = slot % 2
        slug = slot_slugs[slot]

        # Compute this slot's sprite box
        fx = sx + col * col_offset
        fy = sy + row * row_offset
        fw = sw
        fh = sh

        # Convert to pixel coords
        px_x = int(fx * W)
        px_y = int(fy * H)
        px_w = int(fw * W)
        px_h = int(fh * H)

        if slug in ("-", "skip"):
            print(f"  slot {slot} [{row},{col}]  skipped")
            skipped += 1
            continue

        crop = img.crop((px_x, px_y, px_x + px_w, px_y + px_h))
        out_path = os.path.join(SPRITE_CACHE, f"{slug}.png")

        if os.path.exists(out_path):
            # Keep existing if same size, else overwrite with warning.
            existing = Image.open(out_path)
            if existing.size == crop.size:
                print(f"  slot {slot} [{row},{col}]  {slug:<20s}  already cached (same size) -- skipping")
                existing.close()
                skipped += 1
                continue
            print(f"  slot {slot} [{row},{col}]  {slug:<20s}  overwriting (size changed: {existing.size} -> {crop.size})")
            existing.close()

        crop.save(out_path)
        print(f"  slot {slot} [{row},{col}]  {slug:<20s}  saved -> {os.path.relpath(out_path, REPO_ROOT)}  ({px_w}x{px_h}px)")
        saved += 1

    print()
    print(f"Done: {saved} saved, {skipped} skipped.")
    all_cached = sorted(f[:-4] for f in os.listdir(SPRITE_CACHE) if f.endswith(".png"))
    print(f"Sprite cache now contains {len(all_cached)} species: {', '.join(all_cached)}")


if __name__ == "__main__":
    main()
