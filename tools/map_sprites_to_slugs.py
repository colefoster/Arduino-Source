#!/usr/bin/env python3
"""
Map Bulbapedia Menu_CP_*.png filenames to species slugs used in the
PokemonSpeciesOCR.json dictionary.

Outputs data/sprite_reference/sprite_slug_map.json:
    { "Menu_CP_0445.png": "garchomp",
      "Menu_CP_0445-Mega.png": "garchomp-mega", ... }

and a list of unmapped filenames so we can manually resolve them.

Uses PokeAPI for base dex -> species name lookup and a transform
table for form suffixes.
"""

import json
import os
import re
import time

import cloudscraper


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SPRITE_DIR = os.path.join(REPO_ROOT, "data", "sprite_reference")
SPECIES_OCR_PATH = os.path.join(REPO_ROOT, "Resources", "PokemonChampions", "PokemonSpeciesOCR.json")
OUT_MAP = os.path.join(SPRITE_DIR, "sprite_slug_map.json")

POKEAPI_CACHE = os.path.join(SCRIPT_DIR, ".pokeapi_cache.json")


# Suffix in filename -> suffix in slug (or (prefix_inject, suffix_replace))
FORM_SUFFIX_MAP = {
    # Mega suffixes
    "Mega":      "mega",
    "Mega_X":    "mega-x",
    "Mega_Y":    "mega-y",
    # Regional variants
    "Alola":     "alola",
    "Galar":     "galar",
    "Hisui":     "hisui",
    "Paldea_Aqua":   "paldea-aqua",
    "Paldea_Blaze":  "paldea-blaze",
    "Paldea_Combat": "paldea-combat",
    # Rotom appliances
    "Fan":    "fan",
    "Frost":  "frost",
    "Heat":   "heat",
    "Mow":    "mow",
    "Wash":   "wash",
    # Castform weather forms
    "Rainy":  "rainy",
    "Snowy":  "snowy",
    "Sunny":  "sunny",
    # Vivillon patterns
    "Archipelago":   "archipelago",
    "Continental":   "continental",
    "Elegant":       "elegant",
    "Fancy":         "fancy",
    "Garden":        "garden",
    "High_Plains":   "high-plains",
    "Icy_Snow":      "icy-snow",
    "Jungle":        "jungle",
    "Marine":        "marine",
    "Meadow":        "meadow",
    "Modern":        "modern",
    "Monsoon":       "monsoon",
    "Ocean":         "ocean",
    "Poké_Ball":     "poke-ball",
    "Polar":         "polar",
    "River":         "river",
    "Sandstorm":     "sandstorm",
    "Savanna":       "savanna",
    "Sun":           "sun",
    "Tundra":        "tundra",
    # Alcremie
    "Ruby_Cream":    "ruby-cream",
    "Ruby_Swirl":    "ruby-swirl",
    "Salted_Cream":  "salted-cream",
    # Morpeko
    "Hangry":        "hangry",
    # Basculegion / Basculin
    "Female":        "f",
    # Dudunsparce
    "Three":         "three-segment",
    # Palafin
    "Hero":          "hero",
    # Goodra
    "Eternal":       "eternal",
    # Basculin
    "Blue":          "blue-striped",
    "White":         "white-striped",
    # Minior core colors
    "Orange":        "orange",
    "Yellow":        "yellow",
    # Furfrou (cosmetic, same stats)
    "Dandy":         "dandy",
    "Debutante":     "debutante",
    "Diamond":       "diamond",
    "Heart":         "heart",
    "Kabuki":        "kabuki",
    "La_Reine":      "la-reine",
    "Matron":        "matron",
    "Pharaoh":       "pharaoh",
    "Star":          "star",
    # Aegislash
    "Blade":         "blade",
    # Pumpkaboo / Gourgeist (cosmetic)
    "Jumbo":         "super",
    "Large":         "large",
    "Small":         "small",
    # Lycanroc
    "Dusk":          "dusk",
    "Midnight":      "midnight",
    # Alcremie flavors
    "Caramel_Swirl": "caramel-swirl",
    "Lemon_Cream":   "lemon-cream",
    "Matcha_Cream":  "matcha-cream",
    "Mint_Cream":    "mint-cream",
    "Rainbow_Swirl": "rainbow-swirl",
}


