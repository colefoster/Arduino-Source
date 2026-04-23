"""Spectator dashboard — reads replay data directly from disk.

Deploy on ash:
    uvicorn server:app --host 127.0.0.1 --port 8420
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

REPLAY_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
STATIC_DIR = Path(__file__).parent / "static"
DATASET_SUMMARY = Path(__file__).parent / "dataset_summary.json"
SPECTATOR_LOGS = [
    Path("/var/log/pokemon-spectator.log"),
    Path("/var/log/pokemon-spectator-2.log"),
    Path("/var/log/pokemon-spectator-3.log"),
]

FORMATS = {
    "gen9championsvgc2026regma": "VGC 2026",
    "gen9championsbssregma": "BSS",
}

app = FastAPI(title="Pokemon Champions Spectator Dashboard")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_replays(fmt_id: str) -> list[dict]:
    """Return metadata for all replays in a format dir. Cached briefly."""
    fmt_dir = REPLAY_DIR / fmt_id
    if not fmt_dir.exists():
        return []

    results = []
    for f in fmt_dir.iterdir():
        if f.suffix != ".json" or f.name == "index.json":
            continue
        mtime = f.stat().st_mtime
        results.append({"path": f, "mtime": mtime})
    return results


def _read_replay_meta(f: Path) -> dict | None:
    """Read just the metadata fields from a replay JSON (skip full log)."""
    try:
        data = json.loads(f.read_text())
        return {
            "id": data.get("id", f.stem),
            "format": data.get("format", ""),
            "players": data.get("players", []),
            "rating": data.get("rating", 0),
            "uploadtime": data.get("uploadtime", 0),
            "source": data.get("source", "downloaded"),
        }
    except Exception:
        return None


def _spectator_pids() -> list[int]:
    """Return PIDs of running spectator processes."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "spectate_ps_battles"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return [int(p) for p in result.stdout.strip().split("\n") if p]
    except Exception:
        pass
    return []


def _parse_log_saves(log_path: Path, max_lines: int = 5000) -> list[float]:
    """Extract save timestamps from spectator log (by file line order)."""
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text().splitlines()[-max_lines:]
        saves = []
        for line in lines:
            if "Saved " in line:
                saves.append(1)  # we'll use file mtimes instead
        return saves
    except Exception:
        return []


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def status():
    """Overall spectator status."""
    now = time.time()
    pids = _spectator_pids()

    formats = {}
    total_replays = 0
    total_spectated = 0
    newest_save = 0

    for fmt_id, label in FORMATS.items():
        fmt_dir = REPLAY_DIR / fmt_id
        files = _scan_replays(fmt_id)
        count = len(files)
        total_replays += count

        spectated = 0
        last_1h = last_24h = 0
        for f in files:
            age = now - f["mtime"]
            if age < 3600:
                last_1h += 1
            if age < 86400:
                last_24h += 1
            if f["mtime"] > newest_save:
                newest_save = f["mtime"]

        # Count spectated vs downloaded for recent files only (perf)
        for f in files:
            if now - f["mtime"] < 86400:
                meta = _read_replay_meta(f["path"])
                if meta and meta["source"] == "spectated":
                    spectated += 1

        formats[fmt_id] = {
            "label": label,
            "total": count,
            "spectated_24h": spectated,
            "last_1h": last_1h,
            "last_24h": last_24h,
        }
        total_spectated += spectated

    last_save_ago = round(now - newest_save) if newest_save > 0 else -1

    return {
        "instances": len(pids),
        "pids": pids,
        "alive": len(pids) > 0 and last_save_ago < 300,
        "last_save_ago_sec": last_save_ago,
        "total_replays": total_replays,
        "formats": formats,
    }


@app.get("/api/collection")
async def collection():
    """Detailed collection stats — hourly buckets for the last 48h."""
    now = time.time()
    bucket_size = 3600  # 1 hour
    num_buckets = 48

    # Initialize buckets per format
    buckets = {}
    for fmt_id in FORMATS:
        buckets[fmt_id] = [0] * num_buckets

    for fmt_id in FORMATS:
        files = _scan_replays(fmt_id)
        for f in files:
            age = now - f["mtime"]
            if age > bucket_size * num_buckets:
                continue
            idx = int(age / bucket_size)
            if 0 <= idx < num_buckets:
                buckets[fmt_id][idx] += 1

    # Build response — buckets[0] = current hour, buckets[1] = 1h ago, etc.
    labels = []
    for i in range(num_buckets):
        if i == 0:
            labels.append("now")
        elif i < 24:
            labels.append(f"{i}h ago")
        else:
            labels.append(f"{i}h ago")

    return {
        "bucket_size_sec": bucket_size,
        "labels": labels,
        "series": {
            fmt_id: {"label": FORMATS[fmt_id], "data": counts}
            for fmt_id, counts in buckets.items()
        },
    }


@app.get("/api/ratings")
async def ratings():
    """Rating distribution for recent replays (last 7 days)."""
    now = time.time()
    cutoff = now - 7 * 86400

    bins = list(range(900, 1800, 50))  # 900, 950, ..., 1750
    distributions = {fmt_id: [0] * len(bins) for fmt_id in FORMATS}

    for fmt_id in FORMATS:
        files = _scan_replays(fmt_id)
        for f in files:
            if f["mtime"] < cutoff:
                continue
            meta = _read_replay_meta(f["path"])
            if not meta or not meta["rating"]:
                continue
            rating = meta["rating"]
            for i, edge in enumerate(bins):
                if rating < edge + 50:
                    distributions[fmt_id][i] += 1
                    break

    return {
        "bins": [f"{b}-{b+49}" for b in bins],
        "bin_edges": bins,
        "series": {
            fmt_id: {"label": FORMATS[fmt_id], "data": counts}
            for fmt_id, counts in distributions.items()
        },
    }


