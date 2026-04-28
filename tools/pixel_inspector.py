#!/usr/bin/env python3
"""
Pixel Inspector — interactive tool for tuning PokemonAutomation detectors.

NOTE: The web-based Inspector at champions.colefoster.ca (Dashboard → Inspector tab)
replaces this tool for most workflows. It has click-drag box drawing, crop preview,
binarized preview, is_solid() tests, C++ code generation, and save-to-box_definitions.
Use this tkinter version only if you need offline/local-only measurement.

Opens a screenshot, lets you drag-select regions, and outputs:
  - ImageFloatBox coordinates (normalized 0.0-1.0)
  - image_stats() equivalent (average RGB, stddev per channel)
  - Color ratio (r/(r+g+b), ...)
  - is_solid() result with configurable thresholds
  - Copy-pasteable C++ declarations

Usage:
  python3 tools/pixel_inspector.py                     (opens file picker)
  python3 tools/pixel_inspector.py <img> [img2] ...    (open one or more images)
  python3 tools/pixel_inspector.py <img> --box 0.9062 0.5694 0.0260 0.0185
  python3 tools/pixel_inspector.py <img> --load action_menu/fight_button
  python3 tools/pixel_inspector.py <img> --check-all
  python3 tools/pixel_inspector.py --list
  python3 tools/pixel_inspector.py --measure            (walk through pending boxes)
  python3 tools/pixel_inspector.py --measure-status      (show progress)
  python3 tools/pixel_inspector.py --remeasure <name>...  (re-open specific boxes for adjustment)

Controls (interactive mode):
  Click + drag    Select a region
  Right-click     Clear selection
  Scroll          Zoom (centered on cursor)
  Middle-drag     Pan
  Left / Right    Switch between loaded images
  o               Open more images (file picker)
  s               Save current selection
  l               Load a saved/detector box
  n / p           Cycle through loaded boxes (next/prev)
  a               Toggle all box overlays
  q               Quit

Controls (--measure mode):
  Click + drag    Select the box region
  Right-click     Clear selection
  Enter / Return  Confirm current selection and advance to next box
  Backspace       Go back to previous box
  Escape          Skip current box
  Scroll / Pan    Zoom and pan as usual
  q               Save progress and quit
"""

import json
import math
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, simpledialog
from PIL import Image, ImageTk


# ─── Paths ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SAVED_BOXES_PATH = os.path.join(SCRIPT_DIR, "pixel_inspector_boxes.json")
BOX_DEFINITIONS_PATH = os.path.join(SCRIPT_DIR, "box_definitions.json")
INFERENCE_DIR = os.path.join(
    REPO_ROOT, "SerialPrograms", "Source", "PokemonChampions", "Inference"
)


# ─── Color math (matches C++ exactly) ───────────────────────────────────────

def image_stats(pixels):
    """Compute average RGB and per-channel stddev. Matches C++ image_stats()."""
    n = len(pixels)
    if n == 0:
        return (0, 0, 0), (0, 0, 0), 0

    sum_r = sum_g = sum_b = 0
    sqr_r = sqr_g = sqr_b = 0

    for r, g, b in pixels:
        sum_r += r; sum_g += g; sum_b += b
        sqr_r += r * r; sqr_g += g * g; sqr_b += b * b

    avg = (sum_r / n, sum_g / n, sum_b / n)

    if n > 1:
        var_r = (sqr_r - sum_r * sum_r / n) / (n - 1)
        var_g = (sqr_g - sum_g * sum_g / n) / (n - 1)
        var_b = (sqr_b - sum_b * sum_b / n) / (n - 1)
        sd = (math.sqrt(max(0, var_r)), math.sqrt(max(0, var_g)), math.sqrt(max(0, var_b)))
    else:
        sd = (0, 0, 0)

    return avg, sd, n


def color_ratio(avg):
    """Compute normalized color ratio {r/(r+g+b), ...}."""
    s = avg[0] + avg[1] + avg[2]
    if s == 0:
        return (0.333, 0.333, 0.333)
    return (avg[0] / s, avg[1] / s, avg[2] / s)


def euclidean_distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def is_solid(avg, sd, expected_ratio, max_dist=0.15, max_stddev_sum=120):
    stddev_sum = sd[0] + sd[1] + sd[2]
    if stddev_sum > max_stddev_sum:
        return False, stddev_sum, None
    ratio = color_ratio(avg)
    dist = euclidean_distance(ratio, expected_ratio)
    return dist <= max_dist, stddev_sum, dist


def extract_pixels(img, x, y, w, h):
    """Extract RGB tuples from a pixel region."""
    pixels = []
    for py in range(y, min(y + h, img.height)):
        for px in range(x, min(x + w, img.width)):
            p = img.getpixel((px, py))
            pixels.append((p[0], p[1], p[2]))
    return pixels


def format_report(img_w, img_h, px_x, px_y, px_w, px_h):
    """Return the normalized box."""
    fx = px_x / img_w
    fy = px_y / img_h
    fw = px_w / img_w
    fh = px_h / img_h
    return fx, fy, fw, fh


def print_report(img, px_x, px_y, px_w, px_h, label="selection", expected=None):
    """Compute and print full analysis for a pixel region."""
    if px_w <= 0 or px_h <= 0:
        return

    fx, fy, fw, fh = format_report(img.width, img.height, px_x, px_y, px_w, px_h)
    pixels = extract_pixels(img, px_x, px_y, px_w, px_h)
    avg, sd, count = image_stats(pixels)
    ratio = color_ratio(avg)

    print()
    print(f"=== {label} ===")
    print(f"  Pixel region:  x={px_x}, y={px_y}, w={px_w}, h={px_h}  ({count} pixels)")
    print(f"  Image size:    {img.width} x {img.height}")
    print()
    print(f"  Average RGB:   ({avg[0]:.1f}, {avg[1]:.1f}, {avg[2]:.1f})")
    print(f"  Stddev RGB:    ({sd[0]:.1f}, {sd[1]:.1f}, {sd[2]:.1f})")
    print(f"  Stddev sum:    {sd[0] + sd[1] + sd[2]:.1f}")
    print(f"  Color ratio:   ({ratio[0]:.4f}, {ratio[1]:.4f}, {ratio[2]:.4f})")
    print()
    print(f"  // C++ -- paste into your detector")
    print(f"  ImageFloatBox  box({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f});")
    print(f"  FloatPixel     expected{{{ratio[0]:.2f}, {ratio[1]:.2f}, {ratio[2]:.2f}}};")

    # If an expected ratio was provided, test against it
    if expected:
        print()
        print(f"  // Testing against expected ratio ({expected[0]:.2f}, {expected[1]:.2f}, {expected[2]:.2f})")
        dist = euclidean_distance(ratio, expected)
        sdsum = sd[0] + sd[1] + sd[2]
        print(f"  Distance from expected: {dist:.4f}")
        print(f"  Stddev sum:             {sdsum:.1f}")
        for max_dist, max_sdsum in [(0.10, 100), (0.15, 120), (0.18, 150), (0.25, 200)]:
            ok = dist <= max_dist and sdsum <= max_sdsum
            tag = "PASS" if ok else "FAIL"
            reasons = []
            if dist > max_dist:
                reasons.append(f"dist {dist:.4f} > {max_dist}")
            if sdsum > max_sdsum:
                reasons.append(f"sdsum {sdsum:.1f} > {max_sdsum}")
            reason_s = "  (" + ", ".join(reasons) + ")" if reasons else ""
            print(f"  is_solid(dist={max_dist}, sdsum={max_sdsum:3d}): {tag}{reason_s}")
    else:
        print()
        # Self-test (distance is always 0 against own ratio)
        sdsum = sd[0] + sd[1] + sd[2]
        for max_dist, max_sdsum in [(0.10, 100), (0.15, 120), (0.18, 150), (0.25, 200)]:
            ok = sdsum <= max_sdsum
            tag = "PASS" if ok else "FAIL"
            reason = f"  (stddev_sum {sdsum:.1f} > {max_sdsum})" if not ok else ""
            print(f"  is_solid(dist={max_dist}, sdsum={max_sdsum:3d}): {tag}{reason}")

    print()