# OCR-dict slug adjustments: PokeAPI uses 'mr-rime' but our dict uses 'mr.-rime'
OCR_SLUG_FIXUPS = {
    "mr-rime":           "mr.-rime",
    "mr-mime":           "mr.-mime",
    "mr-mime-galar":     "mr.-mime-galar",
    "mime-jr":           "mime-jr.",
    "maushold-three-segment": "maushold",   # collapse to base; battle-equivalent
    "morpeko-hangry":    "morpeko",           # collapse
    "castform-rainy":    "castform",          # collapse
    "castform-snowy":    "castform",
    "castform-sunny":    "castform",
    "vivillon-archipelago":  "vivillon",
    "vivillon-continental":  "vivillon",
    "vivillon-elegant":      "vivillon",
    "vivillon-fancy":        "vivillon",
    "vivillon-garden":       "vivillon",
    "vivillon-high-plains":  "vivillon",
    "vivillon-icy-snow":     "vivillon",
    "vivillon-jungle":       "vivillon",
    "vivillon-marine":       "vivillon",
    "vivillon-meadow":       "vivillon",
    "vivillon-modern":       "vivillon",
    "vivillon-monsoon":      "vivillon",
    "vivillon-ocean":        "vivillon",
    "vivillon-poke-ball":    "vivillon",
    "vivillon-polar":        "vivillon",
    "vivillon-river":        "vivillon",
    "vivillon-sandstorm":    "vivillon",
    "vivillon-savanna":      "vivillon",
    "vivillon-sun":          "vivillon",
    "vivillon-tundra":       "vivillon",
    "furfrou-dandy":         "furfrou",
    "furfrou-debutante":     "furfrou",
    "furfrou-diamond":       "furfrou",
    "furfrou-heart":         "furfrou",
    "furfrou-kabuki":        "furfrou",
    "furfrou-la-reine":      "furfrou",
    "furfrou-matron":        "furfrou",
    "furfrou-pharaoh":       "furfrou",
    "furfrou-star":          "furfrou",
    "pumpkaboo-small":       "pumpkaboo",
    "pumpkaboo-large":       "pumpkaboo",
    "pumpkaboo-super":       "pumpkaboo",
    "gourgeist-small":       "gourgeist",
    "gourgeist-large":       "gourgeist",
    "gourgeist-super":       "gourgeist",
    "alcremie-ruby-cream":      "alcremie",
    "alcremie-ruby-swirl":      "alcremie",
    "alcremie-salted-cream":    "alcremie",
    "alcremie-caramel-swirl":   "alcremie",
    "alcremie-lemon-cream":     "alcremie",
    "alcremie-matcha-cream":    "alcremie",
    "alcremie-mint-cream":      "alcremie",
    "alcremie-rainbow-swirl":   "alcremie",
    # Florges color variants (dex 671) — collapse (cosmetic only)
    "florges-blue-striped":   "florges",
    "florges-white-striped":  "florges",
    "florges-orange":         "florges",
    "florges-yellow":         "florges",
}


def load_pokeapi_cache():
    if os.path.exists(POKEAPI_CACHE):
        with open(POKEAPI_CACHE) as f:
            return json.load(f)
    return {}


def save_pokeapi_cache(cache):
    with open(POKEAPI_CACHE, 'w') as f:
        json.dump(cache, f, indent=2)


