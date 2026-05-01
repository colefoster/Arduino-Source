"""Pokemon Champions Dev Tools Hub.

Extends the spectator dashboard with interactive dev tools:
- OCR Gallery: browse test images with crops and regression results
- Frame Labeler: label extracted VOD frames for the C++ test suite
- Pixel Inspector: measure screen regions for detector tuning

Data layout on ash:
    /opt/pokemon-champions/
        data/showdown_replays/     <- spectated + downloaded replays
        test_images/               <- synced CommandLineTests/PokemonChampions/
        ref_frames/                <- synced ref_frames/vod_extract/
        Resources/PokemonChampions/ <- OCR dictionaries

Deploy:
    uvicorn server:app --host 127.0.0.1 --port 8420
"""

from __future__ import annotations

import asyncio
import functools
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Thread pool + time-based cache for expensive blocking I/O
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=4)
_cache: dict[str, tuple[float, object]] = {}   # key -> (expires_at, value)
CACHE_TTL = 30  # seconds


def _cache_get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    return None


def _cache_set(key: str, value: object, ttl: float = CACHE_TTL):
    _cache[key] = (time.time() + ttl, value)


async def _run_in_executor(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent.parent
REPLAY_BASE = BASE / "data" / "showdown_replays"
SPECTATED_DIR = REPLAY_BASE / "spectated"
DOWNLOADED_DIR = REPLAY_BASE / "downloaded"
# New hour-bucketed replay layout (Phase 1 of pipeline redesign).
# replays/<format>/YYYY-MM-DD/HH/<id>.json — written by spectator, synced to unraid.
BUCKETED_REPLAY_DIR = BASE / "data" / "replays"
STATUS_FILE = SPECTATED_DIR / ".orchestrator_status.json"
STATIC_DIR = Path(__file__).parent / "static"

TEST_IMAGES_DIR = BASE / "test_images"
REF_FRAMES_DIR = BASE / "ref_frames"
RESOURCES_DIR = BASE / "Resources" / "PokemonChampions"
LABELS_DIR = BASE / "labels"

FORMATS = {
    "gen9championsvgc2026regma": "VGC 2026",
    "gen9championsbssregma": "BSS",
}

app = FastAPI(title="Pokemon Champions Dev Hub")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ═══════════════════════════════════════════════════════════════════════════
# CROP DEFINITIONS (normalized to 1920x1080)
# ═══════════════════════════════════════════════════════════════════════════

CROP_DEFS = {
    "MoveNameReader": [
        {"name": f"move_{i}", "box": [0.776, y, 0.120, 0.031]}
        for i, y in enumerate([0.536, 0.655, 0.775, 0.894])
    ],
    #  Unified BattleHUDReader: opponent (top) + own (bottom) species + HP,
    #  both slots. Mirrors the C++ box layout in
    #  PokemonChampions_BattleHUDReader.cpp (singles uses slot-0 boxes;
    #  doubles uses both). Singles-only HP% sits at the same screen
    #  position as doubles slot 1 — the singles slot 0 box matches.
    #  Singles reuses the slot-1 (far right) opponent boxes and the slot-0
    #  own boxes — no separate singles entries needed.
    "BattleHUDReader": [
        {"name": "opp0_species",    "box": [0.6172, 0.0454, 0.1219, 0.0417]},
        {"name": "opp1_species",    "box": [0.8286, 0.0481, 0.1151, 0.0417]},
        {"name": "opp0_hp_pct",     "box": [0.6932, 0.1174, 0.0429, 0.0354]},
        {"name": "opp1_hp_pct",     "box": [0.9002, 0.1176, 0.0420, 0.0349]},
        {"name": "own0_species",    "box": [0.0814, 0.8705, 0.0918, 0.0272]},
        {"name": "own1_species",    "box": [0.2901, 0.8705, 0.0835, 0.0267]},
        {"name": "own0_hp_current", "box": [0.1304, 0.9338, 0.0448, 0.0362]},
        {"name": "own0_hp_max",     "box": [0.1746, 0.9464, 0.0335, 0.0229]},
        {"name": "own1_hp_current", "box": [0.3363, 0.9342, 0.0450, 0.0361]},
        {"name": "own1_hp_max",     "box": [0.3800, 0.9473, 0.0340, 0.0215]},
    ],
    "CommunicatingDetector": [
        {"name": "communicating_text", "box": [0.380, 0.450, 0.240, 0.050]},
    ],
    "MoveSelectCursorSlot": [
        {"name": f"pill_{i}", "box": [0.7292, y, 0.0101, 0.0139]}
        for i, y in enumerate([0.5116, 0.6338, 0.7542, 0.8746])
    ],
    "MoveSelectDetector": [
        {"name": f"pill_{i}", "box": [0.7292, y, 0.0101, 0.0139]}
        for i, y in enumerate([0.5116, 0.6338, 0.7542, 0.8746])
    ],
    "ActiveHUDSlot": [
        {"name": "slot0_top", "box": [0.0527, 0.8530, 0.1728, 0.0030]},
        {"name": "slot1_top", "box": [0.2628, 0.8530, 0.1728, 0.0030]},
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
    #  Locked-in screen: sprites are inward (post-selection layout).
    #  Anchors saved in inspector; rest extrapolated linearly.
    "TeamPreviewReader": [
        #  Own species text labels (used by the OCR side of TeamPreviewReader).
        {"name": f"own_{i}", "box": [
            0.0760 + (i / 5.0) * (0.0724 - 0.0760),
            0.1565 + (i / 5.0) * (0.7389 - 0.1565),
            0.0969, 0.0389
        ]} for i in range(6)
    ] + [
        #  Opp sprite cells — locked-in (inward) positions.
        {"name": f"opp_sprite_{i}", "box": [
            0.7224, 0.1509 + i * ((0.7409 - 0.1509) / 5.0),
            0.0590, 0.0953
        ]} for i in range(6)
    ] + [
        #  Own sprite cells — locked-in (inward) positions. Not yet read by
        #  the C++ side (own uses species text OCR), kept here for visibility
        #  and as a forward base if we add own-sprite matching.
        {"name": f"own_sprite_{i}", "box": [
            0.1850, 0.1517 + i * ((0.7287 - 0.1517) / 5.0),
            0.0570, 0.0970
        ]} for i in range(6)
    ],
    #  Selecting screen: sprites are outward (pre-confirmation layout).
    #  Tune in inspector; will plumb through a screen-state branch in C++ once
    #  you've dialed them in.
    "TeamPreviewReader_selecting": [
        {"name": f"opp_sprite_{i}", "box": [
            0.8380, 0.1509 + i * ((0.7407 - 0.1509) / 5.0),
            0.0583, 0.0917
        ]} for i in range(6)
    ],
    "ActionMenuDetector": [
        {"name": "fight_glow", "box": [0.9219, 0.5787, 0.0182, 0.0213]},
        {"name": "pokemon_glow", "box": [0.8932, 0.7907, 0.0182, 0.0213]},
    ],
    "PreparingForBattleDetector": [
        {"name": "player_pill", "box": [0.2280, 0.8695, 0.0016, 0.0204]},
        {"name": "opponent_pill", "box": [0.7656, 0.8695, 0.0016, 0.0204]},
    ],
    "TeamPreviewDetector": [
        {"name": "title_text", "box": [0.3604, 0.2037, 0.1375, 0.0389]},
    ],
    "MegaEvolveDetector": [
        #  Tuned via inspector. Pill with black "R" — detector requires
        #  white-pixel fraction >= 0.30 AND OCR reads "R".
        {"name": "toggle_region", "box": [0.5968, 0.9198, 0.0194, 0.0325]},
    ],
}

BOOL_DETECTORS = {
    "MoveSelectDetector", "ActionMenuDetector", "PostMatchScreenDetector",
    "PreparingForBattleDetector", "TeamSelectDetector", "TeamPreviewDetector",
    "MainMenuDetector", "MovesMoreDetector", "CommunicatingDetector",
    "MegaEvolveDetector",
}

BATTLE_LOG_EVENTS = [
    "MOVE_USED", "FAINTED", "SUPER_EFFECTIVE", "NOT_VERY_EFFECTIVE",
    "CRITICAL_HIT", "NO_EFFECT", "SENT_OUT", "WITHDREW", "STAT_CHANGE",
    "STATUS_INFLICTED", "WEATHER", "TERRAIN", "ABILITY_ACTIVATED",
    "ITEM_USED", "HEALED", "DAMAGED", "OTHER",
]

FOLDER_TO_READER = {
    "action_menu": "ActionMenuDetector",
    "battle_log": "BattleLogReader",
    "move_select": "MoveNameReader",
    "post_match": "PostMatchScreenDetector",
    "preparing": "PreparingForBattleDetector",
    "team_select": "TeamSelectReader",
    "team_preview": "TeamPreviewReader",
    "team_summary": "TeamSummaryReader",
}

# Which readers to show together for each screen type
FOLDER_READERS = {
    "action_menu": ["ActionMenuDetector", "BattleHUDReader"],
    "move_select": ["MoveSelectDetector", "MegaEvolveDetector", "MoveNameReader", "MoveSelectCursorSlot", "BattleHUDReader"],
    "battle_log": ["BattleLogReader", "BattleHUDReader"],
    "post_match": ["PostMatchScreenDetector"],
    "preparing": ["PreparingForBattleDetector"],
    "team_select": ["TeamSelectReader"],
    "team_preview": ["TeamPreviewReader", "TeamPreviewDetector"],
    "team_summary": ["TeamSummaryReader"],
}

READER_TYPES = {}
for _r in BOOL_DETECTORS:
    READER_TYPES[_r] = "bool"
READER_TYPES.update({
    "MoveNameReader": "multi_text:4",
    "BattleHUDReader": "battle_hud",
    "MoveSelectCursorSlot": "int:0:3",
    "BattleLogReader": "event",
    "CommunicatingDetector": "bool",
    "TeamSelectReader": "multi_text:6",
    "TeamSummaryReader": "multi_text:6",
    "TeamPreviewReader": "multi_text:12",
})


# ═══════════════════════════════════════════════════════════════════════════
# SPECTATOR HELPERS (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def _scan_dir(base: Path, fmt_id: str) -> list[dict]:
    fmt_dir = base / fmt_id
    if not fmt_dir.exists():
        return []
    return [
        {"path": f, "mtime": f.stat().st_mtime}
        for f in fmt_dir.iterdir()
        if f.suffix == ".json" and f.name != "index.json"
    ]

def _read_replay_meta(f: Path) -> dict | None:
    try:
        data = json.loads(f.read_text(errors="replace"))
        return {
            "id": data.get("id", f.stem), "format": data.get("format", ""),
            "players": data.get("players", []), "rating": data.get("rating", 0),
            "uploadtime": data.get("uploadtime", 0), "source": data.get("source", "downloaded"),
        }
    except Exception:
        return None

def _orchestrator_status() -> dict:
    if not STATUS_FILE.exists():
        return {"alive": False, "connections": 0, "rooms_in_use": 0, "capacity": 0}
    try:
        data = json.loads(STATUS_FILE.read_text())
        try:
            os.kill(data["pid"], 0)
            data["alive"] = True
        except OSError:
            data["alive"] = False
        if STATUS_FILE.stat().st_mtime < time.time() - 30:
            data["alive"] = False
        return data
    except Exception:
        return {"alive": False, "connections": 0, "rooms_in_use": 0, "capacity": 0}

async def _scan_dir_cached(base: Path, fmt_id: str) -> list[dict]:
    """Return _scan_dir results, cached for CACHE_TTL seconds and run off the event loop."""
    key = f"scan:{base}:{fmt_id}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    result = await _run_in_executor(_scan_dir, base, fmt_id)
    _cache_set(key, result)
    return result


def _rating_buckets(ratings: list[int], step: int = 50) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for r in ratings:
        b = (r // step) * step
        buckets[str(b)] = buckets.get(str(b), 0) + 1
    return dict(sorted(buckets.items(), key=lambda x: int(x[0])))


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _is_real_image(name: str) -> bool:
    """True for actual image files (not macOS dot-files like ._foo.png or special _foo)."""
    return not (name.startswith("_") or name.startswith("."))


def _make_thumbnail(img_path: Path, max_w: int = 480, max_h: int = 270) -> bytes:
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()

def _extract_crop(img_path: Path, box: list, scale: int = 4) -> bytes:
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    x0, y0 = max(0, int(box[0]*w)), max(0, int(box[1]*h))
    x1, y1 = min(w, x0+int(box[2]*w)), min(h, y0+int(box[3]*h))
    crop = img.crop((x0, y0, x1, y1))
    cw, ch = crop.size
    up_w, up_h = min(cw*scale, 480), min(ch*scale, 240)
    upscaled = crop.resize((up_w, up_h), Image.NEAREST)
    buf = io.BytesIO()
    upscaled.save(buf, format="PNG")
    return buf.getvalue()

def _parse_ground_truth(filename: str, reader_name: str) -> dict:
    base = os.path.splitext(filename)[0]
    words = base.split("_")
    if reader_name == "OCRDump":
        return {"type": "void", "values": [], "raw": base}
    if base.endswith("_True"):
        return {"type": "bool", "values": [True], "raw": base}
    if base.endswith("_False"):
        return {"type": "bool", "values": [False], "raw": base}
    if reader_name == "MoveSelectCursorSlot":
        try:
            return {"type": "int", "values": [int(words[-1])], "raw": base}
        except ValueError:
            pass
    if reader_name == "MoveNameReader":
        slugs = words[-4:] if len(words) >= 4 else words
        return {"type": "words", "values": [("" if s == "NONE" else s) for s in slugs], "raw": base}
    if reader_name in ("TeamSelectReader", "TeamSummaryReader", "TeamPreviewReader"):
        slugs = words[-6:] if len(words) >= 6 else words
        return {"type": "words", "values": [("" if s == "NONE" else s) for s in slugs], "raw": base}
    if reader_name == "BattleHUDReader":
        return {"type": "battle_hud", "values": [], "raw": base}
    if reader_name == "BattleLogReader":
        type_words = []
        for w in words:
            if w and w[0].isupper():
                type_words.append(w)
            elif type_words:
                break
        return {"type": "words", "values": ["_".join(type_words)] if type_words else [base], "raw": base}
    return {"type": "words", "values": words, "raw": base}


# ═══════════════════════════════════════════════════════════════════════════
# SPECTATOR API (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
async def status():
    now = time.time()
    orch = _orchestrator_status()
    formats = {}
    total_replays = 0
    newest_save = 0
    for fmt_id, label in FORMATS.items():
        spec_files = await _scan_dir_cached(SPECTATED_DIR, fmt_id)
        dl_files = await _scan_dir_cached(DOWNLOADED_DIR, fmt_id)
        last_1h = last_24h = 0
        for f in spec_files:
            age = now - f["mtime"]
            if age < 3600: last_1h += 1
            if age < 86400: last_24h += 1
            if f["mtime"] > newest_save: newest_save = f["mtime"]
        formats[fmt_id] = {
            "label": label, "spectated": len(spec_files), "downloaded": len(dl_files),
            "total": len(spec_files) + len(dl_files), "last_1h": last_1h, "last_24h": last_24h,
        }
        total_replays += len(spec_files) + len(dl_files)
    return {
        "alive": orch.get("alive", False), "connections": orch.get("connections", 0),
        "total_connections": orch.get("total_connections", 0),
        "rooms_in_use": orch.get("rooms_in_use", 0), "capacity": orch.get("capacity", 0),
        "pending": orch.get("pending", 0), "draining": orch.get("draining", False),
        "stats": orch.get("stats", {}), "uptime_sec": orch.get("uptime_sec", 0),
        "per_connection": orch.get("per_connection", []),
        "last_save_ago_sec": round(now - newest_save) if newest_save > 0 else -1,
        "total_replays": total_replays, "formats": formats,
    }

@app.get("/api/collection")
async def collection():
    now = time.time()
    buckets = {fmt_id: [0]*48 for fmt_id in FORMATS}
    for fmt_id in FORMATS:
        for f in await _scan_dir_cached(SPECTATED_DIR, fmt_id):
            age = now - f["mtime"]
            if age > 3600*48: continue
            idx = int(age / 3600)
            if 0 <= idx < 48: buckets[fmt_id][idx] += 1
    return {
        "bucket_size_sec": 3600,
        "labels": ["now"] + [f"{i}h ago" for i in range(1, 48)],
        "series": {fid: {"label": FORMATS[fid], "data": c} for fid, c in buckets.items()},
    }

def _compute_ratings() -> dict:
    """Blocking: scan dirs + read replay metadata for rating distribution."""
    now = time.time()
    cutoff = now - 7*86400
    bins = list(range(900, 1800, 50))
    distributions = {fmt_id: [0]*len(bins) for fmt_id in FORMATS}
    for fmt_id in FORMATS:
        for f in _scan_dir(SPECTATED_DIR, fmt_id):
            if f["mtime"] < cutoff: continue
            meta = _read_replay_meta(f["path"])
            if not meta or not meta["rating"]: continue
            for i, edge in enumerate(bins):
                if meta["rating"] < edge + 50:
                    distributions[fmt_id][i] += 1; break
    return {
        "bins": [f"{b}-{b+49}" for b in bins], "bin_edges": bins,
        "series": {fid: {"label": FORMATS[fid], "data": c} for fid, c in distributions.items()},
    }


@app.get("/api/ratings")
async def ratings():
    key = "endpoint:ratings"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    result = await _run_in_executor(_compute_ratings)
    _cache_set(key, result, ttl=60)
    return result

def _compute_recent(limit: int = 30) -> list:
    """Blocking: scan dirs + read metadata for recent replays."""
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


@app.get("/api/recent")
async def recent(limit: int = 30):
    key = f"endpoint:recent:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    result = await _run_in_executor(_compute_recent, limit)
    _cache_set(key, result)
    return result

def _compute_dataset() -> dict:
    """Blocking: scan all dirs + read metadata for dataset overview."""
    combined = {}
    for key, fmt_id in [("vgc", "gen9championsvgc2026regma"), ("bss", "gen9championsbssregma")]:
        dl_files = _scan_dir(DOWNLOADED_DIR, fmt_id)
        sp_files = _scan_dir(SPECTATED_DIR, fmt_id)
        dl_ratings = [m["rating"] for f in dl_files if (m := _read_replay_meta(f["path"])) and m.get("rating")]
        sp_ratings = [m["rating"] for f in sp_files if (m := _read_replay_meta(f["path"])) and m.get("rating")]
        dl_buckets = _rating_buckets(dl_ratings)
        sp_buckets = _rating_buckets(sp_ratings)
        all_keys = set(list(dl_buckets.keys()) + list(sp_buckets.keys()))
        merged = {b: {"downloaded": dl_buckets.get(b, 0), "spectated": sp_buckets.get(b, 0),
                       "total": dl_buckets.get(b, 0) + sp_buckets.get(b, 0)}
                  for b in sorted(all_keys, key=lambda x: int(x))}
        all_ratings = dl_ratings + sp_ratings
        combined[key] = {
            "downloaded": len(dl_files), "spectated": len(sp_files), "total": len(dl_files) + len(sp_files),
            "rated": len(all_ratings),
            "rating_min": min(all_ratings) if all_ratings else 0,
            "rating_max": max(all_ratings) if all_ratings else 0,
            "rating_median": sorted(all_ratings)[len(all_ratings)//2] if all_ratings else 0,
            "rating_buckets": merged,
        }
    return {
        "combined": combined,
        "grand_total": sum(c["total"] for c in combined.values()),
        "grand_downloaded": sum(c["downloaded"] for c in combined.values()),
        "grand_spectated": sum(c["spectated"] for c in combined.values()),
    }


@app.get("/api/dataset")
async def dataset():
    key = "endpoint:dataset"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    result = await _run_in_executor(_compute_dataset)
    _cache_set(key, result, ttl=60)
    return result

@app.get("/api/coverage")
async def coverage():
    import websockets, asyncio
    elo_slices = [0, 1200, 1400]
    try:
        async with websockets.connect("wss://sim3.psim.us/showdown/websocket", ping_interval=30, open_timeout=10) as ws:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                if "|updateuser|" in msg: break
            expected = 0
            for fmt in FORMATS:
                for elo in elo_slices:
                    await ws.send(f"|/crq roomlist {fmt},{elo}" if elo else f"|/crq roomlist {fmt}")
                    expected += 1; await asyncio.sleep(0.3)
            all_rooms: dict[str, set[str]] = {fmt: set() for fmt in FORMATS}
            received = 0; deadline = time.time() + 8
            while received < expected and time.time() < deadline:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                if "|queryresponse|roomlist|" in msg:
                    received += 1
                    data = json.loads(msg.split("|queryresponse|roomlist|", 1)[1])
                    for fmt_id in FORMATS:
                        for rid in data.get("rooms", {}):
                            if fmt_id in rid: all_rooms[fmt_id].add(rid)
            await ws.close()
        orch = _orchestrator_status()
        active = {fmt: len(rids) for fmt, rids in all_rooms.items()}
        total = sum(active.values())
        return {
            "active_battles": active, "total_active": total,
            "total_active_note": "100+" if any(len(r) >= 100 for r in all_rooms.values()) else None,
            "connections": orch.get("connections", 0), "rooms_in_use": orch.get("rooms_in_use", 0),
            "capacity": orch.get("capacity", 0), "elo_slices": elo_slices,
            "coverage_pct": round(min(orch.get("capacity", 0) / max(total, 1), 1.0) * 100),
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# GALLERY API
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/gallery/readers")
async def gallery_readers():
    if not TEST_IMAGES_DIR.exists():
        return []
    readers = []
    for d in sorted(TEST_IMAGES_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("_"):
            count = sum(1 for f in d.rglob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg") and _is_real_image(f.name))
            readers.append({
                "name": d.name, "count": count,
                "crop_count": len(CROP_DEFS.get(d.name, [])),
                "type": READER_TYPES.get(d.name, "unknown"),
                "is_bool": d.name in BOOL_DETECTORS,
            })
    return readers

@app.get("/api/gallery/reader/{name}")
async def gallery_reader(name: str):
    reader_dir = TEST_IMAGES_DIR / name
    if not reader_dir.exists():
        return JSONResponse({"error": "reader not found"}, 404)
    images = []
    for f in sorted(reader_dir.rglob("*")):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg") or not _is_real_image(f.name):
            continue
        images.append({
            "filename": f.name,
            "path": str(f.relative_to(TEST_IMAGES_DIR)),
            "ground_truth": _parse_ground_truth(f.name, name),
        })
    return {"reader": name, "count": len(images), "images": images}

@app.get("/api/gallery/thumb/{path:path}")
async def gallery_thumb(path: str):
    full = TEST_IMAGES_DIR / path
    if not full.exists(): return JSONResponse({"error": "not found"}, 404)
    return Response(content=_make_thumbnail(full), media_type="image/jpeg")

@app.get("/api/gallery/image/{path:path}")
async def gallery_image(path: str):
    full = TEST_IMAGES_DIR / path
    if not full.exists(): return JSONResponse({"error": "not found"}, 404)
    return Response(content=full.read_bytes(), media_type="image/png" if full.suffix == ".png" else "image/jpeg")

@app.get("/api/gallery/crops/{reader}/{filename}")
async def gallery_crops(reader: str, filename: str):
    import base64
    img_path = TEST_IMAGES_DIR / reader / filename
    if not img_path.exists(): return JSONResponse({"error": "not found"}, 404)
    return [
        {"name": cd["name"], "box": cd["box"],
         "data": f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, cd['box'])).decode()}"}
        for cd in CROP_DEFS.get(reader, [])
    ]


@app.post("/api/gallery/crops_custom/{reader}/{filename}")
async def gallery_crops_custom(reader: str, filename: str, request: Request):
    """Return crops using custom box coordinates (for live adjustment)."""
    import base64
    img_path = TEST_IMAGES_DIR / reader / filename
    if not img_path.exists(): return JSONResponse({"error": "not found"}, 404)
    body = await request.json()
    boxes = body.get("boxes", [])  # [{name, box: [x, y, w, h]}, ...]
    return [
        {"name": b["name"], "box": b["box"],
         "data": f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, b['box'])).decode()}"}
        for b in boxes
    ]


@app.get("/api/gallery/crop_defs/{reader}")
async def gallery_crop_defs(reader: str):
    """Return current crop definitions for a reader."""
    return {"reader": reader, "crops": CROP_DEFS.get(reader, [])}


# ═══════════════════════════════════════════════════════════════════════════
# SCREEN-BASED GALLERY API (new manifest-driven structure)
# ═══════════════════════════════════════════════════════════════════════════

SCREENS_YAML_PATH = TEST_IMAGES_DIR / "screens.yaml"

def _load_screens_yaml():
    """Load and cache screens.yaml."""
    key = "screens_yaml"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if not SCREENS_YAML_PATH.exists():
        return {}
    try:
        import yaml
        with open(SCREENS_YAML_PATH) as f:
            data = yaml.safe_load(f)
        _cache_set(key, data, ttl=300)  # cache 5 min
        return data
    except Exception:
        return {}


def _load_manifest(screen_dir: Path) -> dict:
    """Load manifest.json from a screen directory."""
    manifest_path = screen_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except Exception:
        return {}


@app.get("/api/gallery/screens")
async def gallery_screens():
    """List all screen directories with image counts and registered detectors/readers."""
    config = _load_screens_yaml()
    screens = config.get("screens", {})
    overlays = config.get("overlays", {})
    result = []

    # Regular screens
    for name, defn in screens.items():
        screen_dir = TEST_IMAGES_DIR / name
        count = sum(1 for f in screen_dir.glob("*.png") if _is_real_image(f.name)) if screen_dir.exists() else 0
        manifest = _load_manifest(screen_dir)
        #  "labeled" counts only entries with all expected readers present —
        #  partials are treated as unlabeled so the sidebar surfaces work-to-do.
        expected = set(defn.get("readers", {}).keys()) | set(defn.get("detectors", []))
        labeled = sum(1 for v in manifest.values() if v and expected.issubset(set(v.keys())))
        result.append({
            "name": name,
            "description": defn.get("description", ""),
            "count": count,
            "labeled": labeled,
            "detectors": defn.get("detectors", []),
            "readers": list(defn.get("readers", {}).keys()),
            "transitions_to": defn.get("transitions_to", []),
            "type": "screen",
        })

    # Overlays
    for name, defn in overlays.items():
        overlay_dir = TEST_IMAGES_DIR / "_overlays" / name
        count = sum(1 for f in overlay_dir.glob("*.png") if _is_real_image(f.name)) if overlay_dir.exists() else 0
        manifest = _load_manifest(overlay_dir)
        expected = set(defn.get("readers", {}).keys())
        labeled = sum(1 for v in manifest.values() if v and expected.issubset(set(v.keys())))
        result.append({
            "name": f"_overlays/{name}",
            "description": defn.get("description", ""),
            "count": count,
            "labeled": labeled,
            "detectors": [],
            "readers": list(defn.get("readers", {}).keys()),
            "transitions_to": [],
            "type": "overlay",
        })

    return result


@app.get("/api/gallery/screen/{name:path}")
async def gallery_screen(name: str):
    """List all images in a screen directory with their manifest labels."""
    screen_dir = TEST_IMAGES_DIR / name
    if not screen_dir.exists():
        return JSONResponse({"error": "screen not found"}, 404)

    manifest = _load_manifest(screen_dir)

    # Get reader info from screens.yaml
    config = _load_screens_yaml()
    screens = config.get("screens", {})
    overlays = config.get("overlays", {})

    screen_def = screens.get(name) or overlays.get(name.replace("_overlays/", "")) or {}
    readers = dict(screen_def.get("readers", {}))

    #  Surface per-image detectors as synthetic single-bool readers so the
    #  gallery card modal renders them as labelable per-image fields.
    #  Skip detectors registered as screen-level positives in test_registry
    #  (those are always-true on this screen — no per-image label needed).
    try:
        registry = json.loads((TEST_IMAGES_DIR / "test_registry.json").read_text())
        screen_level_dets = {
            d for d, screens_list in (registry.get("detectors") or {}).items()
            if name in screens_list
        }
    except Exception:
        screen_level_dets = set()
    for det in screen_def.get("detectors", []):
        if det in readers or det in screen_level_dets:
            continue
        readers[det] = {"is_detector": True, "fields": {"_self": {"type": "bool", "description": "Detector should fire on this image."}}}

    # Determine all crop defs for readers registered on this screen
    screen_crops = {}
    for reader_name in readers:
        if reader_name in CROP_DEFS:
            screen_crops[reader_name] = CROP_DEFS[reader_name]

    images = []
    for f in sorted(screen_dir.glob("*.png")):
        if not _is_real_image(f.name):
            continue
        labels = manifest.get(f.name, {})
        # Determine label completeness
        expected_readers = set(readers.keys())
        labeled_readers = set(labels.keys())
        status = "complete" if expected_readers <= labeled_readers else (
            "partial" if labeled_readers else "unlabeled"
        )
        images.append({
            "filename": f.name,
            "path": str(f.relative_to(TEST_IMAGES_DIR)),
            "labels": labels,
            "status": status,
        })

    return {
        "screen": name,
        "description": screen_def.get("description", ""),
        "count": len(images),
        "readers": {rname: rdef for rname, rdef in readers.items()},
        "crops": screen_crops,
        "images": images,
    }


@app.get("/api/gallery/screen_crops/{screen:path}/{filename}")
async def gallery_screen_crops(screen: str, filename: str):
    """Return crops for all readers registered on a screen."""
    import base64
    img_path = TEST_IMAGES_DIR / screen / filename
    if not img_path.exists():
        return JSONResponse({"error": "not found"}, 404)

    config = _load_screens_yaml()
    screens_cfg = config.get("screens", {})
    overlays_cfg = config.get("overlays", {})
    screen_def = screens_cfg.get(screen) or overlays_cfg.get(screen.replace("_overlays/", "")) or {}
    readers = screen_def.get("readers", {})

    result = []
    for reader_name in readers:
        for cd in CROP_DEFS.get(reader_name, []):
            result.append({
                "reader": reader_name,
                "name": cd["name"],
                "box": cd["box"],
                "data": f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, cd['box'])).decode()}",
            })
    return result


