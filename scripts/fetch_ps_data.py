#!/usr/bin/env python3
"""Download Pokemon Showdown data files (pokedex, moves, items, abilities)."""

import json
import re
import urllib.request
from pathlib import Path

PS_BASE = "https://play.pokemonshowdown.com/data"
# PS serves some files as .json, others as .js — map source → output name
FILES = {
    "pokedex.json": "pokedex.json",
    "moves.json": "moves.json",
    "items.js": "items.json",
    "abilities.js": "abilities.json",
}

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "ps_data"


def _js_to_json(raw: str) -> str:
    """Convert PS JavaScript object literal to valid JSON.

    PS .js files use unquoted keys and sometimes trailing commas.
    """
    # Strip export wrapper
    if raw.lstrip().startswith("exports."):
        raw = raw.split("=", 1)[1].strip().rstrip(";")
    elif raw.lstrip().startswith("var "):
        raw = raw.split("=", 1)[1].strip().rstrip(";")

    # Quote unquoted keys: word characters before a colon
    # Match key positions: after { or , followed by optional whitespace then a bare identifier
    raw = re.sub(r'(?<=[{,\n])\s*([a-zA-Z_]\w*)\s*:', r'"\1":', raw)

    # Remove trailing commas before } or ]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)

    return raw


def fetch_ps_data():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, out_name in FILES.items():
        url = f"{PS_BASE}/{src_name}"
        print(f"Fetching {url} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "pokemon-champions/1.0"})
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")

        if src_name.endswith(".js"):
            raw = _js_to_json(raw)
        else:
            # .json files may still have var wrapper
            if raw.lstrip().startswith("var "):
                raw = raw.split("=", 1)[1].strip().rstrip(";")

        data = json.loads(raw)
        out_path = OUT_DIR / out_name
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  → {out_path} ({len(data)} entries)")


if __name__ == "__main__":
    fetch_ps_data()
