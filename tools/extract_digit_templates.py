#!/usr/bin/env python3
"""
Extract binarized digit templates (0-9) from HP% test frames.

Applies the same pipeline as the C++ BattleHUDReader:
  1. Crop HP region using ImageFloatBox coordinates
  2. 3x upscale (nearest neighbor)
  3. White-only binarization (mn > 180, mx - mn < 50)
  4. Split into N equal-width strips based on known digit count

Saves each digit as a PNG in Packages/Resources/PokemonChampions/DigitTemplates/.
"""

import os, sys
from collections import defaultdict
from PIL import Image
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(REPO, "CommandLineTests", "PokemonChampions", "OpponentHPReader_Doubles")
OUT_DIR = os.path.join(REPO, "Packages", "Resources", "PokemonChampions", "DigitTemplates")

# Crop boxes from C++ init_doubles_boxes() — ImageFloatBox(x, y, w, h)
SLOT_BOXES = {
    0: (0.707, 0.116, 0.027, 0.034),
    1: (0.9125, 0.119, 0.0295, 0.0306),
}

# Binarization thresholds (must match C++ raw_ocr_numbers)
MIN_BRIGHTNESS = 180
MAX_SPREAD = 50
SCALE = 3


def binarize(img_array):
    """White-only binarize matching C++ raw_ocr_numbers(). Returns bool array (True=foreground/text)."""
    r, g, b = img_array[:, :, 0], img_array[:, :, 1], img_array[:, :, 2]
    mn = np.minimum(np.minimum(r, g), b)
    mx = np.maximum(np.maximum(r, g), b)
    return (mn > MIN_BRIGHTNESS) & ((mx - mn) < MAX_SPREAD)


def find_content_bounds(bw):
    """Find the bounding box of foreground pixels. Returns (x0, y0, x1, y1) or None."""
    col_sums = bw.sum(axis=0)
    row_sums = bw.sum(axis=1)
    cols = np.where(col_sums > 0)[0]
    rows = np.where(row_sums > 0)[0]
    if len(cols) == 0 or len(rows) == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def split_into_digits(bw, n_digits):
    """Split binarized image into n_digits using valley detection on column projection.

    Finds the n_digits-1 deepest valleys in the column sum profile to split digits.
    Falls back to equal-width splitting if valleys aren't clear.
    """
    bounds = find_content_bounds(bw)
    if bounds is None:
        return []
    x0, y0, x1, y1 = bounds
    content = bw[y0:y1, x0:x1]

    if n_digits == 1:
        return [content]

    col_sums = content.sum(axis=0).astype(float)
    w = len(col_sums)

    # Find valleys: local minima in the column sum profile
    # Use a smoothed version to avoid noise
    # For n_digits, we need n_digits-1 split points
    # Look for valleys in the interior (not at edges)
    margin = w // (n_digits * 3)  # don't split too close to edges

    # Find all local minima
    valleys = []
    for x in range(margin, w - margin):
        # Check if this is a local minimum within a window
        window = max(3, w // (n_digits * 2))
        left = max(0, x - window)
        right = min(w, x + window + 1)
        if col_sums[x] == col_sums[left:right].min():
            valleys.append((col_sums[x], x))

    # Pick the n_digits-1 deepest (lowest sum) valleys, sorted by position
    valleys.sort(key=lambda v: v[0])  # sort by depth (lowest first)
    splits = sorted([v[1] for v in valleys[:n_digits - 1]])

    if len(splits) < n_digits - 1:
        # Fallback: equal-width splitting
        strip_w = w // n_digits
        splits = [strip_w * (i + 1) for i in range(n_digits - 1)]

    # Create digit crops using split points
    all_splits = [0] + splits + [w]
    digits = []
    for i in range(n_digits):
        sx, ex = all_splits[i], all_splits[i + 1]
        digit_region = content[:, sx:ex]
        # Trim to tight horizontal bounds
        dcol = digit_region.sum(axis=0)
        dcols = np.where(dcol > 0)[0]
        if len(dcols) > 0:
            digit_region = digit_region[:, dcols[0]:dcols[-1] + 1]
        digits.append(digit_region)

    return digits


def process_frame(filepath):
    """Extract digit crops from a single test frame. Returns list of (digit_char, crop_array)."""
    basename = os.path.splitext(os.path.basename(filepath))[0]
    parts = basename.split("_")
    try:
        hp_val = int(parts[-1])
        slot_str = parts[-2]
        slot = int(slot_str[1]) if slot_str in ("s0", "s1") else None
    except (ValueError, IndexError):
        return []

    if slot is None or slot not in SLOT_BOXES:
        return []

    # Load and crop
    img = Image.open(filepath)
    W, H = img.size
    bx, by, bw, bh = SLOT_BOXES[slot]
    cx, cy = int(bx * W), int(by * H)
    cw, ch = int(bw * W), int(bh * H)
    crop = img.crop((cx, cy, cx + cw, cy + ch))

    # 3x upscale (nearest neighbor to match C++ block-fill)
    scaled = crop.resize((cw * SCALE, ch * SCALE), Image.NEAREST)
    arr = np.array(scaled)[:, :, :3]

    # Binarize
    bw_mask = binarize(arr)

    # Split using known digit count
    hp_str = str(hp_val)
    digit_crops = split_into_digits(bw_mask, len(hp_str))

    if len(digit_crops) != len(hp_str):
        print(f"  WARN: {basename} split into {len(digit_crops)} segments, expected {len(hp_str)} — skipping")
        return []

    results = []
    for ch_char, crop_arr in zip(hp_str, digit_crops):
        results.append((ch_char, crop_arr, basename))

    return results


def save_template(digit_char, crop_bool, out_dir):
    """Save a binarized digit crop as PNG (black text on white bg, matching C++ output)."""
    h, w = crop_bool.shape
    # C++ outputs: 0xFF000000 (black) for text, 0xFFFFFFFF (white) for bg
    img_arr = np.where(crop_bool, 0, 255).astype(np.uint8)
    rgb = np.stack([img_arr, img_arr, img_arr], axis=-1)
    img = Image.fromarray(rgb)
    path = os.path.join(out_dir, f"{digit_char}.png")
    img.save(path)
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Collect all digit crops grouped by digit character
    digit_crops = defaultdict(list)

    files = sorted(f for f in os.listdir(TEST_DIR) if f.endswith(".png"))
    print(f"Processing {len(files)} test frames from {TEST_DIR}")

    for f in files:
        path = os.path.join(TEST_DIR, f)
        results = process_frame(path)
        for ch, crop, src in results:
            digit_crops[ch].append((src, crop))

    # Pick best template per digit (most foreground pixels = cleanest)
    print(f"\nDigit coverage:")
    for d in "0123456789":
        crops = digit_crops.get(d, [])
        if crops:
            best_src, best_crop = max(crops, key=lambda x: x[1].sum())
            h, w = best_crop.shape
            path = save_template(d, best_crop, OUT_DIR)
            print(f"  {d}: {len(crops)} instances, saved {w}x{h}px from {best_src}")
        else:
            print(f"  {d}: MISSING — no instances found")

    # Summary
    have = sorted(digit_crops.keys())
    missing = [d for d in "0123456789" if d not in digit_crops]
    print(f"\nHave: {', '.join(have)}")
    if missing:
        print(f"Missing: {', '.join(missing)} — need additional test frames")
    else:
        print("All digits 0-9 covered!")


if __name__ == "__main__":
    main()