@app.get("/api/gallery/manifest/{screen:path}")
async def gallery_manifest(screen: str):
    """Return the full manifest.json for a screen."""
    screen_dir = TEST_IMAGES_DIR / screen
    return _load_manifest(screen_dir)


@app.put("/api/gallery/manifest/{screen:path}/{filename}")
async def gallery_manifest_update(screen: str, filename: str, request: Request):
    """Update manifest labels for a single image."""
    screen_dir = TEST_IMAGES_DIR / screen
    manifest_path = screen_dir / "manifest.json"
    img_path = screen_dir / filename
    if not img_path.exists():
        return JSONResponse({"error": "image not found"}, 404)

    body = await request.json()
    manifest = _load_manifest(screen_dir)
    manifest[filename] = body
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"ok": True, "filename": filename}


@app.post("/api/gallery/manifest/{screen:path}/bulk-confirm")
async def gallery_manifest_bulk_confirm(screen: str):
    """Mark all unlabeled images in a reader-less screen as confirmed (empty labels)."""
    screen_dir = TEST_IMAGES_DIR / screen
    if not screen_dir.exists():
        return JSONResponse({"error": "screen not found"}, 404)
    manifest = _load_manifest(screen_dir)
    count = 0
    for f in sorted(screen_dir.glob("*.png")):
        if not _is_real_image(f.name):
            continue
        if f.name not in manifest:
            manifest[f.name] = {}
            count += 1
    manifest_path = screen_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"ok": True, "confirmed": count}


