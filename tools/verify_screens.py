#!/usr/bin/env python3
"""
Verify screen assignments by running C++ detectors on each image.

For each screen directory, runs the registered detectors on every image.
Flags images where no registered detector returns True — these are likely
misclassified by the migration script.

Usage:
    # On ColePC (where the C++ binary is):
    python tools/verify_screens.py [--fix]

    # --fix mode moves misclassified images to _inbox for re-sorting
"""

import json
import os
import subprocess
import sys
import argparse
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_IMAGES = REPO / "test_images"
BUILD_DIR = REPO / "build" / "Release"
EXE = BUILD_DIR / "SerialProgramsCommandLine.exe"

if not EXE.exists():
    EXE = BUILD_DIR / "SerialProgramsCommandLine"


def load_registry():
    reg_path = TEST_IMAGES / "test_registry.json"
    with open(reg_path) as f:
        return json.load(f)


def run_detector(detector_name, image_path):
    """Run a detector on an image via --manifest-test style check.
    Returns True if detector fires, False if not, None on error."""
    # We can't easily run individual detectors via CLI.
    # Instead, use OCR suggest with a known reader and check if it errors.
    # Actually, the simplest approach: use the regression output to identify failures.
    pass


def check_screen_with_regression(screen, detectors):
    """Run regression on a single screen and check for detector failures."""
    screen_dir = TEST_IMAGES / screen
    if not screen_dir.exists():
        return []

    images = sorted(f.name for f in screen_dir.glob("*.png") if not f.name.startswith("_"))
    if not images:
        return []

    # Run the C++ test for each detector on each image
    # We use --manifest-test but only for this screen
    # Actually, let's parse the regression output directly
    result = subprocess.run(
        [str(EXE), "--manifest-regression", str(TEST_IMAGES)],
        capture_output=True, text=True, timeout=300,
        cwd=str(BUILD_DIR),
    )

    # Parse failures: lines like "FAIL  DetectorName  ←  screen/file.png"
    failures = {}
    for line in result.stdout.split("\n"):
        if "FAIL" in line and "←" in line:
            parts = line.strip().split()
            # FAIL  DetectorName  ←  screen/file.png
            if len(parts) >= 4:
                det = parts[1]
                path = parts[3]
                if "/" in path:
                    scr, fname = path.split("/", 1)
                    if scr not in failures:
                        failures[scr] = {}
                    if fname not in failures[scr]:
                        failures[scr][fname] = set()
                    failures[scr][fname].add(det)

    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true", help="Move misclassified images to _inbox")
    args = parser.parse_args()

    registry = load_registry()

    print("Running full regression to identify misclassified images...")
    print(f"Using: {EXE}")
    print()

    result = subprocess.run(
        [str(EXE), "--manifest-regression", str(TEST_IMAGES)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=600, cwd=str(BUILD_DIR),
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")

    # Parse: for each screen, which detectors SHOULD fire True?
    # A "positive failure" = detector expected True but got False
    # This means the image is in a screen where the detector is registered,
    # but the detector doesn't recognize it → likely wrong screen

    positive_failures = {}  # screen -> [filenames where registered detector returned False]

    for line in result.stdout.split("\n"):
        line = line.strip()
        if not line.startswith("FAIL"):
            continue
        parts = line.split()
        if len(parts) < 4 or "←" not in line:
            continue
        det = parts[1]
        path = parts[3]
        if "/" not in path:
            continue
        screen, fname = path.split("/", 1)

        # Is this detector registered for this screen? (positive test failure)
        registered_screens = registry.get("detectors", {}).get(det, [])
        if screen in registered_screens:
            # Detector is registered for this screen but returned False → misclassified image
            if screen not in positive_failures:
                positive_failures[screen] = []
            positive_failures[screen].append((fname, det))

    if not positive_failures:
        print("No misclassified images found!")
        return

    print("Likely misclassified images (detector registered for screen but returned False):")
    print()

    total = 0
    for screen in sorted(positive_failures.keys()):
        files = positive_failures[screen]
        print(f"  {screen}/ ({len(files)} failures)")
        for fname, det in files:
            print(f"    {fname}  (expected True from {det})")
            total += 1

    print(f"\n  Total: {total} likely misclassified images")

    if args.fix:
        inbox = TEST_IMAGES / "_inbox"
        inbox.mkdir(exist_ok=True)
        moved = 0
        for screen, files in positive_failures.items():
            for fname, det in files:
                src = TEST_IMAGES / screen / fname
                if src.exists():
                    shutil.move(str(src), str(inbox / fname))
                    moved += 1
        print(f"\nMoved {moved} images to _inbox/")


if __name__ == "__main__":
    main()