# ─── Box store: save/load + C++ source parsing ─────────────────────────────

def load_saved_boxes():
    """Load user-saved boxes from JSON file."""
    if os.path.exists(SAVED_BOXES_PATH):
        with open(SAVED_BOXES_PATH, "r") as f:
            return json.load(f)
    return {}


def save_boxes(boxes):
    """Save boxes to JSON file."""
    with open(SAVED_BOXES_PATH, "w") as f:
        json.dump(boxes, f, indent=2)


def parse_cpp_detectors():
    """Parse ImageFloatBox definitions from PokemonChampions C++ detector sources.

    Returns dict of "detector/variable" -> {"box": [x,y,w,h], "source": "path:line",
                                            "expected": [r,g,b] or None}

    For detectors that test a box against multiple colors (like BattleEndDetector
    which checks left_won_glow against both WINNER_BLUE and LOSER_RED), we create
    separate entries: "detector/m_box:COLOR_NAME" for each pairing.
    """
    boxes = {}
    if not os.path.isdir(INFERENCE_DIR):
        return boxes

    for fname in os.listdir(INFERENCE_DIR):
        if not fname.endswith(".cpp"):
            continue
        fpath = os.path.join(INFERENCE_DIR, fname)
        with open(fpath, "r") as f:
            lines = f.readlines()
        full_text = "".join(lines)

        # Extract detector name from filename
        base = fname.replace("PokemonChampions_", "").rsplit(".", 1)[0]
        rel_path = os.path.relpath(fpath, REPO_ROOT)

        # ── Pass 1: Find FloatPixel color constants ──
        color_constants = {}
        for i, line in enumerate(lines):
            m = re.search(
                r'FloatPixel\s+(\w+)\s*[\{(]\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*[\})]',
                line
            )
            if m:
                color_constants[m.group(1)] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))

        # ── Pass 2: Find ImageFloatBox member definitions ──
        # Maps member name -> {box, source_line}
        member_boxes = {}
        for i, line in enumerate(lines):
            # m_var(x, y, w, h) in constructor initializer list
            m = re.search(
                r'(m_\w+)\s*[\({]\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*[\})]',
                line
            )
            if not m:
                # ImageFloatBox(x, y, w, h) with a variable context
                m2 = re.search(
                    r'ImageFloatBox\s*[\({]\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*[\})]',
                    line
                )
                if m2:
                    var_m = re.search(r'(m_\w+)', line)
                    var_name = var_m.group(1) if var_m else f"box_line{i+1}"
                    box_vals = [float(m2.group(j)) for j in range(1, 5)]
                else:
                    continue
            else:
                var_name = m.group(1)
                box_vals = [float(m.group(j)) for j in range(2, 6)]

            if all(v == 0.0 for v in box_vals):
                continue

            member_boxes[var_name] = {"box": box_vals, "line": i + 1}

        # ── Pass 3: Trace is_solid() calls to pair boxes with colors ──
        # Track: image_stats(extract_box_reference(screen, m_box)) -> stats_var
        # Then:  is_solid(stats_var, COLOR_CONST, ...)
        #
        # stats_var -> [member_names] (file-wide, across all functions)
        # A var name like "stats" can appear in multiple functions mapping to
        # different members, so we collect all (stats_var, member) pairs.
        stats_pairs = []  # [(stats_var, member_name, line_idx), ...]
        for i, line in enumerate(lines):
            m = re.search(r'(\w+)\s*=\s*image_stats\(.*?(m_\w+)', line)
            if m:
                stats_pairs.append((m.group(1), m.group(2), i))

        # Collect (member_name, color_const_name) pairs from is_solid calls
        box_color_pairs = []
        for i, line in enumerate(lines):
            # Case 1: is_solid(stats_var, COLOR_CONST, ...)
            m = re.search(r'is_solid\(\s*(\w+)\s*,\s*(\w+)', line)
            if m:
                stats_var = m.group(1)
                color_name = m.group(2)
                if color_name not in color_constants:
                    continue
                # Find the closest preceding image_stats assignment for this var
                member = None
                for sv, mem, li in reversed(stats_pairs):
                    if sv == stats_var and li <= i:
                        member = mem
                        break
                if member and member in member_boxes:
                    box_color_pairs.append((member, color_name))
                    continue

            # Case 2: is_solid(image_stats(extract_box_reference(screen, m_box)), COLOR, ...)
            m2 = re.search(r'is_solid\(\s*image_stats\(.*?(m_\w+).*?,\s*(\w+)', line)
            if m2:
                member = m2.group(1)
                color_name = m2.group(2)
                if member in member_boxes and color_name in color_constants:
                    box_color_pairs.append((member, color_name))

        # ── Build output entries ──
        if box_color_pairs:
            # We have precise is_solid mappings
            seen_members = set()
            for member, color_name in box_color_pairs:
                seen_members.add(member)
                info = member_boxes[member]
                # Use "member:COLOR" key if a member maps to multiple colors
                member_color_count = sum(1 for m, _ in box_color_pairs if m == member)
                if member_color_count > 1:
                    key = f"{base}/{member}:{color_name}"
                else:
                    key = f"{base}/{member}"
                boxes[key] = {
                    "box": info["box"],
                    "source": f"{rel_path}:{info['line']}",
                    "expected": list(color_constants[color_name]),
                }

            # Add any member boxes not referenced in is_solid (overlay-only, etc.)
            for member, info in member_boxes.items():
                if member not in seen_members:
                    key = f"{base}/{member}"
                    boxes[key] = {
                        "box": info["box"],
                        "source": f"{rel_path}:{info['line']}",
                    }
                    if color_constants:
                        boxes[key]["color_constants"] = {
                            k: list(v) for k, v in color_constants.items()
                        }
        else:
            # No is_solid calls found — store boxes with available color constants
            for member, info in member_boxes.items():
                key = f"{base}/{member}"
                entry = {
                    "box": info["box"],
                    "source": f"{rel_path}:{info['line']}",
                }
                if color_constants:
                    entry["color_constants"] = {
                        k: list(v) for k, v in color_constants.items()
                    }
                boxes[key] = entry

    return boxes


