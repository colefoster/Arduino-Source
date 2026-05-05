# Live Detector Trace

A new dev tool that watches live gameplay, runs the same detector/reader pipeline `AutoLadder` uses, and surfaces the **engine's-eye view** + a flag-and-capture button + (later) contradiction detection in the dashboard. Lets Cole play a real game manually with a real controller while the program watches the capture card and confirms that the assembled state stream the inference engine consumes is coherent and correct.

## Shape (post-Phase-0 audit + grilling)

**This is a new SerialPrograms C++ program, not a Python sidecar.** The reusable pipeline is C++:

- **Detectors/readers:** `BattleHUDReader::read_all()` and friends, invoked from `AutoLadder.cpp:668-672`.
- **Engine view assembly:** `BattleStateTracker::to_predict_json()` in `SerialPrograms/Source/PokemonChampions/Programs/PokemonChampions_BattleStateTracker.h:89` — header-only, pure game-state. Note: `update_from_log()` is unused on the Switch path (verified — `AutoLadder.cpp` never calls it). Engine view is HUD-derived only, same as AutoLadder. Continuous per-frame `to_predict_json()` calls produce partial state in early frames, which is correct and matches AutoLadder behavior.
- **Frame source:** `VideoSession::snapshot_*()` — multi-consumer safe.
- **Passive-program pattern:** copy `NintendoSwitch_SwitchViewer` — `FeedbackType::NONE` + `DISABLE_COMMANDS`, no controller wire. Cole plays manually; program only watches video.

**Spectator is out of scope.** PS-websocket-only, deployed on `ash`, never sees Switch video.

## Key design decisions (locked)

| # | Branch | Decision |
|---|---|---|
| 1 | Who drives the Switch | Manual play with a real controller. Trace tool is video-only (`FeedbackType::NONE`). |
| 2 | Per-frame work | Classifier-first. Run only the active screen's readers, **plus** cheap sanity readers (`pokeballs`, `sprite-match`) on every frame for cross-screen flap signal. |
| 3 | Frame rate | 4 Hz. Sweet spot: live-feeling, catches <500ms flap, cheap CPU, manageable ring buffer. |
| 4 | What gets shipped to the dashboard | **Event-rate, not frame-rate.** State-change events (engine view diffs) + end-of-game summary + contradictions/flags. The 4 Hz per-frame work stays local on the Mac. |
| 5 | Transport | C++ POSTs events to `mac_dev_runner` (port 9876); Python rebroadcasts via SSE to the dashboard. Reuses existing Tailscale plumbing; no new C++ networking. |
| 6 | Ring buffer | Disk-backed JPEG ring on the Mac (`/tmp/live_trace_ring/` or similar), ~5 min depth, plus matching `ring.jsonl` of detector outputs. Sliding-window cleanup. |
| 7 | Dashboard view | New `/live-trace` view. Don't merge with Inspector. |
| 8 | Flag-and-capture format | Match existing `test_images/` manifest schema 1:1. Captured frames slot into the existing C++ regression suite with zero suite-side changes. |
| 9 | Program location | `SerialPrograms/Source/PokemonChampions/Programs/PokemonChampions_LiveDetectorTrace.{h,cpp}`. Registered like a normal PokemonChampions program. |
| 10 | Flag trigger | Dashboard button only. No keyboard shortcut. Button POSTs to `mac_dev_runner`, which signals the C++ program (HTTP poll or shared file). |
| 11 | Session boundaries | No explicit session concept. End-of-game summary fires when screen classifier transitions into `ResultScreen`/`PostMatch`. New game = transition into `TeamPreview`. C++ owns this. |
| 12 | Engine view panel | Mirror `to_predict_json()` 1:1. Two columns (own / opp), active mons highlighted. Don't invent a new visualization. |
| 13 | Contradiction rules (Phase 4) | Three only: HP teleport, species-change-without-switch, classifier flap <500ms. Each = small pure function over recent state. Resist adding more in v1. |

## Phased plan

### Phase 0 — Audit ✅ done.

