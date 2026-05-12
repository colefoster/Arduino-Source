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
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
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
RESOURCES_DIR = BASE / "switch_bot" / "Resources" / "PokemonChampions"
LABELS_DIR = BASE / "labels"

FORMATS = {
    "gen9championsvgc2026regma": "VGC 2026",
    "gen9championsbssregma": "BSS",
}

app = FastAPI(title="Pokemon Champions Dev Hub")

# When set, spectator-resident endpoints proxy to the host that runs the
# spectator (ash). Mac-local dashboard sets this; ash itself leaves it unset.
SPECTATOR_PROXY = os.environ.get("SPECTATOR_PROXY", "").rstrip("/")


async def _proxy_spectator(method: str, path: str, query: str = "", body: bytes | None = None) -> Response:
    """Proxy a request to SPECTATOR_PROXY and return a FastAPI Response."""
    import urllib.request
    import urllib.error
    url = f"{SPECTATOR_PROXY}{path}"
    if query:
        url = f"{url}?{query}"

    def _fetch():
        req = urllib.request.Request(url, method=method, data=body)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "application/json")
        except Exception as e:
            return 502, json.dumps({"error": f"spectator proxy: {e}"}).encode(), "application/json"

    status, payload, ctype = await _run_in_executor(_fetch)
    return Response(content=payload, status_code=status, media_type=ctype)

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
        {"name": "own0_hp",         "box": [0.1303, 0.9340, 0.0768, 0.0346]},
        {"name": "own1_hp",         "box": [0.3381, 0.9343, 0.0757, 0.0357]},
        #  Move-PP boxes — only present on move_select. Mirrors PP_X/PP_Y/
        #  PP_WIDTH/PP_HEIGHT in PokemonChampions_BattleHUDReader.cpp.
        {"name": "pp_0",            "box": [0.932, 0.508, 0.042, 0.043]},
        {"name": "pp_1",            "box": [0.932, 0.628, 0.042, 0.043]},
        {"name": "pp_2",            "box": [0.932, 0.749, 0.042, 0.043]},
        {"name": "pp_3",            "box": [0.932, 0.869, 0.042, 0.043]},
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
            0.8390, 0.1473 + i * ((0.7317 - 0.1473) / 5.0),
            0.0604, 0.0986
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
    #  Pokeball alive/fainted indicators. Extrapolated linearly from
    #  inspector-saved anchors:
    #    own_0 + own_3
    #    opp_0 + opp_1 + opp_3
    #  Own row: bottom-left at y~0.815, opp row: top-right at y~0.167.
    #  Alive = green/yellow ball, fainted = grey ball, empty = small grey dot.
    "PokeballAliveDetector": [
        {"name": "own_0", "box": [0.0518, 0.8155, 0.0085, 0.0155]},
        {"name": "own_1", "box": [0.0660, 0.8154, 0.0087, 0.0152]},
        {"name": "own_2", "box": [0.0801, 0.8152, 0.0090, 0.0149]},
        {"name": "own_3", "box": [0.0943, 0.8151, 0.0092, 0.0146]},
        {"name": "own_4", "box": [0.1085, 0.8150, 0.0094, 0.0143]},
        {"name": "own_5", "box": [0.1226, 0.8148, 0.0097, 0.0140]},
        {"name": "opp_0", "box": [0.8665, 0.1664, 0.0110, 0.0125]},
        {"name": "opp_1", "box": [0.8809, 0.1677, 0.0106, 0.0113]},
        {"name": "opp_2", "box": [0.8953, 0.1677, 0.0103, 0.0111]},
        {"name": "opp_3", "box": [0.9097, 0.1677, 0.0099, 0.0109]},
        {"name": "opp_4", "box": [0.9241, 0.1677, 0.0099, 0.0109]},
        {"name": "opp_5", "box": [0.9385, 0.1677, 0.0099, 0.0109]},
    ],
    #  Target Select (doubles): 4 potential targets (2 opp, 2 own).
    #  is_targeted = thin vertical strip whose color flips yellow/green
    #  (targeted) vs red/blue (not targeted). effectiveness = OCR'd label.
    #  move_name = OCR'd "currently selecting target for X" header per own
    #  active mon. own_1 move_name + own_0/own_1 effectiveness extrapolated
    #  from the user-drawn opp boxes (column x-delta = 0.2575; effectiveness
    #  y sits ~0.005 above is_targeted y, mirroring the opp pattern).
    #  Pokemon Switch screen (POKEMON menu reached from action_menu).
    #  Left column shows up to 6 own mons with HP fraction; right column
    #  shows opp mons with HP%. Center panel is Moves&More-style detail
    #  for the selected mon (already covered by TeamSummaryReader if needed).
    #
    #  Boxes are seeds — refine in inspector. Per-slot Y delta extrapolated
    #  from a visible-rows estimate (~0.144 between row tops).
    #  PokemonSwitchDetector co-evidence samples (mirrors C++ boxes in
    #  PokemonChampions_PokemonSwitchDetector.cpp). Two samples per tab
    #  (Moves & More left, Stats right). Accept iff exactly one tab is
    #  fully lime/yellow active and the other fully dark-blue inactive.
    "PokemonSwitchDetector": [
        {"name": "moves_left",  "box": [0.3977, 0.1079, 0.0221, 0.0273]},
        {"name": "moves_right", "box": [0.5137, 0.1136, 0.0198, 0.0258]},
        {"name": "stats_left",  "box": [0.5581, 0.1122, 0.0246, 0.0244]},
        {"name": "stats_right", "box": [0.6419, 0.1114, 0.0282, 0.0258]},
    ],
    "PokemonSwitchReader": [
        #  ── Doubles 4-row layout ───────────────────────────────────
        #  Own column (left). Per-row Y delta = 0.1185 (derived from user-
        #  drawn slot-0 + slot-2 anchors). HP text sits +0.0355 below species.
        #  Box width / height taken from user's slot-0 draws.
        *[{"name": f"doubles_own_{i}_species", "box": [0.0610, 0.2291 + i*0.1185, 0.0893, 0.0395]} for i in range(4)],
        *[{"name": f"doubles_own_{i}_hp_text", "box": [0.0629, 0.2646 + i*0.1185, 0.0745, 0.0425]} for i in range(4)],
        *[{"name": f"doubles_own_{i}_highlight", "box": [0.0420, 0.2291 + i*0.1185, 0.0150, 0.0850]} for i in range(4)],
        #  Split current / max HP boxes (doubles). User drew slots 0+2;
        #  1+3 extrapolated by linear interpolation (delta ≈ 0.1152).
        {"name": "doubles_own_0_hp_current", "box": [0.0640, 0.2699, 0.0453, 0.0355]},
        {"name": "doubles_own_1_hp_current", "box": [0.0640, 0.3851, 0.0444, 0.0375]},
        {"name": "doubles_own_2_hp_current", "box": [0.0639, 0.5003, 0.0434, 0.0394]},
        {"name": "doubles_own_3_hp_current", "box": [0.0640, 0.6155, 0.0444, 0.0375]},
        {"name": "doubles_own_0_hp_max",     "box": [0.1099, 0.2777, 0.0294, 0.0261]},
        {"name": "doubles_own_1_hp_max",     "box": [0.1092, 0.3937, 0.0310, 0.0265]},
        {"name": "doubles_own_2_hp_max",     "box": [0.1085, 0.5098, 0.0325, 0.0269]},
        {"name": "doubles_own_3_hp_max",     "box": [0.1092, 0.6258, 0.0310, 0.0265]},

        #  ── Singles 3-row layout ───────────────────────────────────
        #  User-drawn boxes 2026-05-10 on
        #  test_images/singles_switch/20260509-154834669879.png. HP boxes
        #  span the full "X/Y" text. Cursor strips are wider than doubles
        #  (full pill-left swatch rather than hairline yellow edge).
        {"name": "singles_own_0_species",   "box": [0.0620, 0.2321, 0.0828, 0.0367]},
        {"name": "singles_own_1_species",   "box": [0.0621, 0.3492, 0.0848, 0.0314]},
        {"name": "singles_own_2_species",   "box": [0.0627, 0.4659, 0.0734, 0.0344]},
        {"name": "singles_own_0_hp_text",   "box": [0.0694, 0.2635, 0.0682, 0.0429]},
        {"name": "singles_own_1_hp_text",   "box": [0.0650, 0.3854, 0.0736, 0.0362]},
        {"name": "singles_own_2_hp_text",   "box": [0.0633, 0.5029, 0.0763, 0.0358]},
        {"name": "singles_own_0_highlight", "box": [0.0429, 0.2308, 0.0184, 0.0255]},
        {"name": "singles_own_1_highlight", "box": [0.0388, 0.3506, 0.0239, 0.0255]},
        {"name": "singles_own_2_highlight", "box": [0.0421, 0.4658, 0.0191, 0.0209]},
        #  Split current / max HP boxes (singles). User drew slots 1+2;
        #  slot 0 extrapolated using the singles per-row delta (~0.117).
        {"name": "singles_own_0_hp_current", "box": [0.0604, 0.2676, 0.0480, 0.0383]},
        {"name": "singles_own_1_hp_current", "box": [0.0604, 0.3846, 0.0480, 0.0383]},
        {"name": "singles_own_2_hp_current", "box": [0.0619, 0.5039, 0.0502, 0.0356]},
        {"name": "singles_own_0_hp_max",     "box": [0.1111, 0.2787, 0.0282, 0.0240]},
        {"name": "singles_own_1_hp_max",     "box": [0.1111, 0.3957, 0.0282, 0.0240]},
        {"name": "singles_own_2_hp_max",     "box": [0.1117, 0.5117, 0.0253, 0.0242]},

        #  Opp column (right). Independent of own row count — same boxes
        #  for both layouts.
        *[{"name": f"opp_{i}_hp_pct", "box": [0.9131, 0.2622 + i*0.1170, 0.0356, 0.0345]} for i in range(6)],
    ],
    #  Battle Info tab — boxes drawn by user 2026-05-07.
    #
    #  Top-bar icon layout: 4 active mons in doubles (own_0, own_1, opp_0,
    #  opp_1) or N icons when fewer are alive. The yellow highlight bar
    #  above whichever icon is currently focused is the "selected slot"
    #  signal. The user drew opp_*_top + own_species_SOLO_top (singles-only
    #  centered position). Doubles own boxes are extrapolated by mirroring
    #  the opp boxes around screen center x=0.5.
    "BattleInfoReader": [
        # Top icon row — singles (1 own + 2 opp) and doubles (2 own + 2 opp).
        {"name": "own_species_0_top",    "box": [0.34334, 0.0722, 0.03936, 0.0728]}, # mirrored from opp; -2px L
        {"name": "own_species_1_top",    "box": [0.4238,  0.0722, 0.03936, 0.0728]}, # mirrored from opp; -2px R
        {"name": "own_species_SOLO_top", "box": [0.3821, 0.0706, 0.0411, 0.0814]},   # singles-only center position
        {"name": "opp_species_0_top",    "box": [0.5358, 0.0722, 0.0404, 0.0728]},
        {"name": "opp_species_1_top",    "box": [0.6169, 0.0716, 0.0408, 0.0743]},
        # Focused-mon left panel.
        {"name": "species_name",         "box": [0.1973, 0.2228, 0.1582, 0.0408]},
        {"name": "species_hp_text",     "box": [0.3372, 0.2772, 0.0782, 0.0377]},  # own=X/Y, opp=NN%
        # Type pills (2). Color classifier — each PS type has a unique hue.
        {"name": "type_0",               "box": [0.2280, 0.3336, 0.0670, 0.0383]},
        {"name": "type_1",               "box": [0.3393, 0.3353, 0.0655, 0.0364]},
        # Ability + item — own only (opp panel just shows types in this region).
        {"name": "ability_own",          "box": [0.3125, 0.3881, 0.1101, 0.0431]},
        {"name": "item_own",             "box": [0.2887, 0.4394, 0.1351, 0.0449]},
        # Per-stat boost multiplier text (×1.0, ×0.67, ×1.5, etc.). 7 rows.
        {"name": "attk_multiplier",      "box": [0.3840, 0.5190, 0.0272, 0.0352]},
        {"name": "def_multiplier",       "box": [0.3839, 0.5657, 0.0257, 0.0348]},
        {"name": "spa_multiplier",       "box": [0.3848, 0.6074, 0.0311, 0.0357]},
        {"name": "spdef_multiplier",     "box": [0.3853, 0.6495, 0.0299, 0.0418]},
        {"name": "speed_multiplier",     "box": [0.3847, 0.6942, 0.0269, 0.0383]},
        {"name": "accuracy_multiplier",  "box": [0.3849, 0.7620, 0.0272, 0.0393]},
        {"name": "evasiveness_multiplier","box":[0.3848, 0.8060, 0.0249, 0.0405]},
        # Active Statuses & Effects (right panel) — phase-3 OCR target.
        {"name": "first_status",                "box": [0.5275, 0.3138, 0.2084, 0.0471]},
        {"name": "second_status_guess",         "box": [0.5243, 0.4036, 0.2787, 0.0536]},
        {"name": "second_status_duration_guess","box": [0.8113, 0.4086, 0.0393, 0.0544]},
    ],
    #  Investigation tab: 6 own-side icon slots on the locked-in team
    #  preview screen (own ICONS, opp sprites are inward). Boxes drawn
    #  by user 2026-05-07. Top-to-bottom positional indexing — semantic
    #  lead-order mapping is TBD; investigate via /#/tplocked.
    #  Mirrors C++ TeamPreviewCursorReader: 6 highlight strips on the left
    #  edge of each own card on the team_preview_selecting screen.
    "MainMenuDetector": [
        {"name": "Battle_cursor",   "box": [0.5403, 0.3214, 0.0083, 0.1857]},
        {"name": "Box_cursor",      "box": [0.9807, 0.1817, 0.0045, 0.1337]},
        {"name": "Train_cursor",    "box": [0.9801, 0.5813, 0.0054, 0.1341]},
        {"name": "Recruit_cursor",  "box": [0.5451, 0.6028, 0.0052, 0.0824]},
        {"name": "Missions_cursor", "box": [0.2169, 0.9295, 0.0231, 0.0175]},
        {"name": "Mailbox_cursor",  "box": [0.3761, 0.9268, 0.0188, 0.0221]},
        {"name": "Style_cursor",    "box": [0.5308, 0.9265, 0.0256, 0.0211]},
        {"name": "SubMenu_cursor",  "box": [0.6844, 0.9269, 0.0239, 0.0241]},
    ],
    "BattleModeMenuDetector": [
        {"name": "season_pill",   "box": [0.6563, 0.1574, 0.0078, 0.0139]},
        {"name": "top_row_burst", "box": [0.9271, 0.2963, 0.0078, 0.0139]},
        {"name": "cursor_0_ranked",         "box": [0.7103, 0.1990, 0.0192, 0.0341]},
        {"name": "cursor_1_casual",         "box": [0.7078, 0.3583, 0.0229, 0.0428]},
        {"name": "cursor_2_private",        "box": [0.7004, 0.5044, 0.0253, 0.0527]},
        {"name": "cursor_3_online_comp",    "box": [0.7426, 0.6621, 0.0258, 0.0451]},
        {"name": "cursor_4_battle_data",    "box": [0.7240, 0.8227, 0.0284, 0.0504]},
    ],
    "RankedFormatSelectDetector": [
        {"name": "top_tile_cyan", "box": [0.7708, 0.3333, 0.0078, 0.0139]},
        {"name": "btm_tile_pink", "box": [0.8333, 0.5556, 0.0078, 0.0139]},
        {"name": "cursor_0_singles", "box": [0.7027, 0.4299, 0.0340, 0.0409]},
        {"name": "cursor_1_doubles", "box": [0.6962, 0.6637, 0.0310, 0.0427]},
    ],
    "CasualFormatSelectDetector": [
        {"name": "casual_detect",  "box": [0.6544, 0.1806, 0.2542, 0.0355]},
        {"name": "casual_singles", "box": [0.6828, 0.3375, 0.0410, 0.1587]},
        {"name": "casual_doubles", "box": [0.6849, 0.5822, 0.0389, 0.1662]},
    ],
    "CasualPreMatchDetector": [
        {"name": "cursor_0_team_select",       "box": [0.5236, 0.2909, 0.1409, 0.0391]},
        {"name": "cursor_1_change_music",      "box": [0.5126, 0.5059, 0.1359, 0.0426]},
        {"name": "cursor_2_begin_matchmaking", "box": [0.5036, 0.8399, 0.1319, 0.0551]},
    ],
    "PreMatchDetector": [
        {"name": "team_card",   "box": [0.7917, 0.5556, 0.0078, 0.0139]},
        {"name": "format_band", "box": [0.6250, 0.1667, 0.0130, 0.0231]},
        {"name": "cursor_0_team_select",       "box": [0.5743, 0.4779, 0.0334, 0.0441]},
        {"name": "cursor_1_change_music",      "box": [0.5716, 0.7012, 0.0237, 0.0393]},
        {"name": "cursor_2_begin_matchmaking", "box": [0.5711, 0.8555, 0.0270, 0.0393]},
    ],
    "TeamPreviewCursorReader": [
        {"name": "cursor_0",    "box": [0.0235, 0.1821, 0.0143, 0.0235]},
        {"name": "cursor_1",    "box": [0.0279, 0.3011, 0.0115, 0.0213]},
        {"name": "cursor_2",    "box": [0.0239, 0.4165, 0.0163, 0.0222]},
        {"name": "cursor_3",    "box": [0.0299, 0.5300, 0.0108, 0.0268]},
        {"name": "cursor_4",    "box": [0.0318, 0.6513, 0.0093, 0.0237]},
        {"name": "cursor_5",    "box": [0.0335, 0.7654, 0.0069, 0.0300]},
        {"name": "cursor_done", "box": [0.1324, 0.8572, 0.0146, 0.0428]},
    ],
    #  Lead-mark digit boxes for team_preview_selecting. Mirrors the
    #  selecting_screen_boxes() coords in TeamPreviewLeadsReader.cpp.
    "TeamPreviewSelectingMarksReader": [
        {"name": "digit_0", "box": [0.0462, 0.1699, 0.0253, 0.0527]},
        {"name": "digit_1", "box": [0.0462, 0.2865, 0.0240, 0.0554]},
        {"name": "digit_2", "box": [0.0476, 0.4017, 0.0234, 0.0536]},
        {"name": "digit_3", "box": [0.0467, 0.5218, 0.0246, 0.0476]},
        {"name": "digit_4", "box": [0.0466, 0.6375, 0.0223, 0.0484]},
        {"name": "digit_5", "box": [0.0466, 0.7555, 0.0229, 0.0522]},
    ],
    "TeamPreviewLockedInReader": [
        {"name": "own_slot_0", "box": [0.1599, 0.1747, 0.0270, 0.0532]},
        {"name": "own_slot_1", "box": [0.1561, 0.2872, 0.0287, 0.0540]},
        {"name": "own_slot_2", "box": [0.1586, 0.4048, 0.0299, 0.0615]},
        {"name": "own_slot_3", "box": [0.1578, 0.5218, 0.0316, 0.0577]},
        {"name": "own_slot_4", "box": [0.1599, 0.6395, 0.0308, 0.0660]},
        {"name": "own_slot_5", "box": [0.1586, 0.7526, 0.0274, 0.0637]},
    ],
    "TargetSelectReader": [
        {"name": "opp_0_is_targeted",    "box": [0.4741, 0.2355, 0.0062, 0.1172]},
        {"name": "opp_1_is_targeted",    "box": [0.7338, 0.2340, 0.0045, 0.1228]},
        {"name": "own_0_is_targeted",    "box": [0.4741, 0.5832, 0.0053, 0.1030]},
        {"name": "own_1_is_targeted",    "box": [0.7334, 0.5714, 0.0053, 0.1117]},
        {"name": "opp_0_effectiveness",  "box": [0.3083, 0.2308, 0.1190, 0.0269]},
        {"name": "opp_1_effectiveness",  "box": [0.5658, 0.2300, 0.1056, 0.0285]},
        {"name": "own_0_effectiveness",  "box": [0.3083, 0.5640, 0.1190, 0.0269]},
        {"name": "own_1_effectiveness",  "box": [0.5658, 0.5667, 0.1056, 0.0285]},
        {"name": "own_0_move_name",      "box": [0.3203, 0.4914, 0.1046, 0.0317]},
        {"name": "own_1_move_name",      "box": [0.5778, 0.4914, 0.1046, 0.0317]},
    ],
}

