#!/usr/bin/env python3
"""Download Pokemon Showdown data files and apply Champions mod overrides.

Fetches base PS data (pokedex, moves, items, abilities) then downloads the
Champions-specific mod from the smogon/pokemon-showdown GitHub repo to apply
balance changes (BP buffs/nerfs, accuracy changes, secondary effect changes,
flag changes, etc.).
"""

import json
import re
import urllib.request
from pathlib import Path

PS_BASE = "https://play.pokemonshowdown.com/data"
# PS serves some files as .json, others as .js — map source → output name
BASE_FILES = {
    "pokedex.json": "pokedex.json",
    "moves.json": "moves.json",
    "items.js": "items.json",
    "abilities.js": "abilities.json",
}

# Champions mod overrides from the PS GitHub repo
GH_RAW = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions"
MOD_FILES = {
    "moves.ts": "moves.json",
    "abilities.ts": "abilities.json",
    # items.ts is only legality flags, no property changes — skip
}

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "ps_data"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "pokemon-champions/1.0"})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")


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
    raw = re.sub(r'(?<=[{,\n])\s*([a-zA-Z_]\w*)\s*:', r'"\1":', raw)

    # Remove trailing commas before } or ]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)

    return raw


def _ts_to_overrides(raw: str) -> dict:
    """Parse a Champions mod .ts file into {id: {field: value}} overrides.

    These files are TypeScript with `inherit: true` entries. We extract only
    the JSON-serializable property overrides (basePower, accuracy, pp, type,
    secondary, flags, etc.) and skip code blocks (functions, conditions with
    inherit).
    """
    # Strip the outer export wrapper to get the object body
    match = re.search(r'=\s*\{', raw)
    if not match:
        return {}
    body = raw[match.end():]

    overrides = {}
    # Match top-level entries: identifier: { ... }
    # We need to handle nested braces properly
    pos = 0
    while pos < len(body):
        # Find next entry identifier (skip trailing comma from previous entry)
        id_match = re.match(r'[,\s]*(\w+)\s*:\s*\{', body[pos:])
        if not id_match:
            break
        entry_id = id_match.group(1)
        start = pos + id_match.end()

        # Find matching closing brace
        depth = 1
        i = start
        while i < len(body) and depth > 0:
            if body[i] == '{':
                depth += 1
            elif body[i] == '}':
                depth -= 1
            i += 1
        entry_body = body[start:i - 1]
        pos = i

        # Parse simple property overrides from this entry
        props = _parse_entry_props(entry_body)
        if props:
            overrides[entry_id] = props

    return overrides