@app.post("/api/gallery/manifest/{screen:path}/bulk-update")
async def gallery_manifest_bulk_update(screen: str, request: Request):
    """Merge labels for multiple images at once.

    Body: { "labels": { "filename.png": { "ReaderName": { "field": "val" } } } }
    """
    screen_dir = TEST_IMAGES_DIR / screen
    if not screen_dir.exists():
        return JSONResponse({"error": "screen not found"}, 404)
    body = await request.json()
    new_labels = body.get("labels", {})
    manifest = _load_manifest(screen_dir)
    updated = 0
    for fname, readers in new_labels.items():
        if fname not in manifest:
            manifest[fname] = {}
        for reader_name, fields in readers.items():
            manifest[fname][reader_name] = fields
        updated += 1
    manifest_path = screen_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"ok": True, "updated": updated}


# ── Inbox API ──

INBOX_DIR = TEST_IMAGES_DIR / "_inbox"


@app.get("/api/gallery/inbox")
async def gallery_inbox():
    """List all images in the inbox (unsorted)."""
    if not INBOX_DIR.exists():
        return {"count": 0, "images": []}
    images = []
    for f in sorted(INBOX_DIR.glob("*.png")):
        if not _is_real_image(f.name):
            continue
        images.append({"filename": f.name, "path": f"_inbox/{f.name}"})
    return {"count": len(images), "images": images}


@app.post("/api/gallery/image-move")
async def gallery_image_move(request: Request):
    """Move an image from one screen to another, to inbox, or delete it."""
    body = await request.json()
    screen = body.get("screen", "")
    filename = body.get("filename", "")
    target = body.get("target", "")

    if not screen or not filename or not target:
        return JSONResponse({"error": "screen, filename, and target required"}, 400)

    src = TEST_IMAGES_DIR / screen / filename
    if not src.exists():
        return JSONResponse({"error": "image not found"}, 404)

    # Remove from source manifest
    src_dir = TEST_IMAGES_DIR / screen
    manifest = _load_manifest(src_dir)
    manifest.pop(filename, None)
    (src_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if target == "__delete":
        src.unlink()
        return {"ok": True, "action": "deleted", "filename": filename}

    target_dir = TEST_IMAGES_DIR / target
    if not target_dir.exists():
        return JSONResponse({"error": f"target '{target}' not found"}, 404)

    dest = target_dir / filename
    shutil.move(str(src), str(dest))
    return {"ok": True, "action": "moved", "filename": filename, "target": target}


@app.post("/api/gallery/inbox/assign")
async def gallery_inbox_assign(request: Request):
    """Move image(s) from inbox to a screen directory."""
    body = await request.json()
    filenames = body.get("filenames", [])
    screen = body.get("screen", "")

    screen_dir = TEST_IMAGES_DIR / screen
    if not screen_dir.exists():
        return JSONResponse({"error": f"screen '{screen}' not found"}, 404)

    moved = []
    for fname in filenames:
        src = INBOX_DIR / fname
        if not src.exists():
            continue
        dest = screen_dir / fname
        shutil.move(str(src), str(dest))
        moved.append(fname)

    return {"ok": True, "moved": len(moved), "filenames": moved}


@app.post("/api/teampreview/crops")
async def teampreview_crops(request: Request):
    """Extract crops from any labeler source frame using custom boxes."""
    import base64
    body = await request.json()
    source = body.get("source", "")
    filename = body.get("filename", "")
    boxes = body.get("boxes", [])
    src_dir = _resolve_source_dir(source)
    if not src_dir:
        return JSONResponse({"error": "source not found"}, 404)
    img_path = src_dir / filename
    if not img_path.exists():
        return JSONResponse({"error": "not found"}, 404)
    return [
        {"name": b["name"], "box": b["box"],
         "data": f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, b['box'])).decode()}"}
        for b in boxes
    ]


@app.get("/api/sprites/list")
async def sprites_list():
    """Return the list of sprite slugs in the Pokemon Champions atlas."""
    json_path = RESOURCES_DIR / "PokemonSprites.json"
    if not json_path.exists():
        return JSONResponse({"error": "sprite resources not found"}, 404)
    meta = json.loads(json_path.read_text())
    locs = meta.get("spriteLocations", {})
    return {
        "ok": True,
        "count": len(locs),
        "sprite_size": [meta.get("spriteWidth", 128), meta.get("spriteHeight", 128)],
        "names": sorted(locs.keys()),
    }


@app.get("/api/sprites/examples")
async def sprites_examples(limit: int = 100):
    """Return labeled team-preview frames with the actual opp-sprite crops
    (base64 PNG) alongside the reference sprite slug for each slot.

    Mirrors C++ TeamPreviewReader's locked-in opp coords so the crop the
    user sees here is exactly what the matcher consumed.
    """
    import base64
    OPP_X, OPP_Y0, OPP_Y5, OPP_W, OPP_H = 0.7181, 0.1482, 0.7310, 0.0664, 0.1009
    step = (OPP_Y5 - OPP_Y0) / 5.0
    OPP_BOXES = [[OPP_X, OPP_Y0 + i * step, OPP_W, OPP_H] for i in range(6)]
    examples = []
    candidates = [
        TEST_IMAGES_DIR / "team_preview_locked_in",
        TEST_IMAGES_DIR / "team_preview_selecting",
    ]
    for screen_dir in candidates:
        if not screen_dir.exists():
            continue
        screen_name = screen_dir.name
        manifest = _load_manifest(screen_dir)
        for fname, labels in manifest.items():
            tp = labels.get("TeamPreviewReader")
            if not isinstance(tp, dict):
                continue
            opp = tp.get("opponent_species") or []
            if not any(opp):
                continue
            img_path = screen_dir / fname
            if not img_path.exists():
                continue
            slots = []
            for i in range(min(6, len(opp))):
                crop_b64 = base64.b64encode(_extract_crop(img_path, OPP_BOXES[i])).decode()
                slots.append({
                    "species": opp[i] or "",
                    "crop": f"data:image/png;base64,{crop_b64}",
                })
            examples.append({
                "screen": screen_name,
                "filename": fname,
                "slots": slots,
            })
            if len(examples) >= limit:
                return {"ok": True, "examples": examples, "truncated": True}
    return {"ok": True, "examples": examples, "truncated": False}