BOOL_DETECTORS = {
    "MoveSelectDetector", "ActionMenuDetector", "PostMatchScreenDetector",
    "PreparingForBattleDetector", "TeamSelectDetector", "TeamPreviewDetector",
    "MainMenuDetector", "MovesMoreDetector", "CommunicatingDetector",
    "MegaEvolveDetector", "TargetSelectDetector", "PokemonSwitchDetector",
    "BattleInfoDetector", "TeamStatsTabDetector",
    "BattleModeMenuDetector", "RankedFormatSelectDetector",
    "CasualFormatSelectDetector", "CasualPreMatchDetector",
    "PreMatchDetector", "SearchingForBattleDetector",
}

BATTLE_LOG_EVENTS = [
    "MOVE_USED", "FAINTED", "SUPER_EFFECTIVE", "NOT_VERY_EFFECTIVE",
    "CRITICAL_HIT", "NO_EFFECT", "SENT_OUT", "WITHDREW", "STAT_CHANGE",
    "STATUS_INFLICTED", "WEATHER", "TERRAIN", "ABILITY_ACTIVATED",
    "ITEM_USED", "HEALED", "DAMAGED", "OTHER",
]

FOLDER_TO_READER = {
    "action_menu": "ActionMenuDetector",
    "battle_info": "BattleInfoReader",
    "battle_log": "BattleLogReader",
    "battle_mode_menu": "BattleModeMenuDetector",
    "casual_format_select": "CasualFormatSelectDetector",
    "casual_pre_match": "CasualPreMatchDetector",
    "main_menu": "MainMenuDetector",
    "match_intro": "MainMenuDetector",  # no detector yet — placeholder
    "move_select": "MoveNameReader",
    "singles_switch": "PokemonSwitchReader",
    "doubles_switch": "PokemonSwitchReader",
    "post_match": "PostMatchScreenDetector",
    "pre_match": "PreMatchDetector",
    "preparing": "PreparingForBattleDetector",
    "ranked_format_select": "RankedFormatSelectDetector",
    "result_screen": "ResultScreenDetector",
    "searching_for_battle": "SearchingForBattleDetector",
    "target_select": "TargetSelectReader",
    "team_preview_locked_in": "TeamPreviewLeadsReader",
    "team_preview_selecting": "TeamPreviewCursorReader",
    "team_select": "TeamSelectReader",
    "team_preview": "TeamPreviewReader",
    "team_stats": "TeamStatsReader",
    "team_summary": "TeamSummaryReader",
}

