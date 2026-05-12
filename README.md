# Pokemon Champions Automation

Automation + ML tooling for **Pokemon Champions** (Regulation M-A VGC). Built on top of [PokemonAutomation/Arduino-Source](https://github.com/PokemonAutomation/Arduino-Source) — capture-card + microcontroller automation for a real Switch.

## Layout

The repo is a monorepo of four discrete subsystems plus shared data.

| Dir | What lives here |
|---|---|
| **`switch_bot/`** | C++ Qt fork of Arduino-Source. The live bot, OCR readers, screen detectors, and the `LiveDetectorTrace` passive watcher that drives every match. Includes `SerialPrograms/`, `Common/`, `3rdParty*/`, `IconResource/`, `CommandLineTests/`, `Resources/`, `Packages/`, `build_mac/`. |
| **`ml/`** | Python ML pipeline. `ml/vgc_model/` is the package: data parsing/encoding, model definitions, training, inference server (`/predict`, `/search`), battle sim. `ml/poke_env/` is the vendored Showdown-env library used for self-play. |
| **`spectator/`** | Long-running Showdown websocket spectator (8 connections on `ash`) that collects training replays. `orchestrator.py`, `ps_battles.py`, `status.py`, `sync_replays.sh`. |
| **`sv_trade_bot/`** | Separate Pokemon S/V trade-bot driver (Klawf/scvi-bot ecosystem). Headless Playwright + JSON-over-TCP bridge to a SerialPrograms panel. |
| **`devtools/`** | Mac-local developer surface. `devtools/dashboard/` (FastAPI SPA on :9875), `devtools/tools/` (`mac_dev_runner.py` on :9876, OCR/detector tuning, retest harness, video curation), `devtools/test_images/` (labeled regression corpus). |
| **`scripts/`** | Top-level entry points: training scripts, replay parsing, ladder play, vocab building. |
| **`tests/`** | Python `pytest` suite for ML + sim. |
| **`data/`** | Shared datasets: replays, vocab, feature tables, sprite cache, checkpoints, usage stats. Most subdirs are gitignored (regenerable). |
| **`plans/`, `docs/`** | Design docs + architecture notes. |

## Building

- **macOS (dev + regression):** `cmake -B switch_bot/build_mac -S switch_bot/SerialPrograms` then `cmake --build switch_bot/build_mac --target SerialPrograms --target SerialProgramsCommandLine -j 10`. See `docs/ARCHITECTURE.md`.
- **Linux (training):** PyTorch container on unraid (`pokemon-champions-gpu`). See `infra_unraid_gpu_container.md` in agent memory.
- **Python deps:** `pip install -r requirements.txt` if/when a requirements file lands; for now ad-hoc.

## Running the local stack

Two launchd-managed services on the Mac:

- `com.cole.pokemon-champions.dashboard` — uvicorn server on `:9875` (cwd `devtools/dashboard/`)
- `com.cole.pokemon-champions.mac-dev-runner` — `devtools/tools/mac_dev_runner.py` on `:9876`

Both reload with `launchctl unload <plist> && launchctl load <plist>`.

## Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Topology, system boundaries, data flow |
| [`plans/`](plans/) | Design docs (search engine, sim v2, refactor plans) |
| [`docs/coding_agent_context/PokemonChampionsReference.md`](docs/coding_agent_context/PokemonChampionsReference.md) | Game-data reference (Pokemon, moves, abilities, items) |
| [`docs/coding_agent_context/AutomationProgramPatterns.md`](docs/coding_agent_context/AutomationProgramPatterns.md) | Patterns for new SerialPrograms routines |

---

## Upstream attribution

`switch_bot/` is a fork of [PokemonAutomation/Arduino-Source](https://github.com/PokemonAutomation/Arduino-Source). Pokemon Champions code lives under `switch_bot/SerialPrograms/Source/PokemonChampions/` and is additive — the rest of the upstream tree is preserved largely as-is.

[<img src="https://canary.discordapp.com/api/guilds/695809740428673034/widget.png?style=banner2">](https://discord.gg/cQ4gWxN)

### Licensing

- Unless otherwise specified, all source code is under the MIT license.
- Some files may be under other (compatible) licenses.
- Precompiled binaries and object files are free for non-commercial use only. For other uses, contact the Pokémon Automation server admins.

### Dependencies

| Dependency | License |
|---|---|
| Qt5 / Qt6 | LGPLv3 |
| [QDarkStyleSheet](https://github.com/ColinDuquesnoy/QDarkStyleSheet) | MIT |
| [Qt Wav Reader](https://code.qt.io/cgit/qt/qtmultimedia.git/tree/examples/multimedia/spectrum/app/wavfile.cpp?h=5.15) | BSD |
| [nlohmann json](https://github.com/nlohmann/json) | MIT |
| [D++](https://github.com/brainboxdotcc/DPP) | Apache 2.0 |
| [LUFA](https://github.com/abcminiuser/lufa) | MIT |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Apache 2.0 |
| [Tesseract for Windows](https://github.com/peirick/Tesseract-OCR_for_Windows) | Apache 2.0 |
| [OpenCV](https://github.com/opencv/opencv) | Apache 2.0 |
| [ONNX](https://github.com/microsoft/onnxruntime) | MIT |
| [sdbus-c++](https://github.com/Kistler-Group/sdbus-cpp) | LGPLv2.1 |

Vanilla GPL is disallowed; LGPL is allowed. (1) A small portion of the project is not open-sourced. (2) Re-licensing rights reserved in ways that don't abide by GPL's copy-left.
