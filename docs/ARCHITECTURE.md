# Pokemon Champions — Architecture

*Snapshot: 2026-04-30. The state lines (model accuracies, test pass rates, image counts, deploy status) decay; the topology and component boundaries do not.*

## What this project is

A suite of automation + ML tooling for **Pokemon Champions** (released competitive battle title from The Pokemon Company, confirmed released 2026-04-16). Built as a fork of PokemonAutomation/Arduino-Source.

**Goal:** auto-battle / ladder grinding routines — team selection, move-loop execution, result tracking — driven by a learned battle policy trained on Pokemon Showdown replays.

**Format target:** `gen9championsvgc2026regma` (Champions VGC, Regulation M-A). Mega Evolution doubles. Fairy Aura, type-boost items, and resist berries dominate over Choice/Life Orb. See `CodingAgentContext/PokemonChampionsReference.md` for game data.

## Four distinct systems (do not cross-wire)

### 1. Switch + SerialPrograms (C++23 / Qt6)
The on-hardware automation. Capture card + microcontroller drives a real Switch.
- `SerialPrograms/Source/PokemonChampions/Inference/` — screen detectors and OCR readers
- `SerialPrograms/Source/PokemonChampions/Programs/` — automation routines (AutoLadder, DetectorTest)
- `CommandLineTests/` — offline regression runner
- `Source/Tests/PokemonChampions_Tests.{h,cpp}` + `TestMap.cpp` — registered test functions
- Registration lives in **3 places**: `Source/PanelLists.cpp`, `cmake/SourceFiles.cmake`, the game's `_Panels.cpp`

### 2. Inference engine + models (Python, PyTorch)
The battle decision layer. Connects to C++ via `InferenceClient`.
- `src/vgc_model/` — model code
- `data/checkpoints_*/` — trained weights
- Three models live in this repo:
  - **Action model** (`VGCTransformerV2Seq`, ~961k params) — picks move/switch + target per turn. LSTM history + transformer.
  - **Lead advisor** (`LeadAdvisorModel`, ~100k params) — picks 4 of 6 + 2 leads from team preview. Cross-attention, set-based.
  - **Win probability** (`WinrateModel`, ~769k params) — sigmoid head over board state. Used as eval function for search.
- **Search engine** (`inference/search.py`) — MCTS 1-ply: action model samples rollouts → battle sim → winrate model evaluates leaves. Endpoint: `POST /search` in `inference/server.py`.
- **Battle sim v2** (`sim/battle_sim.py`) — Champions-format-aware: type-boost items, Fairy/Dark Aura, resist berries, Intimidate, weather, Choice items, Trick Room.

### 3. Pokemon Showdown spectator (Python, on ash)
Completely separate from the Switch system. Acquires training data.
- `scripts/spectate_ps_battles.py` — guest connection to PS websocket, joins live Champions battles, saves logs
- 4 systemd services on ash (`pokemon-spectator{,-2,-3,-4}.service`), 40 rooms each, ELO-sliced polling to defeat PS's 100-rooms-per-query cap
- Graceful drain on SIGTERM (90s timeout)
- Output: `/opt/pokemon-champions/data/showdown_replays/{spectated,downloaded}/<format>/`

### 4. Dev tools hub — `champions.colefoster.ca`
Single FastAPI + vanilla-JS SPA on ash. **All UI lives here.** Local Mac runs CLI for C++ builds only.
- Service: `pokemon-champions-dashboard.service` (uvicorn, port 8420, nginx + OTP auth)
- Backend: `dashboard/server.py`
- Frontend: `dashboard/static/index.html`
- 10 hash-route views: `#/dashboard`, `#/gallery`, `#/labeler`, `#/inspector`, `#/recognition`, `#/teampreview`, `#/templates`, `#/model`, `#/training`, `#/validation`
- Internal Tailscale endpoint at `100.113.157.128:8421` (no auth, used by ColePC training to report metrics — Python urllib chokes on the Cloudflare HTTPS path)

**Not part of this project:** `ps.colefoster.ca` (separate Laravel/Vue PS client, different repo).

## Topology — four machines

| Machine | Role | Tree |
|---|---|---|
| **Mac** (`/Users/cole/Dev/pokemon-champions`) | Editing, local C++ builds (`build_mac/`), reference frames (`ref_frames/`, ~1.3 GB, Mac-only) | working copy |
| **ColePC** (Windows, `C:\Dev\pokemon-champions`) | **Canonical tree.** Qt6 + VS toolchain, capture card, microcontroller, RTX GPU. Where live bot tests and OCR/detector dev happen. | canonical |
| **unraid** (Pandora) | **Canonical training rig** (in transition). Linux fork = DataLoader workers actually scale. RTX 4060. Container `pokemon-champions-gpu`, image `pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime`, vol `/mnt/user/data/pokemon-champions → /workspace`. | clone |
| **ash** (Hetzner VPS) | Data acquisition (spectator), dashboard host, public surface | `/opt/pokemon-champions/` |

**Workflow:** Edit on Mac → commit + push → other machines pull. Always commit changes promptly so ColePC/ash/unraid can pull. The Mac copy is **stale by design** for non-reference-frame code.

**Job runners** (HTTP, port 8422, identical API: `POST /run`, `GET /status`, `GET /log`, `POST /kill`, `POST /ocr-suggest`, `POST /detector-debug`):
- ColePC: `scripts/job_runner.py`, runs in desktop session (CUDA stalls in Session 0 / schtasks)
- unraid: `scripts/container_job_runner.py`, intended as container ENTRYPOINT

## Data flow