@app.get("/api/recent")
async def recent(limit: int = 30):
    """Most recent saved replays."""
    now = time.time()
    all_files = []
    for fmt_id in FORMATS:
        for f in _scan_replays(fmt_id):
            all_files.append((f, fmt_id))

    # Sort by mtime desc, take top N
    all_files.sort(key=lambda x: x[0]["mtime"], reverse=True)

    results = []
    for f, fmt_id in all_files[:limit]:
        meta = _read_replay_meta(f["path"])
        if meta:
            meta["format_id"] = fmt_id
            meta["format_label"] = FORMATS[fmt_id]
            meta["ago_sec"] = round(now - f["mtime"])
            results.append(meta)

    return results


@app.get("/api/dataset")
async def dataset():
    """Combined dataset stats — downloaded (from ColePC summary) + spectated (live on ash)."""
    now = time.time()

    # Load ColePC downloaded summary
    downloaded = {}
    if DATASET_SUMMARY.exists():
        downloaded = json.loads(DATASET_SUMMARY.read_text())

    # Count spectated replays on ash with rating info
    spectated = {}
    for fmt_id, label in FORMATS.items():
        files = _scan_replays(fmt_id)
        total = len(files)
        ratings = []
        for f in files:
            meta = _read_replay_meta(f["path"])
            if meta and meta.get("rating"):
                ratings.append(meta["rating"])

        buckets = {}
        for r in ratings:
            b = (r // 50) * 50
            buckets[str(b)] = buckets.get(str(b), 0) + 1

        key = "bss" if "bss" in fmt_id else "vgc"
        spectated[key] = {
            "total": total,
            "rated": len(ratings),
            "rating_min": min(ratings) if ratings else 0,
            "rating_max": max(ratings) if ratings else 0,
            "rating_median": sorted(ratings)[len(ratings) // 2] if ratings else 0,
            "rating_buckets": dict(sorted(buckets.items())),
        }

    # Merge bucket distributions for combined view
    combined = {}
    for key in ["vgc", "bss"]:
        dl = downloaded.get(key, {})
        sp = spectated.get(key, {})
        dl_buckets = dl.get("rating_buckets", {})
        sp_buckets = sp.get("rating_buckets", {})
        all_keys = set(list(dl_buckets.keys()) + list(sp_buckets.keys()))
        merged_buckets = {}
        for b in sorted(all_keys, key=lambda x: int(x)):
            merged_buckets[b] = {
                "downloaded": dl_buckets.get(b, 0),
                "spectated": sp_buckets.get(b, 0),
                "total": dl_buckets.get(b, 0) + sp_buckets.get(b, 0),
            }
        combined[key] = {
            "downloaded": dl.get("indexed", dl.get("rated", 0)),
            "spectated": sp.get("total", 0),
            "total": dl.get("indexed", 0) + sp.get("total", 0),
            "rated": dl.get("rated", 0) + sp.get("rated", 0),
            "rating_min": min(dl.get("rating_min", 9999), sp.get("rating_min", 9999)),
            "rating_max": max(dl.get("rating_max", 0), sp.get("rating_max", 0)),
            "rating_buckets": merged_buckets,
        }

    return {
        "downloaded_summary_age": now - downloaded.get("generated", now),
        "combined": combined,
        "downloaded": downloaded,
        "spectated": spectated,
    }


@app.get("/api/coverage")
async def coverage():
    """Estimate coverage — query PS with ELO-sliced queries to get past the 100-room cap."""
    import websockets
    import asyncio

    elo_slices = [0, 1200, 1400]

    try:
        async with websockets.connect(
            "wss://sim3.psim.us/showdown/websocket",
            ping_interval=30,
            open_timeout=10,
        ) as ws:
            # Wait for login
            logged_in = False
            while not logged_in:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                if "|updateuser|" in msg:
                    logged_in = True

            # Query room lists at multiple ELO thresholds
            expected = 0
            for fmt in FORMATS:
                for elo in elo_slices:
                    cmd = f"|/crq roomlist {fmt},{elo}" if elo else f"|/crq roomlist {fmt}"
                    await ws.send(cmd)
                    expected += 1
                    await asyncio.sleep(0.3)

            # Collect all unique rooms per format
            all_rooms: dict[str, set[str]] = {fmt: set() for fmt in FORMATS}
            received = 0
            deadline = time.time() + 8
            while received < expected and time.time() < deadline:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                if "|queryresponse|roomlist|" in msg:
                    received += 1
                    json_str = msg.split("|queryresponse|roomlist|", 1)[1]
                    data = json.loads(json_str)
                    rooms = data.get("rooms", {})
                    for fmt_id in FORMATS:
                        for rid in rooms:
                            if fmt_id in rid:
                                all_rooms[fmt_id].add(rid)

            await ws.close()

        pids = _spectator_pids()
        capacity = len(pids) * 40  # MAX_CONCURRENT per instance

        active_battles = {fmt: len(rids) for fmt, rids in all_rooms.items()}
        total_active = sum(active_battles.values())
        capped = any(len(rids) >= 100 for rids in all_rooms.values())

        return {
            "active_battles": active_battles,
            "total_active": total_active,
            "total_active_note": "100+ (PS caps roomlist at 100 per query)" if capped else None,
            "instances": len(pids),
            "capacity": capacity,
            "elo_slices": elo_slices,
            "coverage_pct": round(
                min(capacity / max(total_active, 1), 1.0) * 100
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the dashboard."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Dashboard not deployed yet</h1>")
