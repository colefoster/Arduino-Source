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

import io
import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent.parent
REPLAY_BASE = BASE / "data" / "showdown_replays"
SPECTATED_DIR = REPLAY_BASE / "spectated"
DOWNLOADED_DIR = REPLAY_BASE / "downloaded"
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
    "SpeciesReader": [
        {"name": "opp_species", "box": [0.830, 0.052, 0.087, 0.032]},
    ],
    "OpponentHPReader": [
        {"name": "opp_hp_pct", "box": [0.8963, 0.1098, 0.0498, 0.0524]},
    ],
    "OpponentHPReader_Doubles": [
        {"name": "opp0_hp_pct", "box": [0.694, 0.116, 0.041, 0.038]},
    ],
    "SpeciesReader_Doubles": [
        {"name": "opp0_species", "box": [0.6172, 0.0454, 0.1219, 0.0417]},
        {"name": "opp1_species", "box": [0.8286, 0.0481, 0.1151, 0.0417]},
    ],
    "MoveSelectCursorSlot": [
        {"name": f"pill_{i}", "box": [0.7292, y, 0.0101, 0.0139]}
        for i, y in enumerate([0.5116, 0.6338, 0.7542, 0.8746])
    ],
    "MoveSelectDetector": [
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
    "TeamPreviewReader": [
        {"name": f"own_{i}", "box": [
            0.0760 + (i / 5.0) * (0.0724 - 0.0760),
            0.1565 + (i / 5.0) * (0.7389 - 0.1565),
            0.0969, 0.0389
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
}

BOOL_DETECTORS = {
    "MoveSelectDetector", "ActionMenuDetector", "PostMatchScreenDetector",
    "PreparingForBattleDetector", "TeamSelectDetector", "TeamPreviewDetector",
    "MainMenuDetector", "MovesMoreDetector",
}

BATTLE_LOG_EVENTS = [
    "MOVE_USED", "FAINTED", "SUPER_EFFECTIVE", "NOT_VERY_EFFECTIVE",
    "CRITICAL_HIT", "NO_EFFECT", "SENT_OUT", "WITHDREW", "STAT_CHANGE",
    "STATUS_INFLICTED", "WEATHER", "TERRAIN", "ABILITY_ACTIVATED",
    "ITEM_USED", "HEALED", "DAMAGED", "OTHER",
]

READER_TYPES = {}
for _r in BOOL_DETECTORS:
    READER_TYPES[_r] = "bool"
READER_TYPES.update({
    "MoveNameReader": "multi_text:4",
    "SpeciesReader": "text",
    "SpeciesReader_Doubles": "multi_text:2",
    "OpponentHPReader": "int:0:100",
    "OpponentHPReader_Doubles": "int:0:100",
    "MoveSelectCursorSlot": "int:0:3",
    "BattleLogReader": "event",
    "TeamSelectReader": "multi_text:6",
    "TeamSummaryReader": "multi_text:6",
    "TeamPreviewReader": "multi_text:6",
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

def _rating_buckets(ratings: list[int], step: int = 50) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for r in ratings:
        b = (r // step) * step
        buckets[str(b)] = buckets.get(str(b), 0) + 1
    return dict(sorted(buckets.items(), key=lambda x: int(x[0])))


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

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
    if reader_name in ("OpponentHPReader", "OpponentHPReader_Doubles", "MoveSelectCursorSlot"):
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
    if reader_name in ("SpeciesReader", "SpeciesReader_Doubles"):
        return {"type": "words", "values": [words[-1]], "raw": base}
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
        spec_files = _scan_dir(SPECTATED_DIR, fmt_id)
        dl_files = _scan_dir(DOWNLOADED_DIR, fmt_id)
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
        for f in _scan_dir(SPECTATED_DIR, fmt_id):
            age = now - f["mtime"]
            if age > 3600*48: continue
            idx = int(age / 3600)
            if 0 <= idx < 48: buckets[fmt_id][idx] += 1
    return {
        "bucket_size_sec": 3600,
        "labels": ["now"] + [f"{i}h ago" for i in range(1, 48)],
        "series": {fid: {"label": FORMATS[fid], "data": c} for fid, c in buckets.items()},
    }

@app.get("/api/ratings")
async def ratings():
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

@app.get("/api/recent")
async def recent(limit: int = 30):
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
            count = sum(1 for f in d.rglob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg"))
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
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg") or f.name.startswith("_"):
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


# ═══════════════════════════════════════════════════════════════════════════
# LABELER API
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/labeler/sources")
async def labeler_sources():
    sources = []
    if not REF_FRAMES_DIR.exists():
        return sources
    for vod_dir in sorted(REF_FRAMES_DIR.rglob("*")):
        if not vod_dir.is_dir(): continue
        imgs = [f for f in vod_dir.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")]
        if imgs:
            sources.append({
                "path": str(vod_dir.relative_to(REF_FRAMES_DIR)),
                "name": vod_dir.name, "parent": vod_dir.parent.name, "count": len(imgs),
            })
    return sources

@app.get("/api/labeler/images")
async def labeler_images(source: str, reader: str):
    src_dir = REF_FRAMES_DIR / source
    if not src_dir.exists(): return JSONResponse({"error": "source not found"}, 404)
    labels = _load_labels(source, reader)
    images = []
    for f in sorted(src_dir.iterdir()):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png"): continue
        label = labels.get(f.name)
        images.append({
            "filename": f.name, "labeled": label is not None,
            "skipped": label.get("type") == "skip" if label else False, "label": label,
        })
    return {"source": source, "reader": reader, "total": len(images),
            "labeled": sum(1 for i in images if i["labeled"]), "images": images}

@app.get("/api/labeler/frame/{path:path}")
async def labeler_frame(path: str, thumb: bool = False):
    full = REF_FRAMES_DIR / path
    if not full.exists(): return JSONResponse({"error": "not found"}, 404)
    if thumb:
        return Response(content=_make_thumbnail(full, 960, 540), media_type="image/jpeg")
    return Response(content=full.read_bytes(), media_type="image/png" if full.suffix == ".png" else "image/jpeg")

@app.get("/api/labeler/crops")
async def labeler_crops(source: str, filename: str, reader: str):
    import base64
    img_path = REF_FRAMES_DIR / source / filename
    if not img_path.exists(): return JSONResponse({"error": "not found"}, 404)
    return [
        {"name": cd["name"], "box": cd["box"],
         "data": f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, cd['box'])).decode()}"}
        for cd in CROP_DEFS.get(reader, [])
    ]

@app.post("/api/labeler/label")
async def labeler_save_label(source: str = Form(...), filename: str = Form(...),
                              reader: str = Form(...), label_json: str = Form(...)):
    labels = _load_labels(source, reader)
    labels[filename] = json.loads(label_json)
    _save_labels(source, reader, labels)
    return {"ok": True, "labeled": sum(1 for v in labels.values() if v.get("type") != "skip")}

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

@app.post("/api/inspector/analyze")
async def inspector_analyze(path: str = Form(...), x: float = Form(...),
                             y: float = Form(...), w: float = Form(...), h: float = Form(...)):
    from PIL import Image
    full = _resolve_image_path(path)
    if not full or not full.exists(): return JSONResponse({"error": "not found"}, 404)
    img = Image.open(full).convert("RGB")
    iw, ih = img.size
    x0, y0 = max(0, int(x*iw)), max(0, int(y*ih))
    x1, y1 = min(iw, x0+int(w*iw)), min(ih, y0+int(h*ih))
    pixels = list(img.crop((x0, y0, x1, y1)).getdata())
    n = len(pixels)
    if n == 0: return {"error": "empty region"}
    sr = sg = sb = sqr = sqg = sqb = 0
    for r, g, b in pixels:
        sr += r; sg += g; sb += b; sqr += r*r; sqg += g*g; sqb += b*b
    avg = (sr/n, sg/n, sb/n)
    if n > 1:
        sd = tuple(math.sqrt(max(0, (sq - s*s/n)/(n-1))) for s, sq in [(sr,sqr),(sg,sqg),(sb,sqb)])
    else:
        sd = (0, 0, 0)
    s = sum(avg)
    ratio = tuple(a/s for a in avg) if s > 0 else (0.333, 0.333, 0.333)
    return {
        "box": {"x": x, "y": y, "w": w, "h": h},
        "pixels": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "count": n},
        "avg": {"r": round(avg[0],2), "g": round(avg[1],2), "b": round(avg[2],2)},
        "stddev": {"r": round(sd[0],2), "g": round(sd[1],2), "b": round(sd[2],2)},
        "stddev_sum": round(sum(sd), 2),
        "ratio": {"r": round(ratio[0],4), "g": round(ratio[1],4), "b": round(ratio[2],4)},
        "brightness": round(s/3, 2),
        "cpp_box": f"ImageFloatBox({x:.4f}, {y:.4f}, {w:.4f}, {h:.4f})",
    }

@app.get("/api/inspector/boxes")
async def inspector_boxes():
    return CROP_DEFS

@app.get("/api/inspector/image/{path:path}")
async def inspector_image(path: str):
    full = _resolve_image_path(path)
    if not full or not full.exists(): return JSONResponse({"error": "not found"}, 404)
    return Response(content=full.read_bytes(), media_type="image/png" if full.suffix == ".png" else "image/jpeg")

def _resolve_image_path(path: str) -> Optional[Path]:
    for base in [TEST_IMAGES_DIR, REF_FRAMES_DIR]:
        full = base / path
        if full.exists(): return full
    return None


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
# SPA SHELL
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Dashboard not deployed yet</h1>")
