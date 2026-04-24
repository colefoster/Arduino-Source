#!/usr/bin/env python3
"""
Frame Labeling Tool — interactive GUI for labeling extracted VOD frames.

Displays frames one-by-one with crop region previews and lets you quickly
label them for the C++ test suite. Supports keyboard shortcuts for fast
navigation and labeling.

Usage:
    python3 tools/label_frames.py <source_dir> --reader <ReaderName>
    python3 tools/label_frames.py ref_frames/vod_extract/.../move_select --reader MoveNameReader
    python3 tools/label_frames.py ref_frames/vod_extract/.../battle_log --reader BattleLogReader

Readers and label formats:
    MoveNameReader         4 move slugs (e.g. thunderbolt, ice-beam)
    SpeciesReader          1 species slug (e.g. bellibolt)
    OpponentHPReader       HP percentage integer (0-100)
    MoveSelectCursorSlot   Slot index (0-3)
    MoveSelectDetector     True/False
    BattleLogReader        Event type (MOVE_USED, FAINTED, etc.)
    TeamSelectReader       6 species slugs
    ActionMenuDetector     True/False
    PostMatchScreenDetector True/False
    PreparingForBattleDetector True/False
    TeamSelectDetector     True/False
"""

import json
import os
import shutil
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except ImportError:
    print("ERROR: pip install Pillow")
    sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
TESTS_ROOT = REPO / "CommandLineTests" / "PokemonChampions"

# ── Crop definitions (same as ocr_gallery.py) ──────────────────────

CROP_DEFS = {
    "MoveNameReader": [
        {"name": f"move_{i}", "box": [0.776, y, 0.120, 0.031]}
        for i, y in enumerate([0.536, 0.655, 0.775, 0.894])
    ],
    "SpeciesReader": [
        {"name": "opp_species", "box": [0.830, 0.052, 0.087, 0.032]},
    ],
    "OpponentHPReader": [
        {"name": "opp_hp_pct", "box": [0.8963, 0.1098, 0.0498, 0.0524]},
    ],
    "OpponentHPReader_Doubles": [
        {"name": "opp0_hp_pct", "box": [0.694, 0.116, 0.041, 0.038]},
    ],
    "MoveSelectCursorSlot": [
        {"name": f"pill_{i}", "box": [0.7292, y, 0.0101, 0.0139]}
        for i, y in enumerate([0.5116, 0.6338, 0.7542, 0.8746])
    ],
    "BattleLogReader": [
        {"name": "text_bar", "box": [0.104, 0.741, 0.729, 0.046]},
    ],
    "TeamSelectReader": [
        {"name": f"slot_{i}", "box": [0.0807, y, 0.0849, 0.0343]}
        for i, y in enumerate([0.2194, 0.3303, 0.4412, 0.5521, 0.6630, 0.7741])
    ],
    "TeamSummaryReader": [
        {"name": f"species_{slot}", "box": [col_x, row_y, 0.087, 0.038]}
        for slot, (col_x, row_y) in enumerate([
            (0.1391, 0.2769), (0.5552, 0.2769),
            (0.1391, 0.4750), (0.5552, 0.4750),
            (0.1391, 0.6731), (0.5552, 0.6731),
        ])
    ],
    "TeamPreviewReader": (
        [{"name": f"own_{i}", "box": [
            0.0760 + (i / 5.0) * (0.0724 - 0.0760),
            0.1565 + (i / 5.0) * (0.7389 - 0.1565),
            0.0969, 0.0389
        ]} for i in range(6)]
    ),
}

# Bool detectors — no crops needed, just True/False
BOOL_DETECTORS = {
    "MoveSelectDetector", "ActionMenuDetector", "PostMatchScreenDetector",
    "PreparingForBattleDetector", "TeamSelectDetector", "TeamPreviewDetector",
    "MainMenuDetector", "MovesMoreDetector",
}

