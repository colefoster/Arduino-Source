#!/usr/bin/env python3
"""
OCR Gallery Server — DEPRECATED.

This tool has been replaced by:
  - Dashboard at champions.colefoster.ca (Gallery, Labeler, Inspector, Recognition, Templates)
  - tools/retest.py (CLI for cmake build + regression)

The dashboard is the canonical UI. Use retest.py for local C++ build loops.
This file is kept temporarily for reference but will be removed.
"""

import sys
print("=" * 60)
print("DEPRECATED: Use the dashboard at champions.colefoster.ca")
print("  Gallery, Labeler, Inspector, Recognition, Templates")
print()
print("For C++ retest: python3 tools/retest.py [reader]")
print("=" * 60)
print()
print("Starting anyway (will be removed in a future commit)...")
print()

import base64, io, json, os, re, subprocess, sys, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import Image

# ─── Paths ──────────────────────────────────────────────────────────────────

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(REPO, "build_mac")
TEST_ROOT = os.path.join(REPO, "CommandLineTests", "PokemonChampions")
CPP_FILE = os.path.join(REPO, "SerialPrograms", "Source", "PokemonChampions",
                        "Inference", "PokemonChampions_BattleHUDReader.cpp")


# ─── Crop definitions (must match C++ ImageFloatBox values) ───────────────

def _move_name_boxes():
    y_vals = [0.536, 0.655, 0.775, 0.894]
    return [{"name": f"move_{i}", "box": [0.776, y, 0.120, 0.031]} for i, y in enumerate(y_vals)]

def _species_reader_boxes():
    return [{"name": "opp_species", "box": [0.830, 0.052, 0.087, 0.032]}]

def _opponent_hp_boxes():
    return [{"name": "opp_hp_pct", "box": [0.8963, 0.1098, 0.0498, 0.0524]}]

def _opponent_hp_doubles_boxes():
    return read_boxes_from_cpp("OpponentHPReader_Doubles") or [
        {"name": "s0_hp_pct (left)", "box": [0.694, 0.116, 0.041, 0.038]},
        {"name": "s1_hp_pct (right)", "box": [0.9035, 0.1130, 0.040, 0.0426]},
    ]

def _species_reader_doubles_boxes():
    return [
        {"name": "opp0_species", "box": [0.6172, 0.0454, 0.1219, 0.0417]},
        {"name": "opp1_species", "box": [0.8286, 0.0481, 0.1151, 0.0417]},
    ]

def _move_select_detector_boxes():
    y_vals = [0.5116, 0.6338, 0.7542, 0.8746]
    return [{"name": f"pill_{i}", "box": [0.7292, y, 0.0101, 0.0139]} for i, y in enumerate(y_vals)]

def _team_select_reader_boxes():
    y_vals = [0.2194, 0.3303, 0.4412, 0.5521, 0.6630, 0.7741]
    return [{"name": f"slot_{i}", "box": [0.0807, y, 0.0849, 0.0343]} for i, y in enumerate(y_vals)]

