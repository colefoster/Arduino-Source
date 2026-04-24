#!/usr/bin/env python3
"""
Extract and classify frames from a YouTube VOD (or local video).

Downloads via yt-dlp, extracts frames with ffmpeg, classifies each frame
using color-based detectors matching the C++ SerialPrograms logic, deduplicates,
and saves useful frames organized by screen type.

Usage:
    python scripts/extract_vod_frames.py <URL_OR_PATH> [options]

Examples:
    python scripts/extract_vod_frames.py https://youtube.com/watch?v=XXXX
    python scripts/extract_vod_frames.py gameplay.mp4 --skip-download --interval 0.5
    python scripts/extract_vod_frames.py https://youtube.com/watch?v=XXXX --run-ocr --verbose
"""

import argparse
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    from PIL import Image
except ImportError:
    print("ERROR: pip install Pillow")
    sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO / "ref_frames" / "vod_extract"


# ── Color math (matches C++ image_stats / is_solid) ───────────────

def image_stats_box(img, box):
    """Compute avg RGB and stddev for a normalized (x, y, w, h) box."""
    w, h = img.size
    x1 = int(box[0] * w)
    y1 = int(box[1] * h)
    x2 = int((box[0] + box[2]) * w)
    y2 = int((box[1] + box[3]) * h)
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)

    crop = img.crop((x1, y1, x2, y2))
    pixels = list(crop.getdata())
    n = len(pixels)
    if n == 0:
        return (0, 0, 0), (0, 0, 0)

    sum_r = sum_g = sum_b = 0
    sqr_r = sqr_g = sqr_b = 0
    for r, g, b in pixels:
        sum_r += r; sum_g += g; sum_b += b
        sqr_r += r * r; sqr_g += g * g; sqr_b += b * b

    avg = (sum_r / n, sum_g / n, sum_b / n)
    if n > 1:
        var_r = max(0, (sqr_r - sum_r * sum_r / n) / (n - 1))
        var_g = max(0, (sqr_g - sum_g * sum_g / n) / (n - 1))
        var_b = max(0, (sqr_b - sum_b * sum_b / n) / (n - 1))
        sd = (math.sqrt(var_r), math.sqrt(var_g), math.sqrt(var_b))
    else:
        sd = (0, 0, 0)
    return avg, sd


def color_ratio(avg):
    s = avg[0] + avg[1] + avg[2]
    if s == 0:
        return (0.333, 0.333, 0.333)
    return (avg[0] / s, avg[1] / s, avg[2] / s)


def is_solid(avg, sd, expected_ratio, max_dist=0.18, max_stddev_sum=120):
    if sd[0] + sd[1] + sd[2] > max_stddev_sum:
        return False
    ratio = color_ratio(avg)
    dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(ratio, expected_ratio)))
    return dist <= max_dist


def check_box(img, box, expected, max_dist=0.18, max_stddev=120):
    """Check if a box region matches an expected color ratio."""
    avg, sd = image_stats_box(img, box)
    return is_solid(avg, sd, expected, max_dist, max_stddev)


# ── Frame classifiers (ported from C++ detectors) ────────────────

# Colors (as ratio tuples)
WINNER_BLUE     = (0.15, 0.24, 0.61)
LOSER_RED       = (0.67, 0.13, 0.20)
GREEN_PILL      = (0.40, 0.60, 0.00)
PLAYER_BLUE     = (0.14, 0.19, 0.67)
OPPONENT_PINK   = (0.48, 0.17, 0.35)
MOVE_GREEN      = (0.30, 0.47, 0.23)
ACTION_GLOW     = (0.41, 0.46, 0.13)

# Boxes
RESULT_LEFT     = (0.160, 0.870, 0.180, 0.040)
RESULT_RIGHT    = (0.660, 0.870, 0.180, 0.040)

POST_MATCH_BUTTONS = [
    (0.1042, 0.9222, 0.0417, 0.0222),
    (0.3125, 0.9222, 0.0417, 0.0222),
    (0.6719, 0.9222, 0.0208, 0.0222),
]

PREPARING_LEFT  = (0.2083, 0.8519, 0.0521, 0.0278)
PREPARING_RIGHT = (0.7448, 0.8565, 0.0677, 0.0278)