@app.get("/api/teampreview/sprite/{slug}")
async def teampreview_sprite(slug: str):
    """Extract a single sprite from the atlas PNG."""
    import base64
    from PIL import Image
    json_path = RESOURCES_DIR / "PokemonSprites.json"
    atlas_path = RESOURCES_DIR / "PokemonSprites.png"
    if not json_path.exists() or not atlas_path.exists():
        return JSONResponse({"error": "sprite resources not found"}, 404)
    meta = json.loads(json_path.read_text())
    loc = meta.get("spriteLocations", {}).get(slug)
    if not loc:
        return JSONResponse({"error": f"sprite '{slug}' not found"}, 404)
    h = meta.get("spriteHeight", 128)
    atlas = Image.open(atlas_path)
    sprite = atlas.crop((loc["left"], loc["top"], loc["left"] + h, loc["top"] + h))
    buf = io.BytesIO()
    sprite.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# ═══════════════════════════════════════════════════════════════════════════
# LABELER API
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/labeler/sources")
async def labeler_sources():
    sources = []

    # ref_frames subdirectories (VOD extracts)
    if REF_FRAMES_DIR.exists():
        for vod_dir in sorted(REF_FRAMES_DIR.rglob("*")):
            if not vod_dir.is_dir(): continue
            imgs = [f for f in vod_dir.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")]
            if imgs:
                folder_name = vod_dir.name
                readers = FOLDER_READERS.get(folder_name, [FOLDER_TO_READER.get(folder_name, "BattleHUDReader")])
                sources.append({
                    "path": str(vod_dir.relative_to(REF_FRAMES_DIR)),
                    "name": folder_name, "parent": vod_dir.parent.name, "count": len(imgs),
                    "suggested_reader": FOLDER_TO_READER.get(folder_name),
                    "readers": readers,
                    "reader_infos": {
                        r: {"reader": r, "type": READER_TYPES.get(r, "unknown"),
                            "is_bool": r in BOOL_DETECTORS, "crops": CROP_DEFS.get(r, []),
                            "events": BATTLE_LOG_EVENTS if r == "BattleLogReader" else None}
                        for r in readers
                    },
                })

    # test_images subdirectories (labeled test frames from CommandLineTests)
    if TEST_IMAGES_DIR.exists():
        for reader_dir in sorted(TEST_IMAGES_DIR.iterdir()):
            if not reader_dir.is_dir(): continue
            imgs = [f for f in reader_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and _is_real_image(f.name)]
            if imgs:
                reader_name = reader_dir.name
                sources.append({
                    "path": f"__test__/{reader_name}",
                    "name": reader_name, "parent": "test_images", "count": len(imgs),
                    "suggested_reader": reader_name,
                    "readers": [reader_name],
                    "reader_infos": {
                        reader_name: {"reader": reader_name,
                                      "type": READER_TYPES.get(reader_name, "unknown"),
                                      "is_bool": reader_name in BOOL_DETECTORS,
                                      "crops": CROP_DEFS.get(reader_name, []),
                                      "events": BATTLE_LOG_EVENTS if reader_name == "BattleLogReader" else None}
                    },
                })

    return sources

def _resolve_source_dir(source: str) -> Optional[Path]:
    """Resolve a source path to a directory (ref_frames or test_images)."""
    if source.startswith("__test__/"):
        reader = source[len("__test__/"):]
        d = TEST_IMAGES_DIR / reader
        return d if d.exists() else None
    d = REF_FRAMES_DIR / source
    return d if d.exists() else None


@app.get("/api/labeler/images")
async def labeler_images(source: str, reader: str):
    src_dir = _resolve_source_dir(source)
    if not src_dir:
        return JSONResponse({"error": "source not found"}, 404)
    labels = _load_labels(source, reader)
    images = []
    for f in sorted(src_dir.iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png"): continue
        if not _is_real_image(f.name): continue
        label = labels.get(f.name)
        images.append({
            "filename": f.name, "labeled": label is not None,
            "skipped": label.get("type") == "skip" if label else False, "label": label,
        })
    return {"source": source, "reader": reader, "total": len(images),
            "labeled": sum(1 for i in images if i["labeled"]), "images": images}

@app.get("/api/labeler/frame/{path:path}")
async def labeler_frame(path: str, thumb: bool = False):
    # Try ref_frames first, then test_images (for __test__/ paths)
    if path.startswith("__test__/"):
        full = TEST_IMAGES_DIR / path[len("__test__/"):]
    else:
        full = REF_FRAMES_DIR / path
    if not full.exists():
        return JSONResponse({"error": "not found"}, 404)
    if thumb:
        return Response(content=_make_thumbnail(full, 960, 540), media_type="image/jpeg")
    return Response(content=full.read_bytes(), media_type="image/png" if full.suffix == ".png" else "image/jpeg")

@app.get("/api/labeler/crops")
async def labeler_crops(source: str, filename: str, reader: str):
    import base64
    src_dir = _resolve_source_dir(source)
    if not src_dir:
        return JSONResponse({"error": "source not found"}, 404)
    img_path = src_dir / filename
    if not img_path.exists():
        return JSONResponse({"error": "not found"}, 404)
    return [
        {"name": cd["name"], "box": cd["box"],
         "data": f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, cd['box'])).decode()}"}
        for cd in CROP_DEFS.get(reader, [])
    ]

@app.post("/api/labeler/label")
async def labeler_save_label(source: str = Form(...), filename: str = Form(...),
                              reader: str = Form(...), label_json: str = Form(...)):
    labels = _load_labels(source, reader)
    parsed = json.loads(label_json)
    # Wrap bare values (bool, str, int) in a dict so .get("type") works downstream
    if not isinstance(parsed, dict):
        parsed = {"type": READER_TYPES.get(reader, "unknown"), "value": parsed}
    labels[filename] = parsed
    _save_labels(source, reader, labels)
    return {"ok": True, "labeled": sum(1 for v in labels.values() if v.get("type") != "skip")}

@app.post("/api/labeler/label_batch")
async def labeler_save_label_batch(req: Request):
    data = await req.json()
    source, filename = data["source"], data["filename"]
    for reader, value in data["labels"].items():
        reader_labels = _load_labels(source, reader)
        if not isinstance(value, dict):
            value = {"type": READER_TYPES.get(reader, "unknown"), "value": value}
        reader_labels[filename] = value
        _save_labels(source, reader, reader_labels)
    return {"ok": True}

@app.get("/api/labeler/frame_labels")
async def labeler_frame_labels(source: str, filename: str):
    result = {}
    for reader in READER_TYPES:
        labels = _load_labels(source, reader)
        if filename in labels:
            result[reader] = labels[filename]
    return result

@app.post("/api/labeler/export")
async def labeler_export(source: str = Form(...), reader: str = Form(...)):
    labels = _load_labels(source, reader)
    dest_dir = TEST_IMAGES_DIR / reader
    dest_dir.mkdir(parents=True, exist_ok=True)
    exported = skipped = 0
    for filename, label in labels.items():
        if label.get("type") == "skip": skipped += 1; continue
        suffix = _label_to_suffix(label)
        if not suffix: continue
        src = REF_FRAMES_DIR / source / filename
        if not src.exists(): continue
        dest = dest_dir / f"{Path(filename).stem}_{suffix}.png"
        if not dest.exists():
            shutil.copy2(src, dest); exported += 1
    return {"exported": exported, "skipped": skipped, "dest": str(dest_dir)}

@app.get("/api/labeler/completions/{kind}")
async def labeler_completions(kind: str):
    if kind == "species":
        p = RESOURCES_DIR / "PokemonSpeciesOCR.json"
        if p.exists(): return sorted(json.loads(p.read_text()).get("eng", {}).keys())
    elif kind == "moves":
        p = RESOURCES_DIR / "PokemonMovesOCR.json"
        if p.exists(): return sorted(json.loads(p.read_text()).get("eng", {}).keys())
    elif kind == "events":
        return BATTLE_LOG_EVENTS
    return []

@app.get("/api/labeler/reader_info/{reader}")
async def labeler_reader_info(reader: str):
    return {
        "reader": reader, "type": READER_TYPES.get(reader, "unknown"),
        "is_bool": reader in BOOL_DETECTORS, "crops": CROP_DEFS.get(reader, []),
        "events": BATTLE_LOG_EVENTS if reader == "BattleLogReader" else None,
    }

def _label_to_suffix(label: dict) -> str:
    t = label.get("type", "")
    if t == "bool": return "True" if label["value"] else "False"
    if t == "event": return label["value"]
    if t == "int": return str(label["value"])
    if t == "multi": return "_".join(v if v else "NONE" for v in label["values"])
    if t == "text": return label.get("value", "NONE") or "NONE"
    return ""

def _labels_path(source: str, reader: str) -> Path:
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    return LABELS_DIR / f"{source.replace('/', '__').replace(chr(92), '__')}__{reader}.json"

def _load_labels(source: str, reader: str) -> dict:
    p = _labels_path(source, reader)
    return json.loads(p.read_text()) if p.exists() else {}

def _save_labels(source: str, reader: str, labels: dict):
    _labels_path(source, reader).write_text(json.dumps(labels, indent=2))


# ═══════════════════════════════════════════════════════════════════════════
# INSPECTOR API
# ═══════════════════════════════════════════════════════════════════════════

BOX_DEFINITIONS_PATH = BASE / "tools" / "box_definitions.json"


def _resolve_image_path(path: str) -> Optional[Path]:
    """Resolve a relative image path against test_images/ and ref_frames/."""
    for base in [TEST_IMAGES_DIR, REF_FRAMES_DIR]:
        full = base / path
        if full.exists():
            return full
    return None


def _resolve_inspector_image(
    path: str = "", source: str = "", filename: str = ""
) -> Optional[Path]:
    """Resolve an inspector image from either path or source+filename.

    Sources from the labeler API use a "__test__/<screen>" prefix to point
    inside test_images/. Delegate to _resolve_source_dir so the same logic
    handles both ref_frames/ and test_images/ shapes.
    """
    if path:
        return _resolve_image_path(path)
    if source and filename:
        src_dir = _resolve_source_dir(source)
        if src_dir:
            full = src_dir / filename
            if full.exists():
                return full
        # Legacy fallbacks (raw ref_frames/test_images paths without prefix).
        full = REF_FRAMES_DIR / source / filename
        if full.exists():
            return full
        full = TEST_IMAGES_DIR / source / filename
        if full.exists():
            return full
    return None


