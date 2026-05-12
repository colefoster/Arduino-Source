#!/usr/bin/env python3
"""Self-test the Champions-overlay battle-log regexes.

Mirrors the patterns in
``SerialPrograms/Source/PokemonChampions/Inference/PokemonChampions_BattleLogReader.cpp``
(the Champions overlay table inside ``BattleLogReader::parse()``). Curated
test cases below assert that each canonical Pokemon-protocol message routes
to the right event type + effect name.

Use it two ways:

  $ python3 tools/test_battle_log_patterns.py
       Run the built-in corpus.

  $ python3 tools/test_battle_log_patterns.py --inbox
       Re-parse the raw_text strings auto-captured into
       test_images/_inbox/*-novel-event-type-*.json . Useful after a play
       session to see which observed Champions strings the patterns miss.

Patterns here are duplicated from the C++ side intentionally: this script
is the fast feedback loop while iterating on regex tweaks. After getting
the Python side green, port to BattleLogReader.cpp.
"""
from __future__ import annotations
import argparse
import glob
import json
import re
import sys
from pathlib import Path


# ── Overlay patterns (mirror of BattleLogReader.cpp::champions_overlays) ──
#
# Each row: (regex, event_type, effect_name).
# Regexes are case-insensitive (re.IGNORECASE applied below).
PATTERNS: list[tuple[str, str, str]] = [
    # Choice-lock rejection
    (r"The\s+(Choice\s+(?:Scarf|Band|Specs))\s+only\s+allows\s+the\s+use\s+of\s+(.+?)!?\s*$",
     "MOVE_LOCKED", "<item>"),

    # Volatiles
    (r"(.+?)\s+put\s+in\s+a\s+substitute!?$",              "VOLATILE_START", "SUBSTITUTE"),
    (r"(.+?)(?:'s)?\s+substitute\s+faded!?$",              "VOLATILE_END",   "SUBSTITUTE"),
    (r"(.+?)\s+fell\s+for\s+the\s+taunt!?$",               "VOLATILE_START", "TAUNT"),
    (r"(.+?)(?:'s)?\s+taunt\s+wore\s+off!?$",              "VOLATILE_END",   "TAUNT"),
    (r"(.+?)\s+received\s+an\s+encore!?$",                 "VOLATILE_START", "ENCORE"),
    (r"(.+?)(?:'s)?\s+encore\s+ended!?$",                  "VOLATILE_END",   "ENCORE"),
    (r"(.+?)(?:'s)?\s+(?:.+?)\s+was\s+disabled!?$",        "VOLATILE_START", "DISABLE"),
    (r"(.+?)(?:'s)?\s+move\s+is\s+no\s+longer\s+disabled!?$", "VOLATILE_END", "DISABLE"),
    (r"(.+?)\s+was\s+seeded!?$",                           "VOLATILE_START", "LEECHSEED"),
    (r"(.+?)\s+protected\s+itself!?$",                     "VOLATILE_START", "PROTECT"),
    (r"(.+?)\s+is\s+getting\s+pumped!?$",                  "VOLATILE_START", "FOCUSENERGY"),
    (r"(.+?)\s+planted\s+its\s+roots!?$",                  "VOLATILE_START", "INGRAIN"),
    (r"(.+?)\s+levitated\s+with\s+electromagnetism!?$",    "VOLATILE_START", "MAGNETRISE"),
    (r"(.+?)\s+was\s+prevented\s+from\s+healing!?$",       "VOLATILE_START", "HEALBLOCK"),
    (r"(.+?)\s+can't\s+use\s+(?:.+?)\s+via\s+sound!?$",    "VOLATILE_START", "THROATCHOP"),
    (r"(.+?)\s+fell\s+in\s+love!?$",                       "VOLATILE_START", "ATTRACT"),
    (r"(.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+3!?$",  "VOLATILE_START", "PERISH3"),
    (r"(.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+2!?$",  "VOLATILE_START", "PERISH2"),
    (r"(.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+1!?$",  "VOLATILE_START", "PERISH1"),
    (r"(.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+0!?$",  "VOLATILE_START", "PERISH4"),

    # Hazards
    (r"Pointed\s+stones\s+float\s+in\s+the\s+air\s+around\s+(.+?)(?:'s)?\s+team!?$",
     "HAZARD_SET", "stealth_rock"),
    # Poison spikes BEFORE plain spikes — "Poison spikes…" also matches the
    # shorter "Spikes were scattered…" regex via regex_search.
    (r"Poison\s+spikes\s+were\s+scattered\s+all\s+around\s+(.+?)(?:'s)?\s+(?:feet|team)!?$",
     "HAZARD_SET", "toxic_spikes"),
    (r"Spikes\s+were\s+scattered\s+all\s+around\s+(.+?)(?:'s)?\s+(?:feet|team)!?$",
     "HAZARD_SET", "spikes"),
    (r"A\s+sticky\s+web\s+has\s+been\s+laid\s+out\s+beneath\s+(.+?)(?:'s)?\s+feet!?$",
     "HAZARD_SET", "sticky_web"),
    (r"(.+?)\s+blew\s+away\s+(?:the\s+)?(?:stealth\s+rock|spikes|toxic\s+spikes|sticky\s+web|hazards)!?$",
     "HAZARD_CLEAR", "all"),

    # Side conditions
    (r"The\s+tailwind\s+blew\s+from\s+behind\s+(.+?)(?:'s)?\s+team!?$",
     "SIDE_START", "tailwind"),
    (r"(.+?)(?:'s)?\s+tailwind\s+petered\s+out!?$",
     "SIDE_END", "tailwind"),
    (r"Light\s+Screen\s+made\s+(.+?)(?:'s)?\s+team\s+stronger\s+against\s+special\s+moves!?$",
     "SIDE_START", "light_screen"),
    (r"(.+?)(?:'s)?\s+Light\s+Screen\s+wore\s+off!?$",
     "SIDE_END", "light_screen"),
    (r"Reflect\s+made\s+(.+?)(?:'s)?\s+team\s+stronger\s+against\s+physical\s+moves!?$",
     "SIDE_START", "reflect"),
    (r"(.+?)(?:'s)?\s+Reflect\s+wore\s+off!?$",
     "SIDE_END", "reflect"),
    (r"Aurora\s+Veil\s+made\s+(.+?)(?:'s)?\s+team\s+stronger\s+against\s+(?:both\s+physical\s+and\s+special|all)\s+moves!?$",
     "SIDE_START", "aurora_veil"),
    (r"(.+?)(?:'s)?\s+Aurora\s+Veil\s+wore\s+off!?$",
     "SIDE_END", "aurora_veil"),
    (r"(.+?)(?:'s)?\s+team\s+became\s+cloaked\s+by\s+a\s+mystical\s+veil!?$",
     "SIDE_START", "safeguard"),
    (r"(.+?)(?:'s)?\s+team\s+is\s+no\s+longer\s+protected\s+by\s+Safeguard!?$",
     "SIDE_END", "safeguard"),
    (r"(.+?)(?:'s)?\s+team\s+became\s+shrouded\s+in\s+mist!?$",
     "SIDE_START", "mist"),
    (r"(.+?)(?:'s)?\s+team\s+is\s+no\s+longer\s+protected\s+by\s+Mist!?$",
     "SIDE_END", "mist"),
    (r"The\s+Lucky\s+Chant\s+shielded\s+(.+?)(?:'s)?\s+team\s+from\s+critical\s+hits!?$",
     "SIDE_START", "lucky_chant"),
    (r"(.+?)(?:'s)?\s+team's\s+Lucky\s+Chant\s+wore\s+off!?$",
     "SIDE_END", "lucky_chant"),
]