def get_all_boxes():
    """Return merged dict: C++ detector boxes + user-saved boxes.
    User-saved boxes are prefixed with 'saved/' to avoid collisions.
    """
    cpp_boxes = parse_cpp_detectors()
    saved = load_saved_boxes()

    merged = {}
    for k, v in cpp_boxes.items():
        merged[k] = v
    for k, v in saved.items():
        merged[f"saved/{k}"] = v

    return merged


def list_all_boxes():
    """Print all known boxes."""
    all_boxes = get_all_boxes()
    if not all_boxes:
        print("No boxes found.")
        return

    # Group by prefix
    groups = {}
    for key, val in sorted(all_boxes.items()):
        prefix = key.split("/")[0]
        groups.setdefault(prefix, []).append((key, val))

    for prefix, items in sorted(groups.items()):
        print(f"\n  [{prefix}]")
        for key, val in items:
            b = val["box"]
            src = val.get("source", "")
            exp = val.get("expected")
            exp_s = f"  expected=({exp[0]:.2f},{exp[1]:.2f},{exp[2]:.2f})" if exp else ""
            src_s = f"  ({src})" if src else ""
            print(f"    {key:<45s} box=({b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f}){exp_s}{src_s}")
    print()


# ─── CLI modes ──────────────────────────────────────────────────────────────

def cli_box(img_path, box_args):
    img = Image.open(img_path).convert("RGB")
    fx, fy, fw, fh = [float(v) for v in box_args]
    px_x = int(fx * img.width)
    px_y = int(fy * img.height)
    px_w = int(fw * img.width)
    px_h = int(fh * img.height)
    print_report(img, px_x, px_y, px_w, px_h, label=f"box ({fx}, {fy}, {fw}, {fh})")


def cli_load(img_path, name):
    all_boxes = get_all_boxes()
    # Fuzzy match: find keys containing the name
    matches = [k for k in all_boxes if name.lower() in k.lower()]
    if not matches:
        print(f"No box matching '{name}'. Use --list to see available boxes.")
        sys.exit(1)

    img = Image.open(img_path).convert("RGB")
    for key in sorted(matches):
        val = all_boxes[key]
        b = val["box"]
        px_x = int(b[0] * img.width)
        px_y = int(b[1] * img.height)
        px_w = int(b[2] * img.width)
        px_h = int(b[3] * img.height)
        expected = tuple(val["expected"]) if val.get("expected") else None
        src = val.get("source", "")
        label = f"{key}" + (f"  ({src})" if src else "")
        print_report(img, px_x, px_y, px_w, px_h, label=label, expected=expected)


def cli_check_all(img_path):
    """Run all known detector boxes against the given image."""
    all_boxes = get_all_boxes()
    img = Image.open(img_path).convert("RGB")

    for key in sorted(all_boxes):
        val = all_boxes[key]
        b = val["box"]
        px_x = int(b[0] * img.width)
        px_y = int(b[1] * img.height)
        px_w = int(b[2] * img.width)
        px_h = int(b[3] * img.height)
        if px_w <= 0 or px_h <= 0:
            continue
        expected = tuple(val["expected"]) if val.get("expected") else None
        src = val.get("source", "")
        label = f"{key}" + (f"  ({src})" if src else "")
        print_report(img, px_x, px_y, px_w, px_h, label=label, expected=expected)


# ─── Interactive GUI ─────────────────────────────────────────────────────────

# Overlay colors for loaded boxes
BOX_COLORS = [
    "#ff6666", "#66ff66", "#6666ff", "#ffff66", "#ff66ff", "#66ffff",
    "#ff9933", "#33ff99", "#9933ff", "#ff3399", "#99ff33", "#3399ff",
]


