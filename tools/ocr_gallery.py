#!/usr/bin/env python3
"""
OCR Gallery — visual regression viewer for PokemonChampions OCR/detection tests.

Generates an HTML gallery page showing test images with their crop regions
extracted and upscaled, alongside expected ground-truth labels from filenames.
Opens in your default browser. Lets you visually spot trends (specific Pokemon
or moves that are hard to read, crop regions that are off, etc.).

Usage:
  python3 tools/ocr_gallery.py                                        (all readers)
  python3 tools/ocr_gallery.py CommandLineTests/PokemonChampions/MoveNameReader/
  python3 tools/ocr_gallery.py --reader MoveNameReader
  python3 tools/ocr_gallery.py --reader TeamSelectReader --results regression.json
"""

import base64
import io
import json
import os
import re
import sys
import webbrowser
import tempfile
from PIL import Image, ImageDraw


# ─── Paths ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_TEST_ROOT = os.path.join(REPO_ROOT, "CommandLineTests", "PokemonChampions")


# ─── Reader crop definitions ───────────────────────────────────────────────
#
# Maps reader name -> list of named crop boxes.
# Each box: {"name": str, "box": [x, y, w, h]}  (normalized 0-1 for 1920x1080)
#
# These match the ImageFloatBox definitions in the C++ inference code.

def _move_name_boxes():
    """MoveNameReader: 4 move text slots on move-select screen."""
    y_vals = [0.536, 0.655, 0.775, 0.894]
    return [{"name": f"move_{i}", "box": [0.776, y, 0.120, 0.031]} for i, y in enumerate(y_vals)]

def _species_reader_boxes():
    """SpeciesReader (BattleHUDReader): opponent species badge, singles mode."""
    return [{"name": "opp_species", "box": [0.833, 0.042, 0.130, 0.032]}]

def _opponent_hp_boxes():
    """OpponentHPReader: HP percentage display."""
    return [{"name": "opp_hp_pct", "box": [0.964, 0.057, 0.034, 0.031]}]

def _move_select_detector_boxes():
    """MoveSelectDetector: 4 pill indicator strips."""
    y_vals = [0.5116, 0.6338, 0.7542, 0.8746]
    return [{"name": f"pill_{i}", "box": [0.7292, y, 0.0101, 0.0139]} for i, y in enumerate(y_vals)]

def _team_select_reader_boxes():
    """TeamSelectReader: 6 species text boxes on team registration screen."""
    y_vals = [0.2194, 0.3303, 0.4412, 0.5521, 0.6630, 0.7741]
    return [{"name": f"slot_{i}", "box": [0.0807, y, 0.0849, 0.0343]} for i, y in enumerate(y_vals)]

def _team_summary_reader_boxes():
    """TeamSummaryReader: 6 species boxes on Moves & More grid."""
    col_x = [0.1391, 0.5552]
    row_y = [0.2769, 0.4750, 0.6731]
    boxes = []
    for slot in range(6):
        col = slot % 2
        row = slot // 2
        boxes.append({
            "name": f"species_{slot}",
            "box": [col_x[col], row_y[row], 0.087, 0.038]
        })
    return boxes

def _team_preview_reader_boxes():
    """TeamPreviewReader: 6 own species + 6 opp sprite boxes."""
    boxes = []
    for i in range(6):
        t = i / 5.0
        x = 0.0760 + t * (0.0724 - 0.0760)
        y = 0.1565 + t * (0.7389 - 0.1565)
        boxes.append({"name": f"own_{i}", "box": [x, y, 0.0969, 0.0389]})
    opp_step = (0.7407 - 0.1509) / 5.0
    for i in range(6):
        y = 0.1509 + i * opp_step
        boxes.append({"name": f"opp_{i}", "box": [0.8380, y, 0.0583, 0.0917]})
    return boxes

def _battle_log_reader_boxes():
    """BattleLogReader: text bar at bottom center."""
    return [{"name": "text_bar", "box": [0.104, 0.741, 0.729, 0.046]}]

def _bool_detector_boxes():
    """Generic bool detector — no specific crop, show full image."""
    return []


READER_CROPS = {
    "MoveNameReader":           _move_name_boxes,
    "SpeciesReader":            _species_reader_boxes,
    "OpponentHPReader":         _opponent_hp_boxes,
    "MoveSelectDetector":       _move_select_detector_boxes,
    "MoveSelectCursorSlot":     _move_select_detector_boxes,
    "TeamSelectReader":         _team_select_reader_boxes,
    "TeamSummaryReader":        _team_summary_reader_boxes,
    "TeamPreviewReader":        _team_preview_reader_boxes,
    "BattleLogReader":          _battle_log_reader_boxes,
    "TeamSelectDetector":       _bool_detector_boxes,
    "MovesMoreDetector":        _bool_detector_boxes,
    "TeamPreviewDetector":      _bool_detector_boxes,
    "ActionMenuDetector":       lambda: [
        {"name": "fight_glow", "box": [0.9062, 0.5694, 0.0260, 0.0185]},
        {"name": "pokemon_glow", "box": [0.9062, 0.7981, 0.0260, 0.0213]},
    ],
    "ResultScreenDetector":     _bool_detector_boxes,
    "PreparingForBattleDetector": _bool_detector_boxes,
    "PostMatchScreenDetector":  _bool_detector_boxes,
    "MainMenuDetector":         _bool_detector_boxes,
}


