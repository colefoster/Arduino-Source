# Pokemon Champions Automation

Automation + ML tooling for **Pokemon Champions** (Regulation M-A VGC). Built on top of [PokemonAutomation/Arduino-Source](https://github.com/PokemonAutomation/Arduino-Source) — capture-card + microcontroller automation for a real Switch.

## What's here

- **Switch automation** — C++ Serial Programs (auto-ladder, detector test) under `SerialPrograms/Source/PokemonChampions/`
- **Battle policy** — PyTorch action / lead / win-probability models in `src/vgc_model/` with sharded training cache
- **MCTS search** — 1-ply rollouts using a battle sim (`sim/`) and the win-probability model as eval (`inference/`)
- **PS spectator** — websocket client that gathers training data from live Pokemon Showdown battles (`scripts/spectate_ps_battles.py`)
- **Dev dashboard** — FastAPI + JS SPA at [champions.colefoster.ca](https://champions.colefoster.ca) for labeling, regression, training monitoring (`dashboard/`)

## Documentation

| | |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Topology, system boundaries, data flow, operational notes |
| [`plans/`](plans/README.md) | Design docs (search engine, sim v2, test image arch) |
| [`CodingAgentContext/PokemonChampionsReference.md`](CodingAgentContext/PokemonChampionsReference.md) | Game-data reference (Pokemon, moves, abilities, items) |
| [`CodingAgentContext/AutomationProgramPatterns.md`](CodingAgentContext/AutomationProgramPatterns.md) | Patterns for new SerialPrograms routines |

## Building

- **Mac (regression tests + OCR dev):** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — `cmake --build build_mac --target SerialProgramsCommandLine`
- **Windows (live bot):** Visual Studio + Qt6 on ColePC. Capture card + microcontroller required for live automation.
- **Linux (training):** PyTorch container on unraid (`pokemon-champions-gpu`).

---

## Upstream attribution

This repo is a fork of [PokemonAutomation/Arduino-Source](https://github.com/PokemonAutomation/Arduino-Source). Pokemon Champions code lives under `SerialPrograms/Source/PokemonChampions/` and is additive — the rest of the upstream tree (other game programs, framework code, Discord/DPP integrations) is preserved largely as-is.

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
