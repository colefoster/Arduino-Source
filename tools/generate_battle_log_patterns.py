#!/usr/bin/env python3
"""Generate BattleLog regex patterns from Pokemon Showdown's data/text/default.ts.

Reads PS's default.ts (via --ps-repo path or PS_REPO env var) and emits
SerialPrograms/Source/PokemonChampions/Inference/PokemonChampions_BattleLogPatterns_Generated.cpp.

How to refresh:

    git clone --depth 1 https://github.com/smogon/pokemon-showdown.git /tmp/ps/pokemon-showdown
    python3 tools/generate_battle_log_patterns.py --ps-repo /tmp/ps/pokemon-showdown

The generated file is committed; the PS clone is only needed at regeneration time.

Mapping decisions live in EVENT_TYPE_MAP below — each (group, key) -> our
BattleLogEventType. New PS keys default to OTHER until added here.
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional


# ── Mapping: (PS group, PS key) → (event_type, optional boost_stages, optional static_stat) ──
# group is the top-level key in default.ts ("default", "brn", "sandstorm", etc.).
# key is the inner field ("start", "switchIn", "boost2", etc.).
#
# Tuple: (event_type_name, boost_stages, static_stat).
# - boost_stages: signed int for STAT_CHANGE patterns; 0 otherwise.
# - static_stat: a string to stuff into BattleLogEvent.stat unconditionally
#   (used for STATUS_INFLICTED to record "burned"/"poisoned"/etc.).
EVENT_TYPE_MAP = {
    # ── default group ──
    ("default", "move"):              ("MOVE_USED", 0, ""),
    ("default", "switchIn"):          ("SWITCH_IN", 0, ""),
    ("default", "switchInOwn"):       ("SWITCH_IN", 0, ""),
    ("default", "switchOut"):         ("SWITCH_OUT", 0, ""),
    ("default", "switchOutOwn"):      ("SWITCH_OUT", 0, ""),
    ("default", "drag"):              ("DRAG", 0, ""),
    ("default", "faint"):             ("FAINTED", 0, ""),
    ("default", "cant"):              ("CANT", 0, ""),
    ("default", "cantNoMove"):        ("CANT", 0, ""),
    ("default", "fail"):              ("FAILED", 0, ""),
    ("default", "transform"):         ("TRANSFORM", 0, ""),
    ("default", "typeChange"):        ("TYPE_CHANGE", 0, ""),
    ("default", "typeChangeFromEffect"): ("TYPE_CHANGE", 0, ""),
    ("default", "typeAdd"):           ("TYPE_CHANGE", 0, ""),
    ("default", "mega"):              ("MEGA_EVOLVE", 0, ""),
    ("default", "megaNoItem"):        ("MEGA_EVOLVE", 0, ""),
    ("default", "megaGen6"):          ("MEGA_EVOLVE", 0, ""),
    ("default", "transformMega"):     ("MEGA_EVOLVE", 0, ""),
    ("default", "primal"):            ("PRIMAL", 0, ""),
    ("default", "start"):             ("EFFECT_START", 0, ""),
    ("default", "end"):               ("EFFECT_END", 0, ""),
    ("default", "activate"):          ("EFFECT_ACTIVATE", 0, ""),
    ("default", "startTeamEffect"):   ("EFFECT_START", 0, ""),
    ("default", "endTeamEffect"):     ("EFFECT_END", 0, ""),
    ("default", "startFieldEffect"):  ("EFFECT_START", 0, ""),
    ("default", "endFieldEffect"):    ("EFFECT_END", 0, ""),
    ("default", "changeAbility"):     ("ABILITY_CHANGE", 0, ""),
    ("default", "addItem"):           ("ITEM_TRANSFER", 0, ""),
    ("default", "takeItem"):          ("ITEM_TRANSFER", 0, ""),
    ("default", "eatItem"):           ("ITEM_ACTIVATED", 0, ""),
    ("default", "useGem"):            ("ITEM_ACTIVATED", 0, ""),
    ("default", "eatItemWeaken"):     ("ITEM_ACTIVATED", 0, ""),
    ("default", "removeItem"):        ("ITEM_TRANSFER", 0, ""),
    ("default", "activateItem"):      ("ITEM_ACTIVATED", 0, ""),
    ("default", "activateWeaken"):    ("ITEM_ACTIVATED", 0, ""),
    ("default", "damage"):            ("DAMAGE", 0, ""),
    ("default", "damagePercentage"):  ("DAMAGE", 0, ""),
    ("default", "damageFromPokemon"): ("DAMAGE", 0, ""),
    ("default", "damageFromItem"):    ("DAMAGE", 0, ""),
    ("default", "damageFromPartialTrapping"): ("DAMAGE", 0, ""),
    ("default", "heal"):              ("HEAL", 0, ""),
    ("default", "healFromZEffect"):   ("HEAL", 0, ""),
    ("default", "healFromEffect"):    ("HEAL", 0, ""),
    ("default", "boost"):             ("STAT_CHANGE",  1, ""),
    ("default", "boost2"):            ("STAT_CHANGE",  2, ""),
    ("default", "boost3"):            ("STAT_CHANGE",  3, ""),
    ("default", "boost0"):            ("STAT_CHANGE_AT_CAP",  0, ""),
    ("default", "boostFromItem"):     ("STAT_CHANGE",  1, ""),
    ("default", "boost2FromItem"):    ("STAT_CHANGE",  2, ""),
    ("default", "boost3FromItem"):    ("STAT_CHANGE",  3, ""),
    ("default", "boostFromZEffect"):  ("STAT_CHANGE",  1, ""),
    ("default", "boost2FromZEffect"): ("STAT_CHANGE",  2, ""),
    ("default", "boost3FromZEffect"): ("STAT_CHANGE",  3, ""),
    ("default", "boostMultipleFromZEffect"): ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "unboost"):           ("STAT_CHANGE", -1, ""),
    ("default", "unboost2"):          ("STAT_CHANGE", -2, ""),
    ("default", "unboost3"):          ("STAT_CHANGE", -3, ""),
    ("default", "unboost0"):          ("STAT_CHANGE_AT_CAP",  0, ""),
    ("default", "unboostFromItem"):   ("STAT_CHANGE", -1, ""),
    ("default", "unboost2FromItem"):  ("STAT_CHANGE", -2, ""),
    ("default", "unboost3FromItem"):  ("STAT_CHANGE", -3, ""),
    ("default", "swapBoost"):           ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "swapOffensiveBoost"):  ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "swapDefensiveBoost"):  ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "copyBoost"):           ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "clearBoost"):          ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "clearBoostFromZEffect"): ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "invertBoost"):         ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "clearAllBoost"):       ("STAT_CHANGE_OTHER", 0, ""),
    ("default", "superEffective"):       ("SUPER_EFFECTIVE", 0, ""),
    ("default", "superEffectiveSpread"): ("SUPER_EFFECTIVE", 0, ""),
    ("default", "extremelyEffective"):       ("SUPER_EFFECTIVE", 0, ""),
    ("default", "extremelyEffectiveSpread"): ("SUPER_EFFECTIVE", 0, ""),
    ("default", "resisted"):           ("NOT_EFFECTIVE", 0, ""),
    ("default", "resistedSpread"):     ("NOT_EFFECTIVE", 0, ""),
    ("default", "mostlyIneffective"):  ("NOT_EFFECTIVE", 0, ""),
    ("default", "mostlyIneffectiveSpread"): ("NOT_EFFECTIVE", 0, ""),
    ("default", "crit"):               ("CRIT", 0, ""),
    ("default", "critSpread"):         ("CRIT", 0, ""),
    ("default", "immune"):             ("IMMUNE", 0, ""),
    ("default", "immuneNoPokemon"):    ("IMMUNE", 0, ""),
    ("default", "immuneOHKO"):         ("IMMUNE", 0, ""),
    ("default", "miss"):               ("MISS", 0, ""),
    ("default", "missNoPokemon"):      ("MISS", 0, ""),
    ("default", "ohko"):               ("OHKO", 0, ""),
    ("default", "hitCount"):           ("HIT_COUNT", 0, ""),
    ("default", "hitCountSingular"):   ("HIT_COUNT", 0, ""),
    ("default", "startBattle"):        ("BATTLE_START", 0, ""),
    ("default", "winBattle"):          ("BATTLE_END", 0, ""),
    ("default", "tieBattle"):          ("BATTLE_END", 0, ""),
    ("default", "turn"):               ("TURN_MARKER", 0, ""),
    # Skip Z/Dynamax/Tera-only stuff for Champions: still mapped sensibly.
    ("default", "zEffect"):            ("OTHER", 0, ""),
    ("default", "zPower"):             ("OTHER", 0, ""),
    ("default", "zBroken"):            ("OTHER", 0, ""),
    ("default", "terastallize"):       ("OTHER", 0, ""),
    ("default", "canDynamax"):         ("OTHER", 0, ""),
    ("default", "canDynamaxOwn"):      ("OTHER", 0, ""),
    ("default", "abilityActivation"):  ("OTHER", 0, ""),
    # text-substitution helpers — not real events
    ("default", "pokemon"):            None,
    ("default", "opposingPokemon"):    None,
    ("default", "team"):               None,
    ("default", "opposingTeam"):       None,
    ("default", "party"):              None,
    ("default", "opposingParty"):      None,
    ("default", "swap"):               ("SWITCH_OUT", 0, ""),
    ("default", "swapCenter"):         ("OTHER", 0, ""),
    ("default", "noTarget"):           ("FAILED", 0, ""),
    ("default", "center"):             ("OTHER", 0, ""),
    ("default", "combine"):            ("OTHER", 0, ""),
    # ── statuses ──
    ("brn", "start"):       ("STATUS_INFLICTED", 0, "burned"),
    ("brn", "startFromItem"): ("STATUS_INFLICTED", 0, "burned"),
    ("brn", "alreadyStarted"): ("STATUS_INFLICTED", 0, "burned"),
    ("brn", "end"):         ("STATUS_HEALED",    0, "burned"),
    ("brn", "endFromItem"): ("STATUS_HEALED",    0, "burned"),
    ("brn", "damage"):      ("STATUS_DAMAGE",    0, "burned"),
    ("frz", "start"):       ("STATUS_INFLICTED", 0, "frozen"),
    ("frz", "alreadyStarted"): ("STATUS_INFLICTED", 0, "frozen"),
    ("frz", "end"):         ("STATUS_HEALED",    0, "frozen"),
    ("frz", "endFromItem"): ("STATUS_HEALED",    0, "frozen"),
    ("frz", "endFromMove"): ("STATUS_HEALED",    0, "frozen"),
    ("frz", "cant"):        ("CANT",             0, "frozen"),
    ("par", "start"):       ("STATUS_INFLICTED", 0, "paralyzed"),
    ("par", "alreadyStarted"): ("STATUS_INFLICTED", 0, "paralyzed"),
    ("par", "end"):         ("STATUS_HEALED",    0, "paralyzed"),
    ("par", "endFromItem"): ("STATUS_HEALED",    0, "paralyzed"),
    ("par", "cant"):        ("CANT",             0, "paralyzed"),
    ("psn", "start"):       ("STATUS_INFLICTED", 0, "poisoned"),
    ("psn", "alreadyStarted"): ("STATUS_INFLICTED", 0, "poisoned"),
    ("psn", "end"):         ("STATUS_HEALED",    0, "poisoned"),
    ("psn", "endFromItem"): ("STATUS_HEALED",    0, "poisoned"),
    ("psn", "damage"):      ("STATUS_DAMAGE",    0, "poisoned"),
    ("tox", "start"):       ("STATUS_INFLICTED", 0, "badly poisoned"),
    ("tox", "startFromItem"): ("STATUS_INFLICTED", 0, "badly poisoned"),
    ("slp", "start"):           ("STATUS_INFLICTED", 0, "asleep"),
    ("slp", "startFromRest"):   ("STATUS_INFLICTED", 0, "asleep"),
    ("slp", "alreadyStarted"):  ("STATUS_INFLICTED", 0, "asleep"),
    ("slp", "end"):             ("STATUS_HEALED",    0, "asleep"),
    ("slp", "endFromItem"):     ("STATUS_HEALED",    0, "asleep"),
    ("slp", "cant"):            ("CANT",             0, "asleep"),
    # ── volatile / misc effects ──
    ("confusion", "start"):           ("CONFUSION", 0, ""),
    ("confusion", "startFromFatigue"): ("CONFUSION", 0, ""),
    ("confusion", "end"):             ("CONFUSION", 0, ""),
    ("confusion", "endFromItem"):     ("CONFUSION", 0, ""),
    ("confusion", "alreadyStarted"):  ("CONFUSION", 0, ""),
    ("confusion", "activate"):        ("CONFUSION", 0, ""),
    ("confusion", "damage"):          ("DAMAGE", 0, ""),
    ("drain", "heal"):                ("HEAL", 0, ""),
    ("flinch", "cant"):               ("CANT", 0, "flinched"),
    ("heal", "fail"):                 ("FAILED", 0, ""),
    ("healreplacement", "activate"):  ("HEAL", 0, ""),
    ("nopp", "cant"):                 ("CANT", 0, ""),
    ("recharge", "cant"):             ("CANT", 0, "recharging"),
    ("recoil", "damage"):             ("DAMAGE", 0, ""),
    ("unboost", "fail"):              ("STAT_CHANGE_OTHER", 0, ""),
    ("unboost", "failSingular"):      ("STAT_CHANGE_OTHER", 0, ""),
    ("struggle", "activate"):         ("CANT", 0, ""),
    ("trapped", "start"):             ("EFFECT_START", 0, ""),
    ("dynamax", "start"):             ("OTHER", 0, ""),
    ("dynamax", "end"):               ("OTHER", 0, ""),
    ("dynamax", "block"):             ("OTHER", 0, ""),
    ("dynamax", "fail"):              ("OTHER", 0, ""),
    # ── weather ──  (any weather entry → WEATHER)
    # ── terrain ──  (any terrain entry → TERRAIN)
    # ── field effects ──
    ("trickroom", "start"):  ("TRICK_ROOM", 0, ""),
    ("trickroom", "end"):    ("TRICK_ROOM", 0, ""),
    ("gravity", "start"):    ("FIELD_EFFECT", 0, "gravity"),
    ("gravity", "end"):      ("FIELD_EFFECT", 0, "gravity"),
    ("gravity", "cant"):     ("CANT", 0, ""),
    ("gravity", "activate"): ("FIELD_EFFECT", 0, "gravity"),
    ("magicroom", "start"):  ("FIELD_EFFECT", 0, "magic room"),
    ("magicroom", "end"):    ("FIELD_EFFECT", 0, "magic room"),
    ("wonderroom", "start"): ("FIELD_EFFECT", 0, "wonder room"),
    ("wonderroom", "end"):   ("FIELD_EFFECT", 0, "wonder room"),
    ("mudsport", "start"):   ("FIELD_EFFECT", 0, "mud sport"),
    ("mudsport", "end"):     ("FIELD_EFFECT", 0, "mud sport"),
    ("watersport", "start"): ("FIELD_EFFECT", 0, "water sport"),
    ("watersport", "end"):   ("FIELD_EFFECT", 0, "water sport"),
    ("crash", "damage"):     ("DAMAGE", 0, ""),
}

WEATHER_GROUPS = {"sandstorm", "sunnyday", "raindance", "hail", "snowscape",
                  "desolateland", "primordialsea", "deltastream"}
TERRAIN_GROUPS = {"electricterrain", "grassyterrain", "mistyterrain", "psychicterrain"}

# Stat-id groups in default.ts whose entries are name-only (statName, etc.).
STAT_GROUPS = {"hp", "atk", "def", "spa", "spd", "spe", "accuracy", "evasion",
               "spc", "stats"}

# Yawn lives in moves.ts but the user explicitly wants it. Inject as a synthetic
# entry rather than parsing all of moves.ts.
SYNTHETIC_ENTRIES = [
    # (group, key, template, mapping_tuple)
    ("yawn", "start", "[POKEMON] grew drowsy!",
     ("STATUS_INFLICTED", 0, "drowsy")),
]


# ── Parser for the default.ts file ──

# Match a top-level group: e.g.   `slp: {`
GROUP_OPEN_RE = re.compile(r'^\t([A-Za-z_][A-Za-z0-9_]*):\s*\{\s*(?://.*)?$')
# Match an entry inside a group: e.g.   `\tstart: "  [POKEMON] was burned!",`
ENTRY_RE = re.compile(r'^\t\t([A-Za-z_][A-Za-z0-9_]*):\s*"((?:[^"\\]|\\.)*)"\s*,?\s*(?://.*)?$')
GROUP_CLOSE_RE = re.compile(r'^\t\},?\s*(?://.*)?$')


def parse_ps_default_ts(path: Path) -> List[Tuple[str, str, str]]:
    """Yield (group, key, template) tuples in source order."""
    out: List[Tuple[str, str, str]] = []
    current_group: Optional[str] = None
    for raw in path.read_text().splitlines():
        if current_group is None:
            m = GROUP_OPEN_RE.match(raw)
            if m:
                current_group = m.group(1)
            continue
        if GROUP_CLOSE_RE.match(raw):
            current_group = None
            continue
        m = ENTRY_RE.match(raw)
        if m:
            key, template = m.group(1), m.group(2)
            # decode common escapes (PS uses é etc.)
            template = bytes(template, "utf-8").decode("unicode_escape")
            out.append((current_group, key, template))
    return out


# ── Template → regex conversion ──

PLACEHOLDER_RE = re.compile(r"\[(POKEMON|TRAINER|FULLNAME|NICKNAME|TARGET|SOURCE|STAT|MOVE|ITEM|ABILITY|TYPE|EFFECT|TEAM|NUMBER|PERCENTAGE|SPECIES)\]")

# placeholder name → which BattleLogSlot to fill (matches enum in
# PokemonChampions_BattleLogPatterns.h).
PLACEHOLDER_SLOT = {
    "POKEMON": "POKEMON", "FULLNAME": "POKEMON", "NICKNAME": "POKEMON",
    "TARGET": "POKEMON", "SOURCE": "POKEMON",
    "STAT": "STAT",
    "MOVE": "MOVE",
    "ITEM": "ITEM",
    "ABILITY": "ABILITY",
    # everything else: dump to the generic effect slot (or NONE)
    "EFFECT": "EFFECT", "TYPE": "EFFECT", "SPECIES": "EFFECT",
    "NUMBER": "EFFECT", "PERCENTAGE": "EFFECT",
    "TRAINER": "NONE", "TEAM": "NONE",
}


def normalize_template(tpl: str) -> str:
    """Strip leading whitespace, surrounding parens, and PS-protocol markdown
    bold (`**[MOVE]**`) that don't appear in the on-screen text bar."""
    s = tpl.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    s = s.replace("**", "")
    return s