# ─── Filename parsing ──────────────────────────────────────────────────────

def parse_ground_truth(filename, reader_name):
    """Extract expected labels from test filename."""
    base = os.path.splitext(filename)[0]
    words = base.split("_")

    if reader_name == "OCRDump":
        return {"type": "void", "values": [], "raw": base}

    if base.endswith("_True"):
        return {"type": "bool", "values": [True], "raw": base}
    if base.endswith("_False"):
        return {"type": "bool", "values": [False], "raw": base}

    if reader_name in ("OpponentHPReader", "MoveSelectCursorSlot"):
        try:
            val = int(words[-1])
            return {"type": "int", "values": [val], "raw": base}
        except ValueError:
            pass

    if reader_name == "MoveNameReader":
        slugs = words[-4:] if len(words) >= 4 else words
        slugs = ["" if s == "NONE" else s for s in slugs]
        return {"type": "words", "values": slugs, "raw": base}

    if reader_name in ("TeamSelectReader", "TeamSummaryReader", "TeamPreviewReader"):
        slugs = words[-6:] if len(words) >= 6 else words
        slugs = ["" if s == "NONE" else s for s in slugs]
        return {"type": "words", "values": slugs, "raw": base}

    if reader_name == "SpeciesReader":
        return {"type": "words", "values": [words[-1]], "raw": base}

    if reader_name == "BattleLogReader":
        type_words = []
        for w in words:
            if w and w[0].isupper():
                type_words.append(w)
            elif type_words:
                break
        type_name = "_".join(type_words) if type_words else base
        return {"type": "words", "values": [type_name], "raw": base}

    return {"type": "words", "values": words, "raw": base}


# ─── Data loading ──────────────────────────────────────────────────────────

def discover_readers(test_root):
    readers = []
    if not os.path.isdir(test_root):
        return readers
    for name in sorted(os.listdir(test_root)):
        path = os.path.join(test_root, name)
        if os.path.isdir(path) and not name.startswith("_"):
            readers.append(name)
    return readers


def load_reader_images(test_root, reader_name):
    reader_dir = os.path.join(test_root, reader_name)
    if not os.path.isdir(reader_dir):
        return []
    entries = []
    for root, dirs, files in os.walk(reader_dir):
        dirs[:] = [d for d in dirs if not d.startswith("_")]
        for f in sorted(files):
            if f.startswith("_"):
                continue
            if not f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                continue
            path = os.path.join(root, f)
            gt = parse_ground_truth(f, reader_name)
            entries.append({"path": path, "filename": f, "ground_truth": gt})
    return entries


def extract_crops(img, crop_defs):
    w, h = img.size
    crops = []
    for cd in crop_defs:
        box = cd["box"]
        x0 = max(0, min(w, int(box[0] * w)))
        y0 = max(0, min(h, int(box[1] * h)))
        x1 = max(0, min(w, x0 + int(box[2] * w)))
        y1 = max(0, min(h, y0 + int(box[3] * h)))
        if x1 <= x0 or y1 <= y0:
            crops.append(Image.new("RGB", (1, 1), (64, 64, 64)))
        else:
            crops.append(img.crop((x0, y0, x1, y1)))
    return crops


