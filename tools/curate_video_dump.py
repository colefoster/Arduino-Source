#!/usr/bin/env python3
"""
Curate raw SerialPrograms video dumps into labeled inbox samples.

Pipeline:
  1. Extract frames at --fps from each .mp4 (default 1 fps).
  2. Run BattleHUDReader + BattleLogReader on each frame via the Mac dev
     runner at $DEV_RUNNER (default http://127.0.0.1:9876).
  3. Score each frame against the existing test_images corpus. Keep frames
     that introduce a NEW battle log event_type or NEW raw text. Species-
     only novelty is dropped — those are typically OCR misreads on
     non-battle frames.
  4. Convert keepers to PNG and drop them into test_images/_inbox/ with a
     dated prefix so they don't collide with future captures.
  5. Optionally rsync the inbox to ash (--push-to-ash).

Usage:
  python3 tools/curate_video_dump.py video1.mp4 video2.mp4 ...
  python3 tools/curate_video_dump.py --auto    # all video-*.mp4 in default screenshots dir
  python3 tools/curate_video_dump.py --auto --push-to-ash
"""
import argparse, base64, collections, glob, json, os, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
import urllib.request

REPO = Path(__file__).resolve().parent.parent
TEST_IMAGES = REPO / "test_images"
INBOX = TEST_IMAGES / "_inbox"
DEFAULT_DUMP_DIR = Path.home() / "Library/Application Support/SerialPrograms/Screenshots"
DEV_RUNNER = os.environ.get("DEV_RUNNER", "http://127.0.0.1:9876")


def extract_frames(videos, work_dir, fps):
    work_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for v in videos:
        out = work_dir / (v.stem + "_%04d.jpg")
        procs.append(subprocess.Popen(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(v),
             "-vf", f"fps={fps}", "-q:v", "3", str(out)],
        ))
    for p in procs: p.wait()
    return sorted(work_dir.glob("*.jpg"))


def call_runner(image_path, reader):
    with open(image_path, "rb") as fp:
        b64 = base64.b64encode(fp.read()).decode()
    body = json.dumps({"image_base64": b64, "reader": reader, "screen": ""}).encode()
    req = urllib.request.Request(
        f"{DEV_RUNNER}/ocr-suggest", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("result", {})


def call_detector_debug(image_path):
    with open(image_path, "rb") as fp:
        b64 = base64.b64encode(fp.read()).decode()
    body = json.dumps({"image_base64": b64}).encode()
    req = urllib.request.Request(
        f"{DEV_RUNNER}/detector-debug", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("result", {})


def run_readers(frames, workers=12):
    def work(p):
        out = {}
        try: out["BattleHUDReader"] = call_runner(p, "BattleHUDReader")
        except Exception as e: out["BattleHUDReader_err"] = str(e)
        try: out["BattleLogReader"] = call_runner(p, "BattleLogReader")
        except Exception as e: out["BattleLogReader_err"] = str(e)
        try:
            d = call_detector_debug(p)
            flat = {}
            for det in (d.get("detectors") or []):
                flat[det.get("name")] = bool(det.get("detected"))
            out["detectors"] = flat
        except Exception as e: out["detectors_err"] = str(e)
        return p, out
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, p) for p in frames]
        done = 0
        for fut in as_completed(futs):
            p, out = fut.result()
            results[str(p)] = out
            done += 1
            if done % 50 == 0:
                print(f"  readers: {done}/{len(frames)}", file=sys.stderr)
    return results


def load_corpus():
    """Returns (known_species, known_log_events, known_log_text_keys)."""
    known_species = set()
    for path in glob.glob(str(TEST_IMAGES / "*/manifest.json")):
        try: m = json.load(open(path))
        except: continue
        for v in m.values():
            if not isinstance(v, dict): continue
            for reader in ("BattleHUDReader", "TeamPreviewReader", "TeamSelectReader"):
                r = v.get(reader)
                if not isinstance(r, dict): continue
                for fld in ("opponent_species", "own_species", "species"):
                    for s in (r.get(fld) or []):
                        if s: known_species.add(s.lower())
    known_events, known_text = set(), set()
    bl_path = TEST_IMAGES / "_overlays/battle_log/manifest.json"
    if bl_path.exists():
        for v in json.loads(bl_path.read_text()).values():
            blr = v.get("BattleLogReader") or {}
            et = blr.get("event_type")
            if et: known_events.add(et)
            txt = blr.get("event_type_raw") or blr.get("raw_text")
            if et and txt: known_text.add((et, _norm(txt)))
    return known_species, known_events, known_text


def _norm(t): return re.sub(r"\s+", " ", (t or "").strip().lower())