def pick_files(initial_dir=None):
    """Open a native file picker and return selected paths (or empty list)."""
    root = tk.Tk()
    root.withdraw()
    paths = filedialog.askopenfilenames(
        title="Select screenshot(s)",
        initialdir=initial_dir or os.getcwd(),
        filetypes=[
            ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    return list(paths)


class PixelInspector:
    CROSSHAIR_SIZE = 12

    def __init__(self, img_paths):
        # Image list and index
        self.img_paths = list(img_paths)
        self.img_idx = 0

        # Load all known boxes
        self.all_boxes = get_all_boxes()
        self.box_keys = sorted(self.all_boxes.keys())
        self.current_box_idx = -1
        self.show_all_overlays = False

        self.root = tk.Tk()

        # Top bar: info
        self.info_var = tk.StringVar(value="drag=select  s=save  l=load  n/p=cycle boxes  o=open  Left/Right=switch image  q=quit")
        info_label = tk.Label(self.root, textvariable=self.info_var, anchor="w",
                              font=("Menlo", 11), bg="#1e1e1e", fg="#00ff88",
                              padx=8, pady=4)
        info_label.pack(fill="x")

        # Box info bar
        self.box_var = tk.StringVar()
        box_label = tk.Label(self.root, textvariable=self.box_var, anchor="w",
                             font=("Menlo", 10), bg="#2a2a2a", fg="#aaaaff",
                             padx=8, pady=2)
        box_label.pack(fill="x")

        # Canvas
        self.canvas = tk.Canvas(self.root, bg="#111", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Zoom / pan state
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        # Selection state
        self.sel_start = None
        self.sel_rect = None
        self.sel_coords = None  # (px_x, px_y, px_w, px_h) in image space

        # Pan state
        self.pan_start = None

        # Crosshair items
        self.crosshair_items = []

        # Bind events
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self.on_right_click)
        self.canvas.bind("<MouseWheel>", self.on_scroll)       # macOS
        self.canvas.bind("<Button-4>", self.on_scroll_up)      # Linux
        self.canvas.bind("<Button-5>", self.on_scroll_down)    # Linux
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.root.bind("<q>", lambda e: self.root.destroy())
        self.root.bind("<s>", lambda e: self.save_selection())
        self.root.bind("<l>", lambda e: self.load_box_dialog())
        self.root.bind("<n>", lambda e: self.cycle_box(1))
        self.root.bind("<p>", lambda e: self.cycle_box(-1))
        self.root.bind("<a>", lambda e: self.toggle_all_overlays())
        self.root.bind("<o>", lambda e: self.open_files())
        self.root.bind("<Left>", lambda e: self.switch_image(-1))
        self.root.bind("<Right>", lambda e: self.switch_image(1))

        # Load first image and show
        self._load_current_image()

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(self.img_w, int(screen_w * 0.85))
        win_h = min(self.img_h, int(screen_h * 0.85))
        self.root.geometry(f"{win_w}x{win_h}")

        # Force window to render (macOS Tk 8.5 grey-screen workaround)
        self.root.update()
        self.root.after(200, self.fit_to_window)
        self.root.after(400, self.redraw)
        self.root.mainloop()

    def _load_current_image(self):
        """Load the image at self.img_idx and reset view state."""
        self.img_path = self.img_paths[self.img_idx]
        self.img = Image.open(self.img_path).convert("RGB")
        self.img_w, self.img_h = self.img.size

        self.sel_start = None
        self.sel_rect = None
        self.sel_coords = None
        self.crosshair_items = []

        fname = os.path.basename(self.img_path)
        count = len(self.img_paths)
        img_label = f"[{self.img_idx + 1}/{count}] {fname}" if count > 1 else fname
        self.root.title(f"Pixel Inspector -- {img_label}")
        self.box_var.set(f"{img_label}  |  {len(self.box_keys)} boxes available  |  {self.img_w}x{self.img_h}")

    def open_files(self):
        """Open file picker to add more images."""
        initial = os.path.dirname(self.img_path) if self.img_path else None
        paths = pick_files(initial_dir=initial)
        if not paths:
            return
        # Replace the image list and jump to the first new image
        start = len(self.img_paths)
        self.img_paths.extend(paths)
        self.img_idx = start
        self._load_current_image()
        self.fit_to_window()
        self.info_var.set(f"Opened {len(paths)} image(s) -- {len(self.img_paths)} total")

    def switch_image(self, direction):
        """Switch to next/prev image in the list."""
        if len(self.img_paths) < 2:
            self.info_var.set("Only 1 image loaded -- press 'o' to open more")
            return
        self.img_idx = (self.img_idx + direction) % len(self.img_paths)
        self._load_current_image()
        self.fit_to_window()

    def fit_to_window(self):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        zx = cw / self.img_w
        zy = ch / self.img_h
        self.zoom = min(zx, zy)
        self.offset_x = (cw - self.img_w * self.zoom) / 2
        self.offset_y = (ch - self.img_h * self.zoom) / 2
        self.redraw()

    # ── Coordinate transforms ──

    def img_to_canvas(self, ix, iy):
        return ix * self.zoom + self.offset_x, iy * self.zoom + self.offset_y

    def canvas_to_img(self, cx, cy):
        return (cx - self.offset_x) / self.zoom, (cy - self.offset_y) / self.zoom

    # ── Drawing ──

    def redraw(self):
        self.canvas.delete("all")

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        # Determine visible portion of image
        ix0, iy0 = self.canvas_to_img(0, 0)
        ix1, iy1 = self.canvas_to_img(cw, ch)

        # Clamp to image bounds
        ix0 = max(0, int(ix0))
        iy0 = max(0, int(iy0))
        ix1 = min(self.img_w, int(ix1) + 1)
        iy1 = min(self.img_h, int(iy1) + 1)

        if ix1 <= ix0 or iy1 <= iy0:
            return

        # Crop and resize visible portion
        crop = self.img.crop((ix0, iy0, ix1, iy1))
        disp_w = max(1, int((ix1 - ix0) * self.zoom))
        disp_h = max(1, int((iy1 - iy0) * self.zoom))
        resized = crop.resize((disp_w, disp_h), Image.NEAREST if self.zoom > 2 else Image.BILINEAR)

        self._photo = ImageTk.PhotoImage(resized)
        cx0, cy0 = self.img_to_canvas(ix0, iy0)
        self.canvas.create_image(cx0, cy0, image=self._photo, anchor="nw")

        # Draw all overlays if toggled
        if self.show_all_overlays:
            for i, key in enumerate(self.box_keys):
                b = self.all_boxes[key]["box"]
                color = BOX_COLORS[i % len(BOX_COLORS)]
                self._draw_box_overlay(b, color, key)

        # Draw currently loaded box
        if 0 <= self.current_box_idx < len(self.box_keys):
            key = self.box_keys[self.current_box_idx]
            b = self.all_boxes[key]["box"]
            self._draw_box_overlay(b, "#00ff00", key, width=3)

        # Redraw user selection
        if self.sel_coords:
            px_x, px_y, px_w, px_h = self.sel_coords
            sx0, sy0 = self.img_to_canvas(px_x, px_y)
            sx1, sy1 = self.img_to_canvas(px_x + px_w, px_y + px_h)
            self.canvas.create_rectangle(sx0, sy0, sx1, sy1,
                                         outline="#00ffff", width=2, dash=(4, 4))

    def _draw_box_overlay(self, box, color, label="", width=2):
        """Draw a named box overlay on the canvas."""
        bx = box[0] * self.img_w
        by = box[1] * self.img_h
        bw = box[2] * self.img_w
        bh = box[3] * self.img_h
        cx0, cy0 = self.img_to_canvas(bx, by)
        cx1, cy1 = self.img_to_canvas(bx + bw, by + bh)
        self.canvas.create_rectangle(cx0, cy0, cx1, cy1,
                                     outline=color, width=width)
        if label:
            # Truncate label for display
            short = label.split("/")[-1] if "/" in label else label
            self.canvas.create_text(cx0 + 2, cy0 - 2, text=short,
                                    fill=color, anchor="sw",
                                    font=("Menlo", 9, "bold"))

    def draw_crosshair(self, cx, cy):
        for item in self.crosshair_items:
            self.canvas.delete(item)
        self.crosshair_items.clear()

        s = self.CROSSHAIR_SIZE
        self.crosshair_items.append(
            self.canvas.create_line(cx - s, cy, cx + s, cy, fill="#ff0", width=1))
        self.crosshair_items.append(
            self.canvas.create_line(cx, cy - s, cx, cy + s, fill="#ff0", width=1))

    # ── Box management ──

    def save_selection(self):
        if not self.sel_coords:
            self.info_var.set("Nothing to save -- select a region first")
            return

        px_x, px_y, px_w, px_h = self.sel_coords
        fx, fy, fw, fh = format_report(self.img_w, self.img_h, px_x, px_y, px_w, px_h)

        name = simpledialog.askstring("Save Box", "Name for this box (e.g. 'battle_dialog/text_area'):",
                                      parent=self.root)
        if not name:
            return

        boxes = load_saved_boxes()
        boxes[name] = {
            "box": [fx, fy, fw, fh],
            "source": f"saved from {os.path.basename(self.img_path)}",
        }

        # Compute and store the expected color ratio
        pixels = extract_pixels(self.img, px_x, px_y, px_w, px_h)
        avg, sd, count = image_stats(pixels)
        ratio = color_ratio(avg)
        boxes[name]["expected"] = [round(ratio[0], 4), round(ratio[1], 4), round(ratio[2], 4)]
        boxes[name]["avg_rgb"] = [round(avg[0], 1), round(avg[1], 1), round(avg[2], 1)]
        boxes[name]["stddev_sum"] = round(sd[0] + sd[1] + sd[2], 1)

        save_boxes(boxes)

        # Reload
        self.all_boxes = get_all_boxes()
        self.box_keys = sorted(self.all_boxes.keys())

        self.info_var.set(f"Saved '{name}' -> {SAVED_BOXES_PATH}")
        print(f"\nSaved box '{name}': ({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f})")

    def load_box_dialog(self):
        if not self.box_keys:
            self.info_var.set("No boxes available")
            return

        # Build a picker window
        picker = tk.Toplevel(self.root)
        picker.title("Load Box")
        picker.geometry("600x500")
        picker.configure(bg="#1e1e1e")

        # Search field
        search_var = tk.StringVar()
        search_entry = tk.Entry(picker, textvariable=search_var, font=("Menlo", 12),
                                bg="#2a2a2a", fg="#ffffff", insertbackground="#ffffff")
        search_entry.pack(fill="x", padx=8, pady=8)
        search_entry.focus_set()

        # Listbox
        frame = tk.Frame(picker, bg="#1e1e1e")
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        listbox = tk.Listbox(frame, font=("Menlo", 11), bg="#2a2a2a", fg="#cccccc",
                             selectbackground="#444488", yscrollcommand=scrollbar.set)
        listbox.pack(fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        # Populate
        filtered_keys = list(self.box_keys)

        def refresh_list(*_):
            nonlocal filtered_keys
            query = search_var.get().lower()
            listbox.delete(0, "end")
            filtered_keys = [k for k in self.box_keys if query in k.lower()]
            for key in filtered_keys:
                b = self.all_boxes[key]["box"]
                listbox.insert("end", f"{key}  ({b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f})")

        search_var.trace_add("write", refresh_list)
        refresh_list()

        def on_select(event=None):
            sel = listbox.curselection()
            if not sel:
                return
            key = filtered_keys[sel[0]]
            self.current_box_idx = self.box_keys.index(key)
            self._activate_box(key)
            picker.destroy()

        listbox.bind("<Double-Button-1>", on_select)
        listbox.bind("<Return>", on_select)
        search_entry.bind("<Return>", lambda e: on_select())

    def _activate_box(self, key):
        """Load a box, print its report, update overlays."""
        val = self.all_boxes[key]
        b = val["box"]
        px_x = int(b[0] * self.img_w)
        px_y = int(b[1] * self.img_h)
        px_w = int(b[2] * self.img_w)
        px_h = int(b[3] * self.img_h)

        expected = tuple(val["expected"]) if val.get("expected") else None
        src = val.get("source", "")
        label = f"{key}" + (f"  ({src})" if src else "")
        print_report(self.img, px_x, px_y, px_w, px_h, label=label, expected=expected)

        self.sel_coords = (px_x, px_y, px_w, px_h)
        self.redraw()

        self.box_var.set(f"[{self.current_box_idx + 1}/{len(self.box_keys)}] {key}")
        self.info_var.set(
            f"Loaded: {key}  box=({b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f})"
        )

    def cycle_box(self, direction):
        if not self.box_keys:
            return
        self.current_box_idx = (self.current_box_idx + direction) % len(self.box_keys)
        key = self.box_keys[self.current_box_idx]
        self._activate_box(key)

    def toggle_all_overlays(self):
        self.show_all_overlays = not self.show_all_overlays
        self.redraw()
        state = "ON" if self.show_all_overlays else "OFF"
        self.info_var.set(f"All box overlays: {state}  ({len(self.box_keys)} boxes)")

    # ── Selection ──

    def on_press(self, event):
        self.sel_start = (event.x, event.y)
        self.sel_coords = None
        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
            self.sel_rect = None

    def on_drag(self, event):
        if not self.sel_start:
            return

        x0, y0 = self.sel_start
        x1, y1 = event.x, event.y

        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
        self.sel_rect = self.canvas.create_rectangle(
            x0, y0, x1, y1, outline="#00ffff", width=2, dash=(4, 4))

        # Update info with live coordinates
        ix0, iy0 = self.canvas_to_img(min(x0, x1), min(y0, y1))
        ix1, iy1 = self.canvas_to_img(max(x0, x1), max(y0, y1))
        ix0, iy0 = max(0, int(ix0)), max(0, int(iy0))
        ix1, iy1 = min(self.img_w, int(ix1)), min(self.img_h, int(iy1))
        pw, ph = ix1 - ix0, iy1 - iy0
        if pw > 0 and ph > 0:
            fx, fy = ix0 / self.img_w, iy0 / self.img_h
            fw, fh = pw / self.img_w, ph / self.img_h
            self.info_var.set(
                f"Selecting: ({ix0},{iy0}) {pw}x{ph}px  |  "
                f"ImageFloatBox({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f})")

    def on_release(self, event):
        if not self.sel_start:
            return

        x0, y0 = self.sel_start
        x1, y1 = event.x, event.y

        # Convert to image coords
        ix0, iy0 = self.canvas_to_img(min(x0, x1), min(y0, y1))
        ix1, iy1 = self.canvas_to_img(max(x0, x1), max(y0, y1))

        px_x = max(0, int(ix0))
        px_y = max(0, int(iy0))
        px_w = min(self.img_w, int(ix1)) - px_x
        px_h = min(self.img_h, int(iy1)) - px_y

        self.sel_start = None

        if px_w < 2 or px_h < 2:
            # Too small — treat as a single-pixel click, show info
            ix, iy = self.canvas_to_img(event.x, event.y)
            ix, iy = int(ix), int(iy)
            if 0 <= ix < self.img_w and 0 <= iy < self.img_h:
                p = self.img.getpixel((ix, iy))
                s = p[0] + p[1] + p[2]
                ratio = (p[0]/s, p[1]/s, p[2]/s) if s > 0 else (0.333, 0.333, 0.333)
                self.info_var.set(
                    f"Pixel ({ix},{iy}): RGB=({p[0]},{p[1]},{p[2]})  "
                    f"ratio=({ratio[0]:.3f},{ratio[1]:.3f},{ratio[2]:.3f})  "
                    f"norm=({ix/self.img_w:.4f},{iy/self.img_h:.4f})")
            return

        self.sel_coords = (px_x, px_y, px_w, px_h)
        self.redraw()
        print_report(self.img, px_x, px_y, px_w, px_h)

        # Update status bar
        fx, fy, fw, fh = format_report(self.img_w, self.img_h, px_x, px_y, px_w, px_h)
        pixels = extract_pixels(self.img, px_x, px_y, px_w, px_h)
        avg, sd, count = image_stats(pixels)
        ratio = color_ratio(avg)
        self.info_var.set(
            f"Box({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f})  "
            f"ratio=({ratio[0]:.2f},{ratio[1]:.2f},{ratio[2]:.2f})  "
            f"stddev_sum={sd[0]+sd[1]+sd[2]:.1f}  [{count}px]")

    def on_right_click(self, event):
        self.sel_coords = None
        self.current_box_idx = -1
        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
            self.sel_rect = None
        self.redraw()
        self.info_var.set("Selection cleared")

    # ── Pan ──

    def on_pan_start(self, event):
        self.pan_start = (event.x, event.y, self.offset_x, self.offset_y)

    def on_pan_move(self, event):
        if not self.pan_start:
            return
        sx, sy, ox, oy = self.pan_start
        self.offset_x = ox + (event.x - sx)
        self.offset_y = oy + (event.y - sy)
        self.redraw()

    # ── Zoom ──

    def do_zoom(self, event, factor):
        ix, iy = self.canvas_to_img(event.x, event.y)
        self.zoom *= factor
        self.zoom = max(0.1, min(50, self.zoom))
        self.offset_x = event.x - ix * self.zoom
        self.offset_y = event.y - iy * self.zoom
        self.redraw()

    def on_scroll(self, event):
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self.do_zoom(event, factor)

    def on_scroll_up(self, event):
        self.do_zoom(event, 1.15)

    def on_scroll_down(self, event):
        self.do_zoom(event, 1 / 1.15)

    # ── Motion (live pixel readout) ──

    def on_motion(self, event):
        if self.sel_start:
            return  # dragging — handled by on_drag
        ix, iy = self.canvas_to_img(event.x, event.y)
        ix, iy = int(ix), int(iy)
        self.draw_crosshair(event.x, event.y)
        if 0 <= ix < self.img_w and 0 <= iy < self.img_h:
            p = self.img.getpixel((ix, iy))
            s = p[0] + p[1] + p[2]
            ratio = (p[0]/s, p[1]/s, p[2]/s) if s > 0 else (0.333, 0.333, 0.333)
            self.info_var.set(
                f"({ix},{iy})  RGB=({p[0]:3d},{p[1]:3d},{p[2]:3d})  "
                f"ratio=({ratio[0]:.3f},{ratio[1]:.3f},{ratio[2]:.3f})  "
                f"norm=({ix/self.img_w:.4f},{iy/self.img_h:.4f})")


# ─── Box Definitions (--measure mode) ──────────────────────────────────────

def load_box_definitions():
    """Load the box definitions file."""
    if not os.path.exists(BOX_DEFINITIONS_PATH):
        print(f"No box definitions file at {BOX_DEFINITIONS_PATH}")
        sys.exit(1)
    with open(BOX_DEFINITIONS_PATH, "r") as f:
        return json.load(f)


def save_box_definitions(data):
    """Save box definitions back to file."""
    with open(BOX_DEFINITIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def measure_status():
    """Print progress summary of pending box measurements."""
    data = load_box_definitions()
    boxes = data["boxes"]
    pending = [b for b in boxes if b["status"] == "pending"]
    confirmed = [b for b in boxes if b["status"] == "confirmed"]

    print(f"\n  Box measurement progress: {len(confirmed)}/{len(boxes)} confirmed\n")

    # Group by scene
    scenes = {}
    for b in boxes:
        scenes.setdefault(b["scene"], []).append(b)

    for scene, items in scenes.items():
        done = sum(1 for b in items if b["status"] == "confirmed")
        print(f"  [{scene}]  ({done}/{len(items)})")
        for b in items:
            status = "OK" if b["status"] == "confirmed" else ".."
            box_s = ""
            if b["box"]:
                bx = b["box"]
                box_s = f"  ({bx[0]:.4f}, {bx[1]:.4f}, {bx[2]:.4f}, {bx[3]:.4f})"
            print(f"    [{status}] {b['name']:<30s}{box_s}")
    print()


class MeasureMode:
    """Interactive mode that walks through pending box definitions one by one.

    If remeasure_names is provided, walks through ONLY those boxes
    (even if already confirmed) so the user can adjust them.
    """

    CROSSHAIR_SIZE = 12

    def __init__(self, remeasure_names=None):
        self.data = load_box_definitions()
        all_boxes = self.data["boxes"]

        if remeasure_names:
            # Filter to just the requested names (order preserved from argv)
            name_set = set(remeasure_names)
            self.boxes = [b for b in all_boxes if b["name"] in name_set]
            missing = name_set - {b["name"] for b in self.boxes}
            if missing:
                print(f"Unknown box names: {', '.join(sorted(missing))}")
                print("Run --measure-status to see valid names.")
                sys.exit(1)
            # Map filtered boxes back to full list so saves persist correctly.
            self._full_boxes = all_boxes
            self.current_idx = 0
            print(f"Re-measuring {len(self.boxes)} box(es): {', '.join(b['name'] for b in self.boxes)}")
        else:
            self.boxes = all_boxes
            self._full_boxes = all_boxes
            self.current_idx = self._find_first_pending()

            if self.current_idx is None:
                print("All boxes are already confirmed! Use --measure-status to see them.")
                print("To adjust a specific box, use: --remeasure <name>")
                sys.exit(0)

        self.root = tk.Tk()

        # Top bar: box name + progress
        self.progress_var = tk.StringVar()
        progress_label = tk.Label(self.root, textvariable=self.progress_var, anchor="w",
                                  font=("Menlo", 12, "bold"), bg="#1e1e1e", fg="#00ff88",
                                  padx=8, pady=4)
        progress_label.pack(fill="x")

        # Description bar
        self.desc_var = tk.StringVar()
        desc_label = tk.Label(self.root, textvariable=self.desc_var, anchor="w",
                              font=("Menlo", 11), bg="#2a2a2a", fg="#ffcc66",
                              padx=8, pady=4, wraplength=900, justify="left")
        desc_label.pack(fill="x")

        # Info bar (coordinates)
        self.info_var = tk.StringVar(value="Drag a box on the image below, then click Confirm.")
        info_label = tk.Label(self.root, textvariable=self.info_var, anchor="w",
                              font=("Menlo", 11), bg="#333333", fg="#aaaaff",
                              padx=8, pady=4)
        info_label.pack(fill="x")

        # Button bar
        btn_frame = tk.Frame(self.root, bg="#222222")
        btn_frame.pack(fill="x")

        def _make_btn(parent, text, command, bg="#3a3a3a", side="left"):
            lbl = tk.Label(parent, text=f"  {text}  ", font=("Menlo", 11, "bold"),
                           bg=bg, fg="#ffffff", padx=12, pady=6, cursor="hand2")
            lbl.pack(side=side, padx=4, pady=4)
            lbl.bind("<Button-1>", lambda e: command())
            return lbl

        _make_btn(btn_frame, "< Prev (Backspace)", self.prev_box)
        _make_btn(btn_frame, "Skip (Esc)", self.skip_box, bg="#5a4a2a")
        _make_btn(btn_frame, "Clear (Right-click)", self.clear_selection)
        _make_btn(btn_frame, "Save + Quit (q)", self.quit, side="right")
        _make_btn(btn_frame, "Confirm >  (Enter)", self.confirm_box, bg="#2a6a2a", side="right")

        # Canvas
        self.canvas = tk.Canvas(self.root, bg="#111", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # State
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.sel_start = None
        self.sel_rect = None
        self.sel_coords = None  # (px_x, px_y, px_w, px_h) in image space
        self.pan_start = None
        self.crosshair_items = []
        self.img = None
        self.img_w = 0
        self.img_h = 0
        self.current_screenshot = None

        # Bindings
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self.on_right_click)
        self.canvas.bind("<MouseWheel>", self.on_scroll)
        self.canvas.bind("<Button-4>", self.on_scroll_up)
        self.canvas.bind("<Button-5>", self.on_scroll_down)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.root.bind("<Return>", lambda e: self.confirm_box())
        self.root.bind("<Escape>", lambda e: self.skip_box())
        self.root.bind("<BackSpace>", lambda e: self.prev_box())
        self.root.bind("<q>", lambda e: self.quit())

        self._load_current_box()

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(self.img_w, int(screen_w * 0.85))
        win_h = min(self.img_h + 80, int(screen_h * 0.85))
        self.root.geometry(f"{win_w}x{win_h}")

        self.root.after(100, self.fit_to_window)
        self.root.mainloop()

    def _find_first_pending(self):
        for i, b in enumerate(self.boxes):
            if b["status"] == "pending":
                return i
        return None

    def _load_current_box(self):
        box_def = self.boxes[self.current_idx]
        screenshot = os.path.join(REPO_ROOT, box_def["screenshot"])

        # Only reload image if screenshot changed
        if screenshot != self.current_screenshot:
            self.img = Image.open(screenshot).convert("RGB")
            self.img_w, self.img_h = self.img.size
            self.current_screenshot = screenshot

        self.sel_start = None
        self.sel_rect = None
        self.sel_coords = None

        # If box was previously confirmed, show it
        if box_def["box"]:
            b = box_def["box"]
            self.sel_coords = (
                int(b[0] * self.img_w), int(b[1] * self.img_h),
                int(b[2] * self.img_w), int(b[3] * self.img_h),
            )

        confirmed = sum(1 for b in self.boxes if b["status"] == "confirmed")
        total = len(self.boxes)
        self.root.title(f"Measure Mode — {box_def['name']}  [{confirmed}/{total} done]")
        self.progress_var.set(
            f"[{self.current_idx + 1}/{total}]  {box_def['name']}  "
            f"({confirmed}/{total} confirmed)  |  Scene: {box_def['scene']}"
        )
        self.desc_var.set(box_def["description"])

        status = box_def["status"]
        if status == "confirmed" and box_def["box"]:
            b = box_def["box"]
            self.info_var.set(
                f"CONFIRMED: ({b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f})  "
                f"|  Redraw to update  |  Enter=keep  Esc=skip  Backspace=prev"
            )
        else:
            self.info_var.set("Drag to select box region  |  Enter=confirm  Esc=skip  Backspace=prev  q=quit")

    def confirm_box(self):
        if not self.sel_coords:
            self.info_var.set("Nothing selected — draw a box first!")
            return

        px_x, px_y, px_w, px_h = self.sel_coords
        fx, fy, fw, fh = format_report(self.img_w, self.img_h, px_x, px_y, px_w, px_h)

        box_def = self.boxes[self.current_idx]
        box_def["box"] = [round(fx, 4), round(fy, 4), round(fw, 4), round(fh, 4)]
        box_def["status"] = "confirmed"

        # Store color stats for reference
        pixels = extract_pixels(self.img, px_x, px_y, px_w, px_h)
        avg, sd, count = image_stats(pixels)
        ratio = color_ratio(avg)
        box_def["avg_rgb"] = [round(avg[0], 1), round(avg[1], 1), round(avg[2], 1)]
        box_def["stddev_sum"] = round(sd[0] + sd[1] + sd[2], 1)
        box_def["color_ratio"] = [round(ratio[0], 4), round(ratio[1], 4), round(ratio[2], 4)]

        save_box_definitions(self.data)

        print(f"  Confirmed: {box_def['name']}  ({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f})")

        # Advance to next
        self._advance()

    def skip_box(self):
        self._advance()

    def prev_box(self):
        if self.current_idx > 0:
            self.current_idx -= 1
            self._load_current_box()
            self.fit_to_window()

    def _advance(self):
        """Move to the next box, or finish if all done."""
        if self.current_idx + 1 < len(self.boxes):
            self.current_idx += 1
            self._load_current_box()
            # Only re-fit if screenshot changed
            self.redraw()
        else:
            confirmed = sum(1 for b in self.boxes if b["status"] == "confirmed")
            total = len(self.boxes)
            if confirmed == total:
                print(f"\n  All {total} boxes confirmed! Results saved to {BOX_DEFINITIONS_PATH}\n")
            else:
                print(f"\n  Reached end. {confirmed}/{total} boxes confirmed.\n")
                print(f"  Re-run --measure to continue with remaining boxes.\n")
            self.root.destroy()

    def quit(self):
        save_box_definitions(self.data)
        confirmed = sum(1 for b in self.boxes if b["status"] == "confirmed")
        print(f"\n  Progress saved. {confirmed}/{len(self.boxes)} boxes confirmed.\n")
        self.root.destroy()

    # ── Drawing ──

    def fit_to_window(self):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        zx = cw / self.img_w
        zy = ch / self.img_h
        self.zoom = min(zx, zy)
        self.offset_x = (cw - self.img_w * self.zoom) / 2
        self.offset_y = (ch - self.img_h * self.zoom) / 2
        self.redraw()

    def img_to_canvas(self, ix, iy):
        return ix * self.zoom + self.offset_x, iy * self.zoom + self.offset_y

    def canvas_to_img(self, cx, cy):
        return (cx - self.offset_x) / self.zoom, (cy - self.offset_y) / self.zoom

    def redraw(self):
        self.canvas.delete("all")

        if self.img is None:
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        ix0, iy0 = self.canvas_to_img(0, 0)
        ix1, iy1 = self.canvas_to_img(cw, ch)
        ix0 = max(0, int(ix0))
        iy0 = max(0, int(iy0))
        ix1 = min(self.img_w, int(ix1) + 1)
        iy1 = min(self.img_h, int(iy1) + 1)
        if ix1 <= ix0 or iy1 <= iy0:
            return

        crop = self.img.crop((ix0, iy0, ix1, iy1))
        disp_w = max(1, int((ix1 - ix0) * self.zoom))
        disp_h = max(1, int((iy1 - iy0) * self.zoom))
        resized = crop.resize((disp_w, disp_h), Image.NEAREST if self.zoom > 2 else Image.BILINEAR)
        self._photo = ImageTk.PhotoImage(resized)
        cx0, cy0 = self.img_to_canvas(ix0, iy0)
        self.canvas.create_image(cx0, cy0, image=self._photo, anchor="nw")

        # Draw previously confirmed boxes from same screenshot (dimmed)
        for i, b in enumerate(self.boxes):
            if i == self.current_idx:
                continue
            if b["box"] and b["screenshot"] == self.boxes[self.current_idx]["screenshot"]:
                bx = b["box"]
                px = bx[0] * self.img_w
                py = bx[1] * self.img_h
                pw = bx[2] * self.img_w
                ph = bx[3] * self.img_h
                cx0, cy0 = self.img_to_canvas(px, py)
                cx1, cy1 = self.img_to_canvas(px + pw, py + ph)
                self.canvas.create_rectangle(cx0, cy0, cx1, cy1,
                                             outline="#666666", width=1, dash=(3, 3))
                short = b["name"].split("/")[-1]
                self.canvas.create_text(cx0 + 2, cy0 - 2, text=short,
                                        fill="#666666", anchor="sw", font=("Menlo", 8))

        # Draw current selection
        if self.sel_coords:
            px_x, px_y, px_w, px_h = self.sel_coords
            sx0, sy0 = self.img_to_canvas(px_x, px_y)
            sx1, sy1 = self.img_to_canvas(px_x + px_w, px_y + px_h)
            self.canvas.create_rectangle(sx0, sy0, sx1, sy1,
                                         outline="#00ffff", width=2, dash=(4, 4))

    def draw_crosshair(self, cx, cy):
        for item in self.crosshair_items:
            self.canvas.delete(item)
        self.crosshair_items.clear()
        s = self.CROSSHAIR_SIZE
        self.crosshair_items.append(
            self.canvas.create_line(cx - s, cy, cx + s, cy, fill="#ff0", width=1))
        self.crosshair_items.append(
            self.canvas.create_line(cx, cy - s, cx, cy + s, fill="#ff0", width=1))

    # ── Selection ──

    def on_press(self, event):
        self.sel_start = (event.x, event.y)
        self.sel_coords = None
        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
            self.sel_rect = None

    def on_drag(self, event):
        if not self.sel_start:
            return
        x0, y0 = self.sel_start
        x1, y1 = event.x, event.y
        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
        self.sel_rect = self.canvas.create_rectangle(
            x0, y0, x1, y1, outline="#00ffff", width=2, dash=(4, 4))
        ix0, iy0 = self.canvas_to_img(min(x0, x1), min(y0, y1))
        ix1, iy1 = self.canvas_to_img(max(x0, x1), max(y0, y1))
        ix0, iy0 = max(0, int(ix0)), max(0, int(iy0))
        ix1, iy1 = min(self.img_w, int(ix1)), min(self.img_h, int(iy1))
        pw, ph = ix1 - ix0, iy1 - iy0
        if pw > 0 and ph > 0:
            fx, fy = ix0 / self.img_w, iy0 / self.img_h
            fw, fh = pw / self.img_w, ph / self.img_h
            self.info_var.set(
                f"Selecting: ({ix0},{iy0}) {pw}x{ph}px  |  "
                f"Box({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f})  |  Enter=confirm")

    def on_release(self, event):
        if not self.sel_start:
            return
        x0, y0 = self.sel_start
        x1, y1 = event.x, event.y
        ix0, iy0 = self.canvas_to_img(min(x0, x1), min(y0, y1))
        ix1, iy1 = self.canvas_to_img(max(x0, x1), max(y0, y1))
        px_x = max(0, int(ix0))
        px_y = max(0, int(iy0))
        px_w = min(self.img_w, int(ix1)) - px_x
        px_h = min(self.img_h, int(iy1)) - px_y
        self.sel_start = None

        if px_w < 2 or px_h < 2:
            # Single pixel click — show info
            ix, iy = self.canvas_to_img(event.x, event.y)
            ix, iy = int(ix), int(iy)
            if 0 <= ix < self.img_w and 0 <= iy < self.img_h:
                p = self.img.getpixel((ix, iy))
                self.info_var.set(
                    f"Pixel ({ix},{iy}): RGB=({p[0]},{p[1]},{p[2]})  "
                    f"norm=({ix/self.img_w:.4f},{iy/self.img_h:.4f})")
            return

        self.sel_coords = (px_x, px_y, px_w, px_h)
        self.redraw()

        fx, fy, fw, fh = format_report(self.img_w, self.img_h, px_x, px_y, px_w, px_h)
        self.info_var.set(
            f"Selected: Box({fx:.4f}, {fy:.4f}, {fw:.4f}, {fh:.4f})  "
            f"{px_w}x{px_h}px  |  Press Enter to confirm")

    def on_right_click(self, event):
        self.clear_selection()

    def clear_selection(self):
        self.sel_coords = None
        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
            self.sel_rect = None
        self.redraw()
        self.info_var.set("Selection cleared — draw a new box")

    # ── Pan / Zoom ──

    def on_pan_start(self, event):
        self.pan_start = (event.x, event.y, self.offset_x, self.offset_y)

    def on_pan_move(self, event):
        if not self.pan_start:
            return
        sx, sy, ox, oy = self.pan_start
        self.offset_x = ox + (event.x - sx)
        self.offset_y = oy + (event.y - sy)
        self.redraw()

    def do_zoom(self, event, factor):
        ix, iy = self.canvas_to_img(event.x, event.y)
        self.zoom *= factor
        self.zoom = max(0.1, min(50, self.zoom))
        self.offset_x = event.x - ix * self.zoom
        self.offset_y = event.y - iy * self.zoom
        self.redraw()

    def on_scroll(self, event):
        self.do_zoom(event, 1.15 if event.delta > 0 else 1 / 1.15)

    def on_scroll_up(self, event):
        self.do_zoom(event, 1.15)

    def on_scroll_down(self, event):
        self.do_zoom(event, 1 / 1.15)

    def on_motion(self, event):
        if self.sel_start:
            return
        self.draw_crosshair(event.x, event.y)
        ix, iy = self.canvas_to_img(event.x, event.y)
        ix, iy = int(ix), int(iy)
        if 0 <= ix < self.img_w and 0 <= iy < self.img_h:
            p = self.img.getpixel((ix, iy))
            self.info_var.set(
                f"({ix},{iy})  RGB=({p[0]:3d},{p[1]:3d},{p[2]:3d})  "
                f"norm=({ix/self.img_w:.4f},{iy/self.img_h:.4f})")


# ─── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        list_all_boxes()
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--measure":
        MeasureMode()
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] in ("--measure-status", "--ms"):
        measure_status()
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--remeasure":
        names = sys.argv[2:]
        if not names:
            print("Usage: --remeasure <box_name> [box_name2] ...")
            print("Run --measure-status to see available names.")
            sys.exit(1)
        MeasureMode(remeasure_names=names)
        sys.exit(0)

    # CLI modes that require an image path as first arg
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("-"):
        img_path = sys.argv[1]

        if "--box" in sys.argv:
            idx = sys.argv.index("--box")
            box_args = sys.argv[idx + 1:idx + 5]
            if len(box_args) != 4:
                print("Error: --box requires 4 values: x y width height")
                sys.exit(1)
            cli_box(img_path, box_args)
        elif "--load" in sys.argv:
            idx = sys.argv.index("--load")
            if idx + 1 >= len(sys.argv):
                print("Error: --load requires a box name")
                sys.exit(1)
            cli_load(img_path, sys.argv[idx + 1])
        elif "--check-all" in sys.argv:
            cli_check_all(img_path)
        else:
            # Collect all non-flag args as image paths
            img_paths = [a for a in sys.argv[1:] if not a.startswith("-")]
            PixelInspector(img_paths)
    else:
        # No image path given -- open file picker
        paths = pick_files(initial_dir=os.path.join(REPO_ROOT, "SerialPrograms", "Source", "PokemonChampions", "ref_frames"))
        if not paths:
            print("No files selected.")
            sys.exit(0)
        PixelInspector(paths)