def template_to_regex(tpl: str) -> Tuple[str, List[str]]:
    """Convert a PS template into (regex_string, ordered_slot_names).

    Returns the slot for each capture group in left-to-right order. Slots are
    the same names as PLACEHOLDER_SLOT values."""
    tpl = normalize_template(tpl)
    slots: List[str] = []
    pieces: List[str] = []
    pos = 0
    for m in PLACEHOLDER_RE.finditer(tpl):
        # Literal text up to placeholder
        literal = tpl[pos:m.start()]
        pieces.append(re.escape(literal))
        # Placeholder → capture group
        ph = m.group(1)
        slots.append(PLACEHOLDER_SLOT[ph])
        pieces.append(r"(.+?)")
        pos = m.end()
    pieces.append(re.escape(tpl[pos:]))
    body = "".join(pieces)
    # Trailing '!' / '.' / '?' is OCR-fragile; make the terminator optional so
    # we still match when OCR drops it or replaces with a confusable (e.g. 'l'
    # for '!'). We rely on regex_search at the C++ side, so trailing garbage
    # in the OCR text doesn't need to be anchored away here.
    if body.endswith("!"):
        body = body[:-1] + "!?"
    elif body.endswith(r"\."):
        body = body[:-2] + r"\.?"
    elif body.endswith(r"\?"):
        body = body[:-2] + r"\??"
    return body, slots