#  Detectors whose first-fire (across the whole dump) is interesting enough
#  to keep one representative frame. These tend to fire on screens we have
#  thin coverage for.
KEEP_FIRST_FIRE_DETECTORS = (
    "PokemonSwitchDetector",     # not yet built — kept for forward-compat
    "TargetSelectDetector",      # not yet built — kept for forward-compat
    "MegaEvolveDetector",        # the rare frames where mega is available
    "ResultScreenDetector",      # post-match sample
)


def pick_keepers(results, known_species, known_events, known_text):
    seen_events, seen_texts = set(), set()
    seen_first_fires = set()
    keep = []
    for path in sorted(results.keys()):
        out = results[path]
        reasons = []
        blr = out.get("BattleLogReader") or {}
        et, raw = blr.get("event_type"), blr.get("event_type_raw") or ""
        if et and et not in ("OTHER", "UNKNOWN"):
            if et not in known_events and et not in seen_events:
                reasons.append(f"new_event={et}")
                seen_events.add(et)
            if raw and len(raw.strip()) > 3:
                key = (et, _norm(raw))
                if key not in known_text and key not in seen_texts:
                    reasons.append(f"new_log_text={et}:{raw[:50]!r}")
                    seen_texts.add(key)
        # First-fire detector frames — useful for thin-coverage screens.
        dets = out.get("detectors") or {}
        for det_name in KEEP_FIRST_FIRE_DETECTORS:
            if dets.get(det_name) and det_name not in seen_first_fires:
                reasons.append(f"first_fire={det_name}")
                seen_first_fires.add(det_name)
        if reasons:
            keep.append((path, reasons))
    return keep, seen_events, seen_texts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="*", type=Path, help=".mp4 files (default: --auto)")
    ap.add_argument("--auto", action="store_true", help=f"use all video-*.mp4 in {DEFAULT_DUMP_DIR}")
    ap.add_argument("--fps", type=float, default=1.0, help="frames per second to extract (default 1)")
    ap.add_argument("--prefix", default=None, help="filename prefix for inbox (default: YYYYMMDD-game-)")
    ap.add_argument("--push-to-ash", action="store_true", help="rsync new inbox files to ash")
    ap.add_argument("--keep-scratch", action="store_true", help="don't delete the temp extraction dir")
    args = ap.parse_args()

    videos = list(args.videos)
    if args.auto:
        videos.extend(sorted(DEFAULT_DUMP_DIR.glob("video-*.mp4")))
    videos = [v for v in videos if v.stat().st_size > 1_000_000]  # drop tiny stubs
    if not videos:
        print("No videos to process.", file=sys.stderr); sys.exit(1)
    print(f"Videos: {len(videos)}")

    prefix = args.prefix or f"{date.today().strftime('%Y%m%d')}-game-"
    scratch = Path(tempfile.mkdtemp(prefix="champ_curate_"))
    print(f"Scratch: {scratch}")

    try:
        frames = extract_frames(videos, scratch / "frames", args.fps)
        print(f"Extracted {len(frames)} frames")

        try:
            urllib.request.urlopen(f"{DEV_RUNNER}/health", timeout=2)
        except Exception:
            print(f"Warning: {DEV_RUNNER} not responding to /health (ok if endpoint missing)", file=sys.stderr)

        results = run_readers(frames)
        print(f"Reader results: {len(results)}")

        known_species, known_events, known_text = load_corpus()
        print(f"Corpus: {len(known_species)} species, {len(known_events)} log events, {len(known_text)} log texts")

        keep, new_events, new_texts = pick_keepers(results, known_species, known_events, known_text)
        print(f"\nKEEPERS: {len(keep)} / {len(results)}")
        print(f"  new event types: {sorted(new_events)}")
        print(f"  new log texts: {len(new_texts)}")

        INBOX.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        moved = []
        for path, reasons in keep:
            new_name = prefix + Path(path).stem + ".png"
            dst = INBOX / new_name
            Image.open(path).save(dst, "PNG")
            moved.append((new_name, reasons))
        print(f"Wrote {len(moved)} PNGs to {INBOX}")

        report = {"prefix": prefix, "new_event_types": sorted(new_events),
                  "new_log_text_count": len(new_texts),
                  "files": [{"file": n, "reasons": r} for n, r in moved]}
        report_path = INBOX.parent / f"_inbox_curation_{date.today().isoformat()}.json"
        report_path.write_text(json.dumps(report, indent=2))
        print(f"Report: {report_path}")

        if args.push_to_ash:
            print("Pushing inbox to ash...")
            cmd = ["rsync", "-av", f"--include={prefix}*.png", "--exclude=*",
                   f"{INBOX}/", "ash:/opt/pokemon-champions/test_images/_inbox/"]
            subprocess.run(cmd, check=True)
            print("ash sync OK")

    finally:
        if not args.keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)
            print(f"Cleaned scratch: {scratch}")


if __name__ == "__main__":
    main()
