#!/usr/bin/env python3
"""Auto-fill BattleHUDReader.own_species in manifests using OcrSuggest.

For each entry in test_images/{move_select,action_menu}/manifest.json:
  - Run SerialProgramsCommandLine --ocr-suggest BattleHUDReader <image>
  - Parse own_species[0..1] from the JSON output
  - Write into manifest's BattleHUDReader.own_species
  - Mode-aware: singles keeps slot 1 = "" (slot 1 box reads garbage for singles)

Run from repo root:
  python3 tools/auto_label_own_species.py [--dry-run]
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


def ocr_suggest(image_path: Path) -> dict | None:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not CLI.exists():
        print(f"build first: {CLI} not found", file=sys.stderr)
        sys.exit(1)

    grand_updated = 0
    grand_unchanged = 0
    grand_failed = 0

    for screen_dir in TARGETS:
        manifest_path = screen_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        updated = unchanged = failed = 0

        for fname, labels in manifest.items():
            hud = labels.get("BattleHUDReader")
            if not isinstance(hud, dict):
                continue
            mode = hud.get("mode", "singles")
            img = screen_dir / fname
            if not img.exists():
                failed += 1
                continue

            res = ocr_suggest(img)
            if not res or "own_species" not in res:
                failed += 1
                continue

            sp = res["own_species"]
            if not isinstance(sp, list) or len(sp) < 2:
                failed += 1
                continue

            new_pair = [sp[0] or "", sp[1] or ""]
            if mode == "singles":
                new_pair[1] = ""

            old_pair = list(hud.get("own_species", ["", ""]))
            while len(old_pair) < 2:
                old_pair.append("")

            if old_pair == new_pair:
                unchanged += 1
                continue

            hud["own_species"] = new_pair
            updated += 1
            print(f"  {screen_dir.name}/{fname}  {old_pair} -> {new_pair} ({mode})")

        if not args.dry_run and updated:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"{screen_dir.name}: updated={updated} unchanged={unchanged} failed={failed}")
        grand_updated += updated
        grand_unchanged += unchanged
        grand_failed += failed

    print(f"\nTOTAL: updated={grand_updated} unchanged={grand_unchanged} failed={grand_failed}")
    if args.dry_run:
        print("(dry-run — no files written)")


if __name__ == "__main__":
    main()