```
PS websocket
   │
   ▼
[spectator x4 on ash] ──► /opt/pokemon-champions/data/showdown_replays/
                                │
                                ▼
                        dashboard "Sync" button
                                │  (rsync over Tailscale)
                                ▼
                          ColePC / unraid
                                │
                                ▼
                       sharded cache (data/dataset_cache/<variant>/)
                       variant = "{history_mode}_r{min_rating}_w{winner_only}"
                                │
                                ▼
                     train_v2 / train_lead / train_winrate
                                │
                                ▼
                       data/checkpoints_*/best.pt
                                │
                                ▼
                       inference/server.py (search endpoint)
                                │
                                ▼
                    InferenceClient in C++ programs ─► Switch automation
```

## Test architecture

Two suites — one C++, one Python.

### C++ OCR / detector regression — `test_images/`
**Screen-based** (overhauled 2026-04-28; replaced filename-encoded `CommandLineTests/PokemonChampions/<DetectorName>/`).
- `test_images/<screen>/manifest.json` — reader labels keyed by filename (`null` for unreadable)
- `test_images/screens.yaml` — **source of truth** for the screen graph
- `test_images/test_registry.json` — auto-generated for C++ consumption
- Detectors are bool-only, determined by directory membership. Negatives are implicit — any image not in a detector's screen is a negative test.
- **Singles/doubles are merged.** One directory each for `action_menu`, `move_select`, `pokemon_switch`. Readers handle 1 or 2 mons (variable-length arrays). Don't re-split — singles detectors fire on doubles, and a doubles screen with one mon left looks like singles.
- Overlays (`_overlays/battle_log`, `_overlays/ability_item`) are cross-screen readers, not in the state graph.
- `_inbox/` for unsorted, `_other/` for animations.

**Screen state graph:**
```
team_select → searching_for_battle → team_preview_selecting → team_preview_locked_in
  → communicating → action_menu → move_select → target_select
  → communicating → ... → result_screen → post_match
  + main_menu, moves_and_more
```

**Runner:** `SerialProgramsCommandLine --manifest-regression`
**Other CLI modes:** `--ocr-suggest <reader> <image>`, `--detector-debug <image>`
**Bridge tools:** `tools/generate_test_registry.py`, `tools/migrate_test_images.py`, `tools/verify_screens.py`, `tools/retest.py`

### Python sim/search — `tests/`
- `pytest tests/` — sim unit tests, search with mock models, replay ground-truth checks
- Replay eval harness: `python -m tests.eval_search_vs_replay`

## Where things live in the repo

```
SerialPrograms/Source/PokemonChampions/   ── all game-specific C++ (detectors, programs, ref_frames)
CommandLineTests/                          ── C++ regression runner + (legacy) test images
test_images/                               ── current screen-based test fixtures + manifests
tests/                                     ── Python pytest suite (sim, search)
src/vgc_model/                             ── model code
data/checkpoints_*/                        ── trained weights (action, lead, winrate)
data/dataset_cache/<variant>/              ── sharded preparsed training data
sim/                                       ── battle sim v2 + type chart
inference/                                 ── search engine + HTTP server
scripts/                                   ── spectator, job runners, training entry points
dashboard/                                 ── FastAPI server + JS SPA (deployed to ash)
tools/                                     ── local CLI utilities (retest, registry, verify)
plans/                                     ── design docs (search engine, sim v2, test image arch)
docs/                                      ── this file + model-v2 plan
CodingAgentContext/                        ── reference docs for sub-tasks (sprites, team scanner)
ref_frames/                                ── Mac-only reference video + extracted frames
```

## Operational notes

- **Always commit + push after changes** — other machines won't see them otherwise.
- **Reference frames stay on Mac** (~1.3 GB; never copied to ColePC).
- **Dashboard deploys** are `sudo cp` then `chown cole:cole` (uvicorn runs as `cole`, not `www-data`, because it needs SSH access to ColePC/unraid). Restart with `sudo systemctl restart pokemon-champions-dashboard`.
- **No Unicode in `<script>` tags** — em dashes etc. break Chrome's parser. ASCII only in dashboard JS.
- **Windows GPU jobs go through the job runner** — never `schtasks` directly (CUDA stalls in Session 0). To restart the runner: `taskkill` the PID then `schtasks /Run /TN JobRunnerOnce`.
- **The dashboard is Claude-edited.** Prefer narrow files over framework-y abstractions.

## Known unfinished work (state, will drift)

- **Search engine lift is neutral (-0.4%).** Bottleneck: `_build_v2_batch` zeros out the LSTM sequence history + team preview context the model trains on. Fix the encoding before chasing more rollouts. See `plans/search_engine.md`.
- **Unraid switchover:** sharded cache + container job runner + dashboard sync target are built (`scripts/deploy_unraid_primary.sh`). Not yet deployed — ash dashboard still has ColePC sync code, container CMD is still `tail -f /dev/null`, ash needs SSH key on unraid.
- **Detectors with known false-negatives:** `MoveSelectDetector` (36), `TeamPreviewDetector` (6), `ResultScreenDetector` (3). `PostMatchScreenDetector` is too permissive. Tuning loop: gallery → "Debug Detectors" → adjust C++ thresholds → `python tools/retest.py`.
- **Screens lacking images:** `target_select`, `pokemon_switch`. Several screens are unlabeled (`action_menu`, `post_match`, `result_screen`, etc.).

## Further reading

- `plans/test_image_architecture.md` — PRD for the screen-based test system
- `plans/search_engine.md`, `plans/sim_v2_improvements.md` — search + sim roadmap
- `docs/model-v2-plan.md` — action model architecture rationale
- `CodingAgentContext/PokemonChampionsReference.md` — game-data reference (Pokemon, moves, abilities, items)
- `CodingAgentContext/AutomationProgramPatterns.md` — patterns for new SerialPrograms routines