def _analyze_region(img, x: float, y: float, w: float, h: float) -> dict:
    """Analyze a normalized box region on a PIL image.

    Returns color stats, is_solid tests, C++ code, and crop data URIs.
    """
    import base64 as b64

    iw, ih = img.size
    x0, y0 = max(0, int(x * iw)), max(0, int(y * ih))
    x1, y1 = min(iw, x0 + int(w * iw)), min(ih, y0 + int(h * ih))
    pw, ph = x1 - x0, y1 - y0
    if pw <= 0 or ph <= 0:
        return {"error": "empty region"}

    crop = img.crop((x0, y0, x1, y1))
    pixels = list(crop.getdata())
    n = len(pixels)
    if n == 0:
        return {"error": "empty region"}

    sr = sg = sb = sqr = sqg = sqb = 0
    for r, g, b in pixels:
        sr += r; sg += g; sb += b
        sqr += r * r; sqg += g * g; sqb += b * b
    avg = (sr / n, sg / n, sb / n)
    if n > 1:
        sd = tuple(
            math.sqrt(max(0, (sq - s * s / n) / (n - 1)))
            for s, sq in [(sr, sqr), (sg, sqg), (sb, sqb)]
        )
    else:
        sd = (0, 0, 0)
    total = sum(avg)
    ratio = tuple(a / total for a in avg) if total > 0 else (0.333, 0.333, 0.333)
    sdsum = sum(sd)

    # is_solid tests at standard thresholds
    solid_tests = []
    for max_dist, max_sd in [(0.10, 100), (0.15, 120), (0.18, 150), (0.25, 200)]:
        # self-test: distance is 0 (comparing ratio to itself)
        solid_tests.append({
            "max_dist": max_dist, "max_stddev": max_sd,
            "passes": sdsum <= max_sd,
        })

    # Crop preview (base64 PNG, upscaled for visibility)
    scale = max(1, min(6, 180 // max(pw, ph, 1)))
    from PIL import Image as PILImage
    crop_scaled = crop.resize((pw * scale, ph * scale), PILImage.NEAREST)
    buf = io.BytesIO()
    crop_scaled.save(buf, "PNG")
    crop_b64 = b64.b64encode(buf.getvalue()).decode()

    # Binarized preview (white-text filter matching C++)
    bw = PILImage.new("RGB", (pw, ph))
    for py_idx in range(ph):
        for px_idx in range(pw):
            r, g, b = crop.getpixel((px_idx, py_idx))
            mn = min(r, g, b)
            mx = max(r, g, b)
            is_white = mn > 180 and (mx - mn) < 50
            val = (0, 0, 0) if is_white else (255, 255, 255)
            bw.putpixel((px_idx, py_idx), val)
    bw_scaled = bw.resize((pw * scale, ph * scale), PILImage.NEAREST)
    buf2 = io.BytesIO()
    bw_scaled.save(buf2, "PNG")
    bw_b64 = b64.b64encode(buf2.getvalue()).decode()

    cpp_box = f"ImageFloatBox({x:.4f}, {y:.4f}, {w:.4f}, {h:.4f})"
    cpp_color = f"FloatPixel{{{ratio[0]:.2f}, {ratio[1]:.2f}, {ratio[2]:.2f}}}"

    return {
        "box": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)],
        "pixels": {"x0": x0, "y0": y0, "w": pw, "h": ph, "count": n},
        "avg_rgb": [round(avg[0], 1), round(avg[1], 1), round(avg[2], 1)],
        "stddev_rgb": [round(sd[0], 1), round(sd[1], 1), round(sd[2], 1)],
        "stddev_sum": round(sdsum, 1),
        "color_ratio": [round(ratio[0], 4), round(ratio[1], 4), round(ratio[2], 4)],
        "brightness": round(total / 3, 1),
        "solid_tests": solid_tests,
        "cpp_box": cpp_box,
        "cpp_color": cpp_color,
        "crop_b64": crop_b64,
        "bw_b64": bw_b64,
    }


@app.post("/api/inspector/analyze")
async def inspector_analyze(
    x: float = Form(...), y: float = Form(...),
    w: float = Form(...), h: float = Form(...),
    path: str = Form(""), source: str = Form(""), filename: str = Form(""),
):
    from PIL import Image
    full = _resolve_inspector_image(path, source, filename)
    if not full or not full.exists():
        return JSONResponse({"error": "not found"}, 404)
    img = Image.open(full).convert("RGB")
    return _analyze_region(img, x, y, w, h)


@app.get("/api/inspector/boxes")
async def inspector_boxes():
    return CROP_DEFS


@app.get("/api/inspector/box-definitions")
async def inspector_box_definitions():
    """Return saved box definitions from tools/box_definitions.json."""
    if BOX_DEFINITIONS_PATH.exists():
        return json.loads(BOX_DEFINITIONS_PATH.read_text())
    return {"boxes": []}


@app.post("/api/inspector/save-box")
async def inspector_save_box(request: Request):
    """Save a box definition to tools/box_definitions.json."""
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, 400)

    defs = json.loads(BOX_DEFINITIONS_PATH.read_text()) if BOX_DEFINITIONS_PATH.exists() else {"boxes": []}
    entry = {
        "name": name,
        "scene": body.get("scene", ""),
        "screenshot": body.get("screenshot", ""),
        "description": body.get("description", ""),
        "status": "confirmed",
        "box": body["box"],
        "avg_rgb": body.get("avg_rgb", [0, 0, 0]),
        "stddev_sum": body.get("stddev_sum", 0),
        "color_ratio": body.get("color_ratio", [0.333, 0.333, 0.333]),
    }
    # Update existing or append
    for i, existing in enumerate(defs["boxes"]):
        if existing["name"] == name:
            defs["boxes"][i] = entry
            break
    else:
        defs["boxes"].append(entry)

    BOX_DEFINITIONS_PATH.write_text(json.dumps(defs, indent=2))
    return {"ok": True}


@app.get("/api/inspector/image/{path:path}")
async def inspector_image(path: str):
    full = _resolve_image_path(path)
    if not full or not full.exists():
        return JSONResponse({"error": "not found"}, 404)
    return Response(
        content=full.read_bytes(),
        media_type="image/png" if full.suffix == ".png" else "image/jpeg",
    )


# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD API
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/upload/ref_frames")
async def upload_ref_frame(file: UploadFile = File(...), dest: str = Form(...)):
    dest_dir = REF_FRAMES_DIR / dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / file.filename).write_bytes(await file.read())
    return {"ok": True}

@app.post("/api/upload/test_images")
async def upload_test_image(file: UploadFile = File(...), reader: str = Form(...)):
    dest_dir = TEST_IMAGES_DIR / reader
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / file.filename).write_bytes(await file.read())
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════
# MODEL REVIEW API (lazy-loaded — torch only imported on first request)
# ═══════════════════════════════════════════════════════════════════════════

SRC_DIR = BASE / "src"
VOCAB_DIR = BASE / "data" / "vocab"
CHECKPOINT_PATH = BASE / "data" / "checkpoints" / "best.pt"
VGC_FMT = "gen9championsvgc2026regma"
MODEL_REPLAY_DIRS = [
    REPLAY_BASE / VGC_FMT,
    SPECTATED_DIR / VGC_FMT,
    DOWNLOADED_DIR / VGC_FMT,
]

_model_state: dict = {"loaded": False, "error": None, "model": None, "vocabs": None, "device": None}
_review_cache: dict[str, dict] = {}


def _ensure_model():
    """Lazy-load vocabs + model on first request."""
    if _model_state["loaded"]:
        return _model_state["error"] is None
    _model_state["loaded"] = True

    # Add both src/ (for `from vgc_model...`) and project root (for pickled
    # objects saved as `src.vgc_model...` on ColePC)
    for p in [str(SRC_DIR), str(BASE)]:
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        import torch
        from vgc_model.data.vocab import Vocabs
        from vgc_model.model.vgc_model import VGCTransformer, ModelConfig

        if not CHECKPOINT_PATH.exists():
            _model_state["error"] = f"No checkpoint at {CHECKPOINT_PATH}"
            return False

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        vocabs = Vocabs.load(VOCAB_DIR)
        checkpoint = torch.load(CHECKPOINT_PATH, map_location=device, weights_only=False)
        config = checkpoint.get("config", ModelConfig())
        model = VGCTransformer(vocabs, config).to(device)
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()

        _model_state["model"] = model
        _model_state["vocabs"] = vocabs
        _model_state["device"] = device
        _model_state["checkpoint_info"] = {
            "val_top1": checkpoint.get("val_top1"),
            "val_top3": checkpoint.get("val_top3"),
            "epoch": checkpoint.get("epoch"),
            "params": model.count_parameters(),
        }
        return True
    except Exception as e:
        _model_state["error"] = str(e)
        return False


