#!/usr/bin/env python3
"""
Generate test_registry.json from screens.yaml for the C++ test runner.

The C++ side only needs nlohmann/json (already in 3rdParty).
This script bridges YAML (human-authored) to JSON (machine-consumed).

Usage:
    python3 tools/generate_test_registry.py

Outputs:
    test_images/test_registry.json
"""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip3 install pyyaml")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENS_YAML = PROJECT_ROOT / "test_images" / "screens.yaml"
REGISTRY_JSON = PROJECT_ROOT / "test_images" / "test_registry.json"


def main():
    if not SCREENS_YAML.exists():
        print(f"Error: {SCREENS_YAML} not found")
        sys.exit(1)

    with open(SCREENS_YAML) as f:
        config = yaml.safe_load(f)

    screens = config.get("screens", {})
    overlays = config.get("overlays", {})

    # Build detector -> [screen_dirs] mapping
    detectors = {}
    for screen_name, screen_def in screens.items():
        for det in screen_def.get("detectors", []):
            if det not in detectors:
                detectors[det] = []
            detectors[det].append(screen_name)

    # Build reader -> {screen_dir: field_schema} mapping
    readers = {}
    for screen_name, screen_def in screens.items():
        for reader_name, reader_def in screen_def.get("readers", {}).items():
            if reader_name not in readers:
                readers[reader_name] = {"screens": {}}
            readers[reader_name]["screens"][screen_name] = reader_def.get("fields", {})

    # Add overlay readers
    for overlay_name, overlay_def in overlays.items():
        overlay_dir = f"_overlays/{overlay_name}"
        for reader_name, reader_def in overlay_def.get("readers", {}).items():
            if reader_name not in readers:
                readers[reader_name] = {"screens": {}}
            readers[reader_name]["screens"][overlay_dir] = reader_def.get("fields", {})

    # Build list of all screen directories (for negative testing)
    all_screen_dirs = list(screens.keys())

    registry = {
        "all_screen_dirs": all_screen_dirs,
        "overlay_dirs": [f"_overlays/{name}" for name in overlays.keys()],
        "detectors": detectors,
        "readers": readers,
    }

    REGISTRY_JSON.write_text(json.dumps(registry, indent=2) + "\n")
    print(f"Generated {REGISTRY_JSON}")
    print(f"  {len(detectors)} detectors, {len(readers)} readers, {len(all_screen_dirs)} screens")


if __name__ == "__main__":
    main()
