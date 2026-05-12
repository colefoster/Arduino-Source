# `/decide` Endpoint Contract

The LiveDetectorTrace will call the inference server for every in-battle
decision point (move-select, pokemon-switch, target-select, mega-evolve).
This document specifies **what the trace assumes the server provides**.
Server-side and model-side implementations chase this contract; the trace
doesn't care which model is behind it.

Status: **design**. Trace integration is scoped to ship in shadow mode
(model decisions logged, heuristic still presses buttons) before flipping
to driver mode.

---

## 1. HTTP surface

### `POST /decide`

The single endpoint the trace ever calls. Stateless: every call carries
the full game state. The server keeps no per-match memory.

**Request body:** the existing `PredictRequest` Pydantic model (see
`src/vgc_model/inference/server.py`). Populated by
`BattleStateTracker::to_predict_json()` plus the `history` array (last
≤8 `BattleHistoryEntry` rows). All encoder-shape fields are populated:
species/hp/status/moves/item/ability/boosts/is_mega/alive plus
`volatile_statuses`, `substitute_hp_frac`, `item_confidence`,
`ability_confidence`, `move_confidences`, `sleep_turns_remaining`,
`toxic_counter`, `locked_to_move`, `last_move`, `nature`, `evs`,
`move_pp`. Field state includes weather/terrain/trick_room, screens,
tailwind, hazards (`hazards_own`/`hazards_opp`), `side_timers_*`,
`last_move_own`/`last_move_opp`, and `legal_actions_a`/`legal_actions_b`.

**Response body — `DecideResponse`:**
```json
{
  "slot_a": {"action": 7, "probs": [0.01, ..., 0.78, ...]},
  "slot_b": {"action": 12, "probs": [...]},
  "win_pct": 0.42,
  "meta": {
    "model_version": "v2_seq_d192_l8_k8",
    "endpoint_impl": "search_1ply",
    "latency_ms": 38,
    "n_rollouts": 20
  }
}
```

| Field | Required | Meaning |
|---|---|---|
| `slot_a.action` | yes | Integer 0..13, encoding `move_i*3 + target_j` (0..11) or `switch_0` (12) / `switch_1` (13). MUST be a legal action per the request's `legal_actions_a` mask. |
| `slot_a.probs` | yes | 14-element float array, sums to ~1.0. Indices outside the legal mask MAY be 0; trace reads only the chosen action's prob for confidence display. |
| `slot_b.action`, `slot_b.probs` | yes | Same shape. Singles: server returns `action=PAD (=14)` with `probs=[0]*14` to indicate "no slot B." Trace ignores slot_b when in singles. |
| `win_pct` | optional | Estimated probability of winning the match from this state. Pure debug / overlay info; trace doesn't gate behavior on it. |
| `meta.model_version` | optional | Free-form string. Trace logs it so we can attribute past predictions. |
| `meta.endpoint_impl` | optional | What the server actually did. Examples: `policy_only`, `search_1ply`, `search_3ply_puct`. Forward-compat. |
| `meta.latency_ms` | optional | Server's self-reported wall-clock. Trace adds its own round-trip measurement. |
| `meta.n_rollouts` | optional | For search-backed responses. |