def _analyze_replay(replay_path: Path) -> Optional[dict]:
    """Parse a replay and run the model on each turn."""
    import torch
    import torch.nn.functional as F
    from vgc_model.data.log_parser import parse_battle, Action
    from vgc_model.data.dataset import MAX_ACTIONS, BOOST_STATS

    model = _model_state["model"]
    vocabs = _model_state["vocabs"]
    device = _model_state["device"]

    try:
        data = json.loads(replay_path.read_text(errors="replace"))
        log = data.get("log", "")
        rating = data.get("rating", 0)
    except Exception:
        return None

    result = parse_battle(log, rating)
    if result is None:
        return None

    winner_samples = [s for s in result.samples if s.is_winner]
    if not winner_samples:
        return None

    TARGET_NAMES = ["opp_a", "opp_b", "ally"]
    SPREAD_MOVES = {
        "Earthquake", "Rock Slide", "Heat Wave", "Blizzard", "Hyper Voice",
        "Dazzling Gleam", "Icy Wind", "Eruption", "Water Spout", "Discharge",
        "Sludge Wave", "Surf", "Muddy Water", "Lava Plume", "Electroweb",
        "Struggle Bug", "Breaking Swipe", "Bulldoze", "Glacial Lance",
        "Astral Barrage", "Matcha Gotcha", "Make It Rain",
    }

    def _encode_sample(sample, battle):
        """Encode a TrainingSample into model input tensors."""
        player = sample.player
        state = sample.state
        if player == "p1":
            own_active, own_bench = state.p1_active, state.p1_bench
            opp_active, opp_bench = state.p2_active, state.p2_bench
            tw_own, tw_opp = state.field.tailwind_p1, state.field.tailwind_p2
            sc_own = [int(state.field.light_screen_p1), int(state.field.reflect_p1), int(state.field.aurora_veil_p1)]
            sc_opp = [int(state.field.light_screen_p2), int(state.field.reflect_p2), int(state.field.aurora_veil_p2)]
        else:
            own_active, own_bench = state.p2_active, state.p2_bench
            opp_active, opp_bench = state.p1_active, state.p1_bench
            tw_own, tw_opp = state.field.tailwind_p2, state.field.tailwind_p1
            sc_own = [int(state.field.light_screen_p2), int(state.field.reflect_p2), int(state.field.aurora_veil_p2)]
            sc_opp = [int(state.field.light_screen_p1), int(state.field.reflect_p1), int(state.field.aurora_veil_p1)]

        slots = [None] * 8
        for i, src in enumerate([own_active, own_bench, opp_active, opp_bench]):
            for j, poke in enumerate(src[:2]):
                slots[i * 2 + j] = poke

        species_ids, hp_vals, status_ids, boosts = [], [], [], []
        item_ids, ability_ids, mega_flags, alive_flags, move_ids = [], [], [], [], []
        v = vocabs
        for poke in slots:
            if poke is None:
                species_ids.append(0); hp_vals.append(0.0); status_ids.append(0)
                boosts.append([0]*6); item_ids.append(0); ability_ids.append(0)
                mega_flags.append(0); alive_flags.append(0); move_ids.append([0,0,0,0])
            else:
                species_ids.append(v.species[poke.species])
                hp_vals.append(poke.hp)
                status_ids.append(v.status[poke.status] if poke.status else 0)
                boosts.append([poke.boosts.get(s, 0) for s in BOOST_STATS])
                item_ids.append(v.items[poke.item] if poke.item else 0)
                ability_ids.append(v.abilities[poke.ability] if poke.ability else 0)
                mega_flags.append(int(poke.mega)); alive_flags.append(1)
                ms = [v.moves[m] for m in poke.moves_known[:4]]
                ms += [0] * (4 - len(ms))
                move_ids.append(ms)

        tp = battle.team_preview
        own_team = tp.p1_team if player == "p1" else tp.p2_team
        opp_team = tp.p2_team if player == "p1" else tp.p1_team
        selected = (tp.p1_selected if player == "p1" else tp.p2_selected)[:4]
        oti = [v.species[s] for s in own_team[:6]] + [0] * max(0, 6 - len(own_team))
        opi = [v.species[s] for s in opp_team[:6]] + [0] * max(0, 6 - len(opp_team))
        si = [v.species[s] for s in selected[:4]] + [0] * max(0, 4 - len(selected))

        return {
            "species_ids": torch.tensor([species_ids], dtype=torch.long),
            "hp_values": torch.tensor([hp_vals], dtype=torch.float),
            "status_ids": torch.tensor([status_ids], dtype=torch.long),
            "boost_values": torch.tensor([boosts], dtype=torch.float),
            "item_ids": torch.tensor([item_ids], dtype=torch.long),
            "ability_ids": torch.tensor([ability_ids], dtype=torch.long),
            "mega_flags": torch.tensor([mega_flags], dtype=torch.float),
            "alive_flags": torch.tensor([alive_flags], dtype=torch.float),
            "move_ids": torch.tensor([move_ids], dtype=torch.long),
            "weather_id": torch.tensor([vocabs.weather[state.field.weather] if state.field.weather else 0], dtype=torch.long),
            "terrain_id": torch.tensor([vocabs.terrain[state.field.terrain] if state.field.terrain else 0], dtype=torch.long),
            "trick_room": torch.tensor([int(state.field.trick_room)], dtype=torch.float),
            "tailwind_own": torch.tensor([int(tw_own)], dtype=torch.float),
            "tailwind_opp": torch.tensor([int(tw_opp)], dtype=torch.float),
            "screens_own": torch.tensor([sc_own], dtype=torch.float),
            "screens_opp": torch.tensor([sc_opp], dtype=torch.float),
            "turn": torch.tensor([min(state.turn, 30)], dtype=torch.float),
            "action_mask_a": torch.tensor([[1]*MAX_ACTIONS], dtype=torch.bool),
            "action_mask_b": torch.tensor([[1]*MAX_ACTIONS], dtype=torch.bool),
            "own_team_ids": torch.tensor([oti[:6]], dtype=torch.long),
            "opp_team_ids": torch.tensor([opi[:6]], dtype=torch.long),
            "selected_ids": torch.tensor([si[:4]], dtype=torch.long),
            "has_team_preview": torch.tensor([True], dtype=torch.bool),
        }, own_active, own_bench, opp_active, opp_bench

    def _decode_action(idx, own_active, own_bench, slot_idx):
        if idx >= 12:
            bi = idx - 12
            return f"Switch → {own_bench[bi].species}" if bi < len(own_bench) else f"Switch → bench[{bi}]"
        mi, ti = idx // 3, idx % 3
        name = "?"
        if slot_idx < len(own_active):
            poke = own_active[slot_idx]
            name = poke.moves_known[mi] if mi < len(poke.moves_known) else f"Move {mi+1}"
        return f"{name} → {TARGET_NAMES[ti]}"

    def _encode_action(action, slot_idx, own_active, own_bench, player):
        if action is None: return 0
        if action.type == "switch":
            for i, p in enumerate(own_bench):
                base = lambda s: s.split("-Mega")[0] if "-Mega" in s else s
                if p.species == action.switch_to or base(p.species) == base(action.switch_to):
                    return 12 + min(i, 1)
            return 12
        if action.type == "move":
            if slot_idx < len(own_active) and action.move in own_active[slot_idx].moves_known:
                mi = own_active[slot_idx].moves_known.index(action.move)
            else:
                return -1  # move not in known list — can't encode, avoid false matches
            ti = 0
            if action.move not in SPREAD_MOVES and action.target:
                tp, ts = action.target[:2], action.target[2]
                ti = 2 if tp == player else (0 if ts == "a" else 1)
            return min(mi, 3) * 3 + min(ti, 2)
        return -1

    def _describe(action):
        if action is None: return "—"
        if action.type == "switch": return f"Switch → {action.switch_to}"
        if action.type == "move":
            t = f" → {action.target}" if action.target else ""
            m = " (Mega)" if action.mega else ""
            return f"{action.move}{t}{m}"
        return "?"

    turns = []
    match_a = match_b = total_a = total_b = 0

    for sample in winner_samples:
        player = sample.player
        try:
            batch, own_active, own_bench, opp_active, opp_bench = _encode_sample(sample, result)
            batch_dev = {k: v.to(device) for k, v in batch.items()}
            with torch.no_grad():
                out = model(batch_dev)
            probs_a = F.softmax(out["logits_a"][0], dim=-1).cpu()
            probs_b = F.softmax(out["logits_b"][0], dim=-1).cpu()
        except Exception:
            continue

        def top3(probs, slot_idx):
            vals, idxs = probs.topk(min(3, len(probs)))
            return [{"action": _decode_action(idx.item(), own_active, own_bench, slot_idx),
                     "prob": round(val.item() * 100, 1), "idx": idx.item()}
                    for val, idx in zip(vals, idxs)]

        preds_a, preds_b = top3(probs_a, 0), top3(probs_b, 1)
        act_a, act_b = sample.actions.slot_a, sample.actions.slot_b
        aidx_a = _encode_action(act_a, 0, own_active, own_bench, player)
        aidx_b = _encode_action(act_b, 1, own_active, own_bench, player)
        ma = preds_a[0]["idx"] == aidx_a if (preds_a and aidx_a >= 0) else False
        mb = preds_b[0]["idx"] == aidx_b if (preds_b and aidx_b >= 0) else False
        if act_a is not None and aidx_a >= 0: total_a += 1; match_a += int(ma)
        if act_b is not None and aidx_b >= 0: total_b += 1; match_b += int(mb)

        state = sample.state
        field_conds = []
        if state.field.weather: field_conds.append(state.field.weather)
        if state.field.terrain: field_conds.append(f"{state.field.terrain} Terrain")
        if state.field.trick_room: field_conds.append("Trick Room")
        tw_own = state.field.tailwind_p1 if player == "p1" else state.field.tailwind_p2
        tw_opp = state.field.tailwind_p2 if player == "p1" else state.field.tailwind_p1
        if tw_own: field_conds.append("Own Tailwind")
        if tw_opp: field_conds.append("Opp Tailwind")

        turns.append({
            "turn": state.turn,
            "own_active": [{"species": p.species, "hp": round(p.hp*100, 1), "status": p.status} for p in own_active],
            "opp_active": [{"species": p.species, "hp": round(p.hp*100, 1), "status": p.status} for p in opp_active],
            "own_bench": [{"species": p.species, "hp": round(p.hp*100, 1)} for p in own_bench],
            "opp_bench": [{"species": p.species, "hp": round(p.hp*100, 1)} for p in opp_bench],
            "field": field_conds,
            "slot_a": {"actual": _describe(act_a), "actual_idx": aidx_a, "predictions": preds_a, "match": ma},
            "slot_b": {"actual": _describe(act_b), "actual_idx": aidx_b, "predictions": preds_b, "match": mb},
        })

    total = total_a + total_b
    matches = match_a + match_b
    return {
        "id": data.get("id", replay_path.stem),
        "players": data.get("players", []),
        "rating": rating,
        "winner": result.winner,
        "total_turns": len(turns),
        "accuracy": round(matches / total * 100, 1) if total > 0 else 0,
        "matches": matches,
        "total_actions": total,
        "turns": turns,
    }


@app.get("/api/model/status")
async def model_status():
    """Check if model is available and return checkpoint info."""
    has_checkpoint = CHECKPOINT_PATH.exists()
    has_vocabs = VOCAB_DIR.exists() and (VOCAB_DIR / "species.json").exists()
    loaded = _model_state["loaded"] and _model_state["error"] is None
    return {
        "has_checkpoint": has_checkpoint,
        "has_vocabs": has_vocabs,
        "loaded": loaded,
        "error": _model_state.get("error"),
        "checkpoint_info": _model_state.get("checkpoint_info"),
        "cached_replays": len(_review_cache),
    }


@app.get("/api/model/analyze")
async def model_analyze(count: int = 20, min_rating: int = 0):
    """Analyze random replays. Results are cached."""
    if not _ensure_model():
        return JSONResponse({"error": _model_state["error"]}, 500)

    # Find replay files
    replay_files = []
    for d in MODEL_REPLAY_DIRS:
        if d.exists():
            replay_files.extend(f for f in d.glob("*.json") if f.name != "index.json")

    if not replay_files:
        return JSONResponse({"error": "No replay files found"}, 404)

    # Filter by rating if requested
    if min_rating > 0:
        filtered = []
        for f in replay_files:
            try:
                d = json.loads(f.read_text(errors="replace"))
                if (d.get("rating") or 0) >= min_rating:
                    filtered.append(f)
            except Exception:
                pass
        replay_files = filtered

    # Sample and analyze
    sample_files = random.sample(replay_files, min(count, len(replay_files)))
    new_results = 0
    for f in sample_files:
        rid = f.stem
        if rid not in _review_cache:
            result = _analyze_replay(f)
            if result:
                _review_cache[result["id"]] = result
                new_results += 1

    return {"analyzed": new_results, "total_cached": len(_review_cache)}


@app.get("/api/model/replays")
async def model_replays():
    """List all cached replay analyses."""
    return [
        {"id": rid, "accuracy": r["accuracy"], "rating": r["rating"],
         "players": r["players"], "total_turns": r["total_turns"], "winner": r["winner"]}
        for rid, r in sorted(_review_cache.items(), key=lambda x: x[1]["rating"] or 0, reverse=True)
    ]


@app.get("/api/model/replay/{replay_id}")
async def model_replay(replay_id: str):
    """Get full turn-by-turn analysis for one replay."""
    if replay_id in _review_cache:
        return _review_cache[replay_id]
    return JSONResponse({"error": "Replay not analyzed yet"}, 404)


@app.get("/api/model/summary")
async def model_summary():
    """Aggregate accuracy stats across cached replays."""
    if not _review_cache:
        return {"total_replays": 0, "avg_accuracy": 0, "total_turns": 0, "total_matches": 0, "total_actions": 0}
    total_matches = sum(r["matches"] for r in _review_cache.values())
    total_actions = sum(r["total_actions"] for r in _review_cache.values())
    return {
        "total_replays": len(_review_cache),
        "avg_accuracy": round(total_matches / total_actions * 100, 1) if total_actions > 0 else 0,
        "total_turns": sum(r["total_turns"] for r in _review_cache.values()),
        "total_matches": total_matches,
        "total_actions": total_actions,
    }


@app.post("/api/model/clear")
async def model_clear():
    """Clear the analysis cache."""
    _review_cache.clear()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING PROGRESS API
# ═══════════════════════════════════════════════════════════════════════════

TRAINING_DIR = BASE / "data" / "training_sessions"

_training_sessions: dict[str, dict] = {}  # session_id -> {meta + epochs: [...]}


def _load_training_sessions():
    """Load persisted sessions from disk on startup."""
    if not TRAINING_DIR.exists():
        return
    for f in TRAINING_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            _training_sessions[data["session_id"]] = data
        except Exception:
            pass


def _save_session(session_id: str):
    """Persist a session to disk."""
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    data = _training_sessions.get(session_id)
    if data:
        (TRAINING_DIR / f"{session_id}.json").write_text(json.dumps(data))


_load_training_sessions()


@app.post("/api/training/report")
async def training_report(request: Request):
    """Receive epoch metrics from a training process."""
    payload = await request.json()
    sid = payload.get("session_id", "unknown")

    if sid not in _training_sessions:
        _training_sessions[sid] = {
            "session_id": sid,
            "machine": payload.get("machine", "?"),
            "model_version": payload.get("model_version", "?"),
            "config": payload.get("config", {}),
            "started": payload.get("timestamp", time.time()),
            "epochs": [],
        }

    session = _training_sessions[sid]
    session["last_update"] = payload.get("timestamp", time.time())
    session["epochs"].append({
        "epoch": payload.get("epoch"),
        "total_epochs": payload.get("total_epochs"),
        "train_loss": payload.get("train_loss"),
        "val_loss": payload.get("val_loss"),
        "train_top1": payload.get("train_top1"),
        "val_top1": payload.get("val_top1"),
        "train_top3": payload.get("train_top3"),
        "val_top3": payload.get("val_top3"),
        "team_acc": payload.get("team_acc"),
        "lead_acc": payload.get("lead_acc"),
        "lr": payload.get("lr"),
        "best_val_loss": payload.get("best_val_loss"),
        "timestamp": payload.get("timestamp"),
    })

    _save_session(sid)
    return {"ok": True}


@app.get("/api/training/sessions")
async def training_sessions():
    """List all training sessions."""
    now = time.time()
    return [
        {
            "session_id": s["session_id"],
            "machine": s.get("machine", "?"),
            "model_version": s.get("model_version", "?"),
            "config": s.get("config", {}),
            "started": s.get("started"),
            "last_update": s.get("last_update"),
            "current_epoch": s["epochs"][-1]["epoch"] if s["epochs"] else 0,
            "total_epochs": s["epochs"][-1]["total_epochs"] if s["epochs"] else 0,
            "latest_val_loss": s["epochs"][-1]["val_loss"] if s["epochs"] else None,
            "latest_val_top1": s["epochs"][-1]["val_top1"] if s["epochs"] else None,
            "best_val_loss": s["epochs"][-1]["best_val_loss"] if s["epochs"] else None,
            "active": (now - s.get("last_update", 0)) < 300,  # active if updated in last 5min
            "num_epochs": len(s["epochs"]),
        }
        for s in sorted(_training_sessions.values(), key=lambda x: x.get("last_update", 0), reverse=True)
    ]