def img_to_data_uri(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def load_regression_results(results_path):
    if not results_path or not os.path.exists(results_path):
        return {}
    with open(results_path) as f:
        data = json.load(f)
    return {entry.get("file", ""): entry for entry in data}


def run_regression_on_colepc(test_path="CommandLineTests\\PokemonChampions"):
    """SSH to ColePC, run regression, parse text output into results dict."""
    import subprocess

    print("  Running regression on ColePC...", flush=True)
    cmd = (
        f'ssh colepc "cd C:\\Dev\\pokemon-champions && '
        f'build\\Release\\SerialProgramsCommandLine.exe '
        f'--regression {test_path} 2>&1"'
    )
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        print("  ERROR: regression timed out", flush=True)
        return {}

    # Parse output: track current reader, collect pass/fail per file
    results = {}
    current_reader = None

    for line in output.split("\n"):
        # "Testing ReaderName:"
        if line.startswith("Testing ") and line.endswith(":"):
            current_reader = line[8:-1].strip()
            continue

        # "FAIL  ReaderName  ←  filename.png"
        if line.strip().startswith("FAIL"):
            parts = line.strip().split("←")
            if len(parts) == 2:
                fname = parts[1].strip()
                results[fname] = {"passed": False}
            continue

        # Track files that were tested (lines ending in .png)
        stripped = line.strip()
        if stripped.endswith(".png") or stripped.endswith(".jpg"):
            fname = os.path.basename(stripped)
            # Will be overwritten by FAIL if it fails; otherwise stays as passed
            if fname not in results:
                results[fname] = {"passed": True}

    # Files in results without a FAIL entry are passes
    # (already handled above)

    passed = sum(1 for r in results.values() if r["passed"])
    failed = sum(1 for r in results.values() if not r["passed"])
    print(f"  Parsed {passed} passed, {failed} failed from ColePC output", flush=True)
    return results


# ─── HTML generation ───────────────────────────────────────────────────────

CROP_SCALE = 3

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #0d1117; color: #c9d1d9; font-family: 'SF Mono', 'Menlo', monospace;
    font-size: 13px; padding: 16px;
}
h1 { color: #58a6ff; margin-bottom: 8px; font-size: 20px; }
.nav { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.nav a {
    display: inline-block; padding: 4px 10px; background: #21262d; color: #8b949e;
    text-decoration: none; border-radius: 6px; font-size: 12px; border: 1px solid #30363d;
}
.nav a:hover { background: #30363d; color: #c9d1d9; }
.nav a.active { background: #1f6feb; color: #fff; border-color: #1f6feb; }
.stats { color: #8b949e; margin-bottom: 16px; font-size: 12px; }
.card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 12px; margin-bottom: 10px;
}
.card.fail { border-color: #f85149; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-filename { color: #58a6ff; font-weight: bold; font-size: 12px; word-break: break-all; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
.badge.pass { background: #238636; color: #fff; }
.badge.fail { background: #da3633; color: #fff; }
.badge.true { background: #1f6feb; color: #fff; }
.badge.false { background: #6e7681; color: #fff; }
.crops { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0; }
.crop-cell { text-align: center; }
.crop-cell img {
    border: 2px solid #30363d; border-radius: 4px; image-rendering: pixelated;
    display: block; margin-bottom: 4px;
}
.crop-name { color: #8b949e; font-size: 10px; }
.crop-label { color: #f0c040; font-size: 11px; font-weight: bold; }
.expected { color: #f0c040; font-size: 12px; margin-top: 4px; }
.actual { font-size: 12px; margin-top: 2px; }
.actual.pass { color: #3fb950; }
.actual.fail { color: #f85149; }
.thumb { margin: 8px 0; }
.thumb img { max-width: 480px; height: auto; border-radius: 4px; border: 1px solid #30363d; }
.section { margin-top: 24px; }
.section h2 { color: #c9d1d9; font-size: 16px; margin-bottom: 8px; border-bottom: 1px solid #21262d; padding-bottom: 4px; }
"""


def build_card_html(entry, crop_defs, reader_name, results):
    gt = entry["ground_truth"]
    result = results.get(entry["filename"])
    passed = result.get("passed") if result else None

    card_class = "card fail" if passed is False else "card"

    html = f'<div class="{card_class}">\n'
    html += '<div class="card-header">\n'
    html += f'  <span class="card-filename">{entry["filename"]}</span>\n'

    if passed is True:
        html += '  <span class="badge pass">PASS</span>\n'
    elif passed is False:
        html += '  <span class="badge fail">FAIL</span>\n'
    elif gt["type"] == "bool":
        val = gt["values"][0]
        cls = "true" if val else "false"
        html += f'  <span class="badge {cls}">expect: {val}</span>\n'

    html += '</div>\n'

    # Load image
    try:
        img = Image.open(entry["path"]).convert("RGB")
    except Exception as e:
        html += f'<div style="color:#f85149">Error loading: {e}</div>\n'
        html += '</div>\n'
        return html

    # Crops
    if crop_defs:
        crops = extract_crops(img, crop_defs)
        html += '<div class="crops">\n'
        for i, (crop_img, cd) in enumerate(zip(crops, crop_defs)):
            cw, ch = crop_img.size
            scale = CROP_SCALE
            while cw * scale > 400 or ch * scale > 200:
                scale -= 0.5
                if scale < 1:
                    scale = 1
                    break
            disp_w = max(1, int(cw * scale))
            disp_h = max(1, int(ch * scale))
            upscaled = crop_img.resize((disp_w, disp_h), Image.NEAREST)
            uri = img_to_data_uri(upscaled)

            html += '<div class="crop-cell">\n'
            html += f'  <img src="{uri}" width="{disp_w}" height="{disp_h}" title="{cd["name"]}">\n'
            html += f'  <div class="crop-name">{cd["name"]}</div>\n'

            gt_vals = gt.get("values", [])
            if gt["type"] == "words" and i < len(gt_vals):
                val = gt_vals[i] if gt_vals[i] else "(none)"
                html += f'  <div class="crop-label">{val}</div>\n'

            html += '</div>\n'
        html += '</div>\n'

    # Thumbnail (always show for context)
    if True:
        scale = min(480 / img.width, 270 / img.height, 1.0)
        tw = max(1, int(img.width * scale))
        th = max(1, int(img.height * scale))
        thumb = img.resize((tw, th), Image.BILINEAR)
        uri = img_to_data_uri(thumb, "JPEG")
        html += f'<div class="thumb"><img src="{uri}" width="{tw}" height="{th}"></div>\n'

    # Ground truth
    if gt["type"] == "int":
        html += f'<div class="expected">expected: {gt["values"][0]}</div>\n'
    elif gt["type"] == "words" and gt["values"]:
        labels = " | ".join(v if v else "(none)" for v in gt["values"])
        html += f'<div class="expected">expected: {labels}</div>\n'

    # Actual results
    if result and result.get("actual"):
        actual = " | ".join(str(v) if v else "(none)" for v in result["actual"])
        cls = "pass" if passed else "fail"
        html += f'<div class="actual {cls}">actual: {actual}</div>\n'

    html += '</div>\n'
    return html


def build_html(test_root, reader_filter=None, results_path=None):
    readers = discover_readers(test_root)
    if not readers:
        print(f"No reader directories found in {test_root}")
        sys.exit(1)

    results = load_regression_results(results_path)

    if reader_filter:
        matches = [r for r in readers if reader_filter.lower() in r.lower()]
        if matches:
            readers = matches
        else:
            print(f"Reader '{reader_filter}' not found. Available: {', '.join(readers)}")
            sys.exit(1)

    html = '<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n'
    html += '<title>OCR Gallery</title>\n'
    html += f'<style>{CSS}</style>\n'
    html += '</head><body>\n'
    html += '<h1>OCR Gallery — Pokemon Champions</h1>\n'

    # Nav bar
    html += '<div class="nav">\n'
    for r in readers:
        html += f'  <a href="#{r}">{r}</a>\n'
    html += '</div>\n'

    # Total stats
    total_images = 0
    for r in readers:
        total_images += len(load_reader_images(test_root, r))
    html += f'<div class="stats">{len(readers)} readers, {total_images} test images</div>\n'

    # Reader sections
    for reader_name in readers:
        entries = load_reader_images(test_root, reader_name)
        crop_fn = READER_CROPS.get(reader_name, _bool_detector_boxes)
        crop_defs = crop_fn()

        html += f'<div class="section" id="{reader_name}">\n'
        html += f'<h2>{reader_name} — {len(entries)} images, {len(crop_defs)} crop regions</h2>\n'

        if not entries:
            html += '<div style="color:#8b949e;padding:16px">No test images.</div>\n'
        else:
            print(f"  {reader_name}: {len(entries)} images...", flush=True)
            for entry in entries:
                html += build_card_html(entry, crop_defs, reader_name, results)

        html += '</div>\n'

    html += '</body></html>\n'
    return html


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)

    test_root = DEFAULT_TEST_ROOT
    reader_name = None
    results_path = None
    run_regression = False

    i = 0
    positional = []
    while i < len(args):
        if args[i] == "--reader" and i + 1 < len(args):
            reader_name = args[i + 1]
            i += 2
        elif args[i] == "--results" and i + 1 < len(args):
            results_path = args[i + 1]
            i += 2
        elif args[i] == "--run":
            run_regression = True
            i += 1
        else:
            positional.append(args[i])
            i += 1

    if positional:
        path = positional[0]
        if os.path.isdir(path):
            parent = os.path.dirname(os.path.normpath(path))
            dirname = os.path.basename(os.path.normpath(path))
            if dirname in READER_CROPS or dirname == "OCRDump":
                test_root = parent
                reader_name = dirname
            else:
                test_root = path

    if run_regression:
        regression_results = run_regression_on_colepc()
        # Save for reuse
        results_cache = os.path.join(tempfile.gettempdir(), "ocr_regression_results.json")
        with open(results_cache, "w") as f:
            json.dump([{"file": k, **v} for k, v in regression_results.items()], f)
        results_path = results_cache
        print(f"  Results cached to {results_cache}", flush=True)

    print("Generating OCR gallery...", flush=True)
    html = build_html(test_root, reader_filter=reader_name, results_path=results_path)

    out_path = os.path.join(tempfile.gettempdir(), "ocr_gallery.html")
    with open(out_path, "w") as f:
        f.write(html)

    print(f"  Written to {out_path}")
    print(f"  Opening in browser...")
    webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