**Error responses:**
- `400` — request validation failed (malformed JSON, illegal field). Trace logs raw body, falls back to heuristic.
- `503` — server up but model not loaded yet. Trace retries every poll; once `200`s come back, normal operation resumes.
- `500` — internal error. Trace logs the error, falls back to heuristic for that turn.
- Timeout (no response within the trace's budget — see §3) — same fallback path.

### `GET /health`

Trace pings at program start. Existing endpoint. Expected response:
```json
{"status": "ok", "device": "cuda:0", "model_loaded": true, "endpoint_impl": "search_1ply"}
```

The trace gates `m_inference_client` initialization on `status=="ok"`.

---

## 2. Legality and masking — server's responsibility

The trace **trusts** the server's `slot_*.action` to be a legal action.
The server is responsible for:
- Reading `legal_actions_a` / `legal_actions_b` from the request.
- Applying the mask to its policy head (zero out illegal logits before
  softmax + argmax).
- For search-backed responses: respecting the mask during sampling too.

If the server returns an illegal action (mask says false at that index),
the trace logs a `model: illegal action <i>` warning and falls back to
heuristic for that decision. This is treated as a bug; it should not
happen in normal operation.

`locked_to_move` is folded into `legal_actions_a/b` on the C++ side
already, so the server doesn't need to special-case Choice locks.

---

## 3. Latency budget and timeout policy

The trace polls roughly every 250ms. The model call is async (Qt
`QNetworkRequest`, no `QEventLoop::exec()` blocking the press path).
The trace stashes the reply, checks `isFinished()` each poll.

Latency assumptions:
- **Typical:** 100ms.
- **Worst acceptable:** 500ms.
- **Hard ceiling:** 750ms (3 poll cycles). Past this, the trace cancels
  the request and logs `model: timeout`.

The server should aim for <200ms p95 even under load. If a single call
is going to exceed budget (e.g. deep search), the server should EITHER:
- Return early with the policy-only result and `endpoint_impl: "policy_only_timeout"`.
- Stream a partial result (future extension; not in v1).

The trace does NOT batch requests across polls. One call per
decision point; if the visit_count increments before the prior call
returns, the prior reply is discarded (logged as `model: stale`).

---

## 4. Versioning and rollout

`meta.model_version` is logged on every shadow-mode prediction. When
the server hot-swaps a model:
- Old in-flight requests resolve against the old model. Trace doesn't
  care; the version field on the reply is the ground truth.
- The trace's `/health` poll picks up the new version on next reconnect.

Server should never silently regress a model. A `/decide` response with
`model_version` differing from the prior call is fine; the trace just
logs the change once.

---

## 5. Server-side implementation gaps (what needs to exist)

The trace can ship its side once the server provides:

1. **`POST /decide`** — currently the server has `/predict` (v1) and
   `/search` (v2). New route, same handlers internally for now; just
   thin wrapper that aliases to whichever pipeline is canonical.
2. **`DecideResponse` schema** — new Pydantic model wrapping the
   existing slot_a/slot_b pair + the meta block.
3. **`meta.model_version`** — pulled from the loaded checkpoint's
   filename or a config field. Surfaced on every response.
4. **`legal_actions_*` honored** — current `_build_v2_batch` reads
   them into `action_mask_*` tensors but should verify the returned
   argmax is in the legal set (defensive — if the model masks correctly
   this is a no-op).
5. **Server reachable from the LiveDetectorTrace host** — Mac calling
   localhost works in dev; production likely points at unraid /
   another host via Tailscale URL.

These are all **server-side** items; the trace assumes them and fails
gracefully (heuristic fallback) when they're absent.

---

## 6. Model-side gaps (informational, not blocking the trace)

The trace assumes "an ideal model" — meaning: a policy that gives a
reasonable action distribution, accuracy improving over time. Specific
model-quality improvements are tracked separately in:
- `plans/search_engine.md` — search tree depth, selection policy.
- `plans/sim_v2_improvements.md` — simulator fidelity for Champions.
- `plans/state_richness.md` — feature richness in the trained model.

The trace does NOT change when the model improves; only the contents
of `meta.model_version` change, and `slot_*.action` gets better.

---

## 7. Trace-side rollout plan

Three milestones, each shippable on its own:

### M1 — Shadow logging (target: next slice)
- LiveDetectorTrace creates `InferenceClient` at program start.
- Each poll where a decision is pending (move_select / pokemon_switch /
  target_select), trace fires `POST /decide` asynchronously.
- On reply: log `model: <move/switch> → <target> (p=0.78, v=<model_version>)`
  to the trace event + video overlay.
- Heuristic continues to press buttons.
- Adds latency/observability: trace event carries the decode + meta.

### M2 — Driver mode behind a flag
- New option `Enable Model-Driven Move Pick` (default OFF).
- When ON and the model has a fresh, valid reply for the current
  visit, the trace uses the predicted slot+target instead of the
  random roll.
- Heuristic remains the fallback (server down, timeout, invalid action,
  flag off).

### M3 — Driver mode for switch + target + mega
- Same flag pattern extended to pokemon_switch decoding,
  target_select decoding, and mega-evolve toggling.
- Future: split into granular flags
  (`Model-Driven Switch`, `Model-Driven Target`, `Model-Driven Mega`).

---

## 8. Open questions (still being grilled)

- Q4: When during a turn to fire the call (action_menu entry, first
  move_select poll, every poll until cursor reads).
- Q5: Action decoding details — confirm the 14-index layout matches
  what both training and the model output.
- Q6: target_select integration — does the model's `target_j` carry
  through automatically to the target_select screen press path?
- Q7: switch_0/_1 → bench slot mapping (which absolute slot is
  "switch 0"?).
- Q8: Doubles slot-B handling — same model call, two decoded actions.
- Q9: Mega-evolve — when does the model want to mega, and how does
  the trace know? `action % 14`? Separate flag? `slot_a.action_mega`
  not currently in response.
- Q10: Confidence threshold — should low-probability actions fall back
  to heuristic? E.g. if `probs[chosen] < 0.25`, treat as "model
  unsure," log but don't drive (in M2/M3).
- Q11: Flag granularity (single Model-Driven flag vs split per
  decision type).
- Q12: Smoke test — a tiny C++ or Python harness that POSTs a real
  `to_predict_json()` payload to a stub server, asserts the schema
  round-trips.
