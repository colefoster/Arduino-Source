#!/usr/bin/env python3
"""
Retest CLI — build C++ and run regression tests.

Builds via cmake, runs SerialProgramsCommandLine --regression,
parses output, saves results to tools/regression_results.json.

Usage:
  python3 tools/retest.py                          # all readers
  python3 tools/retest.py MoveSelectDetector       # single reader
  python3 tools/retest.py --no-build               # skip cmake, just run
  python3 tools/retest.py --list                   # list available readers
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(REPO, "build_mac")
TEST_ROOT = os.path.join(REPO, "CommandLineTests", "PokemonChampions")
RESULTS_PATH = os.path.join(REPO, "tools", "regression_results.json")


def build(jobs=None):
    """Run cmake --build. Returns True on success."""
    jobs = jobs or os.cpu_count() or 4
    print(f"Building ({jobs} jobs)...", flush=True)
    t0 = time.time()
    result = subprocess.run(
        ["cmake", "--build", BUILD_DIR, f"-j{jobs}"],
        capture_output=True, text=True, timeout=180, cwd=REPO,
    )
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"Build FAILED ({elapsed:.1f}s)")
        print(result.stderr[-500:])
        return False
    print(f"Build OK ({elapsed:.1f}s)", flush=True)
    return True


def run_regression(reader=None):
    """Run regression and parse results. Returns dict of {filename: {passed, actual, ...}}."""
    test_path = os.path.join("..", "CommandLineTests", "PokemonChampions")
    if reader:
        test_path = os.path.join(test_path, reader)

    exe = os.path.join(BUILD_DIR, "SerialProgramsCommandLine")
    print(f"Running regression{f' ({reader})' if reader else ''}...", flush=True)
    t0 = time.time()
    result = subprocess.run(
        [exe, "--regression", test_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=600, cwd=BUILD_DIR,
    )
    elapsed = time.time() - t0

    results = {}
    current_file = None
    current_reader = None

    for line in result.stdout.split("\n"):
        stripped = line.strip()

        # Detect reader from path
        if ("CommandLineTests/PokemonChampions/" in stripped
                and (stripped.endswith(".png") or stripped.endswith(".jpg"))
                and not stripped.startswith("Parse")):
            current_file = os.path.basename(stripped)
            # Extract reader name from path
            parts = stripped.split("CommandLineTests/PokemonChampions/")
            if len(parts) > 1:
                current_reader = parts[1].split("/")[0]
            results[current_file] = {"passed": True, "reader": current_reader, "segments": []}

        # Failure
        m = re.search(r'result is (.+?) but should be (.+?)\.', stripped)
        if m and current_file:
            results[current_file]["passed"] = False
            results[current_file]["actual"] = m.group(1)
            results[current_file]["expected"] = m.group(2)

        # Success
        m = re.match(r'OK: actual=(.+)', stripped)
        if m and current_file:
            results[current_file]["actual"] = m.group(1)

        # Raw OCR text
        m = re.search(r"raw='(.*?)(?:'|$)", stripped)
        if m and current_file:
            results[current_file]["raw_ocr"] = m.group(1)

        # Template match segments
        m = re.search(r'segment\[(\d+)\]\s+(\d+)x(\d+)\s+scores:\s+(.+)', stripped)
        if m and current_file:
            seg_idx = int(m.group(1))
            scores = {}
            for pair in m.group(4).split():
                k, v = pair.split(":")
                scores[k] = float(v)
            while len(results[current_file]["segments"]) <= seg_idx:
                results[current_file]["segments"].append(None)
            results[current_file]["segments"][seg_idx] = {
                "w": int(m.group(2)), "h": int(m.group(3)), "scores": scores,
            }

        # Template match result
        m = re.search(r'template: digits=\[([^\]]+)\]\s*->\s*(\d+)', stripped)
        if m and current_file:
            results[current_file]["digits"] = m.group(1).split(",")
            results[current_file]["actual"] = m.group(2)

        if 'template: no digits found' in stripped and current_file:
            results[current_file]["no_digits"] = True

    # Print summary
    by_reader = {}
    for fname, r in results.items():
        rdr = r.get("reader", "unknown")
        by_reader.setdefault(rdr, {"passed": 0, "failed": 0})
        if r["passed"]:
            by_reader[rdr]["passed"] += 1
        else:
            by_reader[rdr]["failed"] += 1

    total_pass = sum(r["passed"] for r in by_reader.values())
    total_fail = sum(r["failed"] for r in by_reader.values())
    total = total_pass + total_fail

    print(f"\n{'Reader':<35} {'Pass':>6} {'Total':>6} {'Acc':>7}")
    print("-" * 58)
    for rdr in sorted(by_reader.keys()):
        p = by_reader[rdr]["passed"]
        f = by_reader[rdr]["failed"]
        t = p + f
        acc = f"{p/t*100:.1f}%" if t > 0 else "N/A"
        color = "\033[92m" if f == 0 else "\033[91m"
        print(f"{color}{rdr:<35} {p:>6} {t:>6} {acc:>7}\033[0m")
    print("-" * 58)
    print(f"{'OVERALL':<35} {total_pass:>6} {total:>6} {total_pass/total*100:.1f}%")
    print(f"\nCompleted in {elapsed:.1f}s")

    # Print failures
    failures = [(f, r) for f, r in results.items() if not r["passed"]]
    if failures:
        print(f"\n\033[91m{len(failures)} failures:\033[0m")
        for fname, r in sorted(failures, key=lambda x: x[1].get("reader", "")):
            actual = r.get("actual", "?")
            expected = r.get("expected", "?")
            print(f"  {r.get('reader', '?')}: {fname}  (got {actual}, expected {expected})")

    return results


def save_results(results):
    """Save results JSON with metadata."""
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(results),
        "passed": sum(1 for r in results.values() if r.get("passed")),
        "results": results,
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {RESULTS_PATH}")


def list_readers():
    """List available test readers."""
    for d in sorted(os.listdir(TEST_ROOT)):
        full = os.path.join(TEST_ROOT, d)
        if os.path.isdir(full):
            count = len([f for f in os.listdir(full) if f.endswith(".png") and not f.startswith("_")])
            print(f"  {d}: {count} frames")


def main():
    parser = argparse.ArgumentParser(description="Build C++ and run regression tests")
    parser.add_argument("reader", nargs="?", help="Reader name (default: all)")
    parser.add_argument("--no-build", action="store_true", help="Skip cmake build")
    parser.add_argument("--list", action="store_true", help="List available readers")
    parser.add_argument("--jobs", "-j", type=int, help="Build parallelism")
    args = parser.parse_args()

    if args.list:
        list_readers()
        return

    if not args.no_build:
        if not build(args.jobs):
            sys.exit(1)

    results = run_regression(args.reader)
    save_results(results)


if __name__ == "__main__":
    main()