def _team_summary_reader_boxes():
    col_x = [0.1391, 0.5552]
    row_y = [0.2769, 0.4750, 0.6731]
    boxes = []
    for slot in range(6):
        boxes.append({"name": f"species_{slot}",
                      "box": [col_x[slot % 2], row_y[slot // 2], 0.087, 0.038]})
    return boxes

def _team_preview_reader_boxes():
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
    return [{"name": "text_bar", "box": [0.104, 0.741, 0.729, 0.046]}]

def _bool_detector_boxes():
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
    "TeamPreviewDetector":      lambda: [{"name": "title_text", "box": [0.3604, 0.2037, 0.1375, 0.0389]}],
    "ActionMenuDetector":       lambda: [
        {"name": "fight_glow", "box": [0.9219, 0.5787, 0.0182, 0.0213]},
        {"name": "pokemon_glow", "box": [0.8932, 0.7907, 0.0182, 0.0213]},
    ],
    "ResultScreenDetector":     _bool_detector_boxes,
    "PreparingForBattleDetector": lambda: [
        {"name": "slot_0", "box": [0.2875, 0.1475, 0.0122, 0.0076]},
        {"name": "slot_1", "box": [0.2837, 0.2656, 0.0155, 0.0080]},
        {"name": "slot_2", "box": [0.2806, 0.3827, 0.0191, 0.0073]},
        {"name": "slot_3", "box": [0.2806, 0.4978, 0.0192, 0.0088]},
        {"name": "slot_4", "box": [0.2839, 0.6151, 0.0138, 0.0075]},
        {"name": "slot_5", "box": [0.2840, 0.7333, 0.0146, 0.0054]},
    ],
    "PostMatchScreenDetector":  _bool_detector_boxes,
    "MainMenuDetector":         _bool_detector_boxes,
    "OpponentHPReader_Doubles": _opponent_hp_doubles_boxes,
    "SpeciesReader_Doubles":    _species_reader_doubles_boxes,
}


# ─── C++ source interaction ──────────────────────────────────────────────

def read_boxes_from_cpp(reader):
    """Read crop box coordinates from C++ source for a reader."""
    try:
        with open(CPP_FILE, "r") as f:
            src = f.read()
    except FileNotFoundError:
        return None

    if reader == "OpponentHPReader_Doubles":
        fn_match = re.search(r'void BattleHUDReader::init_doubles_boxes\(\)\{(.*?)\n\}', src, re.DOTALL)
        if fn_match:
            fn_body = fn_match.group(1)
            boxes = []
            for idx, name in [(0, "s0_hp_pct (left)"), (1, "s1_hp_pct (right)")]:
                m = re.search(rf'm_opponent_hp_boxes\[{idx}\]\s*=\s*ImageFloatBox\(([\d., ]+)\)', fn_body)
                if m:
                    vals = [float(x.strip()) for x in m.group(1).split(",")]
                    boxes.append({"name": name, "box": vals})
            if boxes:
                return boxes
    return None


def patch_cpp_boxes(reader, boxes):
    """Patch C++ source with new box coordinates. boxes = {name: [x,y,w,h]}"""
    with open(CPP_FILE, "r") as f:
        src = f.read()

    if reader == "OpponentHPReader_Doubles":
        fn_match = re.search(r'(void BattleHUDReader::init_doubles_boxes\(\)\{.*?\n\})', src, re.DOTALL)
        if not fn_match:
            return False
        fn_body = fn_match.group(0)
        new_body = fn_body
        slot_map = {"s0_hp_pct (left)": 0, "s1_hp_pct (right)": 1}
        for name, slot_idx in slot_map.items():
            if name in boxes:
                b = boxes[name]
                new_body = re.sub(
                    rf'(m_opponent_hp_boxes\[{slot_idx}\]\s*=\s*ImageFloatBox\()[\d., ]+(\);)',
                    lambda m: f'{m.group(1)}{b[0]}, {b[1]}, {b[2]}, {b[3]}{m.group(2)}',
                    new_body
                )
        src = src.replace(fn_body, new_body)

    with open(CPP_FILE, "w") as f:
        f.write(src)
    return True


def patch_cpp_color_filter(min_brightness, max_spread):
    """Patch the white-only filter thresholds in raw_ocr_numbers."""
    with open(CPP_FILE, "r") as f:
        src = f.read()
    src = re.sub(
        r'(bool is_white = \(mn > )\d+(\) && \(mx - mn < )\d+(\);)',
        lambda m: f'{m.group(1)}{min_brightness}{m.group(2)}{max_spread}{m.group(3)}',
        src
    )
    with open(CPP_FILE, "w") as f:
        f.write(src)


# ─── Data loading ─────────────────────────────────────────────────────────

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
            if f.startswith("_") or not f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                continue
            path = os.path.join(root, f)
            gt = parse_ground_truth(f, reader_name)
            entries.append({"path": path, "filename": f, "ground_truth": gt})
    return entries


def parse_ground_truth(filename, reader_name):
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
            return {"type": "int", "values": [int(words[-1])], "raw": base}
        except ValueError:
            pass

    if reader_name == "OpponentHPReader_Doubles":
        try:
            hp = int(words[-1])
            slot_str = words[-2]
            slot = int(slot_str[1]) if slot_str in ("s0", "s1") else 0
            values = [None, None]
            values[slot] = hp
            return {"type": "slot_int", "slot": slot, "values": values, "raw": base}
        except (ValueError, IndexError):
            pass

    if reader_name == "SpeciesReader_Doubles":
        slot_str = words[-2] if len(words) >= 2 else ""
        species = words[-1]
        slot = int(slot_str[1]) if slot_str in ("s0", "s1") else 0
        values = [None, None]
        values[slot] = species
        return {"type": "slot_words", "slot": slot, "values": values, "raw": base}

    if reader_name == "MoveNameReader":
        slugs = words[-4:] if len(words) >= 4 else words
        return {"type": "words", "values": ["" if s == "NONE" else s for s in slugs], "raw": base}

    if reader_name in ("TeamSelectReader", "TeamSummaryReader", "TeamPreviewReader"):
        slugs = words[-6:] if len(words) >= 6 else words
        return {"type": "words", "values": ["" if s == "NONE" else s for s in slugs], "raw": base}

    if reader_name == "SpeciesReader":
        return {"type": "words", "values": [words[-1]], "raw": base}

    if reader_name == "BattleLogReader":
        type_words = []
        for w in words:
            if w and w[0].isupper():
                type_words.append(w)
            elif type_words:
                break
        return {"type": "words", "values": ["_".join(type_words) if type_words else base], "raw": base}

    return {"type": "words", "values": words, "raw": base}


# ─── Regression runner ────────────────────────────────────────────────────

def run_regression(reader=None):
    """Build and run regression. Returns {filename: {passed, actual, raw_ocr, ...}}"""
    build = subprocess.run(
        ["cmake", "--build", BUILD_DIR, f"-j{os.cpu_count() or 4}"],
        capture_output=True, text=True, timeout=180, cwd=REPO
    )
    if build.returncode != 0:
        return {"_error": f"Build failed: {build.stderr[-300:]}"}

    test_path = os.path.join("..", "CommandLineTests", "PokemonChampions")
    if reader:
        test_path = os.path.join(test_path, reader)

    exe = os.path.join(BUILD_DIR, "SerialProgramsCommandLine")
    result = subprocess.run(
        [exe, "--regression", test_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=300, cwd=BUILD_DIR
    )

    results = {}
    current_file = None
    for line in result.stdout.split("\n"):
        stripped = line.strip()
        if (stripped.endswith(".png") or stripped.endswith(".jpg")) and not stripped.startswith("Parse"):
            current_file = os.path.basename(stripped)
            results[current_file] = {"passed": True, "segments": []}
        m = re.search(r'result is (.+?) but should be (.+?)\.', stripped)
        if m and current_file:
            results[current_file]["passed"] = False
            results[current_file]["actual"] = m.group(1)
            results[current_file]["expected"] = m.group(2)
        m = re.match(r'OK: actual=(.+)', stripped)
        if m and current_file:
            results[current_file]["actual"] = m.group(1)
        # Legacy OCR raw text
        m = re.search(r"raw='(.*?)(?:'|$)", stripped)
        if m and current_file:
            results[current_file]["raw_ocr"] = m.group(1)
        # Template match: per-segment scores
        m = re.search(r'segment\[(\d+)\]\s+(\d+)x(\d+)\s+scores:\s+(.+)', stripped)
        if m and current_file:
            seg_idx = int(m.group(1))
            seg_w, seg_h = int(m.group(2)), int(m.group(3))
            scores_str = m.group(4)
            scores = {}
            for pair in scores_str.split():
                k, v = pair.split(":")
                scores[k] = float(v)
            while len(results[current_file]["segments"]) <= seg_idx:
                results[current_file]["segments"].append(None)
            results[current_file]["segments"][seg_idx] = {
                "w": seg_w, "h": seg_h, "scores": scores
            }
        # Template match: final result
        m = re.search(r'template: digits=\[([^\]]+)\]\s*->\s*(\d+)', stripped)
        if m and current_file:
            results[current_file]["digits"] = m.group(1).split(",")
            results[current_file]["actual"] = m.group(2)
        # Template match: segment no match
        m = re.search(r'template: segment (\d+) no match', stripped)
        if m and current_file:
            results[current_file].setdefault("no_match_segments", []).append(int(m.group(1)))
        # Template match: no digits found
        if 'template: no digits found' in stripped and current_file:
            results[current_file]["no_digits"] = True

    return results


# ─── Server state ─────────────────────────────────────────────────────────

RESULTS = {}  # filename -> {passed, actual, ...}
READERS = []  # list of reader names to show


# ─── HTTP Handler ─────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._serve_html()
        elif parsed.path == "/templates":
            self._serve_template_manager()
        elif parsed.path == "/labeler":
            self._serve_labeler()
        elif parsed.path == "/inspector":
            self._serve_inspector()
        elif parsed.path.startswith("/img/"):
            self._serve_image(parsed.path[5:])
        elif parsed.path.startswith("/template/"):
            self._serve_template(parsed.path[10:])
        elif parsed.path == "/api/retest":
            self._handle_retest(parse_qs(parsed.query))
        elif parsed.path == "/api/readers":
            self._json_response([{
                "name": r,
                "count": len(load_reader_images(TEST_ROOT, r)),
                "crops": READER_CROPS.get(r, _bool_detector_boxes)(),
            } for r in READERS])
        elif parsed.path == "/api/template/delete":
            digit = parse_qs(parsed.query).get("digit", [None])[0]
            self._handle_template_delete(digit)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if parsed.path == "/api/template/save":
            self._handle_template_save(body)
        elif parsed.path == "/api/label/save":
            self._handle_label_save(body)
        elif parsed.path == "/api/label/skip":
            self._handle_label_skip(body)
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _serve_image(self, path):
        full = os.path.join(TEST_ROOT, path)
        if not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(full)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext.lstrip("."), "image/png")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        with open(full, "rb") as f:
            self.wfile.write(f.read())

    def _serve_template(self, name):
        """Serve a digit template PNG from Packages/Resources/PokemonChampions/DigitTemplates/"""
        tmpl_dir = os.path.join(REPO, "Packages", "Resources", "PokemonChampions", "DigitTemplates")
        full = os.path.join(tmpl_dir, name)
        if not os.path.isfile(full) or not name.endswith(".png"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(full, "rb") as f:
            self.wfile.write(f.read())

    def _handle_template_save(self, body):
        """Save PNG data as a digit template. Body is JSON: {digit: "0", png_base64: "..."}"""
        try:
            data = json.loads(body)
            digit = str(data["digit"])
            if digit not in "0123456789" or len(digit) != 1:
                self._json_response({"error": "invalid digit"})
                return
            png_data = base64.b64decode(data["png_base64"])
            tmpl_dir = os.path.join(REPO, "Packages", "Resources", "PokemonChampions", "DigitTemplates")
            os.makedirs(tmpl_dir, exist_ok=True)
            path = os.path.join(tmpl_dir, f"{digit}.png")
            with open(path, "wb") as f:
                f.write(png_data)
            print(f"[template] Saved {digit}.png ({len(png_data)} bytes)", flush=True)
            self._json_response({"ok": True, "digit": digit})
        except Exception as e:
            print(f"[template] Save error: {e}", flush=True)
            self._json_response({"error": str(e)})

    def _handle_template_delete(self, digit):
        """Delete a digit template."""
        if not digit or digit not in "0123456789":
            self._json_response({"error": "invalid digit"})
            return
        tmpl_dir = os.path.join(REPO, "Packages", "Resources", "PokemonChampions", "DigitTemplates")
        path = os.path.join(tmpl_dir, f"{digit}.png")
        if os.path.isfile(path):
            os.remove(path)
            print(f"[template] Deleted {digit}.png", flush=True)
        self._json_response({"ok": True, "digit": digit})

    def _handle_label_skip(self, body):
        """Hide a frame by prefixing its filename with _ (test runner ignores _ files)."""
        try:
            data = json.loads(body)
            source = data["source"]  # e.g. "OpponentHPReader_Doubles/foo.png"
            src_path = os.path.join(TEST_ROOT, source)
            if not os.path.isfile(src_path):
                self._json_response({"error": f"Not found: {source}"})
                return
            dirname = os.path.dirname(src_path)
            basename = os.path.basename(src_path)
            if not basename.startswith("_"):
                dest = os.path.join(dirname, "_" + basename)
                os.rename(src_path, dest)
                print(f"[labeler] Skipped: {source} -> _{basename}", flush=True)
            self._json_response({"ok": True})
        except Exception as e:
            print(f"[labeler] Skip error: {e}", flush=True)
            self._json_response({"error": str(e)})

    def _serve_labeler(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(build_labeler_page().encode())

    def _serve_inspector(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(build_inspector_page().encode())

    def _handle_label_save(self, body):
        """Save a label: copy source image to reader's test dir with label filename.
        Also removes any existing files for this timestamp in the target reader dir
        (so relabeling True->False removes the old True file).
        """
        try:
            data = json.loads(body)
            source = data["source"]  # relative path like "OpponentHPReader_Doubles/foo.png"
            reader = data["reader"]
            label = data["label"]    # the label filename e.g. "foo_True.png"

            src_path = os.path.join(TEST_ROOT, source)
            if not os.path.isfile(src_path):
                self._json_response({"error": f"Source not found: {source}"})
                return

            dest_dir = os.path.join(TEST_ROOT, reader)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, label)

            # Remove any existing files for this timestamp in this reader dir
            # (handles relabeling: True->False, etc.)
            ts = _extract_timestamp(label)
            for existing in os.listdir(dest_dir):
                if _extract_timestamp(existing) == ts and existing != label:
                    old_path = os.path.join(dest_dir, existing)
                    os.remove(old_path)
                    print(f"[labeler] removed old: {reader}/{existing}", flush=True)

            import shutil
            shutil.copy2(src_path, dest_path)
            print(f"[labeler] {source} -> {reader}/{label}", flush=True)
            self._json_response({"ok": True})
        except Exception as e:
            print(f"[labeler] Error: {e}", flush=True)
            self._json_response({"error": str(e)})

    def _serve_template_manager(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(build_template_manager_page().encode())

    def _handle_retest(self, params):
        reader = params.get("reader", [None])[0]

        # Parse box updates: boxes=JSON
        boxes_json = params.get("boxes", [None])[0]
        if boxes_json and reader:
            try:
                boxes = json.loads(boxes_json)
                print(f"[retest] reader={reader} boxes={boxes}", flush=True)
                patched = patch_cpp_boxes(reader, boxes)
                print(f"[retest] patched={patched}", flush=True)
            except Exception as e:
                print(f"[retest] error: {e}", flush=True)
                self._json_response({"_error": str(e)})
                return

        # Patch color filter thresholds
        min_br = params.get("min_brightness", [None])[0]
        max_sp = params.get("max_spread", [None])[0]
        if min_br is not None and max_sp is not None:
            patch_cpp_color_filter(int(min_br), int(max_sp))

        results = run_regression(reader)
        RESULTS.update(results)
        self._json_response(results)

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(build_page().encode())


# ─── HTML page ────────────────────────────────────────────────────────────

def build_page():
    reader_info = []
    for r in READERS:
        entries = load_reader_images(TEST_ROOT, r)
        crops = READER_CROPS.get(r, _bool_detector_boxes)()
        images = []
        for e in entries:
            gt = e["ground_truth"]
            res = RESULTS.get(e["filename"])
            images.append({
                "filename": e["filename"],
                "path": f"{r}/{e['filename']}",
                "gt": gt,
                "result": res,
            })

        # Split slot-based readers into separate tabs per slot
        has_slots = any(img["gt"].get("type") in ("slot_int", "slot_words") for img in images)
        if has_slots:
            for slot_idx, slot_name in enumerate(["s0", "s1"]):
                slot_images = [img for img in images if img["gt"].get("slot") == slot_idx]
                if not slot_images:
                    continue
                # Only include the crop for this slot
                slot_crops = [crops[slot_idx]] if slot_idx < len(crops) else crops
                # Remap gt.values so active slot's value is at index 0
                # (JS checks gt.values[ci] where ci is crop index within this tab)
                remapped = []
                for img in slot_images:
                    gt = img["gt"]
                    remapped.append({
                        **img,
                        "gt": {**gt, "values": [gt["values"][slot_idx]]},
                    })
                reader_info.append({
                    "name": f"{r} ({slot_name})",
                    "reader": r,  # real reader name for retest
                    "crops": slot_crops,
                    "all_crops": crops,  # all crops for patching
                    "images": remapped,
                })
        else:
            reader_info.append({
                "name": r,
                "reader": r,
                "crops": crops,
                "all_crops": crops,
                "images": images,
            })

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>OCR Gallery</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:'SF Mono','Menlo',monospace; font-size:13px; padding:16px; }}
h1 {{ color:#58a6ff; margin-bottom:8px; font-size:20px; }}
h2 {{ color:#c9d1d9; font-size:16px; margin-bottom:8px; border-bottom:1px solid #21262d; padding-bottom:4px; }}

.nav {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; position:sticky; top:0; background:#0d1117; padding:8px 0; z-index:10; }}
.tab-btn {{ padding:4px 10px; background:#21262d; color:#8b949e; border:1px solid #30363d; border-radius:6px; font-size:12px; cursor:pointer; font-family:inherit; }}
.tab-btn:hover {{ background:#30363d; color:#c9d1d9; }}
.tab-btn.active {{ background:#1f6feb; color:#fff; border-color:#1f6feb; }}
.tab-fail {{ color:#f85149; font-weight:bold; font-size:10px; }}
.tab-count {{ font-size:10px; opacity:0.7; margin-left:4px; }}

.section {{ display:none; }}
.section.active {{ display:block; }}

.controls {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:12px; }}
.box-controls {{ display:flex; gap:24px; flex-wrap:wrap; align-items:flex-end; }}
.box-group label {{ color:#8b949e; font-size:10px; margin-right:2px; }}
.box-group input[type=number] {{ width:72px; padding:3px 5px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; font-size:12px; font-family:inherit; text-align:center; }}
.box-title {{ font-weight:bold; font-size:12px; margin-bottom:4px; }}
.btn {{ padding:5px 14px; border:1px solid #30363d; border-radius:6px; background:#21262d; color:#c9d1d9; cursor:pointer; font-size:12px; font-family:inherit; }}
.btn:hover {{ background:#30363d; }}
.btn-green {{ background:#238636; border-color:#238636; color:#fff; }}
.btn-green:hover {{ background:#2ea043; }}
.btn:disabled {{ opacity:0.5; cursor:wait; }}
.status {{ color:#8b949e; font-size:12px; margin-left:8px; }}

.card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px; margin-bottom:8px; cursor:pointer; }}
.card.fail {{ border-color:#f85149; }}
.card .card-body {{ display:none; }}
.card.expanded .card-body {{ display:block; }}
.card.fail {{ }}  /* fails start expanded via JS */
.card-header {{ display:flex; justify-content:space-between; align-items:center; }}
.card-filename {{ color:#58a6ff; font-weight:bold; font-size:12px; }}
.badge {{ padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; }}
.badge.pass {{ background:#238636; color:#fff; }}
.badge.fail {{ background:#da3633; color:#fff; }}
.badge.true {{ background:#1f6feb; color:#fff; }}
.badge.false {{ background:#6e7681; color:#fff; }}

.card-body {{ margin-top:8px; }}
.crop-row {{ display:flex; flex-wrap:wrap; gap:10px; margin:6px 0; }}
.crop-cell {{ text-align:center; }}
.crop-cell canvas {{ border:2px solid #30363d; border-radius:4px; image-rendering:pixelated; display:block; margin-bottom:2px; }}
.crop-name {{ color:#8b949e; font-size:10px; }}
.crop-label {{ font-size:11px; font-weight:bold; }}
.expected {{ color:#3fb950; font-size:12px; }}
.actual {{ font-size:12px; }}
.actual.pass {{ color:#3fb950; }}
.actual.fail {{ color:#f85149; }}
.segment-scores {{ margin-top:4px; font-size:10px; color:#8b949e; }}
.seg-score {{ margin:1px 0; }}
.seg-score.fail {{ color:#f85149; }}
.seg-score b {{ color:#58a6ff; }}
.thumb {{ margin:6px 0; }}
.thumb img {{ max-width:480px; height:auto; border-radius:4px; border:1px solid #30363d; }}
</style>
</head><body>
<h1>OCR Gallery — Pokemon Champions</h1>
<p style="margin-bottom:8px;">
<a href="/templates" style="color:#58a6ff;font-size:12px;">Digit Template Manager</a>
<span style="color:#30363d;margin:0 8px;">|</span>
<a href="/labeler" style="color:#58a6ff;font-size:12px;">Multi-Reader Labeler</a>
</p>
<div class="nav" id="nav"></div>
<div class="controls" style="margin-bottom:12px;display:flex;gap:24px;align-items:center;">
    <span style="color:#8b949e;font-size:12px;">Color Filter:</span>
    <div>
        <label style="color:#8b949e;font-size:10px;">min brightness</label>
        <input type="number" id="color-min-brightness" value="180" min="0" max="255" step="5"
            style="width:60px;padding:3px 5px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:12px;font-family:inherit;text-align:center;">
    </div>
    <div>
        <label style="color:#8b949e;font-size:10px;">max spread</label>
        <input type="number" id="color-max-spread" value="40" min="0" max="255" step="5"
            style="width:60px;padding:3px 5px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:12px;font-family:inherit;text-align:center;">
    </div>
    <button class="btn" onclick="refreshAllCrops()">Preview</button>
</div>
<div id="sections"></div>

<script>
const DATA = {json.dumps(reader_info, default=str)};
let results = {json.dumps(RESULTS)};
const imgCache = {{}};  // path -> HTMLImageElement
let activeTab = null;
let _debounceTimer = null;

function debounce(fn, ms) {{
    return function(...args) {{
        clearTimeout(_debounceTimer);
        _debounceTimer = setTimeout(() => fn(...args), ms);
    }};
}}

function getImg(path) {{
    if (imgCache[path]) return Promise.resolve(imgCache[path]);
    return new Promise(resolve => {{
        const el = new window.Image();
        el.onload = () => {{ imgCache[path] = el; resolve(el); }};
        el.src = '/img/' + path;
    }});
}}

function renderReaderCrops(readerName) {{
    const reader = DATA.find(r => r.name === readerName);
    if (!reader) return;
    reader.images.forEach((img, i) => {{
        getImg(img.path).then(el => renderCrops(readerName, i, el));
    }});
}}

function init() {{
    const nav = document.getElementById('nav');
    const sections = document.getElementById('sections');

    DATA.forEach((reader, idx) => {{
        // Tab button
        const btn = document.createElement('button');
        btn.className = 'tab-btn' + (idx === 0 ? ' active' : '');
        btn.dataset.reader = sid(reader.name);
        btn.onclick = () => switchTab(sid(reader.name));
        updateTabBtn(btn, reader);
        nav.appendChild(btn);

        // Section
        const sec = document.createElement('div');
        sec.className = 'section' + (idx === 0 ? ' active' : '');
        sec.id = 'section-' + sid(reader.name);
        sec.innerHTML = buildSection(reader);
        sections.appendChild(sec);
    }});

    activeTab = DATA.length ? DATA[0].name : null;

    // Preload and render only active tab first, then others in background
    if (activeTab) renderReaderCrops(activeTab);
    DATA.forEach(reader => {{
        if (reader.name !== activeTab) {{
            reader.images.forEach(img => getImg(img.path));  // preload only
        }}
    }});

    // Live preview on box input change (debounced, active tab only)
    const debouncedRender = debounce(() => {{ if (activeTab) renderReaderCrops(activeTab); }}, 120);
    document.querySelectorAll('.box-input').forEach(input => {{
        input.addEventListener('input', debouncedRender);
    }});

    // Live preview on color filter change (debounced, active tab only)
    document.getElementById('color-min-brightness').addEventListener('input', debouncedRender);
    document.getElementById('color-max-spread').addEventListener('input', debouncedRender);
}}

function updateTabBtn(btn, reader) {{
    const nFail = reader.images.filter(img => {{
        const r = results[img.filename];
        return r && !r.passed;
    }}).length;
    const failBadge = nFail ? ' <span class="tab-fail">' + nFail + '✗</span>' : '';
    btn.innerHTML = reader.name + '<span class="tab-count">' + reader.images.length + failBadge + '</span>';
}}

function sid(name) {{ return name.replace(/[^a-zA-Z0-9_-]/g, '_'); }}

function refreshAllCrops() {{
    if (activeTab) renderReaderCrops(activeTab);
}}

function switchTab(name) {{
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const unsid = DATA.find(r => sid(r.name) === name);
    activeTab = unsid ? unsid.name : name;
    document.getElementById('section-' + sid(name)).classList.add('active');
    document.querySelector('.tab-btn[data-reader="' + sid(name) + '"]').classList.add('active');
    renderReaderCrops(activeTab);
}}

function getCrops(readerName) {{
    const inputs = document.querySelectorAll('.box-input[data-reader="' + sid(readerName) + '"]');
    const crops = {{}};
    inputs.forEach(input => {{
        const name = input.dataset.crop;
        const dim = input.dataset.dim;
        if (!crops[name]) crops[name] = [0,0,0,0];
        crops[name][['x','y','w','h'].indexOf(dim)] = parseFloat(input.value) || 0;
    }});
    return crops;
}}

function getCropList(readerName) {{
    const reader = DATA.find(r => r.name === readerName);
    const overrides = getCrops(readerName);
    return reader.crops.map(c => ({{
        name: c.name,
        box: overrides[c.name] || c.box,
    }}));
}}

function renderCrops(readerName, imgIdx, imgEl) {{
    const crops = getCropList(readerName);
    const reader = DATA.find(r => r.name === readerName);
    const img = reader.images[imgIdx];
    const gt = img.gt;
    const W = imgEl.naturalWidth, H = imgEl.naturalHeight;

    crops.forEach((crop, ci) => {{
        // Skip untested slots
        if ((gt.type === 'slot_int' || gt.type === 'slot_words') && gt.values[ci] === null) return;

        const canvas = document.getElementById('crop-' + sid(readerName) + '-' + imgIdx + '-' + ci);
        const bwCanvas = document.getElementById('bw-' + sid(readerName) + '-' + imgIdx + '-' + ci);
        if (!canvas) return;

        const box = crop.box;
        const cx = Math.round(box[0]*W), cy = Math.round(box[1]*H);
        const cw = Math.round(box[2]*W), ch = Math.round(box[3]*H);
        if (cw <= 0 || ch <= 0) return;

        const scale = 4;
        canvas.width = cw * scale; canvas.height = ch * scale;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(imgEl, cx, cy, cw, ch, 0, 0, cw*scale, ch*scale);

        // Binarized preview (matches C++ pipeline: 3x upscale + threshold)
        if (bwCanvas) {{
            const cppScale = 3;
            const sw = cw * cppScale, sh = ch * cppScale;
            bwCanvas.width = sw; bwCanvas.height = sh;

            const tmp = document.createElement('canvas');
            tmp.width = cw; tmp.height = ch;
            const tCtx = tmp.getContext('2d');
            tCtx.drawImage(imgEl, cx, cy, cw, ch, 0, 0, cw, ch);
            const srcData = tCtx.getImageData(0, 0, cw, ch).data;

            // Upscale 3x + threshold (same as C++ block-fill loop)
            const out = document.createElement('canvas');
            out.width = sw; out.height = sh;
            const oCtx = out.getContext('2d');
            const oData = oCtx.createImageData(sw, sh);
            for (let y = 0; y < ch; y++) {{
                for (let x = 0; x < cw; x++) {{
                    const si = (y * cw + x) * 4;
                    const r = srcData[si], g = srcData[si+1], b = srcData[si+2];
                    const mn = Math.min(r, g, b), mx = Math.max(r, g, b);
                    const minBr = parseFloat(document.getElementById('color-min-brightness').value);
                    const maxSpread = parseFloat(document.getElementById('color-max-spread').value);
                    const isWhite = (mn > minBr) && (mx - mn < maxSpread);
                    const v = isWhite ? 0 : 255;
                    for (let sy = 0; sy < cppScale; sy++) {{
                        for (let sx = 0; sx < cppScale; sx++) {{
                            const di = ((y*cppScale+sy) * sw + (x*cppScale+sx)) * 4;
                            oData.data[di] = oData.data[di+1] = oData.data[di+2] = v;
                            oData.data[di+3] = 255;
                        }}
                    }}
                }}
            }}
            oCtx.putImageData(oData, 0, 0);
            const bCtx = bwCanvas.getContext('2d');
            bCtx.imageSmoothingEnabled = false;
            bCtx.drawImage(out, 0, 0);

            // Draw segment boundaries via column projection
            // Compute column sums (count foreground=black pixels per column)
            const bwData = oCtx.getImageData(0, 0, sw, sh).data;
            const colSums = new Array(sw).fill(0);
            for (let bx = 0; bx < sw; bx++) {{
                for (let by = 0; by < sh; by++) {{
                    if (bwData[(by * sw + bx) * 4] === 0) colSums[bx]++;
                }}
            }}

            // Find content bounds
            let firstCol = sw, lastCol = 0;
            for (let bx = 0; bx < sw; bx++) {{
                if (colSums[bx] > 0) {{
                    if (firstCol === sw) firstCol = bx;
                    lastCol = bx;
                }}
            }}

            if (firstCol < lastCol) {{
                const contentW = lastCol - firstCol + 1;
                // Find vertical bounds
                let firstRow = sh, lastRow = 0;
                for (let by = 0; by < sh; by++) {{
                    for (let bx = firstCol; bx <= lastCol; bx++) {{
                        if (bwData[(by * sw + bx) * 4] === 0) {{
                            if (firstRow === sh) firstRow = by;
                            lastRow = by;
                            break;
                        }}
                    }}
                }}

                // Estimate digit count from aspect ratio
                const contentH = lastRow - firstRow + 1;
                const aspect = contentW / contentH;
                let nDigits = 1;
                if (aspect >= 2.2) nDigits = 3;
                else if (aspect >= 1.2) nDigits = 2;

                // Draw content bounding box (cyan)
                bCtx.strokeStyle = 'rgba(0, 255, 255, 0.5)';
                bCtx.lineWidth = 1;
                bCtx.strokeRect(firstCol, firstRow, contentW, contentH);

                // Draw split lines for multi-digit
                if (nDigits > 1) {{
                    const contentCols = colSums.slice(firstCol, lastCol + 1);
                    const window = Math.max(2, Math.floor(contentW / (nDigits * 2)));
                    bCtx.strokeStyle = 'rgba(255, 50, 50, 0.9)';
                    bCtx.lineWidth = 2;
                    for (let d = 1; d < nDigits; d++) {{
                        const expected = Math.floor(d * contentW / nDigits);
                        const lo = Math.max(0, expected - window);
                        const hi = Math.min(contentW - 1, expected + window);
                        let bestX = expected, bestVal = Infinity;
                        for (let bx = lo; bx <= hi; bx++) {{
                            if (contentCols[bx] < bestVal) {{
                                bestVal = contentCols[bx];
                                bestX = bx;
                            }}
                        }}
                        const drawX = firstCol + bestX;
                        bCtx.beginPath();
                        bCtx.moveTo(drawX, 0);
                        bCtx.lineTo(drawX, sh);
                        bCtx.stroke();
                    }}
                }}

                // Show aspect ratio and digit count
                bCtx.fillStyle = 'rgba(255, 255, 255, 0.7)';
                bCtx.font = '10px monospace';
                bCtx.fillText(nDigits + 'd a=' + aspect.toFixed(2), 2, sh - 3);
            }}
        }}
    }});
}}

function buildSection(reader) {{
    let html = '';

    // Template reference strip for HP readers
    if (reader.name.includes('HP')) {{
        html += '<div style="margin-bottom:8px;display:flex;gap:8px;align-items:center;">';
        html += '<span style="color:#8b949e;font-size:11px;">Templates:</span>';
        for (let d = 0; d <= 9; d++) {{
            html += '<div style="text-align:center;">';
            html += '<img src="/template/' + d + '.png" style="height:32px;image-rendering:pixelated;border:1px solid #30363d;border-radius:2px;background:#fff;" onerror="this.parentElement.style.opacity=0.3">';
            html += '<div style="font-size:10px;color:#8b949e;">' + d + '</div>';
            html += '</div>';
        }}
        html += '</div>';
    }}

    // Box controls
    if (reader.crops.length > 0) {{
        html += '<div class="controls"><div class="box-controls">';
        reader.crops.forEach(crop => {{
            html += '<div class="box-group"><div class="box-title">' + crop.name + '</div>';
            ['x','y','w','h'].forEach((dim, di) => {{
                html += '<label>' + dim + '</label>';
                html += '<input type="number" step="0.001" class="box-input" '
                    + 'data-reader="' + sid(reader.name) + '" data-crop="' + crop.name + '" data-dim="' + dim + '" '
                    + 'value="' + crop.box[di].toFixed(4) + '">';
            }});
            html += '</div>';
        }});
        html += '<div style="display:flex;flex-direction:column;gap:4px;justify-content:flex-end;">'
            + '<button class="btn btn-green" onclick="retest(&quot;' + reader.name + '&quot;)">Retest</button>'
            + '<span class="status" id="status-' + sid(reader.name) + '"></span>'
            + '</div>';
        html += '</div></div>';
    }}

    // Cards
    reader.images.forEach((img, i) => {{
        const r = results[img.filename];
        const passed = r ? r.passed : null;
        const cardClass = (passed === false ? 'card fail expanded' : 'card pass');
        html += '<div class="' + cardClass + '" id="card-' + sid(reader.name) + '-' + i + '" onclick="this.classList.toggle(&quot;expanded&quot;)">';
        html += '<div class="card-header"><span class="card-filename">' + img.filename + '</span>';
        if (passed === true) html += '<span class="badge pass">PASS</span>';
        else if (passed === false) html += '<span class="badge fail">FAIL</span>';
        html += '</div>';

        html += '<div class="card-body">';

        // Crop canvases
        html += '<div class="crop-row">';
        reader.crops.forEach((crop, ci) => {{
            const gt = img.gt;
            if ((gt.type === 'slot_int' || gt.type === 'slot_words') && gt.values[ci] === null) return;

            html += '<div class="crop-cell">';
            html += '<canvas id="crop-' + sid(reader.name) + '-' + i + '-' + ci + '"></canvas>';
            html += '<canvas id="bw-' + sid(reader.name) + '-' + i + '-' + ci + '"></canvas>';
            html += '<div class="crop-name">' + crop.name + '</div>';

            // Expected
            if ((gt.type === 'slot_int' || gt.type === 'slot_words') && gt.values[ci] !== null) {{
                html += '<div class="crop-label expected">expected: ' + gt.values[ci] + '</div>';
            }} else if (gt.type === 'words' && ci < gt.values.length) {{
                html += '<div class="crop-label" style="color:#f0c040">' + (gt.values[ci] || '(none)') + '</div>';
            }}

            // Result display: template match or legacy OCR
            if (r) {{
                const cls = r.passed ? 'pass' : 'fail';
                const read = r.actual || '?';

                if (r.digits) {{
                    // Template match result
                    html += '<div class="actual ' + cls + '">digits: [' + r.digits.join('][') + '] → ' + read + '</div>';
                }} else if (r.no_digits) {{
                    html += '<div class="actual fail">no digits found</div>';
                }} else if (r.raw_ocr !== undefined) {{
                    // Legacy OCR
                    const raw = r.raw_ocr;
                    if (raw !== null && raw !== read && raw !== '') {{
                        html += '<div class="actual ' + cls + '">raw: "' + raw + '" → parsed: ' + read + '</div>';
                    }} else {{
                        html += '<div class="actual ' + cls + '">read: ' + read + '</div>';
                    }}
                }} else {{
                    html += '<div class="actual ' + cls + '">read: ' + read + '</div>';
                }}

                // Per-segment scores with template thumbnails
                if (r.segments && r.segments.length > 0) {{
                    html += '<div class="segment-scores">';
                    r.segments.forEach((seg, si) => {{
                        if (!seg) return;
                        const digit = r.digits ? r.digits[si] : '?';
                        const noMatch = r.no_match_segments && r.no_match_segments.includes(si);
                        const segCls = noMatch ? 'fail' : '';
                        // Sort scores descending
                        const sorted = Object.entries(seg.scores).sort((a,b) => b[1] - a[1]);
                        html += '<div class="seg-score ' + segCls + '" style="display:flex;align-items:center;gap:6px;margin:3px 0;">';
                        // Show matched template thumbnail
                        if (digit !== '?' && !noMatch) {{
                            html += '<img src="/template/' + digit + '.png" style="height:24px;image-rendering:pixelated;border:1px solid #58a6ff;border-radius:2px;" title="template ' + digit + '">';
                        }}
                        html += '<span>seg[' + si + '] ' + seg.w + 'x' + seg.h + ' → ';
                        // Top 3 scores with template thumbnails
                        sorted.slice(0, 4).forEach(([d, s]) => {{
                            const isBest = d === digit;
                            const style = isBest ? 'color:#58a6ff;font-weight:bold;' : '';
                            html += '<span style="' + style + 'margin-right:6px;">';
                            html += '<img src="/template/' + d + '.png" style="height:14px;image-rendering:pixelated;vertical-align:middle;opacity:' + (isBest ? '1' : '0.5') + ';" onerror="this.style.display=&quot;none&quot;">';
                            html += d + ':' + s.toFixed(3);
                            html += '</span>';
                        }});
                        html += '</span></div>';
                    }});
                    html += '</div>';
                }}
            }}

            html += '</div>';
        }});
        html += '</div>';

        // Thumbnail
        html += '<div class="thumb"><img src="/img/' + img.path + '" loading="lazy"></div>';

        // Ground truth summary
        const gt = img.gt;
        if (gt.type === 'slot_int') html += '<div class="expected">expected: slot ' + gt.slot + ' = ' + gt.values[gt.slot] + '%</div>';
        else if (gt.type === 'int') html += '<div class="expected">expected: ' + gt.values[0] + '</div>';

        html += '</div></div>';
    }});

    return html;
}}

async function retest(readerName) {{
    const status = document.getElementById('status-' + sid(readerName));
    const btns = document.querySelectorAll('.btn-green');
    btns.forEach(b => b.disabled = true);
    status.textContent = 'Building + testing...';

    const reader = DATA.find(r => r.name === readerName);
    const realReader = reader.reader || readerName;
    // Collect crops from all sibling tabs sharing the same real reader
    const allCrops = {{}};
    DATA.filter(r => (r.reader || r.name) === realReader).forEach(r => {{
        Object.assign(allCrops, getCrops(r.name));
    }});
    const params = new URLSearchParams();
    params.set('reader', realReader);
    if (Object.keys(allCrops).length) params.set('boxes', JSON.stringify(allCrops));
    params.set('min_brightness', document.getElementById('color-min-brightness').value);
    params.set('max_spread', document.getElementById('color-max-spread').value);

    try {{
        const resp = await fetch('/api/retest?' + params.toString());
        const newResults = await resp.json();
        if (newResults._error) {{
            status.textContent = 'Error: ' + newResults._error;
        }} else {{
            Object.assign(results, newResults);
            const total = Object.keys(newResults).length;
            const passed = Object.values(newResults).filter(r => r.passed).length;
            status.textContent = passed + '/' + total + ' passed';

            // Rebuild section
            const reader = DATA.find(r => r.name === readerName);
            // Update result refs in DATA
            reader.images.forEach(img => {{
                if (newResults[img.filename]) img.result = newResults[img.filename];
            }});
            const sec = document.getElementById('section-' + sid(readerName));
            sec.innerHTML = buildSection(reader);
            // Re-render crops from cache
            renderReaderCrops(readerName);
            // Re-bind input listeners (debounced)
            const debouncedRender = debounce(() => renderReaderCrops(readerName), 120);
            sec.querySelectorAll('.box-input').forEach(input => {{
                input.addEventListener('input', debouncedRender);
            }});
            // Update tab
            const tabBtn = document.querySelector('.tab-btn[data-reader="' + sid(readerName) + '"]');
            updateTabBtn(tabBtn, reader);
        }}
    }} catch(e) {{
        status.textContent = 'Error: ' + e.message;
    }}
    btns.forEach(b => b.disabled = false);
}}

init();
</script>
</body></html>"""


# ─── Template Manager Page ────────────────────────────────────────────────

def build_template_manager_page():
    # Gather HP doubles test frames with slot info
    frames = []
    reader = "OpponentHPReader_Doubles"
    crops = _opponent_hp_doubles_boxes()
    reader_dir = os.path.join(TEST_ROOT, reader)
    if os.path.isdir(reader_dir):
        for f in sorted(os.listdir(reader_dir)):
            if not f.lower().endswith(".png"):
                continue
            gt = parse_ground_truth(f, reader)
            frames.append({
                "filename": f,
                "path": f"{reader}/{f}",
                "gt": gt,
            })

    # Current templates
    tmpl_dir = os.path.join(REPO, "Packages", "Resources", "PokemonChampions", "DigitTemplates")
    existing = []
    for d in range(10):
        p = os.path.join(tmpl_dir, f"{d}.png")
        existing.append(os.path.isfile(p))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Digit Template Manager</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:'SF Mono','Menlo',monospace; font-size:13px; padding:16px; }}
h1 {{ color:#58a6ff; margin-bottom:4px; font-size:20px; }}
h2 {{ color:#c9d1d9; font-size:15px; margin:16px 0 8px; border-bottom:1px solid #21262d; padding-bottom:4px; }}
a {{ color:#58a6ff; }}

.templates-grid {{ display:flex; gap:12px; flex-wrap:wrap; margin:12px 0; }}
.tmpl-slot {{ text-align:center; border:2px solid #30363d; border-radius:8px; padding:8px; min-width:70px; background:#161b22; }}
.tmpl-slot.has {{ border-color:#238636; }}
.tmpl-slot.missing {{ border-color:#f85149; opacity:0.5; }}
.tmpl-slot img {{ height:48px; image-rendering:pixelated; background:#fff; border-radius:4px; display:block; margin:0 auto 4px; }}
.tmpl-slot .digit-label {{ font-size:16px; font-weight:bold; }}
.tmpl-slot .btn-del {{ font-size:10px; color:#f85149; cursor:pointer; border:none; background:none; font-family:inherit; margin-top:4px; }}
.tmpl-slot .btn-del:hover {{ text-decoration:underline; }}

.frame-card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px; margin-bottom:10px; }}
.frame-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }}
.frame-filename {{ color:#58a6ff; font-weight:bold; font-size:12px; }}
.frame-gt {{ color:#3fb950; font-size:12px; }}

.crops-row {{ display:flex; gap:16px; flex-wrap:wrap; align-items:flex-start; }}
.crop-col {{ text-align:center; }}
.crop-col canvas {{ border:2px solid #30363d; border-radius:4px; image-rendering:pixelated; display:block; margin-bottom:4px; }}
.crop-label {{ color:#8b949e; font-size:10px; margin-bottom:2px; }}

.segments-row {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; align-items:flex-end; }}
.seg-box {{ text-align:center; border:1px solid #30363d; border-radius:6px; padding:6px; background:#0d1117; }}
.seg-box canvas {{ image-rendering:pixelated; border:1px solid #444; border-radius:3px; display:block; margin:0 auto 4px; }}
.seg-box select {{ background:#21262d; color:#c9d1d9; border:1px solid #30363d; border-radius:4px; padding:2px 4px; font-size:12px; font-family:inherit; }}
.seg-box .btn-save {{ padding:3px 8px; background:#238636; color:#fff; border:1px solid #238636; border-radius:4px; font-size:11px; cursor:pointer; font-family:inherit; margin-top:4px; display:block; }}
.seg-box .btn-save:hover {{ background:#2ea043; }}

.status-msg {{ color:#8b949e; font-size:12px; margin-top:8px; }}
</style>
</head><body>
<h1>Digit Template Manager</h1>
<p style="color:#8b949e;font-size:12px;margin-bottom:12px;"><a href="/">← Back to Gallery</a></p>

<h2>Current Templates</h2>
<div class="templates-grid" id="templates-grid"></div>

<h2>Extract from Frames</h2>
<p style="color:#8b949e;font-size:11px;margin-bottom:8px;">
    Each frame is binarized and segmented. Select which digit each segment represents and click Save.
</p>
<div id="frames"></div>

<script>
const FRAMES = {json.dumps(frames, default=str)};
const CROPS = {json.dumps(crops, default=str)};
const EXISTING = {json.dumps(existing)};
const MIN_BR = 180;
const MAX_SPREAD = 50;
const CPP_SCALE = 3;

// ── Template grid ──
function renderTemplates() {{
    const grid = document.getElementById('templates-grid');
    grid.innerHTML = '';
    for (let d = 0; d < 10; d++) {{
        const slot = document.createElement('div');
        slot.className = 'tmpl-slot ' + (EXISTING[d] ? 'has' : 'missing');
        if (EXISTING[d]) {{
            slot.innerHTML = '<img src="/template/' + d + '.png?t=' + Date.now() + '">'
                + '<div class="digit-label">' + d + '</div>'
                + '<button class="btn-del" onclick="deleteTemplate(' + d + ')">delete</button>';
        }} else {{
            slot.innerHTML = '<div style="height:48px;display:flex;align-items:center;justify-content:center;color:#6e7681;">—</div>'
                + '<div class="digit-label">' + d + '</div>';
        }}
        grid.appendChild(slot);
    }}
}}

async function deleteTemplate(d) {{
    if (!confirm('Delete template for digit ' + d + '?')) return;
    await fetch('/api/template/delete?digit=' + d);
    EXISTING[d] = false;
    renderTemplates();
}}

async function saveTemplate(d, canvas) {{
    const dataUrl = canvas.toDataURL('image/png');
    const base64 = dataUrl.split(',')[1];
    const resp = await fetch('/api/template/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ digit: String(d), png_base64: base64 }}),
    }});
    const result = await resp.json();
    if (result.ok) {{
        EXISTING[d] = true;
        renderTemplates();
    }}
    return result;
}}

// ── Binarize a crop (same as C++ pipeline) ──
function binarize(imgEl, box) {{
    const W = imgEl.naturalWidth, H = imgEl.naturalHeight;
    const cx = Math.round(box[0]*W), cy = Math.round(box[1]*H);
    const cw = Math.round(box[2]*W), ch = Math.round(box[3]*H);
    if (cw <= 0 || ch <= 0) return null;

    // Get native pixels
    const tmp = document.createElement('canvas');
    tmp.width = cw; tmp.height = ch;
    const tCtx = tmp.getContext('2d');
    tCtx.drawImage(imgEl, cx, cy, cw, ch, 0, 0, cw, ch);
    const srcData = tCtx.getImageData(0, 0, cw, ch).data;

    // 3x upscale + threshold
    const sw = cw * CPP_SCALE, sh = ch * CPP_SCALE;
    const out = document.createElement('canvas');
    out.width = sw; out.height = sh;
    const oCtx = out.getContext('2d');
    const oData = oCtx.createImageData(sw, sh);
    for (let y = 0; y < ch; y++) {{
        for (let x = 0; x < cw; x++) {{
            const si = (y * cw + x) * 4;
            const r = srcData[si], g = srcData[si+1], b = srcData[si+2];
            const mn = Math.min(r, g, b), mx = Math.max(r, g, b);
            const isWhite = (mn > MIN_BR) && (mx - mn < MAX_SPREAD);
            const v = isWhite ? 0 : 255;
            for (let sy = 0; sy < CPP_SCALE; sy++) {{
                for (let sx = 0; sx < CPP_SCALE; sx++) {{
                    const di = ((y*CPP_SCALE+sy) * sw + (x*CPP_SCALE+sx)) * 4;
                    oData.data[di] = oData.data[di+1] = oData.data[di+2] = v;
                    oData.data[di+3] = 255;
                }}
            }}
        }}
    }}
    oCtx.putImageData(oData, 0, 0);
    return {{ canvas: out, width: sw, height: sh, imageData: oData }};
}}

// ── Segment binarized image into digits ──
function segmentDigits(bwData, sw, sh) {{
    // Column projection: count foreground (black) pixels per column
    const colSums = new Array(sw).fill(0);
    for (let x = 0; x < sw; x++) {{
        for (let y = 0; y < sh; y++) {{
            if (bwData.data[(y * sw + x) * 4] === 0) colSums[x]++;
        }}
    }}

    // Find content bounds
    let firstCol = sw, lastCol = 0;
    for (let x = 0; x < sw; x++) {{
        if (colSums[x] > 0) {{
            if (firstCol === sw) firstCol = x;
            lastCol = x;
        }}
    }}
    if (firstCol >= lastCol) return [];
    const contentW = lastCol - firstCol + 1;

    // Find vertical bounds
    let firstRow = sh, lastRow = 0;
    for (let y = 0; y < sh; y++) {{
        for (let x = firstCol; x <= lastCol; x++) {{
            if (bwData.data[(y * sw + x) * 4] === 0) {{
                if (firstRow === sh) firstRow = y;
                lastRow = y;
                break;
            }}
        }}
    }}
    if (firstRow >= lastRow) return [];
    const contentH = lastRow - firstRow + 1;

    // Estimate digit count from aspect ratio
    const aspect = contentW / contentH;
    let nDigits = 1;
    if (aspect >= 2.2) nDigits = 3;
    else if (aspect >= 1.2) nDigits = 2;

    // Column sums within content region
    const cc = colSums.slice(firstCol, lastCol + 1);

    // Split using valley detection
    const splits = [];
    if (nDigits > 1) {{
        const window = Math.max(2, Math.floor(contentW / (nDigits * 2)));
        for (let d = 1; d < nDigits; d++) {{
            const expected = Math.floor(d * contentW / nDigits);
            const lo = Math.max(0, expected - window);
            const hi = Math.min(contentW - 1, expected + window);
            let bestX = expected, bestVal = Infinity;
            for (let bx = lo; bx <= hi; bx++) {{
                if (cc[bx] < bestVal) {{ bestVal = cc[bx]; bestX = bx; }}
            }}
            splits.push(bestX);
        }}
    }}

    // Build segments from boundaries
    const boundaries = [0, ...splits, contentW];
    const segments = [];
    for (let i = 0; i < boundaries.length - 1; i++) {{
        const sx = boundaries[i], ex = boundaries[i + 1];
        if (ex <= sx) continue;
        // Trim to tight horizontal bounds
        let trimL = ex, trimR = sx;
        for (let bx = sx; bx < ex; bx++) {{
            if (cc[bx] > 0) {{
                if (bx < trimL) trimL = bx;
                trimR = bx;
            }}
        }}
        if (trimL > trimR) continue;
        segments.push({{
            x0: firstCol + trimL,
            x1: firstCol + trimR + 1,
            y0: firstRow,
            y1: lastRow + 1,
        }});
    }}
    return segments;
}}

// ── Build segment boxes from split positions ──
function buildSegments(bwCanvas, bwData, sw, sh, splits, expectedStr) {{
    // Find content bounds from bwData
    const colSums = new Array(sw).fill(0);
    for (let x = 0; x < sw; x++) {{
        for (let y = 0; y < sh; y++) {{
            if (bwData.data[(y * sw + x) * 4] === 0) colSums[x]++;
        }}
    }}
    let firstCol = sw, lastCol = 0;
    for (let x = 0; x < sw; x++) {{
        if (colSums[x] > 0) {{ if (firstCol === sw) firstCol = x; lastCol = x; }}
    }}
    if (firstCol >= lastCol) return [];
    let firstRow = sh, lastRow = 0;
    for (let y = 0; y < sh; y++) {{
        for (let x = firstCol; x <= lastCol; x++) {{
            if (bwData.data[(y * sw + x) * 4] === 0) {{
                if (firstRow === sh) firstRow = y;
                lastRow = y;
                break;
            }}
        }}
    }}
    if (firstRow >= lastRow) return [];
    const contentW = lastCol - firstCol + 1;
    const cc = colSums.slice(firstCol, lastCol + 1);

    // Build from absolute split positions (relative to full bw image)
    const absSplits = splits.map(s => s - firstCol);  // convert to content-relative
    const boundaries = [0, ...absSplits.filter(s => s > 0 && s < contentW), contentW];
    const segments = [];
    for (let i = 0; i < boundaries.length - 1; i++) {{
        const sx = boundaries[i], ex = boundaries[i + 1];
        if (ex <= sx) continue;
        let trimL = ex, trimR = sx;
        for (let bx = sx; bx < ex; bx++) {{
            if (cc[bx] > 0) {{ if (bx < trimL) trimL = bx; trimR = bx; }}
        }}
        if (trimL > trimR) continue;
        segments.push({{
            x0: firstCol + trimL, x1: firstCol + trimR + 1,
            y0: firstRow, y1: lastRow + 1,
        }});
    }}
    return segments;
}}

// ── Render segment boxes with save buttons ──
function renderSegmentBoxes(segsRow, segments, bwCanvas, expectedStr) {{
    segsRow.innerHTML = '';
    segments.forEach((seg, si) => {{
        const sw2 = seg.x1 - seg.x0;
        const sh2 = seg.y1 - seg.y0;

        const segCanvas = document.createElement('canvas');
        segCanvas.width = sw2; segCanvas.height = sh2;
        const sCtx = segCanvas.getContext('2d');
        sCtx.drawImage(bwCanvas, seg.x0, seg.y0, sw2, sh2, 0, 0, sw2, sh2);

        const guessDigit = si < expectedStr.length ? expectedStr[si] : '';

        const segBox = document.createElement('div');
        segBox.className = 'seg-box';
        segBox.appendChild(segCanvas);

        const info = document.createElement('div');
        info.style.cssText = 'font-size:10px;color:#8b949e;';
        info.textContent = sw2 + 'x' + sh2;
        segBox.appendChild(info);

        const sel = document.createElement('select');
        sel.innerHTML = '<option value="">—</option>';
        for (let d = 0; d <= 9; d++) {{
            sel.innerHTML += '<option value="' + d + '"' + (String(d) === guessDigit ? ' selected' : '') + '>' + d + '</option>';
        }}
        segBox.appendChild(sel);

        const btn = document.createElement('button');
        btn.className = 'btn-save';
        btn.textContent = 'Save as template';
        btn.onclick = async () => {{
            const digit = sel.value;
            if (digit === '') {{ alert('Select a digit first'); return; }}
            btn.textContent = 'Saving...';
            const result = await saveTemplate(digit, segCanvas);
            btn.textContent = result.ok ? 'Saved ✓' : 'Error';
            setTimeout(() => btn.textContent = 'Save as template', 2000);
        }};
        segBox.appendChild(btn);
        segsRow.appendChild(segBox);
    }});
    if (segments.length === 0) {{
        segsRow.innerHTML = '<span style="color:#6e7681;">No segments found</span>';
    }}
}}

// ── Render a frame card ──
function renderFrame(frame, container) {{
    const card = document.createElement('div');
    card.className = 'frame-card';

    const gt = frame.gt;
    const slotIdx = gt.slot !== undefined ? gt.slot : 0;
    const expected = gt.values ? gt.values[slotIdx] : '?';
    const expectedStr = String(expected);
    const crop = CROPS[slotIdx];
    if (!crop) return;

    card.innerHTML = '<div class="frame-header">'
        + '<span class="frame-filename">' + frame.filename + '</span>'
        + '<span class="frame-gt">slot ' + slotIdx + ' = ' + expected + '</span>'
        + '</div>'
        + '<div class="crops-row">'
        + '<div class="crop-col"><div class="crop-label">color crop</div><canvas id="color-' + frame.filename + '"></canvas></div>'
        + '<div class="crop-col" style="position:relative;">'
        + '<div class="crop-label">binarized (drag red line to adjust split)</div>'
        + '<div id="bw-wrap-' + frame.filename + '" style="position:relative;display:inline-block;"></div>'
        + '</div>'
        + '</div>'
        + '<div class="segments-row" id="segs-' + frame.filename + '"></div>';
    container.appendChild(card);

    const img = new Image();
    img.onload = () => {{
        const box = crop.box;
        const W = img.naturalWidth, H = img.naturalHeight;
        const cx = Math.round(box[0]*W), cy = Math.round(box[1]*H);
        const cw = Math.round(box[2]*W), ch = Math.round(box[3]*H);

        // Color crop
        const colorCanvas = document.getElementById('color-' + frame.filename);
        const scale = 4;
        colorCanvas.width = cw * scale; colorCanvas.height = ch * scale;
        const cCtx = colorCanvas.getContext('2d');
        cCtx.imageSmoothingEnabled = false;
        cCtx.drawImage(img, cx, cy, cw, ch, 0, 0, cw*scale, ch*scale);

        // Binarize
        const bw = binarize(img, box);
        if (!bw) return;

        const bwWrap = document.getElementById('bw-wrap-' + frame.filename);
        const bwCanvas = document.createElement('canvas');
        bwCanvas.width = bw.width; bwCanvas.height = bw.height;
        bwCanvas.style.cssText = 'border:2px solid #30363d;border-radius:4px;image-rendering:pixelated;';
        const bCtx = bwCanvas.getContext('2d');
        bCtx.drawImage(bw.canvas, 0, 0);
        bwWrap.appendChild(bwCanvas);

        // Initial auto-segmentation
        const autoSegs = segmentDigits(bw.imageData, bw.width, bw.height);
        const segsRow = document.getElementById('segs-' + frame.filename);

        // Compute initial split positions from auto segments
        let splitXs = [];
        if (autoSegs.length > 1) {{
            for (let i = 0; i < autoSegs.length - 1; i++) {{
                splitXs.push(Math.round((autoSegs[i].x1 + autoSegs[i+1].x0) / 2));
            }}
        }}

        // Draw split lines as draggable divs
        const splitLines = [];
        function addSplitLine(x) {{
            const line = document.createElement('div');
            line.style.cssText = 'position:absolute;top:0;width:3px;height:100%;background:rgba(255,50,50,0.8);cursor:col-resize;z-index:5;';
            line.style.left = x + 'px';
            bwWrap.appendChild(line);

            let dragging = false;
            line.addEventListener('mousedown', (e) => {{ dragging = true; e.preventDefault(); }});
            document.addEventListener('mousemove', (e) => {{
                if (!dragging) return;
                const rect = bwWrap.getBoundingClientRect();
                let nx = Math.round(e.clientX - rect.left);
                nx = Math.max(0, Math.min(bw.width - 1, nx));
                line.style.left = nx + 'px';
                line._splitX = nx;
                updateSegments();
            }});
            document.addEventListener('mouseup', () => {{ dragging = false; }});
            line._splitX = x;
            splitLines.push(line);
        }}

        function updateSegments() {{
            const currentSplits = splitLines.map(l => l._splitX).sort((a,b) => a - b);
            const segs = buildSegments(bwCanvas, bw.imageData, bw.width, bw.height, currentSplits, expectedStr);
            renderSegmentBoxes(segsRow, segs, bwCanvas, expectedStr);
            // Redraw bw canvas clean + split markers
            bCtx.clearRect(0, 0, bw.width, bw.height);
            bCtx.drawImage(bw.canvas, 0, 0);
        }}

        // Add split lines for multi-digit
        splitXs.forEach(x => addSplitLine(x));

        // Add/remove split button
        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'margin-top:4px;display:flex;gap:6px;';
        const addBtn = document.createElement('button');
        addBtn.className = 'btn-save';
        addBtn.style.background = '#1f6feb';
        addBtn.textContent = '+ Add split';
        addBtn.onclick = () => {{
            addSplitLine(Math.round(bw.width / 2));
            updateSegments();
        }};
        const rmBtn = document.createElement('button');
        rmBtn.className = 'btn-save';
        rmBtn.style.background = '#da3633';
        rmBtn.textContent = '− Remove split';
        rmBtn.onclick = () => {{
            if (splitLines.length === 0) return;
            const last = splitLines.pop();
            last.remove();
            updateSegments();
        }};
        btnRow.appendChild(addBtn);
        btnRow.appendChild(rmBtn);
        bwWrap.parentElement.appendChild(btnRow);

        // Initial render
        renderSegmentBoxes(segsRow, autoSegs, bwCanvas, expectedStr);
    }};
    img.src = '/img/' + frame.path;
}}

// ── Init ──
renderTemplates();
const framesContainer = document.getElementById('frames');
FRAMES.forEach(f => renderFrame(f, framesContainer));
</script>
</body></html>"""


# ─── Labeler Page ─────────────────────────────────────────────────────────

# Readers useful for doubles battle frames, with label input types
LABELER_READERS = [
    # ── Bool detectors (True/False) ──
    {"name": "TeamPreviewDetector", "type": "bool",
     "crops": READER_CROPS["TeamPreviewDetector"](),
     "help": "Is the team preview screen visible?"},
    {"name": "TeamSelectDetector", "type": "bool",
     "crops": READER_CROPS["TeamSelectDetector"](),
     "help": "Is the team select screen visible?"},
    {"name": "ActionMenuDetector", "type": "bool",
     "crops": READER_CROPS["ActionMenuDetector"](),
     "help": "Is the action menu (Fight/Pokemon) visible?"},
    {"name": "MoveSelectDetector", "type": "bool",
     "crops": READER_CROPS["MoveSelectDetector"](),
     "help": "Is the move select screen visible?"},
    {"name": "MovesMoreDetector", "type": "bool",
     "crops": READER_CROPS["MovesMoreDetector"](),
     "help": "Is the 'more moves' indicator visible?"},
    {"name": "PreparingForBattleDetector", "type": "bool",
     "crops": READER_CROPS["PreparingForBattleDetector"](),
     "help": "Is the 'preparing for battle' screen visible?"},
    {"name": "PostMatchScreenDetector", "type": "bool",
     "crops": READER_CROPS["PostMatchScreenDetector"](),
     "help": "Is the post-match result screen visible?"},
    {"name": "MainMenuDetector", "type": "bool",
     "crops": READER_CROPS["MainMenuDetector"](),
     "help": "Is the main menu visible?"},
    {"name": "ResultScreenDetector", "type": "bool",
     "crops": READER_CROPS["ResultScreenDetector"](),
     "help": "Is the win/loss result screen visible?"},
    # ── Slot/cursor detectors ──
    {"name": "MoveSelectCursorSlot", "type": "int",
     "crops": READER_CROPS["MoveSelectCursorSlot"](),
     "help": "Which move slot is the cursor on? (0-3)"},
    # ── OCR readers ──
    {"name": "SpeciesReader_Doubles", "type": "slot_words",
     "crops": _species_reader_doubles_boxes(),
     "slots": ["s0 (left opp)", "s1 (right opp)"],
     "help": "Species name slug (e.g. pikachu, iron-hands)"},
    {"name": "MoveNameReader", "type": "words",
     "crops": _move_name_boxes(),
     "help": "Move slug per slot. Use NONE for empty."},
    {"name": "BattleLogReader", "type": "words",
     "crops": _battle_log_reader_boxes(),
     "help": "Log text (e.g. Pikachu_used_Thunderbolt)"},
    # ── Team screens ──
    {"name": "TeamPreviewReader", "type": "words",
     "crops": _team_preview_reader_boxes(),
     "help": "6 own + 6 opp species slugs"},
    {"name": "TeamSelectReader", "type": "words",
     "crops": _team_select_reader_boxes(),
     "help": "6 species slugs for team select slots"},
    {"name": "TeamSummaryReader", "type": "words",
     "crops": _team_summary_reader_boxes(),
     "help": "6 species slugs for team summary"},
]

def build_inspector_page():
    # Collect all test images grouped by reader
    readers = {}
    for reader_dir in sorted(os.listdir(TEST_ROOT)):
        full_dir = os.path.join(TEST_ROOT, reader_dir)
        if not os.path.isdir(full_dir):
            continue
        files = sorted([f for f in os.listdir(full_dir) if f.lower().endswith(('.png', '.jpg')) and not f.startswith('_')])
        if files:
            readers[reader_dir] = [f"{reader_dir}/{f}" for f in files]

    return """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Pixel Inspector</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0d1117; color:#c9d1d9; font-family:'SF Mono','Menlo',monospace; font-size:13px; }
.topbar { padding:8px 12px; background:#161b22; border-bottom:1px solid #30363d; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.topbar h1 { color:#58a6ff; font-size:16px; }
.topbar a { color:#58a6ff; font-size:12px; }
.topbar select { background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:3px 6px; color:#c9d1d9; font-family:inherit; font-size:12px; max-width:400px; }
.topbar button { padding:3px 10px; background:#21262d; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; cursor:pointer; font-family:inherit; font-size:12px; }
.topbar button:hover { background:#30363d; }

.main { display:flex; height:calc(100vh - 44px); }
.canvas-wrap { flex:1; position:relative; overflow:hidden; cursor:crosshair; }
canvas { position:absolute; top:0; left:0; }

.sidebar { width:320px; background:#161b22; border-left:1px solid #30363d; padding:10px; overflow-y:auto; flex-shrink:0; }
.sidebar h3 { color:#58a6ff; font-size:13px; margin:8px 0 4px; }
.box-item { background:#21262d; border:1px solid #30363d; border-radius:4px; padding:6px 8px; margin:4px 0; font-size:11px; }
.box-item .coords { color:#58a6ff; font-weight:bold; }
.box-item .rgb { color:#3fb950; }
.box-item .ratio { color:#d29922; }
.box-item .cpp { color:#8b949e; font-size:10px; word-break:break-all; }
.box-item button { padding:1px 6px; background:#da3633; border:none; border-radius:3px; color:#fff; cursor:pointer; font-size:10px; float:right; }
.live-info { background:#21262d; border:1px solid #30363d; border-radius:4px; padding:6px 8px; margin:4px 0; font-size:11px; }
.hint { color:#484f58; font-size:10px; margin:6px 0; }
</style>
</head><body>

<div class="topbar">
    <h1>Inspector</h1>
    <a href="/">Gallery</a>
    <a href="/labeler">Labeler</a>
    <span style="color:#30363d;">|</span>
    <select id="imgSelect" onchange="loadImage(this.value)">
        <option value="">— select image —</option>
""" + "".join(
        f'<optgroup label="{reader}">' +
        "".join(f'<option value="{path}">{os.path.basename(path)}</option>' for path in files) +
        '</optgroup>'
        for reader, files in readers.items()
    ) + """
    </select>
    <button onclick="prevImage()">← Prev</button>
    <button onclick="nextImage()">Next →</button>
</div>

<div class="main">
    <div class="canvas-wrap" id="canvasWrap">
        <canvas id="canvas"></canvas>
    </div>
    <div class="sidebar">
        <div class="live-info" id="liveInfo">Hover over image for pixel info</div>
        <div class="hint">Click + drag to draw a box. Right-click to clear.</div>
        <h3>Drawn Boxes</h3>
        <div id="boxList"></div>
        <div class="hint" style="margin-top:12px;">
            Box format: ImageFloatBox(x, y, w, h)<br>
            All coordinates are normalized 0.0–1.0
        </div>
    </div>
</div>

<script>
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const wrap = document.getElementById('canvasWrap');
const sel = document.getElementById('imgSelect');

let img = null;
let zoom = 1, offX = 0, offY = 0;
let dragging = false, dragStart = null, dragEnd = null;
let panning = false, panStart = null, panOffStart = null;
let boxes = []; // [{x,y,w,h, rgb, ratio, std}]

function loadImage(path) {
    if (!path) return;
    sel.value = path;
    img = new Image();
    img.onload = () => { fitToWindow(); };
    img.src = '/img/' + path;
}

function prevImage() {
    const opts = [...sel.options].filter(o => o.value);
    const idx = opts.findIndex(o => o.value === sel.value);
    if (idx > 0) loadImage(opts[idx-1].value);
}
function nextImage() {
    const opts = [...sel.options].filter(o => o.value);
    const idx = opts.findIndex(o => o.value === sel.value);
    if (idx < opts.length - 1) loadImage(opts[idx+1].value);
}

function fitToWindow() {
    const W = wrap.clientWidth, H = wrap.clientHeight;
    canvas.width = W; canvas.height = H;
    if (!img) return;
    zoom = Math.min(W / img.naturalWidth, H / img.naturalHeight);
    offX = (W - img.naturalWidth * zoom) / 2;
    offY = (H - img.naturalHeight * zoom) / 2;
    redraw();
}

function imgToCanvas(ix, iy) { return [ix * zoom + offX, iy * zoom + offY]; }
function canvasToImg(cx, cy) { return [(cx - offX) / zoom, (cy - offY) / zoom]; }

function redraw() {
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, W, H);
    if (!img) return;

    ctx.imageSmoothingEnabled = zoom < 2;
    const [dx, dy] = imgToCanvas(0, 0);
    ctx.drawImage(img, dx, dy, img.naturalWidth * zoom, img.naturalHeight * zoom);

    // Draw saved boxes
    boxes.forEach((b, i) => {
        const [x0, y0] = imgToCanvas(b.x * img.naturalWidth, b.y * img.naturalHeight);
        const [x1, y1] = imgToCanvas((b.x+b.w) * img.naturalWidth, (b.y+b.h) * img.naturalHeight);
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2;
        ctx.strokeRect(x0, y0, x1-x0, y1-y0);
        ctx.fillStyle = 'rgba(0,255,0,0.1)';
        ctx.fillRect(x0, y0, x1-x0, y1-y0);
        ctx.fillStyle = '#00ff00';
        ctx.font = '11px monospace';
        ctx.fillText('#' + i, x0+2, y0-3);
    });

    // Draw current selection
    if (dragStart && dragEnd) {
        const [x0, y0] = imgToCanvas(dragStart[0], dragStart[1]);
        const [x1, y1] = imgToCanvas(dragEnd[0], dragEnd[1]);
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 3]);
        ctx.strokeRect(x0, y0, x1-x0, y1-y0);
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(88,166,255,0.15)';
        ctx.fillRect(x0, y0, x1-x0, y1-y0);
    }
}

// Mouse events
wrap.addEventListener('mousedown', e => {
    if (e.button === 2) { // right click = clear
        dragStart = dragEnd = null;
        redraw();
        return;
    }
    if (e.button === 1 || (e.button === 0 && e.altKey)) { // middle or alt+left = pan
        panning = true;
        panStart = [e.clientX, e.clientY];
        panOffStart = [offX, offY];
        return;
    }
    if (!img) return;
    const rect = canvas.getBoundingClientRect();
    const [ix, iy] = canvasToImg(e.clientX - rect.left, e.clientY - rect.top);
    dragStart = [ix, iy];
    dragEnd = [ix, iy];
    dragging = true;
});

wrap.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;

    if (panning && panStart) {
        offX = panOffStart[0] + (e.clientX - panStart[0]);
        offY = panOffStart[1] + (e.clientY - panStart[1]);
        redraw();
        return;
    }

    if (dragging && img) {
        dragEnd = canvasToImg(cx, cy);
        redraw();
        // Show live box info
        updateLiveBox();
        return;
    }

    // Hover info
    if (img) {
        const [ix, iy] = canvasToImg(cx, cy);
        if (ix >= 0 && iy >= 0 && ix < img.naturalWidth && iy < img.naturalHeight) {
            const px = Math.floor(ix), py = Math.floor(iy);
            // Read pixel from a temp canvas
            const tc = document.createElement('canvas');
            tc.width = 1; tc.height = 1;
            const tctx = tc.getContext('2d');
            tctx.drawImage(img, px, py, 1, 1, 0, 0, 1, 1);
            const [r, g, b] = tctx.getImageData(0, 0, 1, 1).data;
            const total = r + g + b || 1;
            document.getElementById('liveInfo').innerHTML =
                `<b>Pixel</b> (${px}, ${py}) = <b style="color:#3fb950;">(${r}, ${g}, ${b})</b><br>` +
                `<b>Normalized</b> (${(px/img.naturalWidth).toFixed(4)}, ${(py/img.naturalHeight).toFixed(4)})<br>` +
                `<b>Ratio</b> <span style="color:#d29922;">(${(r/total).toFixed(3)}, ${(g/total).toFixed(3)}, ${(b/total).toFixed(3)})</span>`;
        }
    }
});

wrap.addEventListener('mouseup', e => {
    if (panning) { panning = false; return; }
    if (!dragging || !img) return;
    dragging = false;
    if (dragStart && dragEnd) {
        const x0 = Math.min(dragStart[0], dragEnd[0]) / img.naturalWidth;
        const y0 = Math.min(dragStart[1], dragEnd[1]) / img.naturalHeight;
        const x1 = Math.max(dragStart[0], dragEnd[0]) / img.naturalWidth;
        const y1 = Math.max(dragStart[1], dragEnd[1]) / img.naturalHeight;
        const w = x1 - x0, h = y1 - y0;
        if (w > 0.001 && h > 0.001) {
            // Measure color stats
            const stats = measureBox(x0, y0, w, h);
            boxes.push({x: x0, y: y0, w, h, ...stats});
            updateBoxList();
        }
    }
    dragStart = dragEnd = null;
    redraw();
});

wrap.addEventListener('contextmenu', e => e.preventDefault());

wrap.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const [ix, iy] = canvasToImg(cx, cy);
    const factor = e.deltaY < 0 ? 1.15 : 1/1.15;
    zoom *= factor;
    offX = cx - ix * zoom;
    offY = cy - iy * zoom;
    redraw();
});

function measureBox(x, y, w, h) {
    if (!img) return {};
    const px = Math.round(x * img.naturalWidth), py = Math.round(y * img.naturalHeight);
    const pw = Math.round(w * img.naturalWidth), ph = Math.round(h * img.naturalHeight);
    const tc = document.createElement('canvas');
    tc.width = pw; tc.height = ph;
    const tctx = tc.getContext('2d');
    tctx.drawImage(img, px, py, pw, ph, 0, 0, pw, ph);
    const data = tctx.getImageData(0, 0, pw, ph).data;
    let rSum=0, gSum=0, bSum=0, count=0;
    for (let i = 0; i < data.length; i += 4) {
        rSum += data[i]; gSum += data[i+1]; bSum += data[i+2]; count++;
    }
    const rAvg = rSum/count, gAvg = gSum/count, bAvg = bSum/count;
    const total = rAvg + gAvg + bAvg || 1;
    // Stddev
    let variance = 0;
    for (let i = 0; i < data.length; i += 4) {
        variance += (data[i]-rAvg)**2 + (data[i+1]-gAvg)**2 + (data[i+2]-bAvg)**2;
    }
    const std = Math.sqrt(variance / (count * 3));
    return {
        rgb: [Math.round(rAvg), Math.round(gAvg), Math.round(bAvg)],
        ratio: [(rAvg/total).toFixed(3), (gAvg/total).toFixed(3), (bAvg/total).toFixed(3)],
        std: std.toFixed(1),
        pixels: `${pw}x${ph}`,
    };
}

function updateLiveBox() {
    if (!dragStart || !dragEnd || !img) return;
    const x0 = Math.min(dragStart[0], dragEnd[0]) / img.naturalWidth;
    const y0 = Math.min(dragStart[1], dragEnd[1]) / img.naturalHeight;
    const x1 = Math.max(dragStart[0], dragEnd[0]) / img.naturalWidth;
    const y1 = Math.max(dragStart[1], dragEnd[1]) / img.naturalHeight;
    const w = x1 - x0, h = y1 - y0;
    if (w < 0.001 || h < 0.001) return;
    const s = measureBox(x0, y0, w, h);
    document.getElementById('liveInfo').innerHTML =
        `<b>Selection</b> ${s.pixels}<br>` +
        `<span class="coords">ImageFloatBox(${x0.toFixed(4)}, ${y0.toFixed(4)}, ${w.toFixed(4)}, ${h.toFixed(4)})</span><br>` +
        `<b>RGB</b> <span style="color:#3fb950;">(${s.rgb})</span>  <b>Ratio</b> <span style="color:#d29922;">(${s.ratio})</span>  <b>Std</b> ${s.std}`;
}

function updateBoxList() {
    const list = document.getElementById('boxList');
    list.innerHTML = '';
    boxes.forEach((b, i) => {
        const div = document.createElement('div');
        div.className = 'box-item';
        div.innerHTML =
            `<button onclick="removeBox(${i})">×</button>` +
            `<b>#${i}</b> <span class="coords">(${b.x.toFixed(4)}, ${b.y.toFixed(4)}, ${b.w.toFixed(4)}, ${b.h.toFixed(4)})</span><br>` +
            `<span class="rgb">RGB (${b.rgb})</span> &nbsp; <span class="ratio">Ratio (${b.ratio})</span> &nbsp; Std ${b.std}<br>` +
            `<span class="cpp">ImageFloatBox(${b.x.toFixed(4)}, ${b.y.toFixed(4)}, ${b.w.toFixed(4)}, ${b.h.toFixed(4)})</span>`;
        list.appendChild(div);
    });
    redraw();
}

function removeBox(i) {
    boxes.splice(i, 1);
    updateBoxList();
}

window.addEventListener('resize', fitToWindow);
document.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft') prevImage();
    if (e.key === 'ArrowRight') nextImage();
});

// Auto-load from URL params
const params = new URLSearchParams(location.search);
if (params.get('img')) loadImage(params.get('img'));
</script>
</body></html>"""


def _extract_timestamp(filename):
    """Extract timestamp prefix from a labeled test frame filename.

    Filenames look like: 20260423-183259675247_True.png
    or: screenshot-20260427-132603218579_s0_38.png
    or: team_preview_True.png (legacy manual names)

    Returns the timestamp prefix (everything before the first label suffix).
    """
    base = os.path.splitext(filename)[0]
    # Match timestamp pattern: digits-digits at the start (with optional prefix)
    m = re.match(r'^((?:[a-z_]+-)?[\d]+-[\d]+)', base)
    if m:
        return m.group(1)
    # Legacy names without timestamps — use the full base minus label suffixes
    # Strip trailing _True, _False, _s0_xxx etc.
    cleaned = re.sub(r'_(?:True|False|s\d+_\S+|\d+)$', '', base)
    return cleaned or base


def _extract_label(filename):
    """Extract the label portion from a test frame filename.

    E.g. '20260423-150121863579_True.png' -> 'True'
         '20260423-150248328346_0_False.png' -> '0_False'
         'team_preview_True.png' -> 'True'
    """
    base = os.path.splitext(filename)[0]
    ts = _extract_timestamp(filename)
    suffix = base[len(ts):]
    # Strip leading underscore
    if suffix.startswith("_"):
        suffix = suffix[1:]
    return suffix


def build_labeler_page():
    # Collect unique frames by timestamp, track which readers have labeled each
    # labels: {reader_name: label_string} for each frame
    all_frames = {}  # timestamp -> {path, labeled_for: set, labels: dict}
    for reader_dir in sorted(os.listdir(TEST_ROOT)):
        full_dir = os.path.join(TEST_ROOT, reader_dir)
        if not os.path.isdir(full_dir):
            continue
        for f in os.listdir(full_dir):
            if not f.lower().endswith((".png", ".jpg")):
                continue
            if f.startswith("_"):  # skipped frames
                continue
            ts = _extract_timestamp(f)
            if ts not in all_frames:
                all_frames[ts] = {"path": f"{reader_dir}/{f}", "labeled_for": set(), "labels": {}}
            all_frames[ts]["labeled_for"].add(reader_dir)
            all_frames[ts]["labels"][reader_dir] = _extract_label(f)

    frames = [{"filename": k, "path": v["path"],
               "labeled_for": sorted(v["labeled_for"]),
               "labels": v["labels"]}
              for k, v in sorted(all_frames.items())]

    # Find one example image per reader (prefer True-labeled for bool detectors)
    reader_examples = {}
    for reader_dir in sorted(os.listdir(TEST_ROOT)):
        full_dir = os.path.join(TEST_ROOT, reader_dir)
        if not os.path.isdir(full_dir):
            continue
        for f in sorted(os.listdir(full_dir)):
            if not f.lower().endswith((".png", ".jpg")):
                continue
            if f.startswith("_"):
                continue
            label = _extract_label(f)
            path = f"{reader_dir}/{f}"
            if reader_dir not in reader_examples:
                reader_examples[reader_dir] = path  # fallback: first file
            if label.startswith("True") or (not label.startswith("False") and "_" not in label):
                reader_examples[reader_dir] = path
                break  # got a positive example, done

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Multi-Reader Labeler</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:'SF Mono','Menlo',monospace; font-size:13px; padding:16px; }}
a {{ color:#58a6ff; }}

/* ── Top bar ── */
.topbar {{ position:sticky; top:0; background:#0d1117; z-index:20; padding:8px 0 12px; border-bottom:1px solid #21262d; margin-bottom:12px; }}
.topbar h1 {{ color:#58a6ff; font-size:18px; margin-bottom:6px; display:inline; }}
.topbar .nav-links {{ font-size:12px; margin-left:16px; }}

/* ── Reader selector ── */
.reader-bar {{ display:flex; flex-wrap:wrap; gap:4px; margin:8px 0; }}
.reader-btn {{ padding:4px 10px; background:#21262d; color:#8b949e; border:1px solid #30363d; border-radius:6px; font-size:11px; cursor:pointer; font-family:inherit; white-space:nowrap; }}
.reader-btn:hover {{ background:#30363d; color:#c9d1d9; }}
.reader-btn.active {{ background:#1f6feb; color:#fff; border-color:#1f6feb; }}
.reader-btn .count {{ font-size:9px; opacity:0.7; margin-left:3px; }}

/* ── Progress ── */
.progress-bar {{ height:4px; background:#21262d; border-radius:2px; margin:8px 0; overflow:hidden; }}
.progress-fill {{ height:100%; background:#238636; transition:width 0.3s; }}
.progress-text {{ font-size:11px; color:#8b949e; margin-bottom:8px; }}

/* ── Filter tabs ── */
.filter-bar {{ display:flex; gap:8px; align-items:center; margin-bottom:8px; }}
.filter-btn {{ padding:2px 8px; background:transparent; color:#8b949e; border:1px solid transparent; border-radius:4px; font-size:11px; cursor:pointer; font-family:inherit; }}
.filter-btn:hover {{ color:#c9d1d9; }}
.filter-btn.active {{ color:#c9d1d9; border-color:#30363d; background:#21262d; }}
.shortcut-hint {{ font-size:10px; color:#484f58; margin-left:auto; }}

/* ── Frame card ── */
.frame-card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 12px; margin-bottom:6px; }}
.frame-card.active {{ border-color:#1f6feb; box-shadow:0 0 0 1px #1f6feb; }}
.frame-card.labeled {{ opacity:0.5; }}
.frame-card.skipped {{ opacity:0.2; }}
.frame-card.hidden {{ display:none; }}

.card-row {{ display:flex; gap:12px; align-items:flex-start; }}
.card-thumb {{ flex-shrink:0; cursor:pointer; }}
.card-thumb img {{ width:240px; height:auto; border-radius:4px; border:1px solid #30363d; }}
.card-thumb img.expanded {{ width:600px; }}

.card-content {{ flex:1; min-width:0; }}
.card-top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }}
.card-filename {{ color:#58a6ff; font-size:11px; font-weight:bold; }}
.card-tags {{ display:flex; gap:3px; flex-wrap:wrap; }}
.tag {{ padding:1px 5px; border-radius:3px; font-size:9px; background:#21262d; color:#8b949e; }}
.tag.done {{ background:#238636; color:#fff; }}

/* ── Crop row ── */
.crop-row {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }}
.crop-cell {{ text-align:center; }}
.crop-cell canvas {{ border:1px solid #30363d; border-radius:3px; image-rendering:pixelated; display:block; margin-bottom:2px; }}
.crop-name {{ font-size:9px; color:#8b949e; }}

/* ── Label buttons ── */
.label-actions {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}
.lbl-btn {{ padding:6px 16px; border:1px solid #30363d; border-radius:6px; background:#21262d; color:#c9d1d9; cursor:pointer; font-size:13px; font-family:inherit; font-weight:bold; min-width:48px; text-align:center; }}
.lbl-btn:hover {{ background:#30363d; }}
.lbl-btn.true {{ border-color:#238636; }}
.lbl-btn.true:hover, .lbl-btn.true.selected {{ background:#238636; color:#fff; }}
.lbl-btn.false {{ border-color:#da3633; }}
.lbl-btn.false:hover, .lbl-btn.false.selected {{ background:#da3633; color:#fff; }}
.lbl-btn.int-btn:hover, .lbl-btn.int-btn.selected {{ background:#1f6feb; color:#fff; border-color:#1f6feb; }}
.lbl-btn.skip {{ color:#8b949e; font-weight:normal; font-size:11px; }}
.lbl-btn.skip:hover {{ background:#30363d; }}

.word-inputs {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}
.word-inputs label {{ font-size:10px; color:#8b949e; }}
.word-inputs input {{ background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:4px 8px; color:#c9d1d9; font-family:inherit; font-size:12px; width:140px; }}
.btn-save {{ padding:5px 14px; border:1px solid #238636; border-radius:6px; background:#238636; color:#fff; cursor:pointer; font-size:12px; font-family:inherit; font-weight:bold; }}
.btn-save:hover {{ background:#2ea043; }}

.save-status {{ font-size:11px; color:#3fb950; margin-left:6px; }}
.help-text {{ font-size:10px; color:#6e7681; margin-bottom:6px; }}
</style>
</head><body>

<div class="topbar">
    <h1>Labeler</h1>
    <span class="nav-links">
        <a href="/">Gallery</a>
        <span style="color:#30363d;margin:0 6px;">|</span>
        <a href="/templates">Templates</a>
    </span>
    <div class="reader-bar" id="readerBar"></div>
    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
    <div style="display:flex;align-items:center;gap:12px;">
        <span class="progress-text" id="progressText"></span>
        <div class="filter-bar">
            <button class="filter-btn active" data-filter="unlabeled" onclick="setFilter('unlabeled')">Unlabeled</button>
            <button class="filter-btn" data-filter="all" onclick="setFilter('all')">All</button>
            <button class="filter-btn" data-filter="labeled" onclick="setFilter('labeled')">Labeled</button>
            <button class="filter-btn" data-filter="true" id="filterTrue" style="display:none;color:#3fb950;" onclick="setFilter('true')">True</button>
            <button class="filter-btn" data-filter="false" id="filterFalse" style="display:none;color:#f85149;" onclick="setFilter('false')">False</button>
        </div>
        <button class="lbl-btn" id="bulkFalseBtn" style="display:none;font-size:11px;padding:3px 10px;border-color:#da3633;color:#f85149;" onclick="bulkLabelPage(false)">Mark page False</button>
        <button class="lbl-btn" id="bulkTrueBtn" style="display:none;font-size:11px;padding:3px 10px;border-color:#238636;color:#3fb950;" onclick="bulkLabelPage(true)">Mark page True</button>
        <span class="shortcut-hint" id="shortcutHint"></span>
    </div>
</div>

<div id="refExample" style="display:none;margin-bottom:10px;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 12px;">
    <div style="display:flex;gap:12px;align-items:flex-start;">
        <div style="flex-shrink:0;">
            <div style="font-size:10px;color:#8b949e;margin-bottom:4px;">Reference (positive example)</div>
            <img id="refImg" style="max-width:360px;height:auto;border-radius:4px;border:1px solid #30363d;cursor:pointer;" onclick="this.style.maxWidth=this.style.maxWidth==='360px'?'700px':'360px'">
        </div>
        <div id="refCrops" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;"></div>
    </div>
</div>
<div id="frames"></div>

<script>
const FRAMES = {json.dumps(frames, default=str)};
const READERS = {json.dumps(LABELER_READERS, default=str)};
const READER_EXAMPLES = {json.dumps(reader_examples)};

let activeReader = null;  // index into READERS
let activeFrame = -1;     // index into FRAMES
let filter = 'unlabeled';
let imgCache = {{}};       // fi -> Image
const BATCH_SIZE = 40;
let filteredFrames = [];  // filtered frame list
let renderedCount = 0;    // how many of filteredFrames we've rendered

function init() {{
    // Build reader selector grouped by type
    const bar = document.getElementById('readerBar');
    let lastType = null;
    READERS.forEach((r, ri) => {{
        if (lastType && r.type !== lastType) {{
            const sep = document.createElement('span');
            sep.style.cssText = 'width:1px;height:20px;background:#30363d;margin:0 4px;';
            bar.appendChild(sep);
        }}
        lastType = r.type;
        const btn = document.createElement('button');
        btn.className = 'reader-btn';
        btn.dataset.ri = ri;
        btn.innerHTML = r.name;
        btn.onclick = () => selectReader(ri);
        bar.appendChild(btn);
    }});

    // Select first reader
    selectReader(0);

    // Keyboard shortcuts
    document.addEventListener('keydown', handleKey);
}}

function selectReader(ri) {{
    activeReader = ri;
    // Update button states
    document.querySelectorAll('.reader-btn').forEach(b => {{
        b.classList.toggle('active', parseInt(b.dataset.ri) === ri);
    }});
    // Update shortcut hint
    const r = READERS[ri];
    const isBool = r.type === 'bool';
    document.getElementById('bulkFalseBtn').style.display = isBool ? '' : 'none';
    document.getElementById('bulkTrueBtn').style.display = isBool ? '' : 'none';
    document.getElementById('filterTrue').style.display = isBool ? '' : 'none';
    document.getElementById('filterFalse').style.display = isBool ? '' : 'none';
    // Reset to 'unlabeled' when switching readers
    filter = 'unlabeled';
    document.querySelectorAll('.filter-btn').forEach(b => {{
        b.classList.toggle('active', b.dataset.filter === 'unlabeled');
    }});
    if (isBool) {{
        document.getElementById('shortcutHint').textContent = 'Keys: T=True  F=False  S=Skip  ↓=Next  ↑=Prev';
    }} else if (r.type === 'int') {{
        document.getElementById('shortcutHint').textContent = 'Keys: 0-9=Value  S=Skip  ↓=Next  ↑=Prev';
    }} else {{
        document.getElementById('shortcutHint').textContent = 'Keys: Enter=Save  S=Skip  ↓=Next  ↑=Prev';
    }}

    // Show reference example image
    const refBox = document.getElementById('refExample');
    const exPath = READER_EXAMPLES[r.name];
    if (exPath) {{
        refBox.style.display = '';
        const refImg = document.getElementById('refImg');
        refImg.src = '/img/' + exPath;
        refImg.style.maxWidth = '360px';
        // Render crop previews on the reference image
        const refCrops = document.getElementById('refCrops');
        refCrops.innerHTML = '';
        if (r.crops && r.crops.length > 0) {{
            const img = new Image();
            img.onload = () => {{
                r.crops.forEach(crop => {{
                    const W = img.naturalWidth, H = img.naturalHeight;
                    const box = crop.box;
                    const cx = Math.round(box[0]*W), cy = Math.round(box[1]*H);
                    const cw = Math.round(box[2]*W), ch = Math.round(box[3]*H);
                    if (cw <= 0 || ch <= 0) return;
                    const scale = 3;
                    const canvas = document.createElement('canvas');
                    canvas.width = cw * scale; canvas.height = ch * scale;
                    canvas.style.cssText = 'border:1px solid #30363d;border-radius:3px;image-rendering:pixelated;';
                    const ctx = canvas.getContext('2d');
                    ctx.imageSmoothingEnabled = false;
                    ctx.drawImage(img, cx, cy, cw, ch, 0, 0, cw*scale, ch*scale);
                    const cell = document.createElement('div');
                    cell.style.textAlign = 'center';
                    cell.appendChild(canvas);
                    const label = document.createElement('div');
                    label.style.cssText = 'font-size:9px;color:#8b949e;';
                    label.textContent = crop.name;
                    cell.appendChild(label);
                    refCrops.appendChild(cell);
                }});
            }};
            img.src = '/img/' + exPath;
        }}
    }} else {{
        refBox.style.display = 'none';
    }}

    renderFrames();
}}

function setFilter(f) {{
    filter = f;
    document.querySelectorAll('.filter-btn').forEach(b => {{
        b.classList.toggle('active', b.dataset.filter === f);
    }});
    renderFrames();
}}

function isLabeledFor(frame, readerName) {{
    return frame.labeled_for.includes(readerName);
}}

function renderFrames() {{
    const container = document.getElementById('frames');
    container.innerHTML = '';
    const reader = READERS[activeReader];

    // Build filtered list
    filteredFrames = [];
    let totalForReader = 0;
    let labeledCount = 0;

    FRAMES.forEach((frame, fi) => {{
        totalForReader++;
        const labeled = isLabeledFor(frame, reader.name);
        if (labeled) labeledCount++;
        const label = (frame.labels || {{}})[reader.name] || '';
        if (filter === 'unlabeled' && labeled) return;
        if (filter === 'labeled' && !labeled) return;
        if (filter === 'true' && !(labeled && label.startsWith('True'))) return;
        if (filter === 'false' && !(labeled && label.startsWith('False'))) return;
        filteredFrames.push({{ fi, frame, labeled }});
    }});

    // Update progress
    const pct = totalForReader > 0 ? (labeledCount / totalForReader * 100) : 0;
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressText').textContent = labeledCount + '/' + totalForReader + ' labeled (' + filteredFrames.length + ' shown)';

    // Render first batch
    renderedCount = 0;
    renderBatch();

    // Auto-select first frame
    if (filteredFrames.length > 0) {{
        setActiveFrame(filteredFrames[0].fi);
    }}
}}

function renderBatch() {{
    const container = document.getElementById('frames');
    const reader = READERS[activeReader];
    const end = Math.min(renderedCount + BATCH_SIZE, filteredFrames.length);

    // Remove existing "load more" button
    const oldBtn = document.getElementById('load-more-btn');
    if (oldBtn) oldBtn.remove();

    for (let idx = renderedCount; idx < end; idx++) {{
        const {{ fi, frame, labeled }} = filteredFrames[idx];
        container.appendChild(buildCard(fi, frame, labeled, reader));
        renderCrops(fi, reader);
    }}
    renderedCount = end;

    // Bottom bulk buttons (bool readers only)
    const oldBulk = document.getElementById('bottom-bulk');
    if (oldBulk) oldBulk.remove();
    if (reader.type === 'bool') {{
        const bulk = document.createElement('div');
        bulk.id = 'bottom-bulk';
        bulk.style.cssText = 'display:flex;gap:8px;justify-content:center;margin:12px 0;';
        bulk.innerHTML = '<button class="lbl-btn" style="font-size:12px;padding:8px 20px;border-color:#da3633;color:#f85149;" onclick="bulkLabelPage(false)">Mark page False</button>'
            + '<button class="lbl-btn" style="font-size:12px;padding:8px 20px;border-color:#238636;color:#3fb950;" onclick="bulkLabelPage(true)">Mark page True</button>';
        container.appendChild(bulk);
    }}

    // Add "load more" if there are more
    if (renderedCount < filteredFrames.length) {{
        const btn = document.createElement('button');
        btn.id = 'load-more-btn';
        btn.className = 'lbl-btn';
        btn.style.cssText = 'display:block;width:100%;padding:12px;margin:12px 0;text-align:center;font-size:14px;';
        btn.textContent = 'Load more (' + (filteredFrames.length - renderedCount) + ' remaining)';
        btn.onclick = () => renderBatch();
        container.appendChild(btn);
    }}
}}

function buildCard(fi, frame, labeled, reader) {{
    const card = document.createElement('div');
    card.className = 'frame-card' + (labeled ? ' labeled' : '');
    card.id = 'frame-' + fi;
    card.dataset.fi = fi;

    const otherTags = frame.labeled_for
        .filter(r => r !== reader.name)
        .slice(0, 3)
        .map(r => '<span class="tag done">' + r + '</span>')
        .join('');
    const labeledTag = labeled ? '<span class="tag done">' + reader.name + '</span>' : '';

    let labelsHtml = '';
    if (reader.type === 'bool') {{
        labelsHtml = '<div class="label-actions">'
            + '<button class="lbl-btn true" onclick="labelBool(' + fi + ',true)">True</button>'
            + '<button class="lbl-btn false" onclick="labelBool(' + fi + ',false)">False</button>'
            + '<button class="lbl-btn skip" onclick="skipFrame(' + fi + ')">Skip</button>'
            + '<span class="save-status" id="status-' + fi + '"></span>'
            + '</div>';
    }} else if (reader.type === 'int') {{
        let btns = '';
        for (let v = 0; v <= 3; v++) {{
            btns += '<button class="lbl-btn int-btn" onclick="labelInt(' + fi + ',' + v + ')">' + v + '</button>';
        }}
        labelsHtml = '<div class="label-actions">'
            + btns
            + '<button class="lbl-btn skip" onclick="skipFrame(' + fi + ')">Skip</button>'
            + '<span class="save-status" id="status-' + fi + '"></span>'
            + '</div>';
    }} else if (reader.type === 'slot_words') {{
        let inputs = '';
        (reader.slots || []).forEach((slot, si) => {{
            inputs += '<label>' + slot + '</label>'
                + '<input id="wlabel-' + fi + '-' + si + '" placeholder="species slug">';
        }});
        labelsHtml = '<div class="word-inputs">'
            + inputs
            + '<button class="btn-save" onclick="labelSlotWords(' + fi + ')">Save</button>'
            + '<button class="lbl-btn skip" onclick="skipFrame(' + fi + ')">Skip</button>'
            + '<span class="save-status" id="status-' + fi + '"></span>'
            + '</div>';
    }} else if (reader.type === 'words') {{
        let inputs = '';
        (reader.crops || []).forEach((crop, ci) => {{
            inputs += '<label>' + crop.name + '</label>'
                + '<input id="wlabel-' + fi + '-' + ci + '" placeholder="value or NONE">';
        }});
        labelsHtml = '<div class="word-inputs">'
            + inputs
            + '<button class="btn-save" onclick="labelWords(' + fi + ')">Save</button>'
            + '<button class="lbl-btn skip" onclick="skipFrame(' + fi + ')">Skip</button>'
            + '<span class="save-status" id="status-' + fi + '"></span>'
            + '</div>';
    }}

    card.innerHTML = '<div class="card-row">'
        + '<div class="card-thumb" onclick="this.querySelector(&quot;img&quot;).classList.toggle(&quot;expanded&quot;)">'
        + '<img src="/img/' + frame.path + '" loading="lazy">'
        + '</div>'
        + '<div class="card-content">'
        + '<div class="card-top">'
        + '<span class="card-filename">' + frame.filename + '</span>'
        + '<div class="card-tags">' + labeledTag + otherTags + '</div>'
        + '</div>'
        + (reader.help ? '<div class="help-text">' + reader.help + '</div>' : '')
        + '<div class="crop-row" id="crops-' + fi + '"></div>'
        + labelsHtml
        + '</div>'
        + '</div>';

    card.onclick = (e) => {{
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT') return;
        setActiveFrame(fi);
    }};

    return card;
}}

function renderCrops(fi, reader) {{
    if (!reader.crops || reader.crops.length === 0) return;
    const frame = FRAMES[fi];
    const container = document.getElementById('crops-' + fi);
    if (!container) return;

    const loadImg = (img) => {{
        reader.crops.forEach((crop, ci) => {{
            const canvas = document.createElement('canvas');
            const W = img.naturalWidth, H = img.naturalHeight;
            const box = crop.box;
            const cx = Math.round(box[0]*W), cy = Math.round(box[1]*H);
            const cw = Math.round(box[2]*W), ch = Math.round(box[3]*H);
            if (cw <= 0 || ch <= 0) return;
            const scale = 3;
            canvas.width = cw * scale; canvas.height = ch * scale;
            const ctx = canvas.getContext('2d');
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(img, cx, cy, cw, ch, 0, 0, cw*scale, ch*scale);

            const cell = document.createElement('div');
            cell.className = 'crop-cell';
            cell.appendChild(canvas);
            const label = document.createElement('div');
            label.className = 'crop-name';
            label.textContent = crop.name;
            cell.appendChild(label);
            container.appendChild(cell);
        }});
    }};

    if (imgCache[fi]) {{
        loadImg(imgCache[fi]);
    }} else {{
        const img = new Image();
        img.onload = () => {{ imgCache[fi] = img; loadImg(img); }};
        img.src = '/img/' + frame.path;
    }}
}}

function setActiveFrame(fi) {{
    document.querySelectorAll('.frame-card.active').forEach(c => c.classList.remove('active'));
    const card = document.getElementById('frame-' + fi);
    if (card) {{
        card.classList.add('active');
        activeFrame = fi;
        // Scroll into view if needed
        const rect = card.getBoundingClientRect();
        if (rect.top < 120 || rect.bottom > window.innerHeight) {{
            card.scrollIntoView({{ behavior:'smooth', block:'center' }});
        }}
    }}
}}

function advanceToNext(fi) {{
    const reader = READERS[activeReader];

    // Mark current card
    const cur = document.getElementById('frame-' + fi);
    if (cur) {{
        cur.classList.add('labeled');
        if (filter === 'unlabeled') cur.classList.add('hidden');
    }}

    // Find next unlabeled in rendered cards
    const cards = document.querySelectorAll('.frame-card:not(.hidden):not(.skipped):not(.labeled)');
    let found = false;
    for (const card of cards) {{
        const cfi = parseInt(card.dataset.fi);
        if (cfi > fi) {{
            setActiveFrame(cfi);
            found = true;
            break;
        }}
    }}

    // If not found, try loading more
    if (!found && renderedCount < filteredFrames.length) {{
        renderBatch();
        // Try again after loading
        const newCards = document.querySelectorAll('.frame-card:not(.hidden):not(.skipped):not(.labeled)');
        for (const card of newCards) {{
            setActiveFrame(parseInt(card.dataset.fi));
            found = true;
            break;
        }}
    }}

    updateProgress();
}}

function updateProgress() {{
    const reader = READERS[activeReader];
    let total = FRAMES.length;
    let labeled = FRAMES.filter(f => isLabeledFor(f, reader.name)).length;
    const remaining = filteredFrames.length - labeled;
    const pct = total > 0 ? (labeled / total * 100) : 0;
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressText').textContent = labeled + '/' + total + ' labeled';
}}

// ── Label actions ──

async function doSave(fi, labelParts, perSlot) {{
    const frame = FRAMES[fi];
    const reader = READERS[activeReader];
    const status = document.getElementById('status-' + fi);

    const base = frame.filename.replace(/\.png$/i, '');

    if (perSlot) {{
        // slot_words: save per-slot
        let ok = true;
        for (let si = 0; si < perSlot.length; si++) {{
            if (!perSlot[si]) continue;
            const labelFile = base + '_s' + si + '_' + perSlot[si] + '.png';
            const resp = await fetch('/api/label/save', {{
                method:'POST', headers:{{'Content-Type':'application/json'}},
                body: JSON.stringify({{ source: frame.path, reader: reader.name, label: labelFile }}),
            }});
            const result = await resp.json();
            if (!result.ok) {{ if (status) status.textContent = 'Error'; ok = false; break; }}
        }}
        if (ok) {{
            if (status) status.textContent = 'Saved';
            if (!frame.labeled_for.includes(reader.name)) frame.labeled_for.push(reader.name);
            if (!frame.labels) frame.labels = {{}};
            frame.labels[reader.name] = perSlot.filter(Boolean).join('_');
            advanceToNext(fi);
        }}
        return;
    }}

    const labelFile = base + '_' + labelParts.join('_') + '.png';
    const resp = await fetch('/api/label/save', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{ source: frame.path, reader: reader.name, label: labelFile }}),
    }});
    const result = await resp.json();
    if (result.ok) {{
        if (status) status.textContent = 'Saved';
        if (!frame.labeled_for.includes(reader.name)) frame.labeled_for.push(reader.name);
        if (!frame.labels) frame.labels = {{}};
        frame.labels[reader.name] = labelParts.join('_');
        advanceToNext(fi);
    }} else {{
        if (status) status.textContent = 'Error';
    }}
}}

function labelBool(fi, val) {{
    doSave(fi, [val ? 'True' : 'False']);
}}

function labelInt(fi, val) {{
    doSave(fi, [String(val)]);
}}

function labelSlotWords(fi) {{
    const reader = READERS[activeReader];
    const slots = [];
    let any = false;
    (reader.slots || []).forEach((_, si) => {{
        const el = document.getElementById('wlabel-' + fi + '-' + si);
        const v = el ? el.value.trim() : '';
        slots.push(v || null);
        if (v) any = true;
    }});
    if (!any) return;
    doSave(fi, [], slots);
}}

function labelWords(fi) {{
    const reader = READERS[activeReader];
    const vals = [];
    let any = false;
    (reader.crops || []).forEach((_, ci) => {{
        const el = document.getElementById('wlabel-' + fi + '-' + ci);
        const v = el ? el.value.trim() : '';
        vals.push(v || 'NONE');
        if (v) any = true;
    }});
    if (!any) return;
    doSave(fi, vals);
}}

async function skipFrame(fi) {{
    const frame = FRAMES[fi];
    const resp = await fetch('/api/label/skip', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{ source: frame.path }}),
    }});
    const result = await resp.json();
    if (result.ok) {{
        const card = document.getElementById('frame-' + fi);
        if (card) {{ card.classList.add('skipped'); }}
        advanceToNext(fi);
    }}
}}

// ── Bulk actions ──

async function bulkLabelPage(val) {{
    const reader = READERS[activeReader];
    if (reader.type !== 'bool') return;
    const cards = document.querySelectorAll('.frame-card:not(.hidden):not(.skipped):not(.labeled)');
    const label = val ? 'True' : 'False';
    const btn = val ? document.getElementById('bulkTrueBtn') : document.getElementById('bulkFalseBtn');
    const count = cards.length;
    if (count === 0) return;
    btn.disabled = true;
    btn.textContent = 'Saving 0/' + count + '...';
    let done = 0;
    for (const card of cards) {{
        const fi = parseInt(card.dataset.fi);
        const frame = FRAMES[fi];
        const base = frame.filename;
        const labelFile = base + '_' + label + '.png';
        const resp = await fetch('/api/label/save', {{
            method:'POST', headers:{{'Content-Type':'application/json'}},
            body: JSON.stringify({{ source: frame.path, reader: reader.name, label: labelFile }}),
        }});
        const result = await resp.json();
        if (result.ok) {{
            if (!frame.labeled_for.includes(reader.name)) frame.labeled_for.push(reader.name);
            if (!frame.labels) frame.labels = {{}};
            frame.labels[reader.name] = label;
            card.classList.add('labeled');
            if (filter === 'unlabeled') card.classList.add('hidden');
        }}
        done++;
        btn.textContent = 'Saving ' + done + '/' + count + '...';
    }}
    btn.disabled = false;
    btn.textContent = val ? 'Mark page True' : 'Mark page False';
    updateProgress();
}}

// ── Keyboard shortcuts ──

function handleKey(e) {{
    // Don't trigger when typing in inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {{
        if (e.key === 'Enter') {{
            // Save words/slot_words on Enter
            const reader = READERS[activeReader];
            if (activeFrame >= 0 && (reader.type === 'words' || reader.type === 'slot_words')) {{
                if (reader.type === 'slot_words') labelSlotWords(activeFrame);
                else labelWords(activeFrame);
            }}
        }}
        return;
    }}

    if (activeFrame < 0 || activeReader === null) return;
    const reader = READERS[activeReader];
    const key = e.key.toLowerCase();

    if (reader.type === 'bool') {{
        if (key === 't') {{ e.preventDefault(); labelBool(activeFrame, true); }}
        else if (key === 'f') {{ e.preventDefault(); labelBool(activeFrame, false); }}
    }} else if (reader.type === 'int') {{
        if (key >= '0' && key <= '9') {{ e.preventDefault(); labelInt(activeFrame, parseInt(key)); }}
    }}

    if (key === 's') {{ e.preventDefault(); skipFrame(activeFrame); }}

    // Arrow navigation
    if (e.key === 'ArrowDown' || key === 'j') {{
        e.preventDefault();
        const cards = [...document.querySelectorAll('.frame-card:not(.hidden):not(.skipped)')];
        const curIdx = cards.findIndex(c => parseInt(c.dataset.fi) === activeFrame);
        if (curIdx < cards.length - 1) setActiveFrame(parseInt(cards[curIdx + 1].dataset.fi));
    }}
    if (e.key === 'ArrowUp' || key === 'k') {{
        e.preventDefault();
        const cards = [...document.querySelectorAll('.frame-card:not(.hidden):not(.skipped)')];
        const curIdx = cards.findIndex(c => parseInt(c.dataset.fi) === activeFrame);
        if (curIdx > 0) setActiveFrame(parseInt(cards[curIdx - 1].dataset.fi));
    }}
}}

init();
</script>
</body></html>"""


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    global READERS, RESULTS

    args = sys.argv[1:]
    reader_filter = None
    run_initial = False

    i = 0
    while i < len(args):
        if args[i] == "--reader" and i + 1 < len(args):
            reader_filter = args[i + 1]
            i += 2
        elif args[i] == "--run":
            run_initial = True
            i += 1
        else:
            i += 1

    READERS = discover_readers(TEST_ROOT)
    if reader_filter:
        READERS = [r for r in READERS if reader_filter.lower() in r.lower()]
        if not READERS:
            print(f"No readers matching '{reader_filter}'")
            sys.exit(1)

    if run_initial:
        print("Running initial regression...", flush=True)
        RESULTS = run_regression()
        p = sum(1 for r in RESULTS.values() if isinstance(r, dict) and r.get("passed"))
        f = sum(1 for r in RESULTS.values() if isinstance(r, dict) and not r.get("passed"))
        print(f"  {p} pass, {f} fail", flush=True)

    port = 8789
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"OCR Gallery at http://localhost:{port}")
    print(f"Readers: {', '.join(READERS)}")
    webbrowser.open(f"http://localhost:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