# Each: (raw_text, expected_event_type, expected_effect). Effect "" means
# "no specific match required" (used for the MOVE_LOCKED case).
CASES: list[tuple[str, str, str]] = [
    # Choice-lock
    ("The Choice Scarf only allows the use of Wave Crash!", "MOVE_LOCKED", ""),
    ("The Choice Band only allows the use of Sucker Punch!", "MOVE_LOCKED", ""),
    ("The Choice Specs only allows the use of Moonblast!", "MOVE_LOCKED", ""),

    # Volatiles
    ("Pikachu put in a substitute!", "VOLATILE_START", "SUBSTITUTE"),
    ("Pikachu's substitute faded!", "VOLATILE_END", "SUBSTITUTE"),
    ("The opposing Garchomp fell for the taunt!", "VOLATILE_START", "TAUNT"),
    ("Garchomp's taunt wore off!", "VOLATILE_END", "TAUNT"),
    ("The opposing Whimsicott received an encore!", "VOLATILE_START", "ENCORE"),
    ("Tornadus's encore ended!", "VOLATILE_END", "ENCORE"),
    ("Tornadus was seeded!", "VOLATILE_START", "LEECHSEED"),
    ("Whimsicott protected itself!", "VOLATILE_START", "PROTECT"),
    ("Heracross is getting pumped!", "VOLATILE_START", "FOCUSENERGY"),
    ("Bulbasaur planted its roots!", "VOLATILE_START", "INGRAIN"),
    ("Jirachi levitated with electromagnetism!", "VOLATILE_START", "MAGNETRISE"),
    ("Charizard was prevented from healing!", "VOLATILE_START", "HEALBLOCK"),
    ("Gardevoir fell in love!", "VOLATILE_START", "ATTRACT"),
    ("Pikachu's perish count fell to 3!", "VOLATILE_START", "PERISH3"),
    ("Pikachu's perish count fell to 2!", "VOLATILE_START", "PERISH2"),
    ("Pikachu's perish count fell to 1!", "VOLATILE_START", "PERISH1"),
    ("Pikachu's perish count fell to 0!", "VOLATILE_START", "PERISH4"),

    # Hazards
    ("Pointed stones float in the air around the opposing Pikachu's team!",
     "HAZARD_SET", "stealth_rock"),
    ("Spikes were scattered all around the opposing Whimsicott's feet!",
     "HAZARD_SET", "spikes"),
    ("Poison spikes were scattered all around the opposing Garchomp's feet!",
     "HAZARD_SET", "toxic_spikes"),
    ("A sticky web has been laid out beneath the opposing Charizard's feet!",
     "HAZARD_SET", "sticky_web"),
    ("Charizard blew away the stealth rock!", "HAZARD_CLEAR", "all"),
    ("Pikachu blew away spikes!", "HAZARD_CLEAR", "all"),

    # Side conditions
    ("The tailwind blew from behind the opposing Whimsicott's team!",
     "SIDE_START", "tailwind"),
    ("Whimsicott's tailwind petered out!", "SIDE_END", "tailwind"),
    ("Light Screen made the opposing Cresselia's team stronger against special moves!",
     "SIDE_START", "light_screen"),
    ("Cresselia's Light Screen wore off!", "SIDE_END", "light_screen"),
    ("Reflect made the opposing Cresselia's team stronger against physical moves!",
     "SIDE_START", "reflect"),
    ("Cresselia's Reflect wore off!", "SIDE_END", "reflect"),
    ("Aurora Veil made the opposing Ninetales's team stronger against both physical and special moves!",
     "SIDE_START", "aurora_veil"),
    ("Ninetales's Aurora Veil wore off!", "SIDE_END", "aurora_veil"),
    ("The opposing Blissey's team became cloaked by a mystical veil!",
     "SIDE_START", "safeguard"),
    ("Blissey's team is no longer protected by Safeguard!",
     "SIDE_END", "safeguard"),
    ("The Lucky Chant shielded the opposing Blissey's team from critical hits!",
     "SIDE_START", "lucky_chant"),
]


