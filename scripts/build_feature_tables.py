#!/usr/bin/env python3
"""Build model-ready feature lookup tables from PS data + hand-built taxonomies.

Reads:
  data/ps_data/{pokedex,moves,items,abilities}.json
  data/vocab/{species,moves,items,abilities}.json

Writes:
  data/feature_tables/{species,move,item,ability}_features.json
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS_DIR = ROOT / "data" / "ps_data"
VOCAB_DIR = ROOT / "data" / "vocab"
OUT_DIR = ROOT / "data" / "feature_tables"

# ── helpers ──────────────────────────────────────────────────────────────

def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  → {path} ({len(data)} entries)")


def _to_ps_id(name: str) -> str:
    """Convert display name to PS id format (lowercase, no spaces/hyphens/special)."""
    return "".join(c for c in name.lower() if c.isalnum())


# ── species ──────────────────────────────────────────────────────────────

def build_species_features():
    pokedex = _load(PS_DIR / "pokedex.json")
    vocab = _load(VOCAB_DIR / "species.json")

    # Build lookup: ps_id → entry, plus handle formes
    ps_lookup = {}
    for ps_id, entry in pokedex.items():
        ps_lookup[ps_id] = entry
        # Also index by name for fallback
        ps_lookup[_to_ps_id(entry.get("name", ""))] = entry

    features = {}
    missing = []
    for name in vocab:
        if name in ("<PAD>", "<UNK>"):
            continue
        ps_id = _to_ps_id(name)
        entry = ps_lookup.get(ps_id)
        # Fall back to base species for cosmetic forms (Alcremie-X, Florges-X, etc.)
        if not entry and "-" in name:
            # Try progressively shorter prefixes (e.g. "Alcremie-Salted-Cream" → "Alcremie-Salted" → "Alcremie")
            parts = name.split("-")
            for i in range(len(parts) - 1, 0, -1):
                base_id = _to_ps_id("-".join(parts[:i]))
                entry = ps_lookup.get(base_id)
                if entry:
                    break
        if not entry:
            missing.append(name)
            features[name] = _default_species()
            continue

        bs = entry.get("baseStats", {})
        types = entry.get("types", [])
        evos = entry.get("evos")
        features[name] = {
            "hp": bs.get("hp", 0),
            "atk": bs.get("atk", 0),
            "def": bs.get("def", 0),
            "spa": bs.get("spa", 0),
            "spd": bs.get("spd", 0),
            "spe": bs.get("spe", 0),
            "type1": types[0] if len(types) > 0 else "",
            "type2": types[1] if len(types) > 1 else "",
            "weight_kg": entry.get("weightkg", 0),
            "bst": sum(bs.values()),
            "is_fully_evolved": not bool(evos),
            "is_mega": "-Mega" in name or ps_id.endswith("mega"),
        }

    if missing:
        print(f"  [warn] {len(missing)} species not found in pokedex: {missing[:5]}...")
    return features


def _default_species():
    return {
        "hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0,
        "type1": "", "type2": "", "weight_kg": 0, "bst": 0,
        "is_fully_evolved": False, "is_mega": False,
    }


# ── moves ────────────────────────────────────────────────────────────────

WEATHER_MOVES = {"sunnyday", "raindance", "sandstorm", "snowscape", "hail"}
TERRAIN_MOVES = {"electricterrain", "grassyterrain", "mistyterrain", "psychicterrain"}
SIDE_CONDITION_MOVES = {
    "reflect", "lightscreen", "auroraveil", "tailwind", "stealthrock",
    "spikes", "toxicspikes", "stickyweb", "safeguard", "wideguard", "quickguard",
}
SECONDARY_STATUSES = {"brn", "par", "slp", "frz", "psn", "tox"}


def build_move_features():
    moves_data = _load(PS_DIR / "moves.json")
    vocab = _load(VOCAB_DIR / "moves.json")

    ps_lookup = {}
    for ps_id, entry in moves_data.items():
        ps_lookup[ps_id] = entry
        ps_lookup[_to_ps_id(entry.get("name", ""))] = entry

    features = {}
    missing = []
    for name in vocab:
        if name in ("<PAD>", "<UNK>"):
            continue
        ps_id = _to_ps_id(name)
        entry = ps_lookup.get(ps_id)
        if not entry:
            missing.append(name)
            features[name] = _default_move()
            continue

        flags = entry.get("flags", {})
        secondary = entry.get("secondary") or {}
        # Some moves have "secondaries" (list) instead
        secondaries = entry.get("secondaries") or []
        if secondaries and not secondary:
            secondary = secondaries[0]

        sec_status = secondary.get("status", "")
        sec_chance = secondary.get("chance", entry.get("secondary", {}).get("chance", 0)) if secondary else 0
        sec_volatileStatus = secondary.get("volatileStatus", "")

        # Drain / recoil
        drain = entry.get("drain", [0, 1])
        recoil = entry.get("recoil", [0, 1])
        drain_frac = drain[0] / drain[1] if isinstance(drain, list) and len(drain) == 2 and drain[1] != 0 else 0
        recoil_frac = recoil[0] / recoil[1] if isinstance(recoil, list) and len(recoil) == 2 and recoil[1] != 0 else 0

        features[name] = {
            "base_power": entry.get("basePower", 0),
            "accuracy": entry.get("accuracy", 100) if entry.get("accuracy") is not True else 0,
            "priority": entry.get("priority", 0),
            "type": entry.get("type", ""),
            "category": entry.get("category", ""),
            "target": entry.get("target", ""),
            "contact": bool(flags.get("contact")),
            "sound": bool(flags.get("sound")),
            "secondary_chance": sec_chance or 0,
            "secondary_flinch": sec_volatileStatus == "flinch" or secondary.get("volatileStatus") == "flinch",
            "secondary_status": sec_status if sec_status in SECONDARY_STATUSES else "",
            "drain": drain_frac,
            "recoil": recoil_frac,
            "self_switch": bool(entry.get("selfSwitch")),
            "force_switch": bool(entry.get("forceSwitch")),
            "stalling_move": bool(entry.get("stallingMove")),
            "sets_weather": ps_id in WEATHER_MOVES,
            "sets_terrain": ps_id in TERRAIN_MOVES,
            "sets_side_condition": ps_id in SIDE_CONDITION_MOVES,
        }

    if missing:
        print(f"  [warn] {len(missing)} moves not found in PS data: {missing[:5]}...")
    return features


def _default_move():
    return {
        "base_power": 0, "accuracy": 0, "priority": 0,
        "type": "", "category": "", "target": "",
        "contact": False, "sound": False,
        "secondary_chance": 0, "secondary_flinch": False, "secondary_status": "",
        "drain": 0, "recoil": 0,
        "self_switch": False, "force_switch": False, "stalling_move": False,
        "sets_weather": False, "sets_terrain": False, "sets_side_condition": False,
    }


# ── items ────────────────────────────────────────────────────────────────

# Hand-built taxonomy for the ~106 items in our vocab
ITEM_TAXONOMY = {
    # Berries — resist type
    "Wacan Berry": ("resist_berry", True),
    "Chople Berry": ("resist_berry", True),
    "Colbur Berry": ("resist_berry", True),
    "Shuca Berry": ("resist_berry", True),
    "Passho Berry": ("resist_berry", True),
    "Coba Berry": ("resist_berry", True),
    "Yache Berry": ("resist_berry", True),
    "Occa Berry": ("resist_berry", True),
    "Haban Berry": ("resist_berry", True),
    "Charti Berry": ("resist_berry", True),
    "Rindo Berry": ("resist_berry", True),
    "Roseli Berry": ("resist_berry", True),
    "Kasib Berry": ("resist_berry", True),
    "Babiri Berry": ("resist_berry", True),
    "Kebia Berry": ("resist_berry", True),
    "Payapa Berry": ("resist_berry", True),
    "Chilan Berry": ("resist_berry", True),

    # Berries — healing / status
    "Sitrus Berry": ("berry", True),
    "Lum Berry": ("berry", True),
    "Leppa Berry": ("berry", True),
    "Chesto Berry": ("berry", True),
    "Persim Berry": ("berry", True),
    "Oran Berry": ("berry", True),
    "Rawst Berry": ("berry", True),

    # Choice items
    "Choice Scarf": ("choice", False),

    # Focus Sash
    "Focus Sash": ("focus_sash", False),

    # Recovery
    "Leftovers": ("recovery", False),
    "Shell Bell": ("recovery", False),

    # Life Orb — its own category
    "Life Orb": ("life_orb", False),

    # Stat boost / type-boost items
    "White Herb": ("stat_boost", False),
    "Mental Herb": ("stat_boost", False),
    "Charcoal": ("stat_boost", False),
    "Black Glasses": ("stat_boost", False),
    "Mystic Water": ("stat_boost", False),
    "Silk Scarf": ("stat_boost", False),
    "Poison Barb": ("stat_boost", False),
    "Spell Tag": ("stat_boost", False),
    "Soft Sand": ("stat_boost", False),
    "Fairy Feather": ("stat_boost", False),
    "Dragon Fang": ("stat_boost", False),
    "Black Belt": ("stat_boost", False),
    "Sharp Beak": ("stat_boost", False),
    "Magnet": ("stat_boost", False),
    "Metal Coat": ("stat_boost", False),
    "Miracle Seed": ("stat_boost", False),
    "Never-Melt Ice": ("stat_boost", False),
    "Scope Lens": ("stat_boost", False),
    "Light Ball": ("stat_boost", False),
    "Hard Stone": ("stat_boost", False),
    "Twisted Spoon": ("stat_boost", False),
    "Bright Powder": ("stat_boost", False),
    "Quick Claw": ("stat_boost", False),
    "King's Rock": ("stat_boost", False),

    # Mega stones
    "Galladite": ("mega_stone", False),
    "Glimmoranite": ("mega_stone", False),
    "Scizorite": ("mega_stone", False),
    "Gardevoirite": ("mega_stone", False),
    "Charizardite Y": ("mega_stone", False),
    "Charizardite X": ("mega_stone", False),
    "Gengarite": ("mega_stone", False),
    "Aggronite": ("mega_stone", False),
    "Kangaskhanite": ("mega_stone", False),
    "Aerodactylite": ("mega_stone", False),
    "Golurkite": ("mega_stone", False),
    "Drampanite": ("mega_stone", False),
    "Clefablite": ("mega_stone", False),
    "Slowbronite": ("mega_stone", False),
    "Blastoisinite": ("mega_stone", False),
    "Houndoominite": ("mega_stone", False),
    "Heracronite": ("mega_stone", False),
    "Skarmorite": ("mega_stone", False),
    "Audinite": ("mega_stone", False),
    "Delphoxite": ("mega_stone", False),
    "Lopunnite": ("mega_stone", False),
    "Ampharosite": ("mega_stone", False),
    "Starminite": ("mega_stone", False),
    "Garchompite": ("mega_stone", False),
    "Crabominite": ("mega_stone", False),
    "Victreebelite": ("mega_stone", False),
    "Chandelurite": ("mega_stone", False),
    "Abomasite": ("mega_stone", False),
    "Alakazite": ("mega_stone", False),
    "Excadrite": ("mega_stone", False),
    "Absolite": ("mega_stone", False),
    "Venusaurite": ("mega_stone", False),
    "Hawluchanite": ("mega_stone", False),
    "Scovillainite": ("mega_stone", False),
    "Banettite": ("mega_stone", False),
    "Greninjite": ("mega_stone", False),
    "Cameruptite": ("mega_stone", False),
    "Steelixite": ("mega_stone", False),
    "Gyaradosite": ("mega_stone", False),
    "Meowsticite": ("mega_stone", False),
    "Feraligite": ("mega_stone", False),
    "Chesnaughtite": ("mega_stone", False),
    "Manectite": ("mega_stone", False),
    "Sharpedonite": ("mega_stone", False),
    "Emboarite": ("mega_stone", False),
    "Pinsirite": ("mega_stone", False),
    "Lucarionite": ("mega_stone", False),
    "Beedrillite": ("mega_stone", False),
    "Floettite": ("mega_stone", False),
    "Meganiumite": ("mega_stone", False),
    "Froslassite": ("mega_stone", False),
    "Dragoninite": ("mega_stone", False),
    "Tyranitarite": ("mega_stone", False),
    "Chimechite": ("mega_stone", False),
}


def build_item_features():
    vocab = _load(VOCAB_DIR / "items.json")

    features = {}
    unmapped = []
    for name in vocab:
        if name in ("<PAD>", "<UNK>"):
            continue
        tax = ITEM_TAXONOMY.get(name)
        if tax:
            category, is_berry = tax
        else:
            unmapped.append(name)
            category, is_berry = "misc", False

        features[name] = {
            "category": category,
            "is_berry": is_berry,
            "is_choice": category == "choice",
            "is_mega_stone": category == "mega_stone",
            "is_focus_sash": category == "focus_sash",
        }

    if unmapped:
        print(f"  [warn] {len(unmapped)} items not in taxonomy (defaulting to misc): {unmapped}")
    return features


# ── abilities ────────────────────────────────────────────────────────────

# Hand-built taxonomy for the ~135 abilities in our vocab
ABILITY_TAXONOMY = {
    # Weather setters
    "Drizzle": "weather_setter",
    "Drought": "weather_setter",
    "Sand Stream": "weather_setter",
    "Snow Warning": "weather_setter",

    # Terrain setters
    # (none in our vocab as abilities — terrain is usually set by moves)

    # Intimidate-like (attack-lowering on switch)
    "Intimidate": "intimidate_like",
    "Supersweet Syrup": "intimidate_like",

    # Stat boost on switch
    "Speed Boost": "stat_boost_on_switch",
    "Moody": "stat_boost_on_switch",
    "Defiant": "stat_boost_on_switch",
    "Competitive": "stat_boost_on_switch",
    "Weak Armor": "stat_boost_on_switch",
    "Justified": "stat_boost_on_switch",
    "Stamina": "stat_boost_on_switch",
    "Berserk": "stat_boost_on_switch",
    "Contrary": "stat_boost_on_switch",
    "Anger Point": "stat_boost_on_switch",
    "Steadfast": "stat_boost_on_switch",
    "Supreme Overlord": "stat_boost_on_switch",

    # Contact punish
    "Rough Skin": "contact_punish",
    "Flame Body": "contact_punish",
    "Poison Point": "contact_punish",
    "Poison Touch": "contact_punish",
    "Static": "contact_punish",
    "Cute Charm": "contact_punish",
    "Gooey": "contact_punish",
    "Wandering Spirit": "contact_punish",
    "Pickpocket": "contact_punish",

    # Immunity abilities
    "Levitate": "immunity",
    "Lightning Rod": "immunity",
    "Volt Absorb": "immunity",
    "Water Absorb": "immunity",
    "Flash Fire": "immunity",
    "Sap Sipper": "immunity",
    "Motor Drive": "immunity",
    "Earth Eater": "immunity",
    "Dry Skin": "immunity",
    "Storm Drain": "immunity",

    # Speed control / priority manipulation
    "Prankster": "speed_control",
    "Gale Wings": "speed_control",
    "Armor Tail": "speed_control",
    "Queenly Majesty": "speed_control",
    "Unburden": "speed_control",
    "Sand Rush": "speed_control",
    "Swift Swim": "speed_control",
    "Chlorophyll": "speed_control",
    "Surge Surfer": "speed_control",

    # Mold Breaker-like
    "Mold Breaker": "mold_breaker_like",
    "Piercing Drill": "mold_breaker_like",
    "Unseen Fist": "mold_breaker_like",
    "Stalwart": "mold_breaker_like",
    "Infiltrator": "mold_breaker_like",

    # Competitive / Defiant (already covered under stat_boost_on_switch)

    # Protective / team support
    "Friend Guard": "team_support",
    "Flower Veil": "team_support",
    "Sweet Veil": "team_support",
    "Aroma Veil": "team_support",
    "Telepathy": "team_support",
    "Healer": "team_support",
    "Hospitality": "team_support",
    "Symbiosis": "team_support",

    # Ability-based power boosts
    "Huge Power": "power_boost",
    "Pure Power": "power_boost",
    "Adaptability": "power_boost",
    "Technician": "power_boost",
    "Tough Claws": "power_boost",
    "Sharpness": "power_boost",
    "Iron Fist": "power_boost",
    "Mega Launcher": "power_boost",
    "Skill Link": "power_boost",
    "Parental Bond": "power_boost",
    "Water Bubble": "power_boost",
    "Pixilate": "power_boost",
    "Protean": "power_boost",
    "Liquid Voice": "power_boost",
    "Dragonize": "power_boost",
    "Solar Power": "power_boost",
    "Sand Force": "power_boost",

    # Defensive
    "Multiscale": "defensive",
    "Filter": "defensive",
    "Sturdy": "defensive",
    "Bulletproof": "defensive",
    "Thick Fat": "defensive",
    "Overcoat": "defensive",
    "Shell Armor": "defensive",
    "Clear Body": "defensive",
    "Mirror Armor": "defensive",
    "Magic Bounce": "defensive",
    "Magic Guard": "defensive",
    "Unaware": "defensive",
    "Soundproof": "defensive",
    "Ice Body": "defensive",
    "Inner Focus": "defensive",
    "Limber": "defensive",
    "Insomnia": "defensive",
    "Oblivious": "defensive",
    "Own Tempo": "defensive",
    "Immunity": "defensive",
    "Hyper Cutter": "defensive",
    "Big Pecks": "defensive",
    "Keen Eye": "defensive",
    "Tangled Feet": "defensive",

    # Disruption
    "Shadow Tag": "disruption",
    "Unnerve": "disruption",
    "Pressure": "disruption",
    "Cursed Body": "disruption",
    "Innards Out": "disruption",
    "Toxic Debris": "disruption",
    "Spicy Spray": "disruption",

    # Recovery / sustain
    "Regenerator": "recovery",
    "Rain Dish": "recovery",
    "Natural Cure": "recovery",

    # Other notable
    "No Guard": "misc",
    "Moxie": "misc",
    "Cloud Nine": "misc",
    "Opportunist": "misc",
    "Scrappy": "misc",
    "Simple": "misc",
    "Heavy Metal": "misc",
    "Leaf Guard": "misc",
    "Rock Head": "misc",
    "Sand Veil": "misc",
    "Snow Cloak": "misc",
    "Illuminate": "misc",
    "Compound Eyes": "misc",
    "Anticipation": "misc",
    "Frisk": "misc",
    "Magician": "misc",
    "Corrosion": "misc",
    "Curious Medicine": "misc",
    "Klutz": "misc",
    "Synchronize": "misc",
    "Plus": "misc",
    "Fairy Aura": "misc",
    "Mega Sol": "misc",
    "Overgrow": "misc",
    "Blaze": "misc",
    "Torrent": "misc",
}


def build_ability_features():
    abilities_data = _load(PS_DIR / "abilities.json")
    vocab = _load(VOCAB_DIR / "abilities.json")

    ps_lookup = {}
    for ps_id, entry in abilities_data.items():
        ps_lookup[ps_id] = entry
        ps_lookup[_to_ps_id(entry.get("name", ""))] = entry

    features = {}
    unmapped = []
    for name in vocab:
        if name in ("<PAD>", "<UNK>"):
            continue
        ps_id = _to_ps_id(name)
        entry = ps_lookup.get(ps_id, {})
        rating = entry.get("rating", 0)
        is_breakable = entry.get("isBreakable", False)

        category = ABILITY_TAXONOMY.get(name, None)
        if category is None:
            unmapped.append(name)
            category = "misc"

        features[name] = {
            "rating": rating,
            "breakable": bool(is_breakable),
            "category": category,
        }

    if unmapped:
        print(f"  [warn] {len(unmapped)} abilities not in taxonomy (defaulting to misc): {unmapped}")
    return features


# ── main ─────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Building species features...")
    _save(OUT_DIR / "species_features.json", build_species_features())

    print("Building move features...")
    _save(OUT_DIR / "move_features.json", build_move_features())

    print("Building item features...")
    _save(OUT_DIR / "item_features.json", build_item_features())

    print("Building ability features...")
    _save(OUT_DIR / "ability_features.json", build_ability_features())

    print("\nDone!")


if __name__ == "__main__":
    main()