# ── Entry-point logic ──

class Pattern:
    __slots__ = ("regex", "event_type", "boost_stages", "static_stat",
                 "slots", "template", "ps_path", "literal_chars")

    def __init__(self, regex, event_type, boost_stages, static_stat, slots,
                 template, ps_path):
        self.regex = regex
        self.event_type = event_type
        self.boost_stages = boost_stages
        self.static_stat = static_stat
        self.slots = slots
        self.template = template
        self.ps_path = ps_path
        # Heuristic specificity: total literal characters in the template
        # (excluding placeholders + outer parens). Longer literals are
        # more specific so we sort them first.
        normalized = normalize_template(template)
        stripped = PLACEHOLDER_RE.sub("", normalized)
        self.literal_chars = len(stripped)


def build_patterns(entries: List[Tuple[str, str, str]]) -> List[Pattern]:
    out: List[Pattern] = []
    seen_templates = set()
    for group, key, template in entries + [(g, k, t) for g, k, t, _ in SYNTHETIC_ENTRIES]:
        if template.startswith("#"):
            continue  # PS alias entry like "#psn"
        # Determine event_type for this entry.
        event_type, boost_stages, static_stat = (None, 0, "")
        if (group, key) in EVENT_TYPE_MAP:
            mapping = EVENT_TYPE_MAP[(group, key)]
            if mapping is None:
                continue
            event_type, boost_stages, static_stat = mapping
        elif group in WEATHER_GROUPS:
            event_type = "WEATHER"
        elif group in TERRAIN_GROUPS:
            event_type = "TERRAIN"
        elif group in STAT_GROUPS:
            continue  # statName helpers, not events
        else:
            # Synthetic entries carry their own mapping
            for g, k, t, mapping in SYNTHETIC_ENTRIES:
                if g == group and k == key:
                    event_type, boost_stages, static_stat = mapping
                    break
            if event_type is None:
                # Unmapped — skip silently. The catch-all OTHER classifies it.
                continue

        regex, slots = template_to_regex(template)
        norm = normalize_template(template)
        if not norm or norm in seen_templates:
            continue
        seen_templates.add(norm)
        out.append(Pattern(regex, event_type, boost_stages, static_stat, slots,
                           template, f"{group}.{key}"))
    # Sort by literal length descending — most specific first.
    out.sort(key=lambda p: -p.literal_chars)
    return out