MOVE_SLOTS = [
    (0.7448, 0.5278, 0.0104, 0.0500),
    (0.7448, 0.6481, 0.0104, 0.0500),
    (0.7448, 0.7685, 0.0104, 0.0500),
    (0.7448, 0.8889, 0.0104, 0.0500),
]

ACTION_FIGHT   = (0.9062, 0.5694, 0.0260, 0.0185)
ACTION_POKEMON = (0.9062, 0.7981, 0.0260, 0.0213)

# Team select: check for the left panel header area (player name bar, blue-ish)
TEAM_SELECT_HEADER = (0.040, 0.050, 0.200, 0.025)
TEAM_SELECT_BLUE   = (0.18, 0.22, 0.60)

# Battle log text bar
BATTLE_LOG_BAR = (0.1042, 0.7454, 0.7292, 0.0417)


def detect_result_screen(img):
    left_blue  = check_box(img, RESULT_LEFT,  WINNER_BLUE, 0.18, 80)
    left_red   = check_box(img, RESULT_LEFT,  LOSER_RED,   0.18, 80)
    right_blue = check_box(img, RESULT_RIGHT, WINNER_BLUE, 0.18, 80)
    right_red  = check_box(img, RESULT_RIGHT, LOSER_RED,   0.18, 80)
    if left_blue and right_red:
        return True, {"won": True}
    if left_red and right_blue:
        return True, {"won": False}
    return False, {}


def detect_post_match(img):
    for i, box in enumerate(POST_MATCH_BUTTONS):
        if check_box(img, box, GREEN_PILL, 0.18, 100):
            names = ["quit", "edit", "continue"]
            return True, {"cursor": names[i]}
    return False, {}


def detect_preparing(img):
    left_ok  = check_box(img, PREPARING_LEFT,  PLAYER_BLUE,   0.18, 150)
    right_ok = check_box(img, PREPARING_RIGHT, OPPONENT_PINK, 0.18, 120)
    if left_ok and right_ok:
        return True, {}
    return False, {}


def detect_move_select(img):
    for i, box in enumerate(MOVE_SLOTS):
        if check_box(img, box, MOVE_GREEN, 0.18, 120):
            return True, {"cursor_slot": i}
    return False, {}


def detect_action_menu(img):
    if check_box(img, ACTION_FIGHT, ACTION_GLOW, 0.15, 120):
        return True, {"button": "fight"}
    if check_box(img, ACTION_POKEMON, ACTION_GLOW, 0.15, 120):
        return True, {"button": "pokemon"}
    return False, {}


def detect_team_select(img):
    # Heuristic: check for the timer/header area at top which has a blue-purple tint
    # and the left panel has a distinctive green-highlighted slot
    # Check for "Ranked Battles" header bar at top center
    header_box = (0.300, 0.000, 0.400, 0.035)
    avg, sd = image_stats_box(img, header_box)
    # The header bar in team select is dark with white text — low brightness
    brightness = sum(avg) / 3
    if brightness > 40 and brightness < 120:
        # Also check for left panel slots (green/yellow highlighted slots)
        slot_box = (0.035, 0.100, 0.250, 0.080)
        avg2, sd2 = image_stats_box(img, slot_box)
        brightness2 = sum(avg2) / 3
        # Team select left panel slots are brightly colored (green/yellow/purple)
        if brightness2 > 80 and sd2[0] + sd2[1] + sd2[2] > 30:
            # Check for opponent sprites panel on right (reddish-pink headers)
            right_box = (0.830, 0.040, 0.080, 0.025)
            if check_box(img, right_box, OPPONENT_PINK, 0.25, 150):
                return True, {}
    return False, {}


