"""Spectator dashboard — reads replay data from disk.

Data layout:
    data/showdown_replays/
        spectated/       <- from live spectating
        downloaded/      <- from PS replay API

Deploy on ash:
    uvicorn server:app --host 127.0.0.1 --port 8420
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

REPLAY_BASE = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
SPECTATED_DIR = REPLAY_BASE / "spectated"
DOWNLOADED_DIR = REPLAY_BASE / "downloaded"
STATUS_FILE = SPECTATED_DIR / ".orchestrator_status.json"
STATIC_DIR = Path(__file__).parent / "static"

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

def _scan_dir(base: Path, fmt_id: str) -> list[dict]:
    """Return file metadata for all replays in base/fmt_id/."""
    fmt_dir = base / fmt_id
    if not fmt_dir.exists():
        return []
    return [
        {"path": f, "mtime": f.stat().st_mtime}
        for f in fmt_dir.iterdir()
        if f.suffix == ".json" and f.name != "index.json"
    ]


def _scan_all(fmt_id: str) -> list[dict]:
    """Scan both spectated and downloaded dirs for a format."""
    return _scan_dir(SPECTATED_DIR, fmt_id) + _scan_dir(DOWNLOADED_DIR, fmt_id)


def _read_replay_meta(f: Path) -> dict | None:
    try:
        data = json.loads(f.read_text(errors="replace"))
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


def _orchestrator_status() -> dict:
    """Read the orchestrator status file and verify the process is alive."""
    if not STATUS_FILE.exists():
        return {"alive": False, "connections": 0, "rooms_in_use": 0, "capacity": 0}
    try:
        data = json.loads(STATUS_FILE.read_text())
        # Verify PID is still alive
        try:
            os.kill(data["pid"], 0)
            data["alive"] = True
        except OSError:
            data["alive"] = False
        # Check staleness — if status file is >30s old, consider dead
        if STATUS_FILE.stat().st_mtime < time.time() - 30:
            data["alive"] = False
        return data
    except Exception:
        return {"alive": False, "connections": 0, "rooms_in_use": 0, "capacity": 0}


def _rating_buckets(ratings: list[int], step: int = 50) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for r in ratings:
        b = (r // step) * step
        buckets[str(b)] = buckets.get(str(b), 0) + 1
    return dict(sorted(buckets.items(), key=lambda x: int(x[0])))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def status():
    """Overall spectator status — only reads spectated dir for live metrics."""
    now = time.time()
    orch = _orchestrator_status()

    formats = {}
    total_replays = 0
    newest_save = 0

    for fmt_id, label in FORMATS.items():
        spec_files = _scan_dir(SPECTATED_DIR, fmt_id)
        dl_files = _scan_dir(DOWNLOADED_DIR, fmt_id)

        spec_count = len(spec_files)
        dl_count = len(dl_files)

        last_1h = last_24h = 0
        for f in spec_files:
            age = now - f["mtime"]
            if age < 3600:
                last_1h += 1
            if age < 86400:
                last_24h += 1
            if f["mtime"] > newest_save:
                newest_save = f["mtime"]

        formats[fmt_id] = {
            "label": label,
            "spectated": spec_count,
            "downloaded": dl_count,
            "total": spec_count + dl_count,
            "last_1h": last_1h,
            "last_24h": last_24h,
        }
        total_replays += spec_count + dl_count

    last_save_ago = round(now - newest_save) if newest_save > 0 else -1

    return {
        "alive": orch.get("alive", False),
        "connections": orch.get("connections", 0),
        "total_connections": orch.get("total_connections", 0),
        "rooms_in_use": orch.get("rooms_in_use", 0),
        "capacity": orch.get("capacity", 0),
        "pending": orch.get("pending", 0),
        "draining": orch.get("draining", False),
        "stats": orch.get("stats", {}),
        "uptime_sec": orch.get("uptime_sec", 0),
        "per_connection": orch.get("per_connection", []),
        "last_save_ago_sec": last_save_ago,
        "total_replays": total_replays,
        "formats": formats,
    }


@app.get("/api/collection")
async def collection():
    """Hourly spectated collection rate for the last 48h."""
    now = time.time()
    bucket_size = 3600
    num_buckets = 48

    buckets = {fmt_id: [0] * num_buckets for fmt_id in FORMATS}

    for fmt_id in FORMATS:
        for f in _scan_dir(SPECTATED_DIR, fmt_id):
            age = now - f["mtime"]
            if age > bucket_size * num_buckets:
                continue
            idx = int(age / bucket_size)
            if 0 <= idx < num_buckets:
                buckets[fmt_id][idx] += 1

    labels = ["now"] + [f"{i}h ago" for i in range(1, num_buckets)]

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
    """Rating distribution for recent spectated replays (last 7 days)."""
    now = time.time()
    cutoff = now - 7 * 86400

    bins = list(range(900, 1800, 50))
    distributions = {fmt_id: [0] * len(bins) for fmt_id in FORMATS}

    for fmt_id in FORMATS:
        for f in _scan_dir(SPECTATED_DIR, fmt_id):
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
    """Most recent spectated replays."""
    now = time.time()
    all_files = []
    for fmt_id in FORMATS:
        for f in _scan_dir(SPECTATED_DIR, fmt_id):
            all_files.append((f, fmt_id))

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
    """Combined dataset stats — downloaded + spectated, both read from disk."""
    combined = {}

    for key, fmt_id in [("vgc", "gen9championsvgc2026regma"), ("bss", "gen9championsbssregma")]:
        dl_files = _scan_dir(DOWNLOADED_DIR, fmt_id)
        sp_files = _scan_dir(SPECTATED_DIR, fmt_id)

        dl_ratings = []
        for f in dl_files:
            meta = _read_replay_meta(f["path"])
            if meta and meta.get("rating"):
                dl_ratings.append(meta["rating"])

        sp_ratings = []
        for f in sp_files:
            meta = _read_replay_meta(f["path"])
            if meta and meta.get("rating"):
                sp_ratings.append(meta["rating"])

        dl_buckets = _rating_buckets(dl_ratings)
        sp_buckets = _rating_buckets(sp_ratings)
        all_keys = set(list(dl_buckets.keys()) + list(sp_buckets.keys()))
        merged = {}
        for b in sorted(all_keys, key=lambda x: int(x)):
            merged[b] = {
                "downloaded": dl_buckets.get(b, 0),
                "spectated": sp_buckets.get(b, 0),
                "total": dl_buckets.get(b, 0) + sp_buckets.get(b, 0),
            }

        all_ratings = dl_ratings + sp_ratings
        combined[key] = {
            "downloaded": len(dl_files),
            "spectated": len(sp_files),
            "total": len(dl_files) + len(sp_files),
            "downloaded_rated": len(dl_ratings),
            "spectated_rated": len(sp_ratings),
            "rated": len(all_ratings),
            "rating_min": min(all_ratings) if all_ratings else 0,
            "rating_max": max(all_ratings) if all_ratings else 0,
            "rating_median": sorted(all_ratings)[len(all_ratings) // 2] if all_ratings else 0,
            "rating_buckets": merged,
        }

    grand_total = sum(c["total"] for c in combined.values())
    grand_dl = sum(c["downloaded"] for c in combined.values())
    grand_sp = sum(c["spectated"] for c in combined.values())

    return {
        "combined": combined,
        "grand_total": grand_total,
        "grand_downloaded": grand_dl,
        "grand_spectated": grand_sp,
    }


@app.get("/api/coverage")
async def coverage():
    """Estimate coverage — query PS with ELO-sliced queries."""
    import websockets
    import asyncio

    elo_slices = [0, 1200, 1400]

    try:
        async with websockets.connect(
            "wss://sim3.psim.us/showdown/websocket",
            ping_interval=30,
            open_timeout=10,
        ) as ws:
            logged_in = False
            while not logged_in:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                if "|updateuser|" in msg:
                    logged_in = True

            expected = 0
            for fmt in FORMATS:
                for elo in elo_slices:
                    cmd = f"|/crq roomlist {fmt},{elo}" if elo else f"|/crq roomlist {fmt}"
                    await ws.send(cmd)
                    expected += 1
                    await asyncio.sleep(0.3)

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

        orch = _orchestrator_status()
        capacity = orch.get("capacity", 0)
        rooms_in_use = orch.get("rooms_in_use", 0)

        active_battles = {fmt: len(rids) for fmt, rids in all_rooms.items()}
        total_active = sum(active_battles.values())
        capped = any(len(rids) >= 100 for rids in all_rooms.values())

        return {
            "active_battles": active_battles,
            "total_active": total_active,
            "total_active_note": "100+ (PS caps roomlist at 100 per query)" if capped else None,
            "connections": orch.get("connections", 0),
            "rooms_in_use": rooms_in_use,
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
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Dashboard not deployed yet</h1>")