def get_species_name(scraper, dex, cache):
    """Return the PokeAPI species slug for a dex number."""
    key = str(dex)
    if key in cache:
        return cache[key]
    r = scraper.get(f"https://pokeapi.co/api/v2/pokemon-species/{dex}/")
    if r.status_code != 200:
        return None
    data = r.json()
    name = data.get('name')
    cache[key] = name
    return name


def parse_filename(fn):
    """Return (dex_number, form_suffix) from 'Menu_CP_0445-Mega.png'."""
    m = re.match(r'Menu_CP_(\d{4})(?:-(.+))?\.png$', fn)
    if not m:
        return None, None
    dex = int(m.group(1))
    form = m.group(2)    # None if no form suffix
    return dex, form


def filename_to_slug(fn, dex_to_name):
    dex, form = parse_filename(fn)
    if dex is None:
        return None, "unparseable filename"
    base = dex_to_name.get(dex)
    if not base:
        return None, f"no PokeAPI entry for dex {dex}"
    if form is None:
        slug = base
    else:
        form_suffix = FORM_SUFFIX_MAP.get(form)
        if form_suffix is None:
            return None, f"unknown form suffix '{form}'"
        slug = f"{base}-{form_suffix}"
    # Apply OCR-dict fixups: collapse cosmetic forms, handle 'mr.-rime' etc.
    slug = OCR_SLUG_FIXUPS.get(slug, slug)
    return slug, None


def main():
    scraper = cloudscraper.create_scraper()

    # Load species slugs from our OCR dictionary for validation
    with open(SPECIES_OCR_PATH) as f:
        ocr_data = json.load(f)
    known_slugs = set(ocr_data.get('eng', {}).keys())
    print(f"Loaded {len(known_slugs)} known slugs from PokemonSpeciesOCR.json")

    sprites = sorted(f for f in os.listdir(SPRITE_DIR) if f.startswith("Menu_CP_") and f.endswith(".png"))
    print(f"Found {len(sprites)} sprite files\n")

    # Collect unique dex numbers to batch PokeAPI lookups
    unique_dex = sorted({parse_filename(fn)[0] for fn in sprites if parse_filename(fn)[0]})
    print(f"{len(unique_dex)} unique dex numbers to resolve via PokeAPI...")

    cache = load_pokeapi_cache()
    dex_to_name = {}
    for dex in unique_dex:
        name = get_species_name(scraper, dex, cache)
        if name:
            dex_to_name[dex] = name
        else:
            print(f"  WARN: could not resolve dex {dex}")
        if len(cache) % 20 == 0:
            save_pokeapi_cache(cache)
        time.sleep(0.05)
    save_pokeapi_cache(cache)
    print(f"Resolved {len(dex_to_name)} dex -> names\n")

    mapping = {}
    unmapped = []
    mismatched = []

    for fn in sprites:
        slug, err = filename_to_slug(fn, dex_to_name)
        if err:
            unmapped.append((fn, err))
            continue
        if slug not in known_slugs:
            mismatched.append((fn, slug))
        mapping[fn] = slug

    with open(OUT_MAP, 'w') as f:
        json.dump(mapping, f, indent=2, sort_keys=True)

    print(f"Mapped: {len(mapping)}/{len(sprites)}")
    print(f"Validated against OCR slugs: {len(mapping) - len(mismatched)} hit, {len(mismatched)} mismatched")
    print(f"Unmapped: {len(unmapped)}")
    print()
    if unmapped:
        print("Unmapped files (need manual resolution):")
        for fn, err in unmapped:
            print(f"  {fn}: {err}")
        print()
    if mismatched:
        print(f"Mismatched slugs (slug not in PokemonSpeciesOCR.json, may need dictionary update):")
        for fn, slug in mismatched[:40]:
            print(f"  {fn} -> '{slug}'  (not in OCR dict)")
        if len(mismatched) > 40:
            print(f"  ... and {len(mismatched) - 40} more")
        print()

    print(f"Output: {OUT_MAP}")


if __name__ == "__main__":
    main()