def parse(text: str) -> tuple[str, str]:
    """Walk the overlay table in order; first match wins. Returns (type, effect).
    Returns ('OTHER', '') if no row matches."""
    for raw_re, ev_type, effect in PATTERNS:
        m = re.search(raw_re, text, re.IGNORECASE)
        if m is not None:
            return ev_type, effect
    return "OTHER", ""


def run_corpus() -> int:
    failures = 0
    for raw, want_type, want_effect in CASES:
        got_type, got_effect = parse(raw)
        ok = got_type == want_type and (want_effect == "" or got_effect == want_effect)
        mark = "OK " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  [{mark}] type={got_type:<14} eff={got_effect:<14} {raw!r}")
        if not ok:
            print(f"          expected type={want_type} effect={want_effect}")
    print()
    if failures:
        print(f"FAILED {failures}/{len(CASES)}")
    else:
        print(f"PASSED {len(CASES)}/{len(CASES)}")
    return failures


def run_inbox(repo_root: Path) -> int:
    """Re-parse raw_text from auto-captured inbox sidecars and report
    parse coverage. No assertions — just shows which texts got OTHER."""
    inbox = repo_root / "test_images" / "_inbox"
    if not inbox.is_dir():
        print(f"no inbox: {inbox}")
        return 1
    n_total = 0
    n_matched = 0
    others = []
    for jpath in sorted(glob.glob(str(inbox / "*.json"))):
        try:
            d = json.loads(Path(jpath).read_text())
        except Exception:
            continue
        raw = d.get("raw_text") or d.get("raw") or ""
        if not raw:
            continue
        n_total += 1
        ev_type, eff = parse(raw)
        if ev_type == "OTHER":
            others.append((Path(jpath).name, raw))
        else:
            n_matched += 1
    print(f"inbox: {n_matched}/{n_total} matched a Champions overlay pattern")
    if others:
        print(f"\nUnmatched (OTHER) — candidates for new patterns:")
        for name, raw in others[:50]:
            print(f"  {name}: {raw!r}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", action="store_true",
                    help="Re-parse test_images/_inbox/*.json instead of corpus")
    args = ap.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    if args.inbox:
        sys.exit(run_inbox(repo_root))
    sys.exit(1 if run_corpus() else 0)


if __name__ == "__main__":
    main()