def emit_cpp(patterns: List[Pattern], out_path: Path):
    lines = []
    lines.append("//  Generated by tools/generate_battle_log_patterns.py — do not edit by hand.")
    lines.append("//  Source: pokemon-showdown/data/text/default.ts")
    lines.append("")
    lines.append('#include "PokemonChampions_BattleLogPatterns.h"')
    lines.append("")
    lines.append("namespace PokemonAutomation{")
    lines.append("namespace NintendoSwitch{")
    lines.append("namespace PokemonChampions{")
    lines.append("")
    lines.append("const std::vector<BattleLogPattern>& battle_log_patterns(){")
    lines.append("    static const std::vector<BattleLogPattern> patterns = []{")
    lines.append("        std::vector<BattleLogPattern> v;")
    for p in patterns:
        slot_init = ", ".join(f"BattleLogSlot::{s}" for s in p.slots) if p.slots else ""
        # C++ raw string: use a delimiter that won't appear in the regex.
        regex_lit = f'R"___({p.regex})___"'
        tpl_lit = 'R"___(' + p.template.replace('"', '\\"') + ')___"'
        ps_lit = 'R"___(' + p.ps_path + ')___"'
        stat_lit = 'R"___(' + p.static_stat + ')___"'
        lines.append("        v.push_back({")
        lines.append(f"            std::regex({regex_lit}),")
        lines.append(f"            BattleLogEventType::{p.event_type},")
        lines.append(f"            {p.boost_stages},")
        lines.append(f"            {stat_lit},")
        lines.append(f"            {{{slot_init}}},")
        lines.append(f"            {tpl_lit},")
        lines.append(f"            {ps_lit},")
        lines.append("        });")
    lines.append("        return v;")
    lines.append("    }();")
    lines.append("    return patterns;")
    lines.append("}")
    lines.append("")
    lines.append("}")
    lines.append("}")
    lines.append("}")
    out_path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ps-repo", default=os.environ.get("PS_REPO", "/tmp/ps/pokemon-showdown"))
    ap.add_argument("--out", default=None,
                    help="output .cpp path (default: under SerialPrograms/.../Inference/)")
    ap.add_argument("--print-stats", action="store_true")
    args = ap.parse_args()

    ps_default = Path(args.ps_repo) / "data" / "text" / "default.ts"
    if not ps_default.exists():
        print(f"error: PS default.ts not found at {ps_default}", file=sys.stderr)
        print(f"clone with: git clone --depth 1 https://github.com/smogon/pokemon-showdown.git {args.ps_repo}", file=sys.stderr)
        sys.exit(2)

    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent
        / "SerialPrograms" / "Source" / "PokemonChampions" / "Inference"
        / "PokemonChampions_BattleLogPatterns_Generated.cpp"
    )

    entries = parse_ps_default_ts(ps_default)
    patterns = build_patterns(entries)
    emit_cpp(patterns, out)

    print(f"Wrote {len(patterns)} patterns to {out}")
    if args.print_stats:
        from collections import Counter
        c = Counter(p.event_type for p in patterns)
        for t, n in sorted(c.items(), key=lambda x: -x[1]):
            print(f"  {t:25} {n:4}")


if __name__ == "__main__":
    main()