def detect_battle_log(img):
    # The game's battle log bar is white text on a semi-transparent dark overlay.
    # Key: the game text bar has a relatively UNIFORM dark background with scattered
    # bright text pixels. YouTube subtitles (yellow, bold) on transparent bg look
    # different — they have higher color saturation and no dark bar behind them.
    #
    # We check: the bar region must be DARK overall (avg brightness < 80) with
    # some bright pixels creating moderate stddev. Also check that the text is
    # white-ish (low color saturation) rather than yellow (high G, low B).
    avg, sd = image_stats_box(img, BATTLE_LOG_BAR)
    stddev_sum = sd[0] + sd[1] + sd[2]
    brightness = sum(avg) / 3

    # The dark overlay bar: avg brightness 30-80, moderate stddev from white text
    if brightness < 30 or brightness > 80:
        return False, {}
    if stddev_sum < 40:
        return False, {}

    # Check that the bright pixels are white-ish, not yellow (YouTube subs).
    # White text: R≈G≈B. Yellow subs: R≈G >> B.
    # If blue channel avg is very low relative to red/green, it's yellow subs.
    if avg[2] > 0 and avg[0] / (avg[2] + 1) > 2.5:
        return False, {}  # yellow-heavy = YouTube subtitles

    return True, {}


DETECTORS = [
    ("result_screen",  detect_result_screen),
    ("post_match",     detect_post_match),
    ("preparing",      detect_preparing),
    ("move_select",    detect_move_select),
    ("action_menu",    detect_action_menu),
    ("team_select",    detect_team_select),
    ("battle_log",     detect_battle_log),
]

# Types worth saving by default
USEFUL_TYPES = {"result_screen", "post_match", "preparing", "move_select",
                "action_menu", "team_select", "battle_log"}


def classify_frame(img):
    """Run all detectors in priority order, return (type, metadata)."""
    for type_name, detector in DETECTORS:
        matched, meta = detector(img)
        if matched:
            return type_name, meta
    return "unknown", {}


# ── Perceptual hash for dedup ─────────────────────────────────────

def dhash(img, size=8):
    """Compute a difference hash (64-bit) for deduplication."""
    small = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            idx = row * (size + 1) + col
            if pixels[idx] < pixels[idx + 1]:
                bits |= 1 << (row * size + col)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


# ── Frame extraction ──────────────────────────────────────────────

def extract_video_id(url):
    """Extract YouTube video ID from URL."""
    parsed = urlparse(url)
    if "youtube.com" in parsed.hostname or "www.youtube.com" in parsed.hostname:
        qs = parse_qs(parsed.query)
        return qs.get("v", ["unknown"])[0]
    if "youtu.be" in parsed.hostname:
        return parsed.path.lstrip("/")
    return "unknown"


def is_url(source):
    return source.startswith("http") or "youtube" in source or "youtu.be" in source