@app.get("/api/training/session/{session_id}")
async def training_session(session_id: str):
    """Get full epoch history for one session."""
    if session_id in _training_sessions:
        return _training_sessions[session_id]
    return JSONResponse({"error": "Session not found"}, 404)


@app.delete("/api/training/session/{session_id}")
async def training_delete(session_id: str):
    """Delete a training session."""
    if session_id in _training_sessions:
        del _training_sessions[session_id]
        f = TRAINING_DIR / f"{session_id}.json"
        if f.exists():
            f.unlink()
        return {"ok": True}
    return JSONResponse({"error": "Session not found"}, 404)


# ═══════════════════════════════════════════════════════════════════════════
# OCR SUGGESTION (proxy to local Mac dev runner — tools/mac_dev_runner.py)
# ═══════════════════════════════════════════════════════════════════════════

DEV_RUNNER = os.environ.get("DEV_RUNNER", "http://localhost:9876")


@app.post("/api/ocr/suggest")
async def ocr_suggest(request: Request):
    """Proxy OCR suggestion request to the local Mac dev runner.

    Body: { "screen": "move_select_singles", "filename": "20260423-145958889700.png", "reader": "MoveNameReader" }
    Reads the image from test_images, base64-encodes it, sends to the dev runner.
    """
    import base64
    import urllib.request
    import urllib.error

    body = await request.json()
    screen = body.get("screen", "")
    filename = body.get("filename", "")
    reader = body.get("reader", "")

    if not screen or not filename or not reader:
        return JSONResponse({"error": "screen, filename, and reader required"}, 400)

    img_path = TEST_IMAGES_DIR / screen / filename
    if not img_path.exists():
        return JSONResponse({"error": "image not found"}, 404)

    img_b64 = base64.b64encode(img_path.read_bytes()).decode()

    payload = json.dumps({
        "image_base64": img_b64,
        "reader": reader,
        "screen": screen,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{DEV_RUNNER}/ocr-suggest",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.URLError as e:
        return JSONResponse({"error": f"dev runner unreachable: {e}"}, 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/api/detector/debug")
async def detector_debug(request: Request):
    """Run all detectors on an image via the dev runner, return debug info."""
    import base64
    import urllib.request
    import urllib.error

    body = await request.json()
    screen = body.get("screen", "")
    filename = body.get("filename", "")

    if not screen or not filename:
        return JSONResponse({"error": "screen and filename required"}, 400)

    img_path = TEST_IMAGES_DIR / screen / filename
    if not img_path.exists():
        return JSONResponse({"error": "image not found"}, 404)

    img_b64 = base64.b64encode(img_path.read_bytes()).decode()
    payload = json.dumps({"image_base64": img_b64}).encode()

    try:
        req = urllib.request.Request(
            f"{DEV_RUNNER}/detector-debug",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return JSONResponse({"error": f"dev runner unreachable: {e}"}, 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/api/inspector/ocr-crop")
async def inspector_ocr_crop(request: Request):
    """Run number-tuned OCR on an arbitrary box of an image.

    Used by the Inspector "Test OCR" button to iterate on box coords without
    rebuilding. Body must include either {source, filename} or {image_base64}
    plus the box coords {x, y, w, h} (normalized floats).
    """
    import base64
    import urllib.request
    import urllib.error

    body = await request.json()
    img_b64 = body.get("image_base64")
    if not img_b64:
        # Resolve from labeler source paths.
        source = body.get("source", "").strip("/")
        filename = body.get("filename", "")
        if not source or not filename:
            return JSONResponse({"error": "image_base64 OR (source+filename) required"}, 400)
        # Source paths are relative to the project root (BASE).
        img_path = (BASE / source / filename).resolve()
        try:
            img_path.relative_to(BASE.resolve())
        except ValueError:
            return JSONResponse({"error": "source path outside project"}, 400)
        if not img_path.exists():
            return JSONResponse({"error": f"image not found: {img_path}"}, 404)
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()

    payload = json.dumps({
        "image_base64": img_b64,
        "x": body.get("x"), "y": body.get("y"),
        "w": body.get("w"), "h": body.get("h"),
    }).encode()
    try:
        req = urllib.request.Request(
            f"{DEV_RUNNER}/ocr-crop",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return JSONResponse({"error": f"dev runner unreachable: {e}"}, 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/api/detector/debug-batch")
async def detector_debug_batch(request: Request):
    """Run detectors on all images in a screen via the dev runner batch endpoint."""
    import urllib.request
    import urllib.error

    body = await request.json()
    screen = body.get("screen", "")
    if not screen:
        return JSONResponse({"error": "screen required"}, 400)

    payload = json.dumps({"screen": screen}).encode()
    try:
        req = urllib.request.Request(
            f"{DEV_RUNNER}/detector-debug-batch",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return JSONResponse({"error": f"dev runner unreachable: {e}"}, 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.post("/api/ocr/suggest-bulk")
async def ocr_suggest_bulk(request: Request):
    """Run OCR suggestions for all unlabeled images in a screen directory."""
    import base64
    import urllib.request
    import urllib.error

    body = await request.json()
    screen = body.get("screen", "")
    reader = body.get("reader", "")

    if not screen or not reader:
        return JSONResponse({"error": "screen and reader required"}, 400)

    screen_dir = TEST_IMAGES_DIR / screen
    if not screen_dir.exists():
        return JSONResponse({"error": "screen not found"}, 404)

    manifest = _load_manifest(screen_dir)

    # Build the work list: unlabeled-for-this-reader, real images only.
    targets = []
    for f in sorted(screen_dir.glob("*.png")):
        if f.name.startswith("_") or f.name.startswith("."):
            continue
        if reader in manifest.get(f.name, {}):
            continue
        targets.append(f)

    def _suggest_one(path: Path):
        try:
            img_b64 = base64.b64encode(path.read_bytes()).decode()
            payload = json.dumps({
                "image_base64": img_b64,
                "reader": reader,
                "screen": screen,
            }).encode()
            req = urllib.request.Request(
                f"{DEV_RUNNER}/ocr-suggest",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            if result.get("ok"):
                return path.name, result.get("result", {}), None
            return path.name, None, result.get("error", "unknown")
        except Exception as e:
            return path.name, None, str(e)

    # Run in parallel — the C++ OCR binary is single-threaded per call,
    # but multiple concurrent subprocesses share the CPU well up to ~8.
    results = {}
    errors = []
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = [loop.run_in_executor(pool, _suggest_one, f) for f in targets]
        for fname, result, err in await asyncio.gather(*tasks):
            if result is not None:
                results[fname] = result
            elif err is not None:
                errors.append({"filename": fname, "error": err})

    return {"ok": True, "suggested": len(results), "results": results, "errors": errors}


# ── Mismatches API ──
#
# Compare labeled ground-truth (manifest.json) against current reader output
# across all labeled screens. Surfaces "label says X, reader returned Y" rows
# so the user can either fix the label (Accept got) or fix the reader/box
# (open in inspector).

#  In-memory cache: (screen, filename, reader, mtime) -> result dict
_MISMATCH_CACHE: dict = {}

#  Readers we know how to run via OcrSuggest. Anything else is skipped.
_SUGGEST_READERS = {
    "BattleHUDReader",
    "MoveNameReader",
    "BattleLogReader",
    "TeamSelectReader",
    "TeamSummaryReader",
    "TeamPreviewReader",
}


def _suggest_via_runner(screen: str, filename: str, reader: str):
    """Synchronous helper: ask the dev runner for one reader's output on one image.
    Returns (result_dict | None, error_str | None)."""
    import base64
    import urllib.request
    import urllib.error
    img_path = TEST_IMAGES_DIR / screen / filename
    if not img_path.exists():
        return None, "image not found"
    mtime = img_path.stat().st_mtime
    key = (screen, filename, reader, mtime)
    if key in _MISMATCH_CACHE:
        return _MISMATCH_CACHE[key], None
    try:
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        payload = json.dumps({
            "image_base64": img_b64,
            "reader": reader,
            "screen": screen,
        }).encode()
        req = urllib.request.Request(
            f"{DEV_RUNNER}/ocr-suggest",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            envelope = json.loads(resp.read())
        if not envelope.get("ok"):
            return None, envelope.get("error", "unknown")
        result = envelope.get("result", {}) or {}
        _MISMATCH_CACHE[key] = result
        return result, None
    except urllib.error.URLError as e:
        return None, f"dev runner unreachable: {e}"
    except Exception as e:
        return None, str(e)


def _is_absent(v) -> bool:
    """Treat empty string and -1 as the universal "no label" sentinel."""
    return v == "" or v == -1 or v is None


def _coerce_pair(expected, got):
    """Normalize values for comparison. Strings are case-folded; ints stay ints."""
    if isinstance(expected, str) and isinstance(got, str):
        return expected.strip().lower(), got.strip().lower()
    return expected, got


@app.get("/api/mismatches")
async def mismatches(screen: Optional[str] = None, reader: Optional[str] = None):
    """Find label-vs-reader disagreements across all labeled images.

    Query params:
      screen: optional filter (e.g. "move_select").
      reader: optional filter (e.g. "BattleHUDReader").
    """
    config = _load_screens_yaml()
    screens = config.get("screens", {})
    overlays = {f"_overlays/{k}": v for k, v in config.get("overlays", {}).items()}
    all_screens = {**screens, **overlays}

    targets = []
    for name in all_screens.keys():
        if screen and name != screen:
            continue
        screen_dir = TEST_IMAGES_DIR / name
        if not screen_dir.exists():
            continue
        manifest = _load_manifest(screen_dir)
        for fname, labels in manifest.items():
            for rname, fields in (labels or {}).items():
                if rname not in _SUGGEST_READERS:
                    continue
                if reader and rname != reader:
                    continue
                if not isinstance(fields, dict):
                    continue
                targets.append((name, fname, rname, fields))

    def _process_one(t):
        s, fname, rname, fields = t
        result, err = _suggest_via_runner(s, fname, rname)
        if err is not None or result is None:
            return []
        rows = []
        for field, expected_val in fields.items():
            got_val = result.get(field)
            if got_val is None:
                continue
            if isinstance(expected_val, list) and isinstance(got_val, list):
                for i in range(min(len(expected_val), len(got_val))):
                    e = expected_val[i]
                    g = got_val[i]
                    if _is_absent(e):
                        continue
                    e_cmp, g_cmp = _coerce_pair(e, g)
                    if e_cmp != g_cmp:
                        rows.append({
                            "screen": s,
                            "filename": fname,
                            "reader": rname,
                            "field": field,
                            "slot": i,
                            "expected": e,
                            "got": g,
                        })
            else:
                if _is_absent(expected_val):
                    continue
                e_cmp, g_cmp = _coerce_pair(expected_val, got_val)
                if e_cmp != g_cmp:
                    rows.append({
                        "screen": s,
                        "filename": fname,
                        "reader": rname,
                        "field": field,
                        "slot": None,
                        "expected": expected_val,
                        "got": got_val,
                    })
        return rows

    rows = []
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = [loop.run_in_executor(pool, _process_one, t) for t in targets]
        for batch in await asyncio.gather(*tasks):
            rows.extend(batch)

    rows.sort(key=lambda r: (r["screen"], r["filename"], r["reader"], r["field"], r["slot"] or 0))
    return {"ok": True, "rows": rows, "scanned": len(targets)}


@app.post("/api/mismatches/swap-slots")
async def mismatches_swap_slots(request: Request):
    """Swap slot 0 ↔ slot 1 for every length-2 array field of one reader on one image.

    Body: { screen, filename, reader }
    Useful when ground-truth was hand-typed with slots transposed (e.g. left/right
    confusion in doubles).
    """
    body = await request.json()
    screen = body.get("screen")
    filename = body.get("filename")
    reader = body.get("reader")
    if not all([screen, filename, reader]):
        return JSONResponse({"error": "screen, filename, reader required"}, 400)

    screen_dir = TEST_IMAGES_DIR / screen
    manifest_path = screen_dir / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse({"error": "manifest not found"}, 404)

    manifest = _load_manifest(screen_dir)
    entry = manifest.get(filename, {}).get(reader)
    if not isinstance(entry, dict):
        return JSONResponse({"error": "no labels for that reader on that image"}, 404)

    swapped = 0
    for field, val in entry.items():
        if isinstance(val, list) and len(val) == 2:
            val[0], val[1] = val[1], val[0]
            swapped += 1

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    img_path = screen_dir / filename
    if img_path.exists():
        mtime = img_path.stat().st_mtime
        _MISMATCH_CACHE.pop((screen, filename, reader, mtime), None)
    return {"ok": True, "fields_swapped": swapped}


@app.post("/api/mismatches/accept")
async def mismatches_accept(request: Request):
    """Patch a single field/slot in a manifest to accept the reader's output.

    Body: { screen, filename, reader, field, slot|null, value }
    """
    body = await request.json()
    screen = body.get("screen")
    filename = body.get("filename")
    reader = body.get("reader")
    field = body.get("field")
    slot = body.get("slot")
    value = body.get("value")

    if not all([screen, filename, reader, field]):
        return JSONResponse({"error": "screen, filename, reader, field required"}, 400)

    screen_dir = TEST_IMAGES_DIR / screen
    manifest_path = screen_dir / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse({"error": "manifest not found"}, 404)

    manifest = _load_manifest(screen_dir)
    entry = manifest.setdefault(filename, {}).setdefault(reader, {})
    current = entry.get(field)

    if slot is None:
        entry[field] = value
    else:
        if not isinstance(current, list):
            current = ["", ""] if isinstance(value, str) else [-1, -1]
        if slot >= len(current):
            return JSONResponse({"error": "slot out of range"}, 400)
        current[slot] = value
        entry[field] = current

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    #  Bust the cache for this image so the row doesn't re-appear.
    img_path = screen_dir / filename
    if img_path.exists():
        mtime = img_path.stat().st_mtime
        _MISMATCH_CACHE.pop((screen, filename, reader, mtime), None)
    return {"ok": True}


# ── Validation API ──

@app.get("/api/validation/summary")
async def validation_summary():
    """Per-screen completion stats and schema validation."""
    config = _load_screens_yaml()
    screens = config.get("screens", {})
    overlays = config.get("overlays", {})

    result = []
    for name, defn in {**screens, **{f"_overlays/{k}": v for k, v in overlays.items()}}.items():
        screen_dir = TEST_IMAGES_DIR / name
        if not screen_dir.exists():
            continue

        readers = defn.get("readers", {})
        images = [f for f in screen_dir.glob("*.png") if _is_real_image(f.name)]
        manifest = _load_manifest(screen_dir)

        total = len(images)
        labeled = 0
        partial = 0
        unlabeled = 0
        errors = []

        for f in images:
            entry = manifest.get(f.name, {})
            if not entry:
                unlabeled += 1
                continue
            # Check completeness
            expected_readers = set(readers.keys())
            present_readers = set(entry.keys())
            if expected_readers <= present_readers:
                labeled += 1
            else:
                partial += 1
                missing = expected_readers - present_readers
                errors.append({"filename": f.name, "missing_readers": list(missing)})

            # Type validation
            for rname, rdef in readers.items():
                if rname not in entry:
                    continue
                fields = rdef.get("fields", {})
                for fname, fdef in fields.items():
                    val = entry[rname].get(fname)
                    if val is None:
                        continue
                    if fdef.get("type") == "array":
                        if not isinstance(val, list):
                            errors.append({"filename": f.name, "reader": rname, "field": fname, "error": "expected array"})
                        elif fdef.get("length") and len(val) != fdef["length"]:
                            errors.append({"filename": f.name, "reader": rname, "field": fname, "error": f"expected length {fdef['length']}, got {len(val)}"})

        result.append({
            "screen": name,
            "total": total,
            "labeled": labeled,
            "partial": partial,
            "unlabeled": unlabeled,
            "errors": errors[:20],  # cap to avoid huge responses
        })

    return result


# ═══════════════════════════════════════════════════════════════════════════
# REPLAY SYNC (ash → unraid container volume)
# ═══════════════════════════════════════════════════════════════════════════
#
# Sync target switched from ColePC (Windows) to unraid (Linux container volume)
# to make the unraid pokemon-champions-gpu container the canonical training
# rig. The unraid host has the workspace at /mnt/user/data/pokemon-champions
# which is mounted into the container as /workspace.

SYNC_HOST = os.environ.get("SYNC_HOST", "unraid")
SYNC_REPLAY_DIR = os.environ.get(
    "SYNC_REPLAY_DIR",
    "/mnt/user/data/pokemon-champions/data/replays",
)

_sync_state: dict = {
    "running": False,
    "last_run": None,
    "last_result": None,
    "last_error": None,
    "formats_synced": {},
}


async def _run_sync_index() -> dict:
    """Index sync is obsolete with the bucketed layout.

    The legacy preparse pipeline relied on a flat index.json mapping replay_id
    -> rating to filter at training time. Layer 1 parquet (Phase 3) records
    rating per row, so the index isn't needed downstream.
    """
    return {"skipped": True, "reason": "obsolete with bucketed layout"}


async def _run_sync_format(fmt_id: str, sources: list[Path]) -> dict:
    """Sync one format's bucketed replays from ash to the configured remote.

    Source layout: data/replays/<fmt>/YYYY-MM-DD/HH/<id>.json (bucketed).
    rsync -a recurses the date/hour subtree natively. --ignore-existing skips
    files already on the remote without checksumming (replay JSONs are
    immutable, so no checksum needed).
    """
    src_dir = BUCKETED_REPLAY_DIR / fmt_id
    if not src_dir.exists():
        return {"format": fmt_id, "local": 0, "synced": 0, "skipped": True}

    remote_dir = f"{SYNC_REPLAY_DIR}/{fmt_id}"
    proc = await asyncio.create_subprocess_exec(
        "ssh", SYNC_HOST, f'mkdir -p "{remote_dir}"',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    proc = await asyncio.create_subprocess_exec(
        "rsync",
        "-a",
        "--ignore-existing",
        "--info=stats2",
        f"{src_dir.as_posix()}/",
        f"{SYNC_HOST}:{remote_dir}/",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"rsync {src_dir} -> {SYNC_HOST}:{remote_dir} failed: "
            f"{stderr.decode(errors='replace')[-500:]}"
        )

    transferred = 0
    last_stats = ""
    for line in stdout.decode(errors="replace").splitlines():
        if "regular files transferred" in line.lower():
            try:
                transferred += int(line.rsplit(":", 1)[1].strip().replace(",", ""))
            except (ValueError, IndexError):
                pass
            last_stats = line.strip()

    return {
        "format": fmt_id,
        "synced": transferred,
        "stats": last_stats,
    }


@app.post("/api/sync/trigger")
async def sync_trigger(request: Request):
    """Trigger replay sync from ash to ColePC."""
    if _sync_state["running"]:
        return JSONResponse({"error": "Sync already in progress"}, 409)

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    formats = body.get("formats", list(FORMATS.keys()))

    _sync_state["running"] = True
    _sync_state["last_error"] = None

    try:
        # Check sync host is reachable
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
            SYNC_HOST, "echo ok",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0 or b"ok" not in stdout:
            _sync_state["running"] = False
            _sync_state["last_error"] = f"{SYNC_HOST} unreachable"
            return JSONResponse({"error": f"{SYNC_HOST} unreachable — is it on?"}, 503)

        # Ensure remote dirs exist (Linux mkdir -p)
        for fmt_id in formats:
            remote_dir = f"{SYNC_REPLAY_DIR}/{fmt_id}"
            await asyncio.create_subprocess_exec(
                "ssh", SYNC_HOST, f'mkdir -p "{remote_dir}"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        results = {}
        for fmt_id in formats:
            results[fmt_id] = await _run_sync_format(fmt_id, [])

        index_result = await _run_sync_index()

        total_synced = sum(r["synced"] for r in results.values())
        _sync_state["last_run"] = time.time()
        _sync_state["last_result"] = {
            "timestamp": time.time(),
            "formats": results,
            "total_synced": total_synced,
            "index": index_result,
        }
        _sync_state["formats_synced"] = results
        return {"ok": True, "total_synced": total_synced, "formats": results, "index": index_result}

    except Exception as e:
        _sync_state["last_error"] = str(e)
        return JSONResponse({"error": str(e)}, 500)
    finally:
        _sync_state["running"] = False


@app.get("/api/sync/status")
async def sync_status():
    """Get current sync status."""
    # Quick check if sync host is reachable (non-blocking, cached for 60s)
    reachable = None
    if not _sync_state["running"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes",
                SYNC_HOST, "echo ok",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            reachable = b"ok" in stdout
        except Exception:
            reachable = False

    return {
        "running": _sync_state["running"],
        "sync_host_reachable": reachable,
        "sync_host": SYNC_HOST,
        "last_run": _sync_state["last_run"],
        "last_result": _sync_state["last_result"],
        "last_error": _sync_state["last_error"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# REGRESSION RESULTS
# ═══════════════════════════════════════════════════════════════════════════

REGRESSION_RESULTS_PATH = BASE / "tools" / "regression_results.json"


@app.get("/api/regression/results")
async def regression_results():
    """Return the last regression run results (from tools/retest.py)."""
    if not REGRESSION_RESULTS_PATH.exists():
        return {"timestamp": None, "total": 0, "passed": 0, "results": {}}
    try:
        data = json.loads(REGRESSION_RESULTS_PATH.read_text())
        return data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/regression/summary")
async def regression_summary():
    """Summarized regression results grouped by reader."""
    if not REGRESSION_RESULTS_PATH.exists():
        return {"timestamp": None, "readers": {}}
    try:
        data = json.loads(REGRESSION_RESULTS_PATH.read_text())
        by_reader: dict[str, dict] = {}
        for fname, r in data.get("results", {}).items():
            rdr = r.get("reader", "unknown")
            if rdr not in by_reader:
                by_reader[rdr] = {"passed": 0, "failed": 0, "failures": []}
            if r.get("passed"):
                by_reader[rdr]["passed"] += 1
            else:
                by_reader[rdr]["failed"] += 1
                by_reader[rdr]["failures"].append({
                    "filename": fname,
                    "actual": r.get("actual", ""),
                    "expected": r.get("expected", ""),
                })
        return {"timestamp": data.get("timestamp"), "readers": by_reader}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════════
# DIGIT TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════

DIGIT_TEMPLATES_DIR = RESOURCES_DIR / "DigitTemplates"


@app.get("/api/templates/list")
async def templates_list():
    """List all digit templates (0-9)."""
    templates = []
    if DIGIT_TEMPLATES_DIR.exists():
        for f in sorted(DIGIT_TEMPLATES_DIR.iterdir()):
            if f.suffix == ".png":
                templates.append({"digit": f.stem, "filename": f.name})
    return {"templates": templates}


@app.get("/api/templates/image/{digit}")
async def templates_image(digit: str):
    """Serve a digit template PNG."""
    path = DIGIT_TEMPLATES_DIR / f"{digit}.png"
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(content=path.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@app.post("/api/templates/save")
async def templates_save(digit: str = Form(...), png_base64: str = Form(...)):
    """Save a digit template PNG."""
    import base64
    DIGIT_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(png_base64)
    path = DIGIT_TEMPLATES_DIR / f"{digit}.png"
    path.write_bytes(data)
    return {"ok": True, "digit": digit}


@app.delete("/api/templates/{digit}")
async def templates_delete(digit: str):
    """Delete a digit template."""
    path = DIGIT_TEMPLATES_DIR / f"{digit}.png"
    if path.exists():
        path.unlink()
        return {"ok": True}
    return JSONResponse({"error": "not found"}, status_code=404)


# ═══════════════════════════════════════════════════════════════════════════
# SPA SHELL
# ═══════════════════════════════════════════════════════════════════════════

_INCLUDE_RE = re.compile(r"\{\{include\s+([^\s}]+)\s*\}\}")


def _render_index() -> str:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return "<h1>Dashboard not deployed yet</h1>"
    html = index_path.read_text()

    def _sub(m):
        rel = m.group(1)
        target = STATIC_DIR / rel
        try:
            target.resolve().relative_to(STATIC_DIR.resolve())
        except ValueError:
            return f"<!-- include rejected: {rel} -->"
        if not target.exists():
            return f"<!-- include missing: {rel} -->"
        return target.read_text()

    return _INCLUDE_RE.sub(_sub, html)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_render_index())