# Which readers to show together for each screen type
FOLDER_READERS = {
    "action_menu": ["ActionMenuDetector", "BattleHUDReader", "PokeballAliveDetector"],
    "battle_info": ["BattleInfoDetector", "BattleInfoReader"],
    "battle_mode_menu": ["BattleModeMenuDetector"],
    "casual_format_select": ["CasualFormatSelectDetector"],
    "casual_pre_match": ["CasualPreMatchDetector"],
    "main_menu": ["MainMenuDetector"],
    "move_select": ["MoveSelectDetector", "MegaEvolveDetector", "MoveNameReader", "MoveSelectCursorSlot", "BattleHUDReader", "PokeballAliveDetector"],
    "battle_log": ["BattleLogReader", "BattleHUDReader", "PokeballAliveDetector"],
    "singles_switch": ["PokemonSwitchDetector", "PokemonSwitchReader"],
    "doubles_switch": ["PokemonSwitchDetector", "PokemonSwitchReader"],
    "post_match": ["PostMatchScreenDetector"],
    "pre_match": ["PreMatchDetector"],
    "preparing": ["PreparingForBattleDetector", "TeamPreviewLeadsReader"],
    "ranked_format_select": ["RankedFormatSelectDetector"],
    "result_screen": ["ResultScreenDetector"],
    "searching_for_battle": ["SearchingForBattleDetector"],
    "target_select": ["TargetSelectDetector", "TargetSelectReader"],
    "team_preview_locked_in": ["PreparingForBattleDetector", "TeamPreviewLeadsReader"],
    "team_preview_selecting": ["TeamPreviewDetector", "TeamPreviewReader", "TeamPreviewCursorReader", "TeamPreviewSelectingMarksReader"],
    "team_select": ["TeamSelectReader", "TeamSelectDetector"],
    "team_preview": ["TeamPreviewReader", "TeamPreviewDetector", "TeamPreviewCursorReader"],
    "team_stats": ["TeamStatsTabDetector", "TeamStatsReader"],
    "team_summary": ["TeamSummaryReader", "MovesMoreDetector"],
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
    #  Per-slot state: "alive" (green/yellow), "fainted" (grey ball),
    #  or "empty" (small grey dot). 12 slots total: own 0..5, opp 0..5.
    "PokeballAliveDetector": "multi_state:12:alive,fainted,empty",
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

def _yellow_inner_image(img_path: Path, box: list, scale: int = 3):
    """User's pipeline:
    1. yellow -> white
    2. invert (dark -> white outline; bg+inner -> black)
    3. flood-fill from edges over BLACK -> 'outside' painted white
    4. surviving black pixels = inner trapped center (digit body)
    Output: black inner-center on white bg, no outline.
    """
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    x0, y0 = max(0, int(box[0]*w)), max(0, int(box[1]*h))
    x1, y1 = min(w, x0+int(box[2]*w)), min(h, y0+int(box[3]*h))
    crop = img.crop((x0, y0, x1, y1))
    cw, ch = crop.size
    upscaled = crop.resize((cw*scale, ch*scale), Image.NEAREST)
    px = upscaled.load()
    W, H = upscaled.size
    #  Step 1+2 combined: classify each pixel after yellow-paint, then invert.
    #   - yellow OR light non-yellow -> BLACK after invert (was bg/inner light)
    #   - dark navy outline           -> WHITE after invert
    bin_inv = [[False]*W for _ in range(H)]   # True = BLACK pixel
    for j in range(H):
        for i in range(W):
            r,g,b = px[i,j]
            is_yellow = (r > 150) and (g > 150) and (b < 140) and (r-b > 40) and (g-b > 40)
            if is_yellow:
                bin_inv[j][i] = True   # was yellow -> white -> invert -> black
                continue
            brightness = (r + g + b) / 3
            if brightness < 130:
                bin_inv[j][i] = False  # dark outline -> invert -> white
            else:
                bin_inv[j][i] = True   # light non-yellow -> invert -> black
    #  Step 3: flood-fill from edges over BLACK (True) pixels.
    visited = [[False]*W for _ in range(H)]
    stack = []
    for i in range(W):
        if bin_inv[0][i]: stack.append((i,0)); visited[0][i] = True
        if bin_inv[H-1][i]: stack.append((i,H-1)); visited[H-1][i] = True
    for j in range(H):
        if bin_inv[j][0]: stack.append((0,j)); visited[j][0] = True
        if bin_inv[j][W-1]: stack.append((W-1,j)); visited[j][W-1] = True
    while stack:
        x,y = stack.pop()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny = x+dx, y+dy
            if 0<=nx<W and 0<=ny<H and bin_inv[ny][nx] and not visited[ny][nx]:
                visited[ny][nx] = True
                stack.append((nx,ny))
    #  Step 4: trapped black survives; everything else -> white.
    for j in range(H):
        for i in range(W):
            if bin_inv[j][i] and not visited[j][i]:
                px[i,j] = (0,0,0)         # inner trapped center
            else:
                px[i,j] = (255,255,255)   # outline OR outside bg
    return upscaled


def _yellow_paint_filled_image(img_path: Path, box: list, scale: int = 3):
    """Yellow-paint binarize, then flood-fill from edges over white pixels
    and flip 'trapped' white (digit interior) to black. Produces a solid
    black digit shape — much easier for Tesseract than a hollow outline."""
    img = _yellow_paint_image(img_path, box, scale)
    w, h = img.size
    px = img.load()
    #  BFS from every edge pixel that's currently white. Anything reached =
    #  outside background. Implemented w/ a simple stack to avoid recursion.
    is_white = [[False]*w for _ in range(h)]
    for j in range(h):
        for i in range(w):
            r,g,b = px[i,j]
            is_white[j][i] = (r > 200 and g > 200 and b > 200)
    visited = [[False]*w for _ in range(h)]
    stack = []
    for i in range(w):
        if is_white[0][i] and not visited[0][i]:
            stack.append((i,0)); visited[0][i] = True
        if is_white[h-1][i] and not visited[h-1][i]:
            stack.append((i,h-1)); visited[h-1][i] = True
    for j in range(h):
        if is_white[j][0] and not visited[j][0]:
            stack.append((0,j)); visited[j][0] = True
        if is_white[j][w-1] and not visited[j][w-1]:
            stack.append((w-1,j)); visited[j][w-1] = True
    while stack:
        x,y = stack.pop()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny = x+dx, y+dy
            if 0<=nx<w and 0<=ny<h and is_white[ny][nx] and not visited[ny][nx]:
                visited[ny][nx] = True
                stack.append((nx,ny))
    #  Trapped white -> black. Outline stays black. Reached white stays white.
    for j in range(h):
        for i in range(w):
            if is_white[j][i] and not visited[j][i]:
                px[i,j] = (0,0,0)
    return img


def _yellow_paint_image(img_path: Path, box: list, scale: int = 3):
    """Returns the PIL.Image for the yellow-paint binarization (used for
    both display and Python-side OCR). Same logic as _binarize_yellow_paint
    but returns the image, not bytes."""
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    x0, y0 = max(0, int(box[0]*w)), max(0, int(box[1]*h))
    x1, y1 = min(w, x0+int(box[2]*w)), min(h, y0+int(box[3]*h))
    crop = img.crop((x0, y0, x1, y1))
    cw, ch = crop.size
    upscaled = crop.resize((cw*scale, ch*scale), Image.NEAREST)
    px = upscaled.load()
    for j in range(upscaled.size[1]):
        for i in range(upscaled.size[0]):
            r, g, b = px[i, j]
            is_yellow = (r > 150) and (g > 150) and (b < 140) and (r - b > 40) and (g - b > 40)
            if is_yellow:
                px[i, j] = (255, 255, 255)
                continue
            brightness = (r + g + b) / 3
            if brightness < 130:
                px[i, j] = (0, 0, 0)
            else:
                px[i, j] = (255, 255, 255)
    return upscaled


def _binarize_yellow_paint(img_path: Path, box: list, scale: int = 3) -> bytes:
    img = _yellow_paint_image(img_path, box, scale)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _normalize_lead_digit(raw: str) -> str:
    """Map Tesseract's inner-OCR output to {1,2,3,4} or '' for bench.
    1's inner shape (thin slash) reliably misreads as 7 / / / |. Bench
    slots have no digit and produce punctuation noise — return ''."""
    if not raw:
        return ""
    for ch in raw:
        if ch in "1234":
            return ch
        if ch in "7/|":   # confusables for 1
            return "1"
    return ""


def _tesseract_digit(img):
    """Single-glyph OCR. Whitelist breaks psm 10 in tesseract 5.x, so we
    take the raw read and let the caller decide. Stylized italic font is
    poorly handled by Tesseract regardless of config — this view exists
    so we can SEE that and switch to digit-template matching."""
    try:
        import pytesseract
        return pytesseract.image_to_string(img, config="--psm 10").strip()
    except Exception as e:
        return f"err: {e}"


def _binarize_for_ocr(img_path: Path, box: list, scale: int = 3) -> bytes:
    """Mirror of C++ raw_ocr_numbers() preprocessing: crop, NEAREST-upscale,
    then white-only mask -> black text on white bg. Returns PNG bytes.
    Filter: pixel is text iff min(R,G,B) > 180 AND (max - min) < 50."""
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    x0, y0 = max(0, int(box[0]*w)), max(0, int(box[1]*h))
    x1, y1 = min(w, x0+int(box[2]*w)), min(h, y0+int(box[3]*h))
    crop = img.crop((x0, y0, x1, y1))
    cw, ch = crop.size
    upscaled = crop.resize((cw*scale, ch*scale), Image.NEAREST)
    px = upscaled.load()
    for j in range(upscaled.size[1]):
        for i in range(upscaled.size[0]):
            r, g, b = px[i, j]
            mn = min(r, g, b); mx = max(r, g, b)
            is_text = (mn > 180) and (mx - mn < 50)
            px[i, j] = (0, 0, 0) if is_text else (255, 255, 255)
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
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/status")
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
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/collection")
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
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/ratings")
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
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/recent", f"limit={int(limit)}")
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
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/dataset")
    key = "endpoint:dataset"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    result = await _run_in_executor(_compute_dataset)
    _cache_set(key, result, ttl=60)
    return result

@app.get("/api/coverage")
async def coverage():
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/coverage")
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
    for f in sorted(INBOX_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
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


# Inbox triage helpers

def _ocr_suggest_inbox(filename: str, reader: str):
    """Run a reader on an _inbox/<filename> image via the dev runner.
    Returns (result_dict | None, error_str | None)."""
    import base64
    import urllib.request
    import urllib.error
    img_path = INBOX_DIR / filename
    if not img_path.exists():
        return None, "image not found"
    try:
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        payload = json.dumps({
            "image_base64": img_b64,
            "reader": reader,
            "screen": "_inbox",
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
        return envelope.get("result", {}) or {}, None
    except urllib.error.URLError as e:
        return None, f"dev runner unreachable: {e}"
    except Exception as e:
        return None, str(e)


_INBOX_LOG_CACHE: dict = {}  # filename -> (mtime, result)


#  ── HUD pill atlas ──────────────────────────────────────────────────
HUD_PILL_ATLAS_DIR = BASE / "data" / "hud_pill_atlas"

@app.get("/api/hud-pill-atlas")
async def hud_pill_atlas_index():
    """Return the index + per-species averaged thumbnail (computed on the fly)."""
    import base64, io
    idx_path = HUD_PILL_ATLAS_DIR / "index.json"
    if not idx_path.exists():
        return {"error": "atlas not built — run tools/build_hud_pill_atlas.py", "sides": {}}
    idx = json.loads(idx_path.read_text())
    out = {"sides": {}}
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        return {"error": f"pillow/numpy missing: {e}", "sides": {}}
    refs_dir = HUD_PILL_ATLAS_DIR / "refs"
    for side, species_map in idx.items():
        species_out = {}
        for sp, info in species_map.items():
            arrs = []
            for r in info.get("refs", []):
                try:
                    p = refs_dir / r["ref"]
                    arrs.append(np.array(Image.open(p).convert("RGB"), dtype=np.float32))
                except Exception:
                    continue
            mean_b64 = None
            if arrs:
                mean = np.clip(np.mean(arrs, axis=0), 0, 255).astype(np.uint8)
                buf = io.BytesIO()
                Image.fromarray(mean).save(buf, format="PNG")
                mean_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            species_out[sp] = {
                "count": info.get("count", len(arrs)),
                "mean_thumb": mean_b64,
                "refs": info.get("refs", []),
            }
        out["sides"][side] = species_out
    return out

@app.get("/api/hud-pill-atlas/ref/{filename}")
async def hud_pill_atlas_ref(filename: str):
    """Serve one reference crop file from the atlas."""
    if "/" in filename or ".." in filename:
        return JSONResponse({"error": "invalid filename"}, 400)
    p = HUD_PILL_ATLAS_DIR / "refs" / filename
    if not p.exists():
        return JSONResponse({"error": "not found"}, 404)
    return Response(p.read_bytes(), media_type="image/png")

@app.get("/api/hud-pill-atlas/audit")
async def hud_pill_atlas_audit(unknown_threshold: float = 25.0):
    """For each ref crop, compare its RMSD against every species mean
    (excluding itself from its labeled species's mean) and flag cases where
    the top-1 predicted species != the labeled species. Catches mislabels
    (hidden megas labeled as base form, OCR slips, etc.).

    Returns a list of suspect crops sorted by confidence-of-mismatch."""
    import base64, io
    idx_path = HUD_PILL_ATLAS_DIR / "index.json"
    if not idx_path.exists():
        return {"suspects": [], "error": "atlas not built"}
    idx = json.loads(idx_path.read_text())
    refs_dir = HUD_PILL_ATLAS_DIR / "refs"
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        return {"suspects": [], "error": f"pillow/numpy missing: {e}"}

    suspects = []
    unknowns = []
    for side, species_map in idx.items():
        # Load all crops once.
        crops_per_sp: dict = {}
        all_crops_with_label: list = []
        for sp, info in species_map.items():
            arrs = []
            for r in info.get("refs", []):
                p = refs_dir / r["ref"]
                if not p.exists(): continue
                try:
                    arr = np.array(Image.open(p).convert("RGB"), dtype=np.float32)
                    arrs.append((arr, r))
                except Exception:
                    continue
            if arrs:
                crops_per_sp[sp] = arrs
                for arr, meta in arrs:
                    all_crops_with_label.append((side, sp, arr, meta))

        # For each crop, compute RMSD vs each species mean (excluding self
        # from its own species mean if its species has multiple refs).
        for side_q, label_sp, query, meta in all_crops_with_label:
            # Build means per species; for the labeled sp, leave the query out.
            best_sp, best_rmsd = None, float('inf')
            label_rmsd = float('inf')
            for sp, arrs in crops_per_sp.items():
                if sp == label_sp:
                    others = [a for a, m in arrs if m["ref"] != meta["ref"]]
                    if not others: continue  # only self → can't score against own
                    ref = np.mean(others, axis=0)
                else:
                    ref = np.mean([a for a, _ in arrs], axis=0)
                rmsd = float(np.sqrt(np.mean((query - ref) ** 2)))
                if sp == label_sp: label_rmsd = rmsd
                if rmsd < best_rmsd:
                    best_rmsd = rmsd; best_sp = sp
            if best_sp is None: continue
            if best_sp != label_sp:
                # Suspect: predicted != labeled
                suspects.append({
                    "side": side_q,
                    "labeled_species": label_sp,
                    "predicted_species": best_sp,
                    "ref": meta["ref"],
                    "source_frame": meta.get("source_frame", ""),
                    "slot": meta.get("slot", -1),
                    "rmsd_predicted": round(best_rmsd, 2),
                    "rmsd_labeled": round(label_rmsd, 2) if label_rmsd != float('inf') else None,
                    # Confidence-of-mismatch: bigger gap = stronger signal
                    "confidence": round(label_rmsd - best_rmsd, 2) if label_rmsd != float('inf') else None,
                })
            #  Out-of-atlas candidates: even the best species match is poor.
            #  Likely a new species/variant the atlas can't yet represent.
            if best_rmsd >= unknown_threshold:
                unknowns.append({
                    "side": side_q,
                    "labeled_species": label_sp,
                    "best_match": best_sp,
                    "ref": meta["ref"],
                    "source_frame": meta.get("source_frame", ""),
                    "slot": meta.get("slot", -1),
                    "rmsd_best": round(best_rmsd, 2),
                    "rmsd_labeled": round(label_rmsd, 2) if label_rmsd != float('inf') else None,
                })

    suspects.sort(key=lambda s: -(s["confidence"] or 0))
    unknowns.sort(key=lambda u: -u["rmsd_best"])
    return {
        "suspects": suspects,
        "count": len(suspects),
        "unknowns": unknowns,
        "unknown_count": len(unknowns),
        "unknown_threshold": unknown_threshold,
    }


@app.post("/api/hud-pill-atlas/relabel")
async def hud_pill_atlas_relabel(request: Request):
    """Apply an audit suggestion: update the manifest's BattleHUDReader
    {own,opponent}_species[slot] for the source frame to the predicted slug.
    Atlas itself isn't regenerated — caller should hit /rebuild after batching
    a few of these so we don't re-extract on each click.
    """
    body = await request.json()
    ref = body.get("ref", "")
    new_species = (body.get("new_species") or "").strip().lower()
    if not ref or not new_species:
        return JSONResponse({"error": "ref and new_species required"}, 400)
    # ref filename format: <side>__<species>__<frame_id>__slot<i>.png
    parts = ref.replace(".png", "").split("__")
    if len(parts) < 4:
        return JSONResponse({"error": f"unexpected ref format: {ref}"}, 400)
    side = parts[0]
    frame_id = parts[2]
    slot_str = parts[3]
    if not slot_str.startswith("slot"):
        return JSONResponse({"error": f"unexpected slot: {slot_str}"}, 400)
    try: slot_idx = int(slot_str[4:])
    except ValueError:
        return JSONResponse({"error": f"bad slot int: {slot_str}"}, 400)
    if side not in ("own", "opp") or slot_idx not in (0, 1):
        return JSONResponse({"error": f"unsupported side/slot: {side}/{slot_idx}"}, 400)

    field = "own_species" if side == "own" else "opponent_species"
    target_filename = frame_id + ".png"
    # Search action_menu / move_select manifests.
    updated = False
    for screen in ("action_menu", "move_select"):
        mpath = TEST_IMAGES_DIR / screen / "manifest.json"
        if not mpath.exists(): continue
        manifest = json.loads(mpath.read_text())
        entry = manifest.get(target_filename)
        if not entry: continue
        bhr = entry.setdefault("BattleHUDReader", {})
        arr = bhr.get(field) or ["", ""]
        if not isinstance(arr, list) or len(arr) < 2:
            arr = ["", ""]
        old = arr[slot_idx]
        arr[slot_idx] = new_species
        bhr[field] = arr
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        updated = True
        return {"ok": True, "screen": screen, "frame": target_filename,
                "field": field, "slot": slot_idx, "old": old, "new": new_species}
    if not updated:
        return JSONResponse({"error": f"frame {target_filename} not found in any screen manifest"}, 404)


@app.post("/api/hud-pill-atlas/rebuild")
async def hud_pill_atlas_rebuild():
    """Re-run the atlas build script (re-extracts crops from current
    test_images manifests)."""
    import subprocess
    result = subprocess.run(
        ["python3", str(BASE / "tools" / "build_hud_pill_atlas.py")],
        capture_output=True, text=True, cwd=str(BASE),
    )
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


@app.get("/api/targetselect-gallery")
async def targetselect_gallery():
    """For each target_select test image, return the 10 crops + reader's
    parsed values + raw OCR text per cell. Mirror of pp/hp galleries."""
    import base64
    from concurrent.futures import ThreadPoolExecutor, as_completed
    screen_dir = TEST_IMAGES_DIR / "target_select"
    if not screen_dir.exists():
        return {"images": []}
    boxes = CROP_DEFS.get("TargetSelectReader") or []
    files = sorted(f for f in screen_dir.iterdir()
                   if f.is_file() and f.suffix.lower() == ".png" and _is_real_image(f.name))
    manifest = _load_manifest(screen_dir)

    def work(img_path):
        crops = []
        for cd in boxes:
            try:
                crops.append({
                    "name": cd["name"],
                    "data": "data:image/png;base64," + base64.b64encode(_extract_crop(img_path, cd["box"], scale=4)).decode(),
                })
            except Exception:
                crops.append({"name": cd["name"], "data": None})
        result, err = _suggest_via_runner("target_select", img_path.name, "TargetSelectReader")
        result = result or {}
        m_entry = (manifest.get(img_path.name) or {}).get("TargetSelectReader") or {}
        return {
            "filename": img_path.name,
            "thumb": f"/api/gallery/thumb/target_select/{img_path.name}",
            "crops": crops,
            "own_moves":             result.get("own_moves",             ["", ""]),
            "own_moves_raw":         result.get("own_moves_raw",         ["", ""]),
            "opp_targeted":          result.get("opp_targeted",          [False, False]),
            "own_targeted":          result.get("own_targeted",          [False, False]),
            "opp_effectiveness":     result.get("opp_effectiveness",     ["", ""]),
            "own_effectiveness":     result.get("own_effectiveness",     ["", ""]),
            "opp_effectiveness_raw": result.get("opp_effectiveness_raw", ["", ""]),
            "own_effectiveness_raw": result.get("own_effectiveness_raw", ["", ""]),
            "manifest_own_moves":         m_entry.get("own_moves"),
            "manifest_opp_effectiveness": m_entry.get("opp_effectiveness"),
            "manifest_own_effectiveness": m_entry.get("own_effectiveness"),
            "error": err,
        }

    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(work, f) for f in files]
        for fut in as_completed(futs):
            out.append(fut.result())
    out.sort(key=lambda r: r["filename"])
    return {"images": out, "count": len(out)}


@app.get("/api/saved-teams/list")
async def saved_teams_list():
    """List saved-team JSONs in the SerialPrograms team library directory.
    Each file = one unique team composition keyed by sorted species slugs."""
    team_dir = Path.home() / "Library" / "Application Support" / "SerialPrograms" / "UserSettings" / "PokemonChampionsTeams"
    teams = []
    if team_dir.exists():
        for f in sorted(team_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                mons = data.get("own_team", [])
                teams.append({
                    "filename": f.name,
                    "key": f.stem,                       # sorted slug list
                    "species": [m.get("species", "") for m in mons],
                    "mons": mons,
                    "mtime": f.stat().st_mtime,
                })
            except Exception as e:
                teams.append({"filename": f.name, "error": str(e)})
    teams.sort(key=lambda t: -t.get("mtime", 0))
    return {"dir": str(team_dir), "count": len(teams), "teams": teams}


@app.get("/api/tp-locked/list")
async def tp_locked_list():
    screen_dir = TEST_IMAGES_DIR / "team_preview_locked_in"
    if not screen_dir.exists():
        return {"files": []}
    files = sorted([
        f.name for f in screen_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".png" and _is_real_image(f.name)
    ])
    return {"files": files}


@app.get("/api/tp-locked/read")
async def tp_locked_read(filename: str):
    """For one team_preview_locked_in image, return the 6 own-slot crops
    (b64) + sprite-match top-N per slot. Investigation tool."""
    import base64
    import urllib.request
    import urllib.error
    img_path = TEST_IMAGES_DIR / "team_preview_locked_in" / filename
    if not img_path.exists():
        return JSONResponse({"error": "not found"}, 404)

    boxes = CROP_DEFS.get("TeamPreviewLockedInReader") or []
    img_b64 = base64.b64encode(img_path.read_bytes()).decode()

    def _ocr_digit(box):
        payload = json.dumps({
            "image_base64": img_b64,
            "x": box[0], "y": box[1], "w": box[2], "h": box[3],
        }).encode()
        try:
            req = urllib.request.Request(
                f"{DEV_RUNNER}/ocr-crop", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read())
                return d.get("result") or d
        except Exception as e:
            return {"error": str(e)}

    slots = []
    for b in boxes:
        try:
            crop_b64 = "data:image/png;base64," + base64.b64encode(
                _extract_crop(img_path, b["box"], scale=4)
            ).decode()
        except Exception:
            crop_b64 = None
        try:
            bin_b64 = "data:image/png;base64," + base64.b64encode(
                _binarize_for_ocr(img_path, b["box"], scale=3)
            ).decode()
        except Exception:
            bin_b64 = None
        yp_b64 = None; yp_text = ""
        try:
            yp_img = _yellow_paint_image(img_path, b["box"], scale=3)
            buf = io.BytesIO(); yp_img.save(buf, format="PNG")
            yp_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            yp_text = _tesseract_digit(yp_img)
        except Exception as e:
            yp_text = f"err: {e}"
        yf_b64 = None; yf_text = ""
        try:
            yf_img = _yellow_paint_filled_image(img_path, b["box"], scale=3)
            buf = io.BytesIO(); yf_img.save(buf, format="PNG")
            yf_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            yf_text = _tesseract_digit(yf_img)
        except Exception as e:
            yf_text = f"err: {e}"
        yi_b64 = None; yi_text = ""
        try:
            yi_img = _yellow_inner_image(img_path, b["box"], scale=3)
            buf = io.BytesIO(); yi_img.save(buf, format="PNG")
            yi_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            yi_text = _tesseract_digit(yi_img)
        except Exception as e:
            yi_text = f"err: {e}"
        ocr = _ocr_digit(b["box"])
        slots.append({
            "name": b["name"],
            "box": b["box"],
            "crop": crop_b64,
            "binarized": bin_b64,
            "yellow_paint": yp_b64,
            "yellow_paint_ocr": yp_text,
            "yellow_filled": yf_b64,
            "yellow_filled_ocr": yf_text,
            "yellow_inner": yi_b64,
            "yellow_inner_ocr": yi_text,
            "lead_digit": _normalize_lead_digit(yi_text),
            "ocr": ocr,
        })

    return {"filename": filename, "slots": slots}


@app.get("/api/tp-marks/list")
async def tp_marks_list():
    screen_dir = TEST_IMAGES_DIR / "team_preview_selecting"
    if not screen_dir.exists():
        return {"files": []}
    files = sorted([
        f.name for f in screen_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".png" and _is_real_image(f.name)
    ])
    return {"files": files}


@app.get("/api/tp-marks/read")
async def tp_marks_read(filename: str):
    """Mirror of /api/tp-locked/read but for the team_preview_selecting
    digit badges. Same OCR pipeline (raw / binarize / yellow_paint /
    yellow_filled / yellow_inner / Tesseract per stage)."""
    import base64
    import urllib.request
    img_path = TEST_IMAGES_DIR / "team_preview_selecting" / filename
    if not img_path.exists():
        return JSONResponse({"error": "not found"}, 404)

    boxes = CROP_DEFS.get("TeamPreviewSelectingMarksReader") or []
    img_b64 = base64.b64encode(img_path.read_bytes()).decode()

    def _ocr_digit(box):
        payload = json.dumps({
            "image_base64": img_b64,
            "x": box[0], "y": box[1], "w": box[2], "h": box[3],
        }).encode()
        try:
            req = urllib.request.Request(
                f"{DEV_RUNNER}/ocr-crop", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read())
                return d.get("result") or d
        except Exception as e:
            return {"error": str(e)}

    slots = []
    for b in boxes:
        try:
            crop_b64 = "data:image/png;base64," + base64.b64encode(
                _extract_crop(img_path, b["box"], scale=4)
            ).decode()
        except Exception:
            crop_b64 = None
        try:
            bin_b64 = "data:image/png;base64," + base64.b64encode(
                _binarize_for_ocr(img_path, b["box"], scale=3)
            ).decode()
        except Exception:
            bin_b64 = None
        yp_b64 = None; yp_text = ""
        try:
            yp_img = _yellow_paint_image(img_path, b["box"], scale=3)
            buf = io.BytesIO(); yp_img.save(buf, format="PNG")
            yp_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            yp_text = _tesseract_digit(yp_img)
        except Exception as e:
            yp_text = f"err: {e}"
        yf_b64 = None; yf_text = ""
        try:
            yf_img = _yellow_paint_filled_image(img_path, b["box"], scale=3)
            buf = io.BytesIO(); yf_img.save(buf, format="PNG")
            yf_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            yf_text = _tesseract_digit(yf_img)
        except Exception as e:
            yf_text = f"err: {e}"
        yi_b64 = None; yi_text = ""
        try:
            yi_img = _yellow_inner_image(img_path, b["box"], scale=3)
            buf = io.BytesIO(); yi_img.save(buf, format="PNG")
            yi_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            yi_text = _tesseract_digit(yi_img)
        except Exception as e:
            yi_text = f"err: {e}"
        ocr = _ocr_digit(b["box"])
        slots.append({
            "name": b["name"],
            "box": b["box"],
            "crop": crop_b64,
            "binarized": bin_b64,
            "yellow_paint": yp_b64,
            "yellow_paint_ocr": yp_text,
            "yellow_filled": yf_b64,
            "yellow_filled_ocr": yf_text,
            "yellow_inner": yi_b64,
            "yellow_inner_ocr": yi_text,
            "lead_digit": _normalize_lead_digit(yi_text),
            "ocr": ocr,
        })

    return {"filename": filename, "slots": slots}


@app.get("/api/tp-cursor/list")
async def tp_cursor_list():
    screen_dir = TEST_IMAGES_DIR / "team_preview_selecting"
    if not screen_dir.exists():
        return {"files": []}
    files = sorted([
        f.name for f in screen_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".png" and _is_real_image(f.name)
    ])
    return {"files": files}


@app.get("/api/tp-cursor/read")
async def tp_cursor_read(filename: str):
    """For one team_preview_selecting image, return the 6 highlight crops
    + per-slot yellow-score (mirrors C++ TeamPreviewCursorReader::read).
    Mirrors the C++ formula: (R+G)/2 - B, floor 30; highest scoring slot wins."""
    import base64
    from PIL import Image
    img_path = TEST_IMAGES_DIR / "team_preview_selecting" / filename
    if not img_path.exists():
        return JSONResponse({"error": "not found"}, 404)

    boxes = CROP_DEFS.get("TeamPreviewCursorReader") or []

    def _yellow_score(box):
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        x0 = max(0, int(box[0]*w)); y0 = max(0, int(box[1]*h))
        x1 = min(w, x0+int(box[2]*w)); y1 = min(h, y0+int(box[3]*h))
        crop = img.crop((x0, y0, x1, y1))
        if crop.size[0] == 0 or crop.size[1] == 0:
            return None
        pixels = list(crop.getdata())
        n = len(pixels)
        r = sum(p[0] for p in pixels) / n
        g = sum(p[1] for p in pixels) / n
        b = sum(p[2] for p in pixels) / n
        score = (r + g) / 2 - b
        return {"r": round(r, 1), "g": round(g, 1), "b": round(b, 1),
                "score": round(score, 1)}

    slots = []
    for i, b in enumerate(boxes):
        try:
            crop_b64 = "data:image/png;base64," + base64.b64encode(
                _extract_crop(img_path, b["box"], scale=4)
            ).decode()
        except Exception:
            crop_b64 = None
        stats = _yellow_score(b["box"])
        slots.append({
            "slot": i,
            "name": b["name"],
            "box": b["box"],
            "crop": crop_b64,
            "stats": stats,
        })

    FLOOR = 30.0
    best_slot = -1
    best_score = 0.0
    for s in slots:
        st = s["stats"]
        if st and st["score"] > best_score and st["score"] >= FLOOR:
            best_score = st["score"]
            best_slot = s["slot"]

    img_b64 = "data:image/png;base64," + base64.b64encode(img_path.read_bytes()).decode()
    return {
        "filename": filename,
        "image": img_b64,
        "floor": FLOOR,
        "selected_slot": best_slot,
        "slots": slots,
    }


@app.get("/api/hp-gallery")
async def hp_gallery():
    """For each action_menu + move_select image, return the 4 HP crops
    (opp0/opp1/own0/own1) + the BattleHUDReader's reads. Mirror of
    /api/pp-gallery but for HP boxes."""
    import base64
    from concurrent.futures import ThreadPoolExecutor, as_completed

    hp_box_names = ["opp0_hp_pct", "opp1_hp_pct", "own0_hp", "own1_hp"]
    hp_boxes = [c for c in CROP_DEFS["BattleHUDReader"] if c["name"] in hp_box_names]
    targets = []  # (screen, path)
    manifests = {}
    for screen in ("action_menu", "move_select"):
        d = TEST_IMAGES_DIR / screen
        if not d.exists():
            continue
        manifests[screen] = _load_manifest(d)
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() == ".png" and _is_real_image(f.name):
                targets.append((screen, f))

    def work(item):
        screen, img_path = item
        crops = []
        for cd in hp_boxes:
            try:
                crops.append({
                    "name": cd["name"],
                    "data": "data:image/png;base64," + base64.b64encode(_extract_crop(img_path, cd["box"], scale=6)).decode(),
                })
            except Exception:
                crops.append({"name": cd["name"], "data": None})
        result, err = _suggest_via_runner(screen, img_path.name, "BattleHUDReader")
        result = result or {}
        m_entry = (manifests.get(screen, {}).get(img_path.name) or {}).get("BattleHUDReader") or {}
        return {
            "filename": img_path.name,
            "screen": screen,
            "thumb": f"/api/gallery/thumb/{screen}/{img_path.name}",
            "crops": crops,
            "opp_hp_pct":             result.get("opponent_hp_pct",   [-1, -1]),
            "own_hp_current":         result.get("own_hp_current",    [-1, -1]),
            "own_hp_max":             result.get("own_hp_max",        [-1, -1]),
            "own_hp_current_raw":     result.get("own_hp_current_raw",[-1, -1]),
            "own_hp_max_raw":         result.get("own_hp_max_raw",    [-1, -1]),
            "manifest_opp_hp_pct":    m_entry.get("opponent_hp_pct"),
            "manifest_own_hp_current":m_entry.get("own_hp_current"),
            "manifest_own_hp_max":    m_entry.get("own_hp_max"),
            "error": err,
        }

    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(work, t) for t in targets]
        for fut in as_completed(futs):
            out.append(fut.result())
    out.sort(key=lambda r: (r["screen"], r["filename"]))
    return {"images": out, "count": len(out)}


@app.get("/api/pp-gallery")
async def pp_gallery():
    """For each move_select test image, return the 4 PP crops + the
    BattleHUDReader's current PP read for each slot + manifest's expected
    values (if any). Used by the PP Crops view for visual tuning."""
    import base64
    from concurrent.futures import ThreadPoolExecutor, as_completed
    screen_dir = TEST_IMAGES_DIR / "move_select"
    if not screen_dir.exists():
        return {"images": []}
    pp_boxes = [c for c in CROP_DEFS["BattleHUDReader"] if c["name"].startswith("pp_")]
    files = sorted(f for f in screen_dir.iterdir()
                   if f.is_file() and f.suffix.lower() == ".png" and _is_real_image(f.name))
    manifest = _load_manifest(screen_dir)

    def work(img_path):
        crops = []
        for cd in pp_boxes:
            try:
                crops.append({
                    "name": cd["name"],
                    "data": "data:image/png;base64," + base64.b64encode(_extract_crop(img_path, cd["box"], scale=6)).decode(),
                })
            except Exception:
                crops.append({"name": cd["name"], "data": None})
        result, err = _suggest_via_runner("move_select", img_path.name, "BattleHUDReader")
        pp_cur = (result or {}).get("move_pp_current", [-1, -1, -1, -1])
        m_entry = (manifest.get(img_path.name) or {}).get("BattleHUDReader") or {}
        manifest_pp = m_entry.get("move_pp_current")
        return {
            "filename": img_path.name,
            "thumb": f"/api/gallery/thumb/move_select/{img_path.name}",
            "crops": crops,
            "pp_current": pp_cur if isinstance(pp_cur, list) else [-1, -1, -1, -1],
            "manifest_pp_current": manifest_pp if isinstance(manifest_pp, list) else None,
            "error": err,
        }

    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(work, f): f for f in files}
        for fut in as_completed(futs):
            out.append(fut.result())
    out.sort(key=lambda r: r["filename"])
    return {"images": out, "count": len(out)}


@app.post("/api/inbox/scan-battle-log")
async def inbox_scan_battle_log():
    """Run BattleLogReader on every _inbox/*.png. Returns {filename: {event_type, raw_text, error?}}.
    Cached by mtime so repeated calls are cheap."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not INBOX_DIR.exists():
        return {"results": {}}
    files = [f for f in sorted(INBOX_DIR.glob("*.png")) if _is_real_image(f.name)]
    out = {}

    def work(f):
        mtime = f.stat().st_mtime
        cached = _INBOX_LOG_CACHE.get(f.name)
        if cached and cached[0] == mtime:
            return f.name, cached[1]
        result, err = _ocr_suggest_inbox(f.name, "BattleLogReader")
        if err:
            entry = {"error": err}
        else:
            entry = {
                "event_type": result.get("event_type"),
                "raw_text": result.get("event_type_raw") or "",
            }
        _INBOX_LOG_CACHE[f.name] = (mtime, entry)
        return f.name, entry

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(work, f) for f in files]
        for fut in as_completed(futs):
            name, entry = fut.result()
            out[name] = entry
    return {"results": out, "count": len(out)}


@app.post("/api/inbox/accept-battle-log")
async def inbox_accept_battle_log(request: Request):
    """Accept an inbox image as a labeled battle_log overlay sample.
    Body: {filename, event_type}. Moves image to _overlays/battle_log/
    and writes manifest entry."""
    body = await request.json()
    filename = body.get("filename", "")
    event_type = (body.get("event_type") or "").strip()
    if not filename or not event_type:
        return JSONResponse({"error": "filename and event_type required"}, 400)
    src = INBOX_DIR / filename
    if not src.exists():
        return JSONResponse({"error": "inbox image not found"}, 404)
    target_dir = TEST_IMAGES_DIR / "_overlays" / "battle_log"
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    shutil.move(str(src), str(dest))
    manifest = _load_manifest(target_dir)
    manifest[filename] = {"BattleLogReader": {"event_type": event_type}}
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    _INBOX_LOG_CACHE.pop(filename, None)
    return {"ok": True, "filename": filename, "event_type": event_type}


@app.post("/api/inbox/delete")
async def inbox_delete(request: Request):
    """Delete an inbox image."""
    body = await request.json()
    filename = body.get("filename", "")
    if not filename:
        return JSONResponse({"error": "filename required"}, 400)
    src = INBOX_DIR / filename
    if not src.exists():
        return JSONResponse({"error": "not found"}, 404)
    src.unlink()
    _INBOX_LOG_CACHE.pop(filename, None)
    return {"ok": True, "filename": filename}


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


def _team_scan_ps_paste(slots: list) -> str:
    """Render 6 merged slot dicts as a Pokemon Showdown set paste."""
    out = []
    for s in slots:
        species = (s.get("species") or "Unknown").title()
        item = (s.get("item") or "").replace("-", " ").title()
        ability = (s.get("ability") or "").replace("-", " ").title()
        nature = s.get("nature") or ""
        moves = [m for m in (s.get("moves") or []) if m]
        evs = s.get("evs") or {}
        ev_parts = []
        for k, label in [("hp","HP"),("atk","Atk"),("def","Def"),("spa","SpA"),("spd","SpD"),("spe","Spe")]:
            v = evs.get(k, 0)
            if v: ev_parts.append(f"{v} {label}")

        block = [f"{species}" + (f" @ {item}" if item else "")]
        if ability: block.append(f"Ability: {ability}")
        if ev_parts: block.append("EVs: " + " / ".join(ev_parts))
        if nature: block.append(f"{nature} Nature")
        for m in moves:
            block.append(f"- {m.replace('-', ' ').title()}")
        out.append("\n".join(block))
    return "\n\n".join(out)


@app.post("/api/team-scan/read")
async def team_scan_read(request: Request):
    """Run TeamSummaryReader on the M&M screenshot + TeamStatsReader on the
    Stats screenshot, merge per-slot, and render as a PS paste.
    Body: {moves_more_file, stats_file} — both relative paths under
    test_images/{moves_and_more,team_stats}/."""
    body = await request.json()
    mm_file = body.get("moves_more_file", "")
    st_file = body.get("stats_file", "")

    mm_result, err = _suggest_via_runner("moves_and_more", mm_file, "TeamSummaryReader")
    if err:
        return JSONResponse({"ok": False, "error": f"moves_and_more: {err}"}, 500)
    st_result, err = _suggest_via_runner("team_stats", st_file, "TeamStatsReader")
    if err:
        return JSONResponse({"ok": False, "error": f"team_stats: {err}"}, 500)

    mm_slots = (mm_result or {}).get("slots", [])
    st_slots = (st_result or {}).get("slots", [])
    merged = []
    for i in range(6):
        m = mm_slots[i] if i < len(mm_slots) else {}
        s = st_slots[i] if i < len(st_slots) else {}
        stats = s.get("stats", {})
        merged.append({
            "slot": i,
            "species": m.get("species", ""),
            "ability": m.get("ability", ""),
            "item":    m.get("item", ""),
            "moves":   m.get("moves", ["", "", "", ""]),
            "nature":  s.get("nature", ""),
            "stats":   stats,                       # full per-stat detail (actual/evs/nature/raw_*)
            "evs":     {k: stats.get(k, {}).get("evs", 0) for k in ["hp","atk","def","spa","spd","spe"]},
        })

    return {
        "ok": True,
        "slots": merged,
        "ps_paste": _team_scan_ps_paste(merged),
        "moves_more_file": mm_file,
        "stats_file": st_file,
    }


@app.get("/api/team-scan/crops")
async def team_scan_crops(slot: int, mm_file: str = "", st_file: str = ""):
    """Return per-field crops for one slot's M&M boxes + Stats boxes,
    pulled straight from tools/box_definitions.json. Used by the Team Scan
    tab's per-slot expand panel for OCR debugging."""
    import base64
    if slot < 0 or slot > 5:
        return JSONResponse({"error": "slot out of range"}, 400)
    defs = json.loads(BOX_DEFINITIONS_PATH.read_text()) if BOX_DEFINITIONS_PATH.exists() else {"boxes": []}

    mm_path = TEST_IMAGES_DIR / "moves_and_more" / mm_file if mm_file else None
    st_path = TEST_IMAGES_DIR / "team_stats" / st_file if st_file else None

    def crop_or_none(img_path, box):
        if not img_path or not img_path.exists(): return None
        return f"data:image/png;base64,{base64.b64encode(_extract_crop(img_path, box)).decode()}"

    # M&M fields live on the moves_and_more screenshot.
    # Stats fields live on the team_stats screenshot.
    # Slot 0's name box is unique: "mon_0_species" not "mon_0_name".
    name_field = "species" if slot == 0 else "name"
    mm_fields = [name_field, "ability", "item", "move_0", "move_1", "move_2", "move_3"]
    stat_fields = []
    for stat in ["hp", "atk", "def", "spa", "spd", "spe"]:
        for sub in ["actual", "evs"] + ([] if stat == "hp" else ["nature"]):
            stat_fields.append(f"{stat}_{sub}")

    out = {"slot": slot, "mm": [], "stats": []}
    by_name = {b["name"]: b for b in defs["boxes"]}
    for f in mm_fields:
        key = f"mon_{slot}_{f}"
        b = by_name.get(key)
        if not b: continue
        out["mm"].append({"field": f, "name": key, "box": b["box"],
                          "data": crop_or_none(mm_path, b["box"])})
    for f in stat_fields:
        key = f"mon_{slot}_{f}"
        b = by_name.get(key)
        if not b: continue
        out["stats"].append({"field": f, "name": key, "box": b["box"],
                             "data": crop_or_none(st_path, b["box"])})
    return out


@app.get("/api/team-scan/latest")
async def team_scan_latest():
    """Return the most-recent M&M and Stats screenshots (mtime-sorted) so the
    UI auto-loads the freshest pair without the user picking files."""
    mm_dir = TEST_IMAGES_DIR / "moves_and_more"
    st_dir = TEST_IMAGES_DIR / "team_stats"
    def newest_png(d):
        if not d.exists(): return None
        files = [f for f in d.iterdir() if f.suffix == ".png"]
        if not files: return None
        return max(files, key=lambda f: f.stat().st_mtime).name
    return {
        "ok": True,
        "moves_more_file": newest_png(mm_dir),
        "stats_file": newest_png(st_dir),
    }


@app.get("/api/sprites/list")
async def sprites_list():
    """Return the list of sprite slugs in the Pokemon Champions atlas.
    Includes "-shiny" variants if the shiny atlas is present."""
    json_path = RESOURCES_DIR / "PokemonSprites.json"
    if not json_path.exists():
        return JSONResponse({"error": "sprite resources not found"}, 404)
    meta = json.loads(json_path.read_text())
    locs = meta.get("spriteLocations", {})
    names = list(locs.keys())
    shiny_path = RESOURCES_DIR / "PokemonSpritesShiny.json"
    if shiny_path.exists():
        shiny_meta = json.loads(shiny_path.read_text())
        names.extend(s + "-shiny" for s in shiny_meta.get("spriteLocations", {}).keys())
    return {
        "ok": True,
        "count": len(names),
        "sprite_size": [meta.get("spriteWidth", 128), meta.get("spriteHeight", 128)],
        "names": sorted(names),
    }


@app.get("/api/sprites/examples")
async def sprites_examples(limit: int = 100):
    """Return labeled team-preview frames with the actual opp-sprite crops
    (base64 PNG) alongside the reference sprite slug for each slot.

    Mirrors C++ TeamPreviewReader's locked-in opp coords so the crop the
    user sees here is exactly what the matcher consumed.
    """
    import base64
    from PIL import Image
    def _crop_b64(img, box, scale=4):
        w, h = img.size
        x0, y0 = max(0, int(box[0]*w)), max(0, int(box[1]*h))
        x1, y1 = min(w, x0+int(box[2]*w)), min(h, y0+int(box[3]*h))
        cr = img.crop((x0, y0, x1, y1))
        cw, ch = cr.size
        up = cr.resize((min(cw*scale, 480), min(ch*scale, 240)), Image.NEAREST)
        buf = io.BytesIO()
        up.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    OPP_LOCKED = (0.7181, 0.1482, 0.7310, 0.0664, 0.1009)
    OPP_SELECT = (0.8390, 0.1473, 0.7317, 0.0604, 0.0986)
    def opp_boxes(coords):
        x, y0, y5, w, h = coords
        step = (y5 - y0) / 5.0
        return [[x, y0 + i * step, w, h] for i in range(6)]

    #  Own species text labels (the C++ reader OCRs these). Linear interp
    #  matches PokemonChampions_TeamPreviewReader.cpp.
    OWN_X0, OWN_X5 = 0.0760, 0.0724
    OWN_Y0, OWN_Y5 = 0.1565, 0.7389
    OWN_W, OWN_H = 0.0969, 0.0389
    OWN_BOXES = [
        [OWN_X0 + (i/5.0)*(OWN_X5 - OWN_X0),
         OWN_Y0 + (i/5.0)*(OWN_Y5 - OWN_Y0),
         OWN_W, OWN_H]
        for i in range(6)
    ]
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
            own = tp.get("own_species") or []
            if not any(opp) and not any(own):
                continue
            img_path = screen_dir / fname
            if not img_path.exists():
                continue
            is_locked_in = "locked_in" in screen_name
            boxes = opp_boxes(OPP_LOCKED if is_locked_in else OPP_SELECT)
            img = Image.open(img_path).convert("RGB")
            opp_slots = [{
                "species": (opp[i] if i < len(opp) else "") or "",
                "crop": f"data:image/png;base64,{_crop_b64(img, boxes[i])}",
            } for i in range(6)]
            #  Locked-in screen: own column is icon-only (no text). Selecting
            #  screen: own column is species TEXT + item TEXT. Only render
            #  the My-side text-OCR panel for selecting frames.
            own_slots = [] if is_locked_in else [{
                "species": (own[i] if i < len(own) else "") or "",
                "crop": f"data:image/png;base64,{_crop_b64(img, OWN_BOXES[i])}",
            } for i in range(6)]
            examples.append({
                "screen": screen_name,
                "filename": fname,
                "opp_slots": opp_slots,
                "own_slots": own_slots,
            })
            if len(examples) >= limit:
                return {"ok": True, "examples": examples, "truncated": True}
    return {"ok": True, "examples": examples, "truncated": False}


@app.get("/api/sprites/battlehud_examples")
async def sprites_battlehud_examples(limit: int = 50, aggregate: bool = True):
    """For labeled action_menu frames, crop slot 0 + slot 1 own-species
    icons (boxes saved as own_specoes_icon_0/1) and run sprite-match against
    the atlas. Returns crop b64 + ground truth + top-N matches per slot.

    aggregate=true (default): one entry per unique (slot, ground_truth)
    species, picking the first frame each. Cuts subprocess calls from ~2*N
    to ~unique-species. Pass aggregate=false for the per-frame view.
    """
    import base64, urllib.request, urllib.error
    from PIL import Image

    SLOT_BOXES = {
        0: [0.0249, 0.8763, 0.0556, 0.0803],  # own_specoes_icon_0
        1: [0.2301, 0.8840, 0.0576, 0.0753],  # own_specoes_icon_1
    }
    #  Ask matcher for ALL candidates so the team-atlas filter has every
    #  slug to choose from (atlas is 544 entries: 272 normal + 272 shiny).
    #  Filter happens after matcher returns; we render top 3 of survivors.
    TOP_N = 600
    RENDER_TOP_N = 3

    def _crop_b64(img, box, scale=4):
        w, h = img.size
        x0, y0 = max(0, int(box[0]*w)), max(0, int(box[1]*h))
        x1, y1 = min(w, x0+int(box[2]*w)), min(h, y0+int(box[3]*h))
        cr = img.crop((x0, y0, x1, y1))
        cw, ch = cr.size
        up = cr.resize((min(cw*scale, 480), min(ch*scale, 320)), Image.NEAREST)
        buf = io.BytesIO()
        up.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _sprite_match(img_b64: str, box: list) -> dict:
        payload = json.dumps({
            "image_base64": img_b64,
            "x": box[0], "y": box[1], "w": box[2], "h": box[3],
            "top_n": TOP_N,
        }).encode()
        try:
            req = urllib.request.Request(
                f"{DEV_RUNNER}/sprite-match", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read())
                return d.get("result", {}).get("matches", [])
        except (urllib.error.URLError, urllib.error.HTTPError):
            return []
        except Exception:
            return []

    screen_dir = TEST_IMAGES_DIR / "action_menu"
    if not screen_dir.exists():
        return {"ok": True, "examples": []}

    def _strip_shiny(slug: str) -> str:
        return slug[:-len("-shiny")] if slug.endswith("-shiny") else slug

    manifest = _load_manifest(screen_dir)

    #  Bg paint colors. Each = [r, g, b, dist]. Pixels within dist of any
    #  color get repainted white before matching.
    BG_COLORS = [
        [160, 140, 255, 50],   # pill purple
        [180, 255,   0, 80],   # active-turn lime green outline
    ]

    #  Team-atlas filter. The matcher runs against all 544 atlas entries,
    #  but we only accept results from this set -- "the cole team and the
    #  obvious opponents that show up in labeled frames". This collapses
    #  spurious lookalikes (altaria-mega-shiny dominating Sneasler, etc.)
    #  by removing them from the candidate pool entirely.
    #
    #  Includes: own team's normal + shiny + mega forms (where applicable),
    #  plus the species that actually appear as opponents in labeled
    #  action_menu frames.
    OWN_TEAM = [
        "charizard", "charizard-mega-x", "charizard-mega-y",
        "venusaur", "venusaur-mega",
        "garchomp", "garchomp-mega",
        "sneasler",
        "incineroar",
        "meganium",
        "delphox",
        "basculegion",
        "archaludon",
    ]
    TEAM_ALLOWED = set()
    for slug in OWN_TEAM:
        TEAM_ALLOWED.add(slug)
        TEAM_ALLOWED.add(slug + "-shiny")

    def _sprite_match_debug(img_b64: str, box: list) -> dict:
        """Returns {matches, auto_crop_b64} or {} on failure.
        Matches are filtered to TEAM_ALLOWED then trimmed to RENDER_TOP_N."""
        payload = json.dumps({
            "image_base64": img_b64,
            "x": box[0], "y": box[1], "w": box[2], "h": box[3],
            "top_n": TOP_N,
            "bg": BG_COLORS,
        }).encode()
        try:
            req = urllib.request.Request(
                f"{DEV_RUNNER}/sprite-match-debug", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.loads(resp.read())
                result = d.get("result") or {}
                all_matches = result.get("matches") or []
                #  Team-atlas filter: keep only matches whose slug (base or
                #  shiny variant) is in TEAM_ALLOWED. Preserve sort order
                #  (already alpha-ascending from matcher).
                filtered = [m for m in all_matches if m.get("slug") in TEAM_ALLOWED]
                result["matches"] = filtered[:RENDER_TOP_N]
                result["matches_unfiltered_count"] = len(all_matches)
                return result
        except Exception:
            return {}

    def _is_correct(matches: list, gt: str, gt_shiny: bool) -> bool:
        if not matches or not gt:
            return False
        top = matches[0].get("slug", "")
        if _strip_shiny(top) != gt:
            return False
        is_shiny = top.endswith("-shiny")
        return is_shiny == gt_shiny

    if aggregate:
        #  Group frames by (slot, gt). Pick first frame per group, run
        #  sprite-match-debug once (returns matches + auto-cropped preview).
        seen: dict[tuple[int, str], dict] = {}
        order: list[tuple[int, str]] = []
        for fname, labels in manifest.items():
            bh = labels.get("BattleHUDReader")
            if not isinstance(bh, dict):
                continue
            own = bh.get("own_species") or []
            shiny = bh.get("own_species_shiny") or []
            if not any(own):
                continue
            img_path = screen_dir / fname
            if not img_path.exists():
                continue
            for slot_idx in SLOT_BOXES:
                gt = (own[slot_idx] if slot_idx < len(own) else "") or ""
                if not gt:
                    continue
                gt_shiny = bool(shiny[slot_idx]) if slot_idx < len(shiny) else False
                key = (slot_idx, gt, gt_shiny)
                if key in seen:
                    continue
                seen[key] = {"filename": fname, "img_path": img_path,
                             "gt_shiny": gt_shiny}
                order.append(key)

        rows = []
        img_cache = {}
        for (slot_idx, gt, gt_shiny) in order[:limit]:
            entry = seen[(slot_idx, gt, gt_shiny)]
            img_path = entry["img_path"]
            if img_path not in img_cache:
                img_cache[img_path] = (
                    Image.open(img_path).convert("RGB"),
                    base64.b64encode(img_path.read_bytes()).decode(),
                )
            img, img_b64 = img_cache[img_path]
            box = SLOT_BOXES[slot_idx]
            dbg = _sprite_match_debug(img_b64, box)
            matches = dbg.get("matches", [])
            auto_crop = dbg.get("auto_crop_b64") or ""
            rows.append({
                "slot": slot_idx,
                "ground_truth": gt,
                "ground_truth_shiny": gt_shiny,
                "filename": entry["filename"],
                "crop": f"data:image/png;base64,{_crop_b64(img, box)}",
                "auto_crop": f"data:image/png;base64,{auto_crop}" if auto_crop else "",
                "matches": matches,
                "top_correct": _is_correct(matches, gt, gt_shiny),
            })
        return {"ok": True, "aggregated": True, "rows": rows, "count": len(rows)}

    #  Per-frame mode (legacy / detailed view).
    examples = []
    for fname, labels in manifest.items():
        bh = labels.get("BattleHUDReader")
        if not isinstance(bh, dict):
            continue
        own = bh.get("own_species") or []
        if not any(own):
            continue
        img_path = screen_dir / fname
        if not img_path.exists():
            continue
        img = Image.open(img_path).convert("RGB")
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()

        slots = []
        for slot_idx, box in SLOT_BOXES.items():
            matches = _sprite_match(img_b64, box)
            gt = (own[slot_idx] if slot_idx < len(own) else "") or ""
            slots.append({
                "slot": slot_idx,
                "ground_truth": gt,
                "crop": f"data:image/png;base64,{_crop_b64(img, box)}",
                "matches": matches,
                "top_correct": bool(matches and _strip_shiny(matches[0].get("slug","")) == gt),
            })
        examples.append({"filename": fname, "slots": slots})
        if len(examples) >= limit:
            break
    return {"ok": True, "aggregated": False, "examples": examples, "count": len(examples)}


#  Pokeball detector boxes: mirrors PokemonChampions_PokeballAliveDetector.cpp.
#  Keep these in sync with the C++ side (which is the production path).
POKEBALL_OWN_BOXES = [
    [0.0518, 0.8155, 0.0085, 0.0155],
    [0.0660, 0.8154, 0.0087, 0.0152],
    [0.0801, 0.8152, 0.0090, 0.0149],
    [0.0943, 0.8151, 0.0092, 0.0146],
    [0.1085, 0.8150, 0.0094, 0.0143],
    [0.1226, 0.8148, 0.0097, 0.0140],
]
POKEBALL_OPP_BOXES = [
    [0.8665, 0.1664, 0.0110, 0.0125],
    [0.8809, 0.1677, 0.0106, 0.0113],
    [0.8953, 0.1677, 0.0103, 0.0111],
    [0.9097, 0.1677, 0.0099, 0.0109],
    [0.9241, 0.1677, 0.0099, 0.0109],
    [0.9385, 0.1677, 0.0099, 0.0109],
]


def _classify_pokeball_state(arr) -> str:
    """Mean-green threshold classifier. Mirrors the C++ classify(). Pure
    Python so the dashboard can scan hundreds of frames without paying
    the dev-runner round-trip per frame.
    """
    if arr.size == 0:
        return "empty"
    mean_g = float(arr[:, :, 1].mean())
    if mean_g >= 150.0:
        return "alive"
    if mean_g >= 67.0:
        return "fainted"
    return "empty"


@app.get("/api/pokeballs/scan")
async def pokeballs_scan(offset: int = 0, limit: int = 50):
    """Run PokeballAliveDetector on a page of frames from action_menu /
    move_select / battle_log and return per-frame state + thumbnail URLs.

    Implementation: pure-Python mirror of the C++ classifier (mean green
    > 150 = alive, > 67 = fainted, else empty). The C++ path is the
    production source of truth; this dashboard scan reimplements it for
    speed (no subprocess / Tailscale round-trip per frame).
    """
    import numpy as np
    from PIL import Image

    def _classify_frame(img_path: Path) -> dict:
        try:
            img = np.asarray(Image.open(img_path).convert("RGB"))
        except Exception as e:
            return {"error": str(e), "own": [], "opp": []}
        H, W, _ = img.shape

        def crop_state(box):
            x, y, w, h = box
            x0, y0 = max(0, int(x*W)), max(0, int(y*H))
            x1, y1 = min(W, x0 + int(w*W)), min(H, y0 + int(h*H))
            return _classify_pokeball_state(img[y0:y1, x0:x1])

        own = [crop_state(b) for b in POKEBALL_OWN_BOXES]
        opp = [crop_state(b) for b in POKEBALL_OPP_BOXES]
        return {
            "own": own,
            "opp": opp,
            "own_alive": sum(1 for s in own if s == "alive"),
            "opp_alive": sum(1 for s in opp if s == "alive"),
        }

    all_frames = []
    for screen in ("action_menu", "move_select", "battle_log"):
        screen_dir = TEST_IMAGES_DIR / screen
        if not screen_dir.exists():
            continue
        for img_path in sorted(screen_dir.glob("*.png")):
            if img_path.name.startswith("_"):
                continue
            all_frames.append((screen, img_path))

    total = len(all_frames)
    page = all_frames[offset : offset + limit]

    results = []
    for screen, img_path in page:
        r = _classify_frame(img_path)
        results.append({
            "screen": screen,
            "filename": img_path.name,
            **r,
        })
    return {
        "ok": True,
        "offset": offset,
        "limit": limit,
        "total": total,
        "count": len(results),
        "frames": results,
    }


@app.get("/api/switchprobe/scan")
async def switchprobe_scan():
    """Run the four-box PokemonSwitchDetector logic across every image in
    test_images/pokemon_switch and return per-image box averages + the
    pass/fail verdict. Mirrors PokemonChampions_PokemonSwitchDetector.cpp:
        active   = b < 60 && g > 150
        inactive = b > 80 && r < 80 && g < 80
        accept   = (moves both active && stats both inactive)
                || (moves both inactive && stats both active)
    Boxes are pulled from CROP_DEFS["PokemonSwitchDetector"] so the page
    stays in sync with the inspector.
    """
    import base64
    import urllib.request
    import urllib.error
    import numpy as np
    from PIL import Image

    boxes = CROP_DEFS.get("PokemonSwitchDetector", [])
    screen_dirs = [
        TEST_IMAGES_DIR / "singles_switch",
        TEST_IMAGES_DIR / "doubles_switch",
    ]

    def _run_reader(img_path: Path):
        """Subprocess the dev runner's PokemonSwitchReader for this image."""
        try:
            payload = json.dumps({
                "image_base64": base64.b64encode(img_path.read_bytes()).decode(),
                "reader": "PokemonSwitchReader",
                "screen": "pokemon_switch",
            }).encode()
            req = urllib.request.Request(
                f"{DEV_RUNNER}/ocr-suggest",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                envelope = json.loads(resp.read())
            if not envelope.get("ok"):
                return None, envelope.get("error", "unknown")
            return envelope.get("result", {}) or {}, None
        except urllib.error.URLError as e:
            return None, f"dev runner unreachable: {e}"
        except Exception as e:
            return None, str(e)

    def is_active(r, g, b):
        return b < 60.0 and g > 150.0

    def is_inactive(r, g, b):
        return b > 80.0 and r < 80.0 and g < 80.0

    frames = []
    for screen_dir in screen_dirs:
        if not screen_dir.exists():
            continue
        for img_path in sorted(screen_dir.glob("*.png")):
            if img_path.name.startswith("_"):
                continue
            try:
                img = np.asarray(Image.open(img_path).convert("RGB"))
            except Exception as e:
                frames.append({"filename": img_path.name, "dir": screen_dir.name, "error": str(e)})
                continue
            H, W, _ = img.shape
            box_results = []
            states = {}
            for b in boxes:
                x, y, w, h = b["box"]
                x0, y0 = max(0, int(x*W)), max(0, int(y*H))
                x1, y1 = min(W, x0 + int(w*W)), min(H, y0 + int(h*H))
                crop = img[y0:y1, x0:x1]
                if crop.size == 0:
                    avg = [0.0, 0.0, 0.0]
                else:
                    avg = crop.reshape(-1, 3).mean(axis=0).tolist()
                rr, gg, bb = avg
                if is_active(rr, gg, bb):
                    state = "active"
                elif is_inactive(rr, gg, bb):
                    state = "inactive"
                else:
                    state = "neither"
                states[b["name"]] = state
                box_results.append({
                    "name": b["name"],
                    "box": b["box"],
                    "avg": [round(v, 1) for v in avg],
                    "state": state,
                })
            moves_active   = states.get("moves_left") == "active"   and states.get("moves_right") == "active"
            moves_inactive = states.get("moves_left") == "inactive" and states.get("moves_right") == "inactive"
            stats_active   = states.get("stats_left") == "active"   and states.get("stats_right") == "active"
            stats_inactive = states.get("stats_left") == "inactive" and states.get("stats_right") == "inactive"
            verdict = (moves_active and stats_inactive) or (moves_inactive and stats_active)
            if moves_active and stats_inactive:
                explanation = "moves active + stats inactive"
            elif moves_inactive and stats_active:
                explanation = "stats active + moves inactive"
            else:
                bits = []
                for tab, lname, rname in [("moves", "moves_left", "moves_right"),
                                          ("stats", "stats_left", "stats_right")]:
                    bits.append(f"{tab}=[{states[lname]},{states[rname]}]")
                explanation = "fail: " + " ".join(bits)
            reader_result, reader_err = _run_reader(img_path)
            #  Per-slot OCR crops, keyed by box name. Lets the dashboard show
            #  exactly what each reader box sampled — useful for diagnosing
            #  garbled HP/species reads.
            reader_crops = {}
            for cd in CROP_DEFS.get("PokemonSwitchReader", []):
                try:
                    reader_crops[cd["name"]] = (
                        f"data:image/png;base64,"
                        + base64.b64encode(_extract_crop(img_path, cd["box"])).decode()
                    )
                except Exception:
                    pass
            frames.append({
                "filename": img_path.name,
                "dir": screen_dir.name,
                "boxes": box_results,
                "verdict": verdict,
                "explanation": explanation,
                "reader": reader_result,
                "reader_error": reader_err,
                "reader_crops": reader_crops,
            })
    return {
        "ok": True,
        "boxes": [b["name"] for b in boxes],
        "thresholds": {
            "active": "b < 60 && g > 150",
            "inactive": "b > 80 && r < 80 && g < 80",
        },
        "count": len(frames),
        "frames": frames,
    }


@app.get("/api/teampreview/sprite/{slug}")
async def teampreview_sprite(slug: str):
    """Extract a single sprite from the atlas PNG. A "-shiny" suffix
    redirects to the shiny atlas (PokemonSpritesShiny.{png,json})."""
    from PIL import Image
    if slug.endswith("-shiny"):
        base = slug[:-len("-shiny")]
        json_path = RESOURCES_DIR / "PokemonSpritesShiny.json"
        atlas_path = RESOURCES_DIR / "PokemonSpritesShiny.png"
    else:
        base = slug
        json_path = RESOURCES_DIR / "PokemonSprites.json"
        atlas_path = RESOURCES_DIR / "PokemonSprites.png"
    if not json_path.exists() or not atlas_path.exists():
        return JSONResponse({"error": "sprite resources not found"}, 404)
    meta = json.loads(json_path.read_text())
    loc = meta.get("spriteLocations", {}).get(base)
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

    # ref_frames (VOD/YouTube extracts) intentionally excluded — labeler
    # surfaces only labeled test_images/ + _overlays/ folders.

    # test_images subdirectories (labeled test frames from CommandLineTests)
    if TEST_IMAGES_DIR.exists():
        for reader_dir in sorted(TEST_IMAGES_DIR.iterdir()):
            if not reader_dir.is_dir(): continue
            # _overlays/ holds overlay screens nested one level deeper; handle below.
            if reader_dir.name == "_overlays": continue
            imgs = [f for f in reader_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and _is_real_image(f.name)]
            if imgs:
                folder = reader_dir.name
                #  Map folder -> canonical reader names. Falls back to the
                #  folder name (legacy 1:1 mapping) for older folders that
                #  haven't been registered in FOLDER_TO_READER / FOLDER_READERS.
                readers = FOLDER_READERS.get(folder, [FOLDER_TO_READER.get(folder, folder)])
                suggested = FOLDER_TO_READER.get(folder, folder)
                sources.append({
                    "path": f"__test__/{folder}",
                    "name": folder, "parent": "test_images", "count": len(imgs),
                    "suggested_reader": suggested,
                    "readers": readers,
                    "reader_infos": {
                        r: {"reader": r,
                            "type": READER_TYPES.get(r, "unknown"),
                            "is_bool": r in BOOL_DETECTORS,
                            "crops": CROP_DEFS.get(r, []),
                            "events": BATTLE_LOG_EVENTS if r == "BattleLogReader" else None}
                        for r in readers
                    },
                })

    # _overlays/<name> — overlay screens (battle_log, ability_item, communicating, ...)
    overlays_dir = TEST_IMAGES_DIR / "_overlays"
    if overlays_dir.exists():
        overlays_cfg = (_load_screens_yaml() or {}).get("overlays", {}) or {}
        for ov_dir in sorted(overlays_dir.iterdir()):
            if not ov_dir.is_dir(): continue
            imgs = [f for f in ov_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and _is_real_image(f.name)]
            if not imgs: continue
            ov_name = ov_dir.name
            ov_def = overlays_cfg.get(ov_name, {}) or {}
            readers = list((ov_def.get("readers") or {}).keys())
            sources.append({
                "path": f"__test__/_overlays/{ov_name}",
                "name": ov_name, "parent": "test_images/_overlays", "count": len(imgs),
                "suggested_reader": readers[0] if readers else None,
                "readers": readers,
                "reader_infos": {
                    r: {"reader": r,
                        "type": READER_TYPES.get(r, "unknown"),
                        "is_bool": r in BOOL_DETECTORS,
                        "crops": CROP_DEFS.get(r, []),
                        "events": BATTLE_LOG_EVENTS if r == "BattleLogReader" else None}
                    for r in readers
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
# PAST TRAINING RUNS (jsonl logs on unraid container volume)
# ═══════════════════════════════════════════════════════════════════════════
#
# Action-model training writes per-epoch metrics to
#   /mnt/user/data/pokemon-champions/data/checkpoints/<run_id>.jsonl
# on the unraid host (mounted into the GPU container as /workspace/data/...).
# These are the historical record of completed runs — the live
# /api/training/sessions endpoint only knows about runs that reported via
# --dashboard, which the action-model trainer doesn't.

RUNS_HOST = os.environ.get("RUNS_HOST", "unraid")
RUNS_DIR = os.environ.get(
    "RUNS_DIR",
    "/mnt/user/data/pokemon-champions/data/checkpoints",
)

# cache: name -> (mtime, parsed_rows)
_runs_cache: dict[str, tuple[float, list[dict]]] = {}
_runs_listing: dict = {"ts": 0.0, "data": []}


async def _ssh_run(cmd: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "ssh", RUNS_HOST, cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ssh {RUNS_HOST}: {stderr.decode(errors='replace')[-300:]}")
    return stdout.decode(errors="replace")


async def _fetch_run(name: str, mtime: float) -> list[dict]:
    cached = _runs_cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    raw = await _ssh_run(f'cat "{RUNS_DIR}/{name}.jsonl"')
    rows: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    _runs_cache[name] = (mtime, rows)
    return rows


@app.get("/api/runs/list")
async def runs_list():
    """List past training runs from the unraid checkpoint dir.

    Returns one entry per .jsonl with mtime, num_epochs, and the
    first/last row so the UI can show a summary without fetching
    full epoch histories.
    """
    now = time.time()
    if now - _runs_listing["ts"] < 15:
        return _runs_listing["data"]

    listing = await _ssh_run(
        f'ls -la --time-style=+%s "{RUNS_DIR}"/*.jsonl 2>/dev/null || true'
    )
    files: list[tuple[str, float, int]] = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 7 or not parts[-1].endswith(".jsonl"):
            continue
        try:
            size = int(parts[4])
            mtime = float(parts[5])
            path = parts[-1]
        except (ValueError, IndexError):
            continue
        name = Path(path).stem
        files.append((name, mtime, size))

    out = []
    for name, mtime, size in files:
        try:
            rows = await _fetch_run(name, mtime)
        except RuntimeError:
            rows = []
        first = rows[0] if rows else {}
        last = rows[-1] if rows else {}
        out.append({
            "name": name,
            "mtime": mtime,
            "size": size,
            "num_epochs": len(rows),
            "first_epoch": first,
            "last_epoch": last,
        })

    out.sort(key=lambda r: r["mtime"], reverse=True)
    _runs_listing["ts"] = now
    _runs_listing["data"] = out
    return out


@app.get("/api/runs/get")
async def runs_get(names: str = Query(..., description="comma-separated run names")):
    """Return full per-epoch rows for one or more runs."""
    listing = await runs_list()
    by_name = {r["name"]: r for r in listing}
    out = {}
    for name in names.split(","):
        name = name.strip()
        if not name or name not in by_name:
            continue
        rows = await _fetch_run(name, by_name[name]["mtime"])
        out[name] = rows
    return out


# ── per-run notes (research log; lives on ash next to the dashboard) ──────

RUN_NOTES_PATH = BASE / "data" / "run_notes.json"


def _load_run_notes() -> dict:
    if not RUN_NOTES_PATH.exists():
        return {}
    try:
        return json.loads(RUN_NOTES_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_run_notes(notes: dict) -> None:
    RUN_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_NOTES_PATH.write_text(json.dumps(notes, indent=2))


@app.get("/api/runs/notes")
async def runs_notes_get():
    return _load_run_notes()


@app.post("/api/runs/notes")
async def runs_notes_set(request: Request):
    """Body: {name, hypothesis, changes, result, freeform}. All fields optional."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, 400)
    notes = _load_run_notes()
    entry = notes.get(name, {})
    for field in ("hypothesis", "changes", "result", "freeform"):
        if field in body:
            entry[field] = (body[field] or "").strip()
    entry["updated"] = time.time()
    notes[name] = entry
    _save_run_notes(notes)
    return {"ok": True, "name": name, "notes": entry}


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
        #  Project per-slot OCR output (e.g. TeamSummaryReader's `slots`)
        #  into the manifest's flat-field shape so the per-card Suggest
        #  button populates the manifest inputs the form actually renders.
        if result.get("ok") and isinstance(result.get("result"), dict):
            fields_schema = (
                _load_screens_yaml()
                .get("screens", {})
                .get(screen, {})
                .get("readers", {})
                .get(reader, {})
                .get("fields", {})
            )
            result["result"] = _project_ocr_to_manifest(
                reader, result["result"], fields_schema
            )
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


@app.get("/api/live-trace/recent")
async def live_trace_recent(since: int = 0, limit: int = 100):
    """Proxy to mac_dev_runner: fetch live-trace events newer than `since`."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(
            f"{DEV_RUNNER}/live-trace/recent?since={int(since)}&limit={int(limit)}",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return JSONResponse({"error": f"dev runner unreachable: {e}"}, 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/api/live-trace/status")
async def live_trace_status():
    """Proxy to mac_dev_runner: live-trace ring buffer status."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"{DEV_RUNNER}/live-trace/status", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return JSONResponse({"error": f"dev runner unreachable: {e}"}, 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


# ─── Derived live state (Pokeball-based alive tracking) ────────────────────
# Background poller feeds a LiveStateTracker that accumulates per-match alive
# state across screens. Surfaced via /api/live-trace/derived-state for the
# Live Trace view and any future inference consumer.

_LIVE_STATE_TRACKER = None

def _get_live_state_tracker():
    global _LIVE_STATE_TRACKER
    if _LIVE_STATE_TRACKER is None:
        # Lazy import: keeps server importable without src/ on path during
        # one-off scripting.
        import sys
        repo = str(Path(__file__).resolve().parent.parent)
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from src.vgc_model.inference.live_state_tracker import LiveStateTracker
        tracker = LiveStateTracker()
        tracker.start_polling_thread(DEV_RUNNER, interval_sec=1.0)
        _LIVE_STATE_TRACKER = tracker
    return _LIVE_STATE_TRACKER


@app.get("/api/live-trace/derived-state")
async def live_trace_derived_state():
    """Return accumulated state from the LiveStateTracker (alive bitmap +
    faint events for the current match)."""
    return _get_live_state_tracker().snapshot()


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
    raw_results = {}
    errors = []
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks = [loop.run_in_executor(pool, _suggest_one, f) for f in targets]
        for fname, result, err in await asyncio.gather(*tasks):
            if result is not None:
                raw_results[fname] = result
            elif err is not None:
                errors.append({"filename": fname, "error": err})

    #  Project each OCR result into the manifest's schema-shaped form.
    #  Some readers (TeamSummaryReader, TeamStatsReader) emit a per-slot
    #  `slots` array but the schema declares flat per-field arrays — write
    #  the flat shape so the manifest test runner finds what it expects.
    fields_schema = (
        _load_screens_yaml()
        .get("screens", {})
        .get(screen, {})
        .get("readers", {})
        .get(reader, {})
        .get("fields", {})
    )
    results = {
        fname: _project_ocr_to_manifest(reader, raw, fields_schema)
        for fname, raw in raw_results.items()
    }

    return {"ok": True, "suggested": len(results), "results": results, "errors": errors}


def _project_ocr_to_manifest(reader: str, ocr: dict, fields_schema: dict) -> dict:
    """Reshape an OcrSuggest result into the manifest's flat per-field schema.

    OcrSuggest emits structured output keyed for human-readability (e.g.
    `slots: [{species, ability, item, moves}, ...]`). The manifest test
    runner expects flat per-field arrays declared in screens.yaml (e.g.
    `species: [s0, s1, ..., s5]`). This function projects the former into
    the latter for the readers that need it; pass-through for the rest.
    """
    if not isinstance(ocr, dict):
        return ocr

    slots = ocr.get("slots")
    if isinstance(slots, list) and slots:
        out = {}
        for field_name in fields_schema.keys():
            if all(isinstance(s, dict) and field_name in s for s in slots):
                out[field_name] = [s.get(field_name, "") for s in slots]
        if out:
            return out
        # fall through if nothing matched

    return ocr


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
    "TeamStatsReader",
    "TeamPreviewReader",
    "ResultReader",
    "AbilityItemReader",
    "TargetSelectReader",
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


#  Cache: (screen, filename, mtime) -> {detector_name: bool}.
#  One detector-debug call covers all detectors for an image, so we cache the
#  full dict and let detector mismatch scans pick out the relevant key.
_DETECTOR_RESULT_CACHE: dict = {}


def _load_detector_registry() -> dict:
    """Return {detector_name: set_of_positive_screens}. Empty set ⇒ unknown
    detector; treat all screens as negative."""
    try:
        registry = json.loads((TEST_IMAGES_DIR / "test_registry.json").read_text())
    except Exception:
        return {}
    out = {}
    for name, screens_list in (registry.get("detectors") or {}).items():
        out[name] = set(screens_list or [])
    return out


def _detectors_via_runner(screen: str, filename: str):
    """Run all detectors on one image. Returns ({detector_name: bool} | None,
    error_str | None)."""
    import base64
    import urllib.request
    import urllib.error
    img_path = TEST_IMAGES_DIR / screen / filename
    if not img_path.exists():
        return None, "image not found"
    mtime = img_path.stat().st_mtime
    key = (screen, filename, mtime)
    if key in _DETECTOR_RESULT_CACHE:
        return _DETECTOR_RESULT_CACHE[key], None
    try:
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        payload = json.dumps({"image_base64": img_b64}).encode()
        req = urllib.request.Request(
            f"{DEV_RUNNER}/detector-debug",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            envelope = json.loads(resp.read())
        if not envelope.get("ok"):
            return None, envelope.get("error", "unknown")
        result = envelope.get("result", {}) or {}
        flat = {d.get("name"): bool(d.get("detected")) for d in result.get("detectors", []) if d.get("name")}
        _DETECTOR_RESULT_CACHE[key] = flat
        return flat, None
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

    detector_registry = _load_detector_registry()
    is_detector = bool(reader) and reader in detector_registry

    targets = []
    if is_detector:
        positives = detector_registry.get(reader, set())
        for name in all_screens.keys():
            if screen and name != screen:
                continue
            screen_dir = TEST_IMAGES_DIR / name
            if not screen_dir.exists():
                continue
            expected = name in positives
            for img_path in sorted(screen_dir.iterdir()):
                if not img_path.is_file():
                    continue
                if img_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                    continue
                targets.append((name, img_path.name, "_DETECTOR_", {"expected": expected, "name": reader}))
    else:
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

    #  Map (reader, field, slot|None) -> CROP_DEFS box name. Used to attach
    #  the relevant pixel region to each mismatch row so the user can verify
    #  in-place without opening the Inspector.
    def _crop_box(reader: str, field: str, slot):
        if reader != "BattleHUDReader":
            return None
        if slot is None or not isinstance(slot, int):
            return None
        defs = CROP_DEFS.get(reader, [])
        #  BattleHUDReader uses names like "opp0_hp_pct", "own1_species".
        side = None
        suffix = None
        if field == "opponent_species":
            side, suffix = "opp", "species"
        elif field == "opponent_hp_pct":
            side, suffix = "opp", "hp_pct"
        elif field == "own_species":
            side, suffix = "own", "species"
        elif field == "own_hp_current":
            side, suffix = "own", "hp"
        elif field == "own_hp_max":
            side, suffix = "own", "hp"
        if side is None:
            return None
        target = f"{side}{slot}_{suffix}"
        for d in defs:
            if d["name"] == target:
                return d["box"]
        return None

    def _process_one(t):
        import base64
        s, fname, rname, fields = t
        if rname == "_DETECTOR_":
            det_name = fields["name"]
            expected = fields["expected"]
            flat, err = _detectors_via_runner(s, fname)
            if err is not None or flat is None:
                return []
            got = flat.get(det_name)
            if got is None:
                return []
            if got == expected:
                return []
            return [{
                "screen": s, "filename": fname, "reader": det_name,
                "field": "_self", "slot": None,
                "expected": expected, "got": got, "crop": None,
            }]
        result, err = _suggest_via_runner(s, fname, rname)
        if err is not None or result is None:
            return []
        img_path = TEST_IMAGES_DIR / s / fname
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
                        box = _crop_box(rname, field, i)
                        crop_data = None
                        if box and img_path.exists():
                            try:
                                crop_data = "data:image/png;base64," + base64.b64encode(_extract_crop(img_path, box)).decode()
                            except Exception:
                                pass
                        rows.append({
                            "screen": s,
                            "filename": fname,
                            "reader": rname,
                            "field": field,
                            "slot": i,
                            "expected": e,
                            "got": g,
                            "crop": crop_data,
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


@app.get("/api/mismatches/stream")
async def mismatches_stream(screen: Optional[str] = None, reader: Optional[str] = None):
    """Same scan as /api/mismatches but streams progress as NDJSON.

    Each newline-delimited message is one of:
      {"type":"start","total":N}
      {"type":"row", ...row}
      {"type":"progress","done":i,"total":N}
      {"type":"done","scanned":N,"rows":M}
    """
    config = _load_screens_yaml()
    screens = config.get("screens", {})
    overlays = {f"_overlays/{k}": v for k, v in config.get("overlays", {}).items()}
    all_screens = {**screens, **overlays}

    detector_registry = _load_detector_registry()
    is_detector = bool(reader) and reader in detector_registry

    targets = []
    if is_detector:
        positives = detector_registry.get(reader, set())
        for name in all_screens.keys():
            if screen and name != screen:
                continue
            screen_dir = TEST_IMAGES_DIR / name
            if not screen_dir.exists():
                continue
            expected = name in positives
            for img_path in sorted(screen_dir.iterdir()):
                if not img_path.is_file():
                    continue
                if img_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                    continue
                targets.append((name, img_path.name, "_DETECTOR_", {"expected": expected, "name": reader}))
    else:
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

    #  Reuse helpers from /api/mismatches.
    def _crop_box_local(reader_, field, slot):
        if reader_ != "BattleHUDReader":
            return None
        if slot is None or not isinstance(slot, int):
            return None
        defs = CROP_DEFS.get(reader_, [])
        side = None; suffix = None
        if field == "opponent_species": side, suffix = "opp", "species"
        elif field == "opponent_hp_pct": side, suffix = "opp", "hp_pct"
        elif field == "own_species":     side, suffix = "own", "species"
        elif field == "own_hp_current": side, suffix = "own", "hp"
        elif field == "own_hp_max":     side, suffix = "own", "hp"
        if side is None: return None
        target = f"{side}{slot}_{suffix}"
        for d in defs:
            if d["name"] == target: return d["box"]
        return None

    def _process_one(t):
        import base64
        s, fname, rname, fields = t
        if rname == "_DETECTOR_":
            det_name = fields["name"]
            expected = fields["expected"]
            flat, err = _detectors_via_runner(s, fname)
            if err is not None or flat is None:
                return []
            got = flat.get(det_name)
            if got is None:
                return []
            if got == expected:
                return []
            return [{
                "screen": s, "filename": fname, "reader": det_name,
                "field": "_self", "slot": None,
                "expected": expected, "got": got, "crop": None,
            }]
        result, err = _suggest_via_runner(s, fname, rname)
        if err is not None or result is None:
            return []
        img_path = TEST_IMAGES_DIR / s / fname
        rows = []
        for field, expected_val in fields.items():
            got_val = result.get(field)
            if got_val is None:
                continue
            if isinstance(expected_val, list) and isinstance(got_val, list):
                for i in range(min(len(expected_val), len(got_val))):
                    e = expected_val[i]; g = got_val[i]
                    if _is_absent(e):
                        continue
                    if _coerce_pair(e, g)[0] != _coerce_pair(e, g)[1]:
                        box = _crop_box_local(rname, field, i)
                        crop_data = None
                        if box and img_path.exists():
                            try:
                                crop_data = "data:image/png;base64," + base64.b64encode(_extract_crop(img_path, box)).decode()
                            except Exception:
                                pass
                        raw_list = result.get(field + "_raw")
                        raw_val = raw_list[i] if isinstance(raw_list, list) and i < len(raw_list) else None
                        rows.append({
                            "screen": s, "filename": fname, "reader": rname,
                            "field": field, "slot": i, "expected": e, "got": g,
                            "raw": raw_val,
                            "crop": crop_data,
                        })
            else:
                if _is_absent(expected_val):
                    continue
                if _coerce_pair(expected_val, got_val)[0] != _coerce_pair(expected_val, got_val)[1]:
                    rows.append({
                        "screen": s, "filename": fname, "reader": rname,
                        "field": field, "slot": None,
                        "expected": expected_val, "got": got_val, "crop": None,
                    })
        return rows

    async def gen():
        loop = asyncio.get_running_loop()
        total = len(targets)
        yield json.dumps({"type": "start", "total": total}) + "\n"
        row_count = 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [loop.run_in_executor(pool, _process_one, t) for t in targets]
            done = 0
            for fut in asyncio.as_completed(futures):
                batch = await fut
                done += 1
                for r in batch:
                    yield json.dumps({"type": "row", **r}) + "\n"
                    row_count += 1
                yield json.dumps({"type": "progress", "done": done, "total": total}) + "\n"
        yield json.dumps({"type": "done", "scanned": total, "rows": row_count}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


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
    """Trigger replay sync from ash to unraid."""
    if SPECTATOR_PROXY:
        body = await request.body()
        return await _proxy_spectator("POST", "/api/sync/trigger", body=body)
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
    if SPECTATOR_PROXY:
        return await _proxy_spectator("GET", "/api/sync/status")
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
