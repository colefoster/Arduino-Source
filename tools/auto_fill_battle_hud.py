#!/usr/bin/env python3
"""Bulk-fill BattleHUDReader fields in test_images manifests.

For each entry with a BattleHUDReader block, runs OcrSuggest and fills
gaps per-slot — preserves anything already labeled, replaces -1 ints
and empty "" species with OCR values.

Mode-aware: singles only writes slot 0 (slot 1 stays "" / -1 because the
slot-1 boxes read garbage when there's no second mon).

Run from repo root:
  python3 tools/auto_fill_battle_hud.py             # apply
  python3 tools/auto_fill_battle_hud.py --dry-run   # preview only
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "build_mac" / "SerialProgramsCommandLine"
TARGETS = [
    REPO / "test_images" / "action_menu",
    REPO / "test_images" / "move_select",
]

STR_FIELDS = ("opponent_species", "own_species")
INT_FIELDS = ("opponent_hp_pct", "own_hp_current", "own_hp_max")


def ocr(image_path: Path) -> dict | None:
    try:
        r = subprocess.run(
            [str(CLI), "--ocr-suggest", "BattleHUDReader", str(image_path)],
            capture_output=True, text=True, timeout=30,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)
    except Exception as e:
        print(f"  ERROR {image_path.name}: {e}", file=sys.stderr)
    return None


def merge_str_pair(existing, suggested, *, write_slot1: bool):
    """Fill empty slots in existing str array of length 2 from suggested."""
    cur = list(existing) if isinstance(existing, list) else ["", ""]
    while len(cur) < 2:
        cur.append("")
    sug = list(suggested) if isinstance(suggested, list) else ["", ""]
    while len(sug) < 2:
        sug.append("")
    out = list(cur)
    if not out[0] and sug[0]:
        out[0] = sug[0]
    if write_slot1 and not out[1] and sug[1]:
        out[1] = sug[1]
    return out


def merge_int_pair(existing, suggested, *, write_slot1: bool):
    """Fill -1 slots in existing int array of length 2 from suggested (>= 0)."""
    cur = list(existing) if isinstance(existing, list) else [-1, -1]
    while len(cur) < 2:
        cur.append(-1)
    sug = list(suggested) if isinstance(suggested, list) else [-1, -1]
    while len(sug) < 2:
        sug.append(-1)
    out = list(cur)
    if (out[0] is None or out[0] < 0) and isinstance(sug[0], int) and sug[0] >= 0:
        out[0] = sug[0]
    if write_slot1 and (out[1] is None or out[1] < 0) and isinstance(sug[1], int) and sug[1] >= 0:
        out[1] = sug[1]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not CLI.exists():
        print(f"build first: {CLI}", file=sys.stderr); sys.exit(1)

    grand_changed = grand_unchanged = grand_failed = 0

    for screen_dir in TARGETS:
        manifest_path = screen_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        changed = unchanged = failed = 0

        for fname, labels in manifest.items():
            hud = labels.get("BattleHUDReader")
            if not isinstance(hud, dict):
                continue
            mode = hud.get("mode", "singles")
            doubles = (mode == "doubles")
            img = screen_dir / fname
            if not img.exists():
                failed += 1
                continue

            res = ocr(img)
            if not res:
                failed += 1
                continue

            new_hud = dict(hud)
            for f in STR_FIELDS:
                new_hud[f] = merge_str_pair(hud.get(f), res.get(f), write_slot1=doubles)
            for f in INT_FIELDS:
                new_hud[f] = merge_int_pair(hud.get(f), res.get(f), write_slot1=doubles)

            if new_hud == hud:
                unchanged += 1
                continue

            #  Concise diff line
            diffs = []
            for f in STR_FIELDS + INT_FIELDS:
                if new_hud[f] != hud.get(f):
                    diffs.append(f"{f}:{hud.get(f)}>>{new_hud[f]}")
            print(f"  {screen_dir.name}/{fname}  ({mode})  " + "  ".join(diffs))

            labels["BattleHUDReader"] = new_hud
            changed += 1

        if not args.dry_run and changed:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"{screen_dir.name}: changed={changed} unchanged={unchanged} failed={failed}")
        grand_changed += changed; grand_unchanged += unchanged; grand_failed += failed

    print(f"\nTOTAL: changed={grand_changed} unchanged={grand_unchanged} failed={grand_failed}")
    if args.dry_run:
        print("(dry-run — no files written)")


if __name__ == "__main__":
    main()