# Battle log event types
BATTLE_LOG_EVENTS = [
    "MOVE_USED", "FAINTED", "SUPER_EFFECTIVE", "NOT_VERY_EFFECTIVE",
    "CRITICAL_HIT", "NO_EFFECT", "SENT_OUT", "WITHDREW", "STAT_CHANGE",
    "STATUS_INFLICTED", "WEATHER", "TERRAIN", "ABILITY_ACTIVATED",
    "ITEM_USED", "HEALED", "DAMAGED", "OTHER",
]

def load_species_list():
    """Load species slugs from PokemonSpeciesOCR.json for autocomplete."""
    path = REPO / "Resources" / "PokemonChampions" / "PokemonSpeciesOCR.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return sorted(data.get("eng", {}).keys())
    return []


def load_move_list():
    """Load move slugs from PokemonMovesOCR.json for autocomplete."""
    path = REPO / "Resources" / "PokemonChampions" / "PokemonMovesOCR.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return sorted(data.get("eng", {}).keys())
    return []


def extract_crop(img, box):
    """Extract a crop from an image given normalized box [x, y, w, h]."""
    w, h = img.size
    x0 = max(0, int(box[0] * w))
    y0 = max(0, int(box[1] * h))
    x1 = min(w, x0 + int(box[2] * w))
    y1 = min(h, y0 + int(box[3] * h))
    return img.crop((x0, y0, x1, y1))


def draw_crop_overlay(img, crops):
    """Draw colored rectangles on image showing crop regions."""
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)
    colors = ["#ff4444", "#44ff44", "#4444ff", "#ffff44", "#ff44ff", "#44ffff"]
    for i, cd in enumerate(crops):
        box = cd["box"]
        w, h = img.size
        x0 = int(box[0] * w)
        y0 = int(box[1] * h)
        x1 = x0 + int(box[2] * w)
        y1 = y0 + int(box[3] * h)
        color = colors[i % len(colors)]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
        draw.text((x0 + 2, y0 - 12), cd["name"], fill=color)
    return overlay