def _parse_entry_props(entry_body: str) -> dict:
    """Extract simple JSON-serializable properties from a mod entry body."""
    props = {}

    # basePower: number
    m = re.search(r'"?basePower"?\s*:\s*(\d+)', entry_body)
    if m:
        props["basePower"] = int(m.group(1))

    # accuracy: number or true
    m = re.search(r'"?accuracy"?\s*:\s*(true|\d+)', entry_body)
    if m:
        props["accuracy"] = True if m.group(1) == "true" else int(m.group(1))

    # pp: number
    m = re.search(r'"?pp"?\s*:\s*(\d+)', entry_body)
    if m:
        props["pp"] = int(m.group(1))

    # type: "Type"
    m = re.search(r'"?type"?\s*:\s*"(\w+)"', entry_body)
    if m:
        props["type"] = m.group(1)

    # secondary: undefined (removed)
    if re.search(r'"?secondary"?\s*:\s*undefined', entry_body):
        props["secondary"] = None

    # secondary: { chance: N, ... } — extract chance and key effects
    sec_match = re.search(r'"?secondary"?\s*:\s*\{([^}]+)\}', entry_body)
    if sec_match and "secondary" not in props:
        sec_body = sec_match.group(1)
        sec = {}
        cm = re.search(r'"?chance"?\s*:\s*(\d+)', sec_body)
        if cm:
            sec["chance"] = int(cm.group(1))
        vm = re.search(r'"?volatileStatus"?\s*:\s*["\'](\w+)["\']', sec_body)
        if vm:
            sec["volatileStatus"] = vm.group(1)
        sm = re.search(r'"?status"?\s*:\s*["\'](\w+)["\']', sec_body)
        if sm:
            sec["status"] = sm.group(1)
        # boosts
        boosts_match = re.search(r'"?boosts"?\s*:\s*\{([^}]+)\}', sec_body)
        if boosts_match:
            sec["boosts"] = {}
            for bm in re.finditer(r'"?(\w+)"?\s*:\s*(-?\d+)', boosts_match.group(1)):
                sec["boosts"][bm.group(1)] = int(bm.group(2))
        if sec:
            props["secondary"] = sec

    # flags: { ... } — full replacement
    flags_match = re.search(r'"?flags"?\s*:\s*\{([^}]+)\}', entry_body)
    if flags_match:
        flags = {}
        for fm in re.finditer(r'"?(\w+)"?\s*:\s*(\d+)', flags_match.group(1)):
            flags[fm.group(1)] = int(fm.group(2))
        if flags:
            props["flags"] = flags

    # boosts (top-level, for moves like Toxic Thread)
    # Find all "boosts" blocks, skip ones inside "secondary"
    for bm in re.finditer(r'"?boosts"?\s*:\s*\{([^}]+)\}', entry_body):
        # Check if this boosts block is inside a secondary block
        preceding = entry_body[:bm.start()]
        if '"secondary"' in preceding or 'secondary' in preceding.split('\n')[-1]:
            continue
        boosts = {}
        for pm in re.finditer(r'"?(\w+)"?\s*:\s*(-?\d+)', bm.group(1)):
            boosts[pm.group(1)] = int(pm.group(2))
        if boosts:
            props["boosts"] = boosts
        break

    # isNonstandard: null (re-legalized)
    if re.search(r'"?isNonstandard"?\s*:\s*null', entry_body):
        props["isNonstandard"] = None

    # rating: number (for abilities)
    m = re.search(r'"?rating"?\s*:\s*(\d+(?:\.\d+)?)', entry_body)
    if m:
        props["rating"] = float(m.group(1))

    return props


def _apply_overrides(base_data: dict, overrides: dict, name: str) -> int:
    """Merge Champions mod overrides into the base PS data dict. Returns count of applied changes."""
    applied = 0
    for ps_id, changes in overrides.items():
        if ps_id not in base_data:
            continue
        entry = base_data[ps_id]
        for key, value in changes.items():
            if key == "isNonstandard":
                # Just legality — update but don't count as a feature change
                entry[key] = value
                continue
            old = entry.get(key)
            if old != value:
                entry[key] = value
                applied += 1
    return applied


def fetch_ps_data():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch base PS data
    base_data = {}
    for src_name, out_name in BASE_FILES.items():
        url = f"{PS_BASE}/{src_name}"
        print(f"Fetching {url} ...")
        raw = _fetch(url)

        if src_name.endswith(".js"):
            raw = _js_to_json(raw)
        else:
            if raw.lstrip().startswith("var "):
                raw = raw.split("=", 1)[1].strip().rstrip(";")

        data = json.loads(raw)
        base_data[out_name] = data
        print(f"  → {len(data)} entries")

    # Step 2: Fetch and apply Champions mod overrides
    print("\nApplying Champions mod overrides...")
    for ts_name, target_name in MOD_FILES.items():
        url = f"{GH_RAW}/{ts_name}"
        print(f"Fetching {url} ...")
        raw = _fetch(url)
        overrides = _ts_to_overrides(raw)
        print(f"  → parsed {len(overrides)} entries from mod")

        if target_name in base_data:
            n = _apply_overrides(base_data[target_name], overrides, target_name)
            print(f"  → applied {n} property changes to {target_name}")

    # Step 3: Write output
    print("\nWriting output...")
    for out_name, data in base_data.items():
        out_path = OUT_DIR / out_name
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  → {out_path} ({len(data)} entries)")


if __name__ == "__main__":
    fetch_ps_data()
