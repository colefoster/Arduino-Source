#!/usr/bin/env python3
"""Push training + spectator metrics to the dashboard server every 30s.

Runs on ColePC alongside training/spectating.

Usage:
    python scripts/metrics_reporter.py
    python scripts/metrics_reporter.py --url https://champions.colefoster.ca/api/ingest
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPLAY_DIR = DATA_DIR / "showdown_replays"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
TRAINING_LOG = CHECKPOINT_DIR / "training_log.jsonl"

FORMATS = {
    "gen9championsvgc2026regma": "VGC",
    "gen9championsbssregma": "BSS",
}

REPORT_INTERVAL = 30  # seconds


def count_replays(fmt_dir: Path) -> dict:
    """Count total, spectated, and recent replays."""
    if not fmt_dir.exists():
        return {"total": 0, "spectated": 0, "downloaded": 0, "last_5m": 0, "last_30m": 0, "last_1h": 0}

    total = spectated = downloaded = 0
    last_5m = last_30m = last_1h = 0
    now = time.time()

    for f in fmt_dir.iterdir():
        if f.suffix != ".json":
            continue
        total += 1
        mtime = f.stat().st_mtime
        age = now - mtime

        if age < 300:
            last_5m += 1
        if age < 1800:
            last_30m += 1
        if age < 3600:
            last_1h += 1

        # Check source (only for recent files to avoid reading everything)
        if age < 86400:
            try:
                data = json.loads(f.read_text())
                if data.get("source") == "spectated":
                    spectated += 1
                else:
                    downloaded += 1
            except Exception:
                downloaded += 1
        else:
            downloaded += 1

    return {
        "total": total,
        "spectated": spectated,
        "downloaded": downloaded,
        "last_5m": last_5m,
        "last_30m": last_30m,
        "last_1h": last_1h,
    }


def get_spectator_status() -> dict:
    """Check if spectator process is running and get session info."""
    alive = False
    pid = 0

    # Check for python process running spectate_ps_battles
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            # Count python processes (rough heuristic)
            lines = [l for l in result.stdout.strip().split("\n") if "python" in l.lower()]
            # If there are 2+ python processes, one is likely the spectator
            # (the other is this reporter). If 3+, definitely spectator is running.
            alive = len(lines) >= 2
        else:
            result = subprocess.run(
                ["pgrep", "-f", "spectate_ps_battles"],
                capture_output=True, text=True, timeout=5,
            )
            alive = result.returncode == 0
            if alive:
                pid = int(result.stdout.strip().split("\n")[0])
    except Exception:
        pass

    # Get last save time from recent files
    last_save_ago = -1
    for fmt_id in FORMATS:
        fmt_dir = REPLAY_DIR / fmt_id
        if not fmt_dir.exists():
            continue
        for f in sorted(fmt_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix == ".json":
                age = time.time() - f.stat().st_mtime
                if last_save_ago < 0 or age < last_save_ago:
                    last_save_ago = age
                break

    return {
        "alive": alive,
        "pid": pid,
        "last_save_ago_sec": round(last_save_ago) if last_save_ago >= 0 else -1,
    }


def get_training_status() -> dict:
    """Read the latest training epoch from the JSONL log."""
    if not TRAINING_LOG.exists():
        return {"active": False}

    # Read last line
    last_line = None
    try:
        with open(TRAINING_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
    except Exception:
        return {"active": False}

    if not last_line:
        return {"active": False}

    try:
        entry = json.loads(last_line)
    except json.JSONDecodeError:
        return {"active": False}

    age = time.time() - entry.get("timestamp", 0)
    active = age < 300  # consider active if last epoch was < 5 min ago

    return {
        "active": active,
        "run_id": entry.get("run_id", ""),
        "epoch": entry.get("epoch", 0),
        "total_epochs": entry.get("total_epochs", 0),
        "train_loss": entry.get("train_loss"),
        "val_loss": entry.get("val_loss"),
        "val_top1": entry.get("val_top1"),
        "val_top3": entry.get("val_top3"),
        "team_acc": entry.get("team_acc"),
        "lead_acc": entry.get("lead_acc"),
        "lr": entry.get("lr"),
        "best_val_loss": entry.get("best_val_loss"),
        "last_update_sec_ago": round(age),
    }


def get_training_history() -> list[dict]:
    """Read all training epochs from the JSONL log."""
    if not TRAINING_LOG.exists():
        return []

    entries = []
    try:
        with open(TRAINING_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        pass
    return entries


def build_payload() -> dict:
    """Build the full metrics payload."""
    data_stats = {}
    for fmt_id, label in FORMATS.items():
        data_stats[label.lower()] = count_replays(REPLAY_DIR / fmt_id)

    return {
        "timestamp": time.time(),
        "hostname": os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown")),
        "training": get_training_status(),
        "training_history": get_training_history(),
        "spectator": get_spectator_status(),
        "data": data_stats,
    }


def post_payload(url: str, token: str, payload: dict) -> bool:
    """POST the payload to the dashboard server."""
    try:
        body = json.dumps(payload).encode()
        req = Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        })
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  POST failed: {e}", flush=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Push metrics to dashboard")
    parser.add_argument("--url", default="https://champions.colefoster.ca/api/ingest")
    parser.add_argument("--token", default=os.environ.get("DASHBOARD_TOKEN", "dev"))
    parser.add_argument("--once", action="store_true", help="Send once and exit")
    args = parser.parse_args()

    print(f"Reporter starting — pushing to {args.url} every {REPORT_INTERVAL}s", flush=True)

    while True:
        payload = build_payload()

        t = payload["training"]
        s = payload["spectator"]
        train_status = f"epoch {t['epoch']}/{t['total_epochs']}" if t.get("active") else "idle"
        spec_status = "alive" if s.get("alive") else "dead"

        print(f"  [{time.strftime('%H:%M:%S')}] training: {train_status}, "
              f"spectator: {spec_status}", flush=True)

        post_payload(args.url, args.token, payload)

        if args.once:
            break

        time.sleep(REPORT_INTERVAL)


if __name__ == "__main__":
    main()