### Phase 1 — Tracer bullet (live capture, C++ program, event stream)

- New SerialPrograms program `LiveDetectorTrace` next to `AutoLadder` (decisions 1, 9). `FeedbackType::NONE` + `DISABLE_COMMANDS` per `SwitchViewer` pattern.
- Per snapshot at 4 Hz (decision 3):
  1. Run screen classifier (decision 2).
  2. Run that screen's readers + always-run cheap sanity readers.
  3. Call `to_predict_json()`. Diff vs previous engine view.
  4. If diff non-empty, POST event to `mac_dev_runner` (decision 5).
- Add new endpoints to `mac_dev_runner.py`: `POST /live-trace/event` (ingest from C++) and `GET /live-trace/stream` (SSE to dashboard).
- New dashboard view at `/live-trace` (decision 7): subscribes to SSE, renders engine view panel (decision 12) + raw event feed.
- **Done when:** play a real game, watch engine view update in dashboard as state changes.

### Phase 2 — Ring buffer + flag-and-capture

- C++ program writes each snapshot's JPEG + detector-output JSON line to a disk-backed ring (decision 6). Sliding-window cleanup (5 min).
- Add dashboard "Flag" button (decision 10). POSTs to `mac_dev_runner`, which writes a sentinel file (or HTTP-polls the C++ program; whichever is simpler).
- C++ program on flag: copy current ring contents into `test_images/live_capture/<ts>/`, write `manifest.json` matching existing schema (decision 8).
- **Done when:** flagging produces a fixture that runs in the existing C++ OCR manifest regression test with no suite changes.

### Phase 3 — End-of-game summary

- C++ program watches for `BattleHUD → ResultScreen/PostMatch` transition (decision 11).
- On transition: emit summary event (final teams seen, KO order, all contradictions tripped this game, flag-count, mismatch-count).
- Dashboard view shows a per-game scrollback of summaries.
- **Done when:** finish a game, see the summary appear in the dashboard.

### Phase 4 — Contradiction rules

Three rules only (decision 13). Each = pure function over recent engine-view history maintained in C++:
- **HP teleport** — slot HP went 100 → 0 → 100 without faint/switch.
- **Species-change-without-switch** — slot species changed but no switch event observed.
- **Classifier flap** — screen classifier toggled in <500ms.

On trip: emit a contradiction event (rides decision-4 channel) AND auto-flag (Phase 2 capture).

**Done when:** a play session yields auto-captured fixtures without manually pressing flag.

### Phase 5 — Promote stable rules into AutoLadder

Rules that prove stable graduate into `AutoLadder`/`BattleStateTracker` as state guards (e.g., "if HP teleports, log + don't update state"). Trace tool stays the iteration ground.

## Explicitly deferred / YAGNI

- Recorded-video source.
- Per-frame timeline strip on the dashboard (was Phase 2 in v2 of the plan; replaced by event feed since traffic is event-rate now). Add later only if event feed proves insufficient.
- Multi-source capture, replay sharing, fancy diff UI.
- Auto-promoting captured fixtures into the training data pipeline.
- More contradiction rules beyond the initial three.
- Keyboard-based flag trigger.

## Key file references

- `SerialPrograms/Source/PokemonChampions/Programs/PokemonChampions_AutoLadder.cpp:668-672` — reference call site for snapshot + `read_all()` + tracker update.
- `SerialPrograms/Source/PokemonChampions/Programs/PokemonChampions_BattleStateTracker.h:89` — `to_predict_json()`, the engine view assembler.
- `SerialPrograms/Source/CommonFramework/VideoPipeline/VideoSession.h` — frame source, multi-consumer safe.
- `SerialPrograms/Source/NintendoSwitch/Programs/NintendoSwitch_SwitchViewer.cpp` — passive program pattern (`FeedbackType::NONE` + `DISABLE_COMMANDS`) to copy.
- `tools/mac_dev_runner.py:257` — existing Mac-local Tailscale-exposed service; new ingest + SSE endpoints land here.
