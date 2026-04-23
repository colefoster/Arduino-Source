#!/usr/bin/env python3
"""
Build Pokemon Champions sprite atlas from data/sprite_reference/.

Packs all Menu_CP_*.png sprites into a single PNG grid with an
accompanying JSON describing per-slug pixel coordinates. Format matches
SpriteDatabase loader in CommonTools/Resources/SpriteDatabase.h:

    {
      "spriteWidth":  128,
      "spriteHeight": 128,
      "spriteLocations": {
        "garchomp": { "top": <px>, "left": <px> },
        ...
      }
    }

When multiple sprite files map to the same slug (cosmetic variants
like Vivillon patterns), picks the shortest-named file as canonical
(which is the base-form file, e.g. Menu_CP_0666.png for vivillon).

Output:
  Resources/PokemonChampions/PokemonSprites.png
  Resources/PokemonChampions/PokemonSprites.json
"""

import json
import math
import os
from PIL import Image


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(SCRIPT_DIR)
SPRITE_DIR = os.path.join(REPO_ROOT, "data", "sprite_reference")
MAP_PATH   = os.path.join(SPRITE_DIR, "sprite_slug_map.json")
OUT_DIR    = os.path.join(REPO_ROOT, "Resources", "PokemonChampions")
OUT_PNG    = os.path.join(OUT_DIR, "PokemonSprites.png")
OUT_JSON   = os.path.join(OUT_DIR, "PokemonSprites.json")


SPRITE_W = 128
SPRITE_H = 128


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(MAP_PATH) as f:
        slug_map = json.load(f)   # filename -> slug

    # Invert: slug -> list of filenames. Pick shortest filename as canonical.
    slug_to_files = {}
    for fn, slug in slug_map.items():
        slug_to_files.setdefault(slug, []).append(fn)

    canonical = {slug: sorted(files, key=len)[0] for slug, files in slug_to_files.items()}
    slugs = sorted(canonical.keys())

    # Grid layout: roughly square
    n = len(slugs)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    atlas_w = cols * SPRITE_W
    atlas_h = rows * SPRITE_H

    print(f"Building atlas: {n} unique species")
    print(f"  Grid: {cols} cols x {rows} rows")
    print(f"  Image: {atlas_w} x {atlas_h} px")

    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    sprite_locations = {}

    for idx, slug in enumerate(slugs):
        row = idx // cols
        col = idx % cols
        left = col * SPRITE_W
        top  = row * SPRITE_H

        src_path = os.path.join(SPRITE_DIR, canonical[slug])
        sprite = Image.open(src_path).convert("RGBA")
        if sprite.size != (SPRITE_W, SPRITE_H):
            sprite = sprite.resize((SPRITE_W, SPRITE_H), Image.LANCZOS)

        atlas.paste(sprite, (left, top), sprite)
        sprite_locations[slug] = {"top": top, "left": left}

    atlas.save(OUT_PNG, optimize=True)

    manifest = {
        "spriteWidth":  SPRITE_W,
        "spriteHeight": SPRITE_H,
        "spriteLocations": sprite_locations,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    png_bytes = os.path.getsize(OUT_PNG)
    json_bytes = os.path.getsize(OUT_JSON)
    print(f"\n  PNG:  {OUT_PNG}  ({png_bytes:,} bytes)")
    print(f"  JSON: {OUT_JSON}  ({json_bytes:,} bytes)")
    print(f"  Species: {n}")


if __name__ == "__main__":
    main()
