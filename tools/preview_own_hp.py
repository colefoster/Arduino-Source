#!/usr/bin/env python3
"""Print BattleHUDReader own_hp_current / own_hp_max for every doubles frame
in the action_menu + move_select manifests. Read-only.

Use to eyeball whether the tuned slot-1 HP boxes are reading correctly
before running auto_label_own_hp.py.

Run from repo root:
  python3 tools/preview_own_hp.py            # doubles only (default)
  python3 tools/preview_own_hp.py --all      # singles + doubles
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="include singles frames too (slot 1 will be garbage)")
    args = ap.parse_args()

    if not CLI.exists():
        print(f"build first: {CLI}", file=sys.stderr); sys.exit(1)

    print(f"{'screen/frame':<60}  {'mode':<8}  {'cur':<14}  {'max':<14}  species")
    print("-" * 130)

    for screen_dir in TARGETS:
        manifest = screen_dir / "manifest.json"
        if not manifest.exists():
            continue
        m = json.loads(manifest.read_text())

        for fname, labels in m.items():
            hud = labels.get("BattleHUDReader") or {}
            mode = hud.get("mode", "singles")
            if not args.all and mode != "doubles":
                continue
            img = screen_dir / fname
            if not img.exists():
                continue
            res = ocr(img)
            if not res:
                continue
            cur = res.get("own_hp_current", [-1, -1])
            mx  = res.get("own_hp_max",     [-1, -1])
            sp  = res.get("own_species",    ["", ""])
            label = f"{screen_dir.name}/{fname}"
            if len(label) > 58: label = "..." + label[-55:]
            print(f"{label:<60}  {mode:<8}  {str(cur):<14}  {str(mx):<14}  {sp}")


if __name__ == "__main__":
    main()