class AutocompleteEntry(ttk.Entry):
    """Entry widget with autocomplete dropdown."""

    def __init__(self, parent, completions=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.completions = completions or []
        self.listbox = None
        self.bind("<KeyRelease>", self._on_key)
        self.bind("<FocusOut>", self._hide_list)
        self.bind("<Return>", self._select_first)
        self.bind("<Tab>", self._select_first)

    def _on_key(self, event):
        if event.keysym in ("Return", "Tab", "Escape", "Up", "Down"):
            if event.keysym == "Escape":
                self._hide_list()
            elif event.keysym == "Down" and self.listbox:
                self.listbox.focus_set()
                if self.listbox.size() > 0:
                    self.listbox.selection_set(0)
            return

        text = self.get().lower()
        if len(text) < 1:
            self._hide_list()
            return

        matches = [c for c in self.completions if text in c.lower()][:10]
        if not matches:
            self._hide_list()
            return

        self._show_list(matches)

    def _show_list(self, matches):
        self._hide_list()
        self.listbox = tk.Listbox(self.winfo_toplevel(), height=min(len(matches), 8),
                                  font=("SF Mono", 11), bg="#1e1e1e", fg="#cccccc",
                                  selectbackground="#264f78", selectforeground="#ffffff",
                                  borderwidth=1, relief="solid")

        # Position below the entry
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self.listbox.place(x=x - self.winfo_toplevel().winfo_rootx(),
                          y=y - self.winfo_toplevel().winfo_rooty(),
                          width=self.winfo_width())

        for m in matches:
            self.listbox.insert(tk.END, m)

        self.listbox.bind("<Double-1>", self._on_listbox_select)
        self.listbox.bind("<Return>", self._on_listbox_select)

    def _hide_list(self, event=None):
        if self.listbox:
            self.listbox.destroy()
            self.listbox = None

    def _select_first(self, event=None):
        if self.listbox and self.listbox.size() > 0:
            sel = self.listbox.curselection()
            idx = sel[0] if sel else 0
            val = self.listbox.get(idx)
            self.delete(0, tk.END)
            self.insert(0, val)
            self._hide_list()
            return "break"

    def _on_listbox_select(self, event):
        sel = self.listbox.curselection()
        if sel:
            val = self.listbox.get(sel[0])
            self.delete(0, tk.END)
            self.insert(0, val)
            self._hide_list()
            self.focus_set()


class LabelingApp:
    def __init__(self, source_dir, reader_name):
        self.source_dir = Path(source_dir)
        self.reader_name = reader_name
        self.is_bool = reader_name in BOOL_DETECTORS
        self.crop_defs = CROP_DEFS.get(reader_name, [])
        if callable(self.crop_defs):
            self.crop_defs = list(self.crop_defs)

        # Load completions
        self.species_list = load_species_list()
        self.move_list = load_move_list()

        # Load images
        self.images = sorted([
            f for f in self.source_dir.iterdir()
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
        ])
        self.index = 0
        self.labels = {}  # filename -> label dict
        self.label_file = self.source_dir / f".labels_{reader_name}.json"

        # Load existing labels
        if self.label_file.exists():
            with open(self.label_file) as f:
                self.labels = json.load(f)

        # Determine dest directory
        self.dest_dir = TESTS_ROOT / reader_name

        # Skip already-labeled images
        self._skip_to_unlabeled()

        self._build_ui()

    def _skip_to_unlabeled(self):
        """Skip forward to the first unlabeled image."""
        while self.index < len(self.images):
            fname = self.images[self.index].name
            if fname not in self.labels:
                break
            self.index += 1
        if self.index >= len(self.images):
            self.index = 0  # wrap around if all labeled

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title(f"Frame Labeler — {self.reader_name}")
        self.root.configure(bg="#1a1a2e")

        # Make window large
        self.root.geometry("1400x900")

        # ── Top bar: progress ──
        top = tk.Frame(self.root, bg="#16213e", pady=6, padx=12)
        top.pack(fill=tk.X)

        self.progress_label = tk.Label(top, text="", font=("SF Mono", 12),
                                       bg="#16213e", fg="#e0e0e0")
        self.progress_label.pack(side=tk.LEFT)

        self.reader_label = tk.Label(top, text=self.reader_name, font=("SF Mono", 12, "bold"),
                                     bg="#16213e", fg="#0f9d58")
        self.reader_label.pack(side=tk.RIGHT)

        # ── Main content ──
        main = tk.Frame(self.root, bg="#1a1a2e")
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left: full image with crop overlays
        left = tk.Frame(main, bg="#1a1a2e")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.image_label = tk.Label(left, bg="#0d1117")
        self.image_label.pack(fill=tk.BOTH, expand=True)

        # Right: crop previews + labeling controls
        right = tk.Frame(main, bg="#1a1a2e", width=380)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        right.pack_propagate(False)

        # Crop previews
        self.crops_frame = tk.Frame(right, bg="#1a1a2e")
        self.crops_frame.pack(fill=tk.X, pady=(0, 8))

        # ── Label controls ──
        controls = tk.Frame(right, bg="#1a1a2e")
        controls.pack(fill=tk.X, pady=4)

        self.label_widgets = []

        if self.is_bool:
            self._build_bool_controls(controls)
        elif self.reader_name == "BattleLogReader":
            self._build_battle_log_controls(controls)
        elif self.reader_name in ("MoveSelectCursorSlot",):
            self._build_int_controls(controls, "Cursor Slot", 0, 3)
        elif self.reader_name in ("OpponentHPReader", "OpponentHPReader_Doubles"):
            self._build_int_controls(controls, "HP %", 0, 100)
        elif self.reader_name == "MoveNameReader":
            self._build_multi_text_controls(controls, 4, "Move", self.move_list)
        elif self.reader_name in ("TeamSelectReader", "TeamSummaryReader", "TeamPreviewReader"):
            self._build_multi_text_controls(controls, 6, "Species", self.species_list)
        elif self.reader_name in ("SpeciesReader", "SpeciesReader_Doubles"):
            self._build_multi_text_controls(controls, 1, "Species", self.species_list)
        else:
            self._build_text_controls(controls)

        # ── Bottom bar: nav + actions ──
        bottom = tk.Frame(self.root, bg="#16213e", pady=8, padx=12)
        bottom.pack(fill=tk.X)

        nav_frame = tk.Frame(bottom, bg="#16213e")
        nav_frame.pack(fill=tk.X)

        btn_style = {"font": ("SF Mono", 11), "bg": "#21262d", "fg": "#c9d1d9",
                     "activebackground": "#30363d", "activeforeground": "#ffffff",
                     "relief": "flat", "padx": 12, "pady": 4}

        tk.Button(nav_frame, text="< Prev (Left)", command=self.prev_image, **btn_style).pack(side=tk.LEFT, padx=2)
        tk.Button(nav_frame, text="Next (Right) >", command=self.next_image, **btn_style).pack(side=tk.LEFT, padx=2)
        tk.Button(nav_frame, text="Skip (S)", command=self.skip_image,
                  font=("SF Mono", 11), bg="#6e4000", fg="#ffffff",
                  activebackground="#8b5000", relief="flat", padx=12, pady=4).pack(side=tk.LEFT, padx=8)
        tk.Button(nav_frame, text="Save Label (Enter)", command=self.save_label,
                  font=("SF Mono", 11, "bold"), bg="#238636", fg="#ffffff",
                  activebackground="#2ea043", relief="flat", padx=16, pady=4).pack(side=tk.LEFT, padx=2)
        tk.Button(nav_frame, text="Export All", command=self.export_all,
                  font=("SF Mono", 11), bg="#1f6feb", fg="#ffffff",
                  activebackground="#388bfd", relief="flat", padx=12, pady=4).pack(side=tk.RIGHT, padx=2)

        self.status_label = tk.Label(bottom, text="", font=("SF Mono", 10),
                                     bg="#16213e", fg="#8b949e")
        self.status_label.pack(fill=tk.X, pady=(4, 0))

        # ── Keybindings ──
        self.root.bind("<Left>", lambda e: self.prev_image())
        self.root.bind("<Right>", lambda e: self.next_image())
        self.root.bind("<Return>", lambda e: self.save_label())
        self.root.bind("s", lambda e: self.skip_image())
        self.root.bind("<Escape>", lambda e: self.root.quit())

        # Bool-specific shortcuts
        if self.is_bool:
            self.root.bind("t", lambda e: self._set_bool(True))
            self.root.bind("f", lambda e: self._set_bool(False))
            self.root.bind("1", lambda e: self._set_bool(True))
            self.root.bind("0", lambda e: self._set_bool(False))

        # Cursor slot shortcuts
        if self.reader_name == "MoveSelectCursorSlot":
            for i in range(4):
                self.root.bind(str(i), lambda e, idx=i: self._set_int(idx))

        # Load first image after window is mapped and has real dimensions
        self._first_load_done = False
        self.root.after(100, self._initial_show)

    def _initial_show(self):
        """Keep retrying until widget has real dimensions."""
        self.root.update_idletasks()
        cw = self.image_label.winfo_width()
        ch = self.image_label.winfo_height()
        print(f"[DEBUG] initial_show: label size={cw}x{ch}", flush=True)
        if cw < 50 or ch < 50:
            self.root.after(100, self._initial_show)
            return
        self._first_load_done = True
        try:
            self._show_current()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] _show_current failed: {e}", flush=True)

    def _build_bool_controls(self, parent):
        tk.Label(parent, text="Detection Result:", font=("SF Mono", 12, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(anchor=tk.W, pady=(0, 4))

        self.bool_var = tk.BooleanVar(value=True)

        frame = tk.Frame(parent, bg="#1a1a2e")
        frame.pack(fill=tk.X)

        tk.Radiobutton(frame, text="True (T/1)", variable=self.bool_var, value=True,
                       font=("SF Mono", 12), bg="#1a1a2e", fg="#3fb950",
                       selectcolor="#1a1a2e", activebackground="#1a1a2e").pack(anchor=tk.W)
        tk.Radiobutton(frame, text="False (F/0)", variable=self.bool_var, value=False,
                       font=("SF Mono", 12), bg="#1a1a2e", fg="#f85149",
                       selectcolor="#1a1a2e", activebackground="#1a1a2e").pack(anchor=tk.W)

    def _build_battle_log_controls(self, parent):
        tk.Label(parent, text="Event Type:", font=("SF Mono", 12, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(anchor=tk.W, pady=(0, 4))

        self.event_var = tk.StringVar(value=BATTLE_LOG_EVENTS[0])
        combo = ttk.Combobox(parent, textvariable=self.event_var,
                            values=BATTLE_LOG_EVENTS, font=("SF Mono", 11),
                            state="readonly", width=30)
        combo.pack(fill=tk.X, pady=2)

        # Number shortcuts for common events
        tk.Label(parent, text="Shortcuts: 1=MOVE_USED 2=FAINTED 3=SUPER_EFF\n"
                              "4=NOT_VERY 5=CRIT 6=SENT_OUT 7=STATUS",
                 font=("SF Mono", 9), bg="#1a1a2e", fg="#8b949e",
                 justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 0))

        for i, evt in enumerate(BATTLE_LOG_EVENTS[:7]):
            self.root.bind(str(i + 1), lambda e, ev=evt: self.event_var.set(ev))

    def _build_int_controls(self, parent, label, min_val, max_val):
        tk.Label(parent, text=f"{label}:", font=("SF Mono", 12, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(anchor=tk.W, pady=(0, 4))

        self.int_var = tk.IntVar(value=min_val)

        if max_val <= 10:
            # Use radio buttons for small ranges
            frame = tk.Frame(parent, bg="#1a1a2e")
            frame.pack(fill=tk.X)
            for i in range(min_val, max_val + 1):
                tk.Radiobutton(frame, text=str(i), variable=self.int_var, value=i,
                               font=("SF Mono", 14), bg="#1a1a2e", fg="#58a6ff",
                               selectcolor="#1a1a2e", activebackground="#1a1a2e").pack(side=tk.LEFT, padx=8)
        else:
            # Use spinbox for large ranges
            spin = tk.Spinbox(parent, from_=min_val, to=max_val, textvariable=self.int_var,
                             font=("SF Mono", 14), width=6, bg="#21262d", fg="#c9d1d9",
                             buttonbackground="#30363d")
            spin.pack(anchor=tk.W, pady=2)

    def _build_multi_text_controls(self, parent, count, label, completions):
        tk.Label(parent, text=f"{label} Labels ({count} slots):",
                 font=("SF Mono", 12, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(anchor=tk.W, pady=(0, 4))

        self.text_entries = []
        for i in range(count):
            frame = tk.Frame(parent, bg="#1a1a2e")
            frame.pack(fill=tk.X, pady=1)

            tk.Label(frame, text=f"{i}:", font=("SF Mono", 11),
                     bg="#1a1a2e", fg="#8b949e", width=3).pack(side=tk.LEFT)

            entry = AutocompleteEntry(frame, completions=completions,
                                      font=("SF Mono", 11), width=28)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.text_entries.append(entry)

        tk.Label(parent, text="Use NONE for empty/unreadable slots",
                 font=("SF Mono", 9), bg="#1a1a2e", fg="#8b949e").pack(anchor=tk.W, pady=(4, 0))

    def _build_text_controls(self, parent):
        tk.Label(parent, text="Label:", font=("SF Mono", 12, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(anchor=tk.W, pady=(0, 4))
        self.text_entry = AutocompleteEntry(parent, completions=self.species_list + self.move_list,
                                            font=("SF Mono", 11), width=30)
        self.text_entry.pack(fill=tk.X, pady=2)

    def _set_bool(self, value):
        self.bool_var.set(value)
        self.save_label()

    def _set_int(self, value):
        self.int_var.set(value)
        self.save_label()

    def _get_label(self):
        """Get the current label value from the UI controls."""
        if self.is_bool:
            return {"type": "bool", "value": self.bool_var.get()}

        if self.reader_name == "BattleLogReader":
            return {"type": "event", "value": self.event_var.get()}

        if self.reader_name in ("MoveSelectCursorSlot", "OpponentHPReader", "OpponentHPReader_Doubles"):
            return {"type": "int", "value": self.int_var.get()}

        if hasattr(self, "text_entries"):
            values = [e.get().strip() for e in self.text_entries]
            return {"type": "multi", "values": values}

        if hasattr(self, "text_entry"):
            return {"type": "text", "value": self.text_entry.get().strip()}

        return None

    def _label_to_filename_suffix(self, label):
        """Convert a label dict to the filename suffix for CommandLineTests."""
        if label["type"] == "bool":
            return "True" if label["value"] else "False"

        if label["type"] == "event":
            return label["value"]

        if label["type"] == "int":
            return str(label["value"])

        if label["type"] == "multi":
            vals = [v if v else "NONE" for v in label["values"]]
            return "_".join(vals)

        if label["type"] == "text":
            return label["value"] if label["value"] else "NONE"

        return "UNKNOWN"

    def _render_main_image(self, img_display):
        """Render image into the label widget."""
        self.root.update_idletasks()
        cw = self.image_label.winfo_width()
        ch = self.image_label.winfo_height()
        if cw < 50:
            cw = 900
        if ch < 50:
            ch = 700

        scale = min(cw / img_display.width, ch / img_display.height, 1.0)
        disp_w = max(1, int(img_display.width * scale))
        disp_h = max(1, int(img_display.height * scale))

        img_resized = img_display.resize((disp_w, disp_h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img_resized)
        self.image_label.configure(image=self._photo)
        self.image_label.image = self._photo  # prevent GC
        print(f"[DEBUG] rendered {disp_w}x{disp_h} into {cw}x{ch}", flush=True)

    def _show_current(self):
        if not self.images:
            self.status_label.config(text="No images found!")
            return

        if self.index >= len(self.images):
            self.index = len(self.images) - 1
        if self.index < 0:
            self.index = 0

        img_path = self.images[self.index]
        fname = img_path.name

        # Progress
        labeled_count = sum(1 for f in self.images if f.name in self.labels)
        self.progress_label.config(
            text=f"[{self.index + 1}/{len(self.images)}]  "
                 f"Labeled: {labeled_count}/{len(self.images)}  "
                 f"({100 * labeled_count / max(1, len(self.images)):.0f}%)"
        )

        # Load image
        img = Image.open(img_path).convert("RGB")

        # Draw crop overlays
        if self.crop_defs:
            img_display = draw_crop_overlay(img, self.crop_defs)
        else:
            img_display = img

        self._current_img = img_display
        self._current_img_raw = img
        self._render_main_image(img_display)

        # Show crop previews
        for w in self.crops_frame.winfo_children():
            w.destroy()

        if self.crop_defs:
            tk.Label(self.crops_frame, text="Crop Previews:",
                     font=("SF Mono", 10, "bold"), bg="#1a1a2e", fg="#8b949e").pack(anchor=tk.W)

            for cd in self.crop_defs:
                crop_img = extract_crop(self._current_img_raw, cd["box"])
                # Upscale 4x with nearest neighbor
                cw_crop = max(1, crop_img.width * 4)
                ch_crop = max(1, crop_img.height * 4)
                # Cap at 360px wide
                if cw_crop > 360:
                    ratio = 360 / cw_crop
                    cw_crop = 360
                    ch_crop = max(1, int(ch_crop * ratio))
                crop_up = crop_img.resize((cw_crop, ch_crop), Image.NEAREST)

                frame = tk.Frame(self.crops_frame, bg="#1a1a2e")
                frame.pack(fill=tk.X, pady=2)

                photo = ImageTk.PhotoImage(crop_up)
                label = tk.Label(frame, image=photo, bg="#0d1117", borderwidth=1, relief="solid")
                label.image = photo  # prevent GC
                label.pack(side=tk.LEFT, padx=(0, 8))

                tk.Label(frame, text=cd["name"], font=("SF Mono", 9),
                         bg="#1a1a2e", fg="#8b949e").pack(side=tk.LEFT, anchor=tk.N)

        # Show filename
        status = "LABELED" if fname in self.labels else "unlabeled"
        status_color = "#3fb950" if fname in self.labels else "#8b949e"
        self.status_label.config(text=f"{fname}  [{status}]", fg=status_color)

        # Pre-fill existing label
        if fname in self.labels:
            self._prefill_label(self.labels[fname])

    def _prefill_label(self, label):
        """Pre-fill the UI controls with an existing label."""
        if label["type"] == "bool":
            self.bool_var.set(label["value"])
        elif label["type"] == "event":
            self.event_var.set(label["value"])
        elif label["type"] == "int":
            self.int_var.set(label["value"])
        elif label["type"] == "multi":
            for i, val in enumerate(label.get("values", [])):
                if i < len(self.text_entries):
                    self.text_entries[i].delete(0, tk.END)
                    self.text_entries[i].insert(0, val)
        elif label["type"] == "text":
            self.text_entry.delete(0, tk.END)
            self.text_entry.insert(0, label.get("value", ""))

    def save_label(self):
        if not self.images:
            return

        label = self._get_label()
        if label is None:
            return

        fname = self.images[self.index].name
        self.labels[fname] = label

        # Persist labels
        with open(self.label_file, "w") as f:
            json.dump(self.labels, f, indent=2)

        self.status_label.config(text=f"Saved: {fname} -> {self._label_to_filename_suffix(label)}",
                                 fg="#3fb950")

        # Auto-advance
        self.next_image()

    def skip_image(self):
        """Skip without labeling, mark as skipped."""
        if not self.images:
            return
        fname = self.images[self.index].name
        self.labels[fname] = {"type": "skip", "value": None}
        with open(self.label_file, "w") as f:
            json.dump(self.labels, f, indent=2)
        self.status_label.config(text=f"Skipped: {fname}", fg="#6e4000")
        self.next_image()

    def next_image(self):
        if self.index < len(self.images) - 1:
            self.index += 1
            self._show_current()

    def prev_image(self):
        if self.index > 0:
            self.index -= 1
            self._show_current()

    def export_all(self):
        """Export all labeled images to CommandLineTests with proper filenames."""
        self.dest_dir.mkdir(parents=True, exist_ok=True)

        exported = 0
        skipped = 0
        for img_path in self.images:
            fname = img_path.name
            if fname not in self.labels:
                continue
            label = self.labels[fname]
            if label["type"] == "skip":
                skipped += 1
                continue

            suffix = self._label_to_filename_suffix(label)
            base = img_path.stem
            dest_name = f"{base}_{suffix}.png"
            dest_path = self.dest_dir / dest_name

            if not dest_path.exists():
                shutil.copy2(img_path, dest_path)
                exported += 1

        msg = f"Exported {exported} images to {self.dest_dir}\n({skipped} skipped)"
        self.status_label.config(text=msg, fg="#58a6ff")
        messagebox.showinfo("Export Complete", msg)

    def run(self):
        self.root.mainloop()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Label extracted frames for test suite")
    parser.add_argument("source_dir", help="Directory containing frames to label")
    parser.add_argument("--reader", required=True,
                        help="Reader/detector name (e.g. MoveNameReader, SpeciesReader)")
    args = parser.parse_args()

    if not os.path.isdir(args.source_dir):
        print(f"ERROR: {args.source_dir} is not a directory")
        sys.exit(1)

    valid_readers = list(CROP_DEFS.keys()) + list(BOOL_DETECTORS)
    if args.reader not in valid_readers:
        print(f"WARNING: '{args.reader}' not in known readers.")
        print(f"Known: {', '.join(sorted(valid_readers))}")
        resp = input("Continue anyway? [y/N] ")
        if resp.lower() != "y":
            sys.exit(1)

    app = LabelingApp(args.source_dir, args.reader)
    app.run()


if __name__ == "__main__":
    main()