def download_video(url, out_dir):
    """Download video with yt-dlp, return path to downloaded file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "source.%(ext)s")
    cmd = [
        "yt-dlp", "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--no-warnings", "--merge-output-format", "mp4",
        "-o", template, url,
    ]
    print(f"  Downloading with yt-dlp...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  yt-dlp error: {result.stderr[:500]}")
        sys.exit(1)

    # Find the downloaded file
    for ext in ["mp4", "mkv", "webm"]:
        p = out_dir / f"source.{ext}"
        if p.exists():
            print(f"  Downloaded: {p} ({p.stat().st_size / 1e6:.1f} MB)")
            return str(p)

    print("  ERROR: yt-dlp finished but no output file found")
    sys.exit(1)


def frame_generator(source, interval, start=0):
    """Yield (frame_number, PIL.Image) from a local video file."""
    fps_filter = f"fps=1/{interval}"

    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
    ]
    if start > 0:
        ffmpeg_cmd += ["-ss", str(start)]
    ffmpeg_cmd += [
        "-i", source,
        "-vf", fps_filter,
        "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2",
        "pipe:1",
    ]

    ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    # Read JPEG frames from stdout by scanning for SOI/EOI markers
    buf = b""
    frame_num = int(start / interval)
    SOI = b"\xff\xd8"
    EOI = b"\xff\xd9"

    try:
        while True:
            chunk = ffmpeg.stdout.read(65536)
            if not chunk:
                break
            buf += chunk

            while True:
                soi = buf.find(SOI)
                if soi < 0:
                    buf = buf[-1:]  # keep last byte in case SOI straddles chunks
                    break
                eoi = buf.find(EOI, soi + 2)
                if eoi < 0:
                    break  # need more data

                jpeg_data = buf[soi:eoi + 2]
                buf = buf[eoi + 2:]

                try:
                    img = Image.open(io.BytesIO(jpeg_data)).convert("RGB")
                    yield frame_num, img
                    frame_num += 1
                except Exception:
                    pass  # corrupt frame, skip
    finally:
        ffmpeg.stdout.close()
        ffmpeg.wait()


# ── Main logic ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract and classify frames from a YouTube VOD or local video."
    )
    parser.add_argument("source", help="YouTube URL or local video file path")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between frame samples (default: 1.0)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Base output directory")
    parser.add_argument("--start", type=float, default=0,
                        help="Start time in seconds (skip intro)")
    parser.add_argument("--max-frames", type=int, default=0,
                        help="Stop after N frames (0 = unlimited)")
    parser.add_argument("--run-ocr", action="store_true",
                        help="Run OCR on saved move_select/battle_log frames")
    parser.add_argument("--save-all", action="store_true",
                        help="Also save unknown/battle_hud frames")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify but don't save (print stats only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-frame classification")

    args = parser.parse_args()

    # Check dependencies
    for tool in ["ffmpeg"]:
        if not shutil.which(tool):
            print(f"ERROR: {tool} not found on PATH. brew install {tool}")
            sys.exit(1)

    url_source = is_url(args.source)
    if url_source and not shutil.which("yt-dlp"):
        print("ERROR: yt-dlp not found on PATH. brew install yt-dlp")
        sys.exit(1)

    # Determine output directory
    if url_source:
        video_id = extract_video_id(args.source)
    else:
        video_id = Path(args.source).stem

    out_dir = args.output_dir / video_id

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source: {args.source}")
    print(f"Video ID: {video_id}")
    print(f"Interval: {args.interval}s")
    if args.start > 0:
        print(f"Start: {args.start}s")
    print(f"Output: {out_dir}")
    print()

    # Download video if URL
    if url_source:
        video_path = download_video(args.source, out_dir)
    else:
        video_path = args.source

    # State for deduplication
    prev_type = None
    prev_type_start_frame = 0
    last_saved_time = {}      # type -> last saved timestamp
    last_dhash = {}            # type -> last saved dhash
    pending_last = None        # (frame_num, img, type, meta) — last frame of prev type

    # Stats
    type_counts = {}
    saved_counts = {}
    manifest = []

    DEDUP_INTERVAL = 3.0  # seconds between saves of same type
    DHASH_THRESHOLD = 5   # hamming distance threshold

    def save_frame(frame_num, img, frame_type, meta):
        """Save a frame and update tracking state."""
        if args.dry_run:
            return None

        type_dir = out_dir / frame_type
        type_dir.mkdir(exist_ok=True)

        # Build filename with metadata
        suffix_parts = []
        if "cursor_slot" in meta:
            suffix_parts.append(f"s{meta['cursor_slot']}")
        if "button" in meta:
            suffix_parts.append(meta["button"])
        if "won" in meta:
            suffix_parts.append("won" if meta["won"] else "lost")
        if "cursor" in meta:
            suffix_parts.append(meta["cursor"])

        suffix = "_" + "_".join(suffix_parts) if suffix_parts else ""
        fname = f"frame_{frame_num:05d}{suffix}.jpg"
        path = type_dir / fname
        img.save(path, quality=92)
        return str(path.relative_to(out_dir))

    def should_save(frame_num, img, frame_type, meta):
        """Decide whether to save this frame based on dedup rules."""
        timestamp = frame_num * args.interval

        # Always save on type transition
        if frame_type != prev_type:
            return True, "transition"

        # Check time-based dedup
        last_t = last_saved_time.get(frame_type, -999)
        if timestamp - last_t < DEDUP_INTERVAL:
            return False, "too_soon"

        # Check perceptual hash dedup
        h = dhash(img)
        prev_h = last_dhash.get(frame_type)
        if prev_h is not None and hamming(h, prev_h) < DHASH_THRESHOLD:
            return False, "duplicate"

        return True, "periodic"

    print("Extracting frames...")
    t0 = time.time()

    for frame_num, img in frame_generator(video_path, args.interval, args.start):
        if args.max_frames and frame_num >= args.max_frames:
            break

        frame_type, meta = classify_frame(img)
        timestamp = frame_num * args.interval

        type_counts[frame_type] = type_counts.get(frame_type, 0) + 1

        if args.verbose:
            meta_str = " ".join(f"{k}={v}" for k, v in meta.items())
            print(f"  [{frame_num:5d}] {timestamp:7.1f}s  {frame_type:16s}  {meta_str}")

        # Check if we should save
        is_useful = frame_type in USEFUL_TYPES or args.save_all
        save_it = False
        reason = "not_useful"
        saved_path = None

        if is_useful:
            save_it, reason = should_save(frame_num, img, frame_type, meta)

        # On type transition, also save the pending "last frame" of previous type
        if frame_type != prev_type and pending_last is not None:
            pf, pi, pt, pm = pending_last
            if pt in USEFUL_TYPES or args.save_all:
                p_path = save_frame(pf, pi, pt, pm)
                saved_counts[pt] = saved_counts.get(pt, 0) + 1
                manifest.append({
                    "frame": pf, "time": pf * args.interval,
                    "type": pt, "meta": pm,
                    "saved": True, "reason": "last_before_transition",
                    "path": p_path,
                })
            pending_last = None

        if save_it:
            saved_path = save_frame(frame_num, img, frame_type, meta)
            saved_counts[frame_type] = saved_counts.get(frame_type, 0) + 1
            last_saved_time[frame_type] = timestamp
            last_dhash[frame_type] = dhash(img)

        manifest.append({
            "frame": frame_num, "time": timestamp,
            "type": frame_type, "meta": meta,
            "saved": save_it, "reason": reason,
            "path": saved_path,
        })

        # Track pending last frame for transition saves
        pending_last = (frame_num, img, frame_type, meta)
        if frame_type != prev_type:
            prev_type_start_frame = frame_num
        prev_type = frame_type

        # Progress
        if frame_num > 0 and frame_num % 50 == 0:
            elapsed = time.time() - t0
            print(f"  ... {frame_num} frames in {elapsed:.1f}s "
                  f"({sum(saved_counts.values())} saved)")

    elapsed = time.time() - t0

    # Save manifest
    if not args.dry_run:
        with open(out_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

    # Print summary
    total = sum(type_counts.values())
    total_saved = sum(saved_counts.values())
    print(f"\n{'='*50}")
    print(f"  DONE — {total} frames in {elapsed:.1f}s")
    print(f"  Saved: {total_saved} frames")
    print(f"{'='*50}")
    print(f"\n  {'Type':<20s} {'Detected':>8s}  {'Saved':>6s}")
    print(f"  {'-'*20} {'-'*8}  {'-'*6}")
    for t in [d[0] for d in DETECTORS] + ["unknown"]:
        det = type_counts.get(t, 0)
        sav = saved_counts.get(t, 0)
        if det > 0:
            print(f"  {t:<20s} {det:>8d}  {sav:>6d}")
    print()

    if not args.dry_run:
        print(f"  Output: {out_dir}")
        print(f"  Manifest: {out_dir / 'manifest.json'}")

    # Optional OCR
    if args.run_ocr and not args.dry_run:
        run_ocr_on_saved(out_dir)


def run_ocr_on_saved(out_dir):
    """Run OCR tests on saved move_select and battle_log frames."""
    print(f"\n{'='*50}")
    print(f"  Running OCR on saved frames...")
    print(f"{'='*50}")

    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from test_ocr import test_move_select, test_battle_log
    except ImportError:
        print("  ERROR: Could not import test_ocr.py")
        return

    for subdir, test_fn in [("move_select", test_move_select),
                             ("battle_log", test_battle_log)]:
        frame_dir = out_dir / subdir
        if not frame_dir.exists():
            continue
        frames = sorted(frame_dir.glob("*.jpg"))
        if not frames:
            continue
        print(f"\n  Testing {len(frames)} {subdir} frames:")
        for fpath in frames:
            img = Image.open(fpath)
            test_fn(img, label=fpath.name)


if __name__ == "__main__":
    main()
