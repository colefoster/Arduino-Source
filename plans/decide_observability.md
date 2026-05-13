# Model-Decision Observability — M5

Pure-observability features built on the existing `/decide` response.
No new endpoints; no new model assumptions; no decision-changing
behavior. Adds two windows into what the model is thinking:

1. **Opp-action prediction overlay** — the model's predicted opponent
   action for the current turn, surfaced on the video overlay + trace
   event.
2. **Win-probability gauge** — a per-match plot of `meta.win_pct` over
   turn number, surfaced on the dashboard livetrace view.

Status: **design**. Depends on M1 (shadow `/decide` integration)
being live so the trace is already calling the endpoint each turn.

---

## 1. Opp-action prediction overlay

### What it shows

When `/decide` returns, render on the video overlay:
```
us:  Wave Crash → opp_a  (p=0.78)
opp: Sucker Punch → own_a  (p=0.42)
```

### Where the data comes from

`/decide` already runs the perspective-swapped pass through the
action model (see `search.py::_build_v2_batch(perspective="opp")`).
The opp action distribution is computed; it just isn't surfaced in
the current response shape.

### Schema extension

Add **optional** fields to `DecideResponse`:
```json
{
  "slot_a":     {"action": 7,  "probs": [...]},
  "slot_b":     {"action": 12, "probs": [...]},
  "opp_slot_a": {"action": 3,  "probs": [...]},   // NEW, optional
  "opp_slot_b": {"action": 7,  "probs": [...]},   // NEW, optional
  "win_pct":    0.42,
  "meta":       {...}
}
```

Trace decodes opp's predicted action using the same `decode_action`
helper from M1, with one twist: the slot is from the **opponent's**
team. The own/opp species swap means `target_idx=0` from opp's POV
points at *our* mon. Trace flips the target name accordingly when
rendering (e.g. opp's `(move, opp_a)` displays as "→ own_a" on our
overlay).

### Trace integration

- On `/decide` reply: if `opp_slot_a` / `opp_slot_b` present, decode
  and log an extra line to overlay + trace event.
- No flag — always on when fields are present.

### Server gap

`/decide` currently doesn't expose the opp distributions. Add the
two optional fields to `DecideResponse`. `search.py` already
computes them; just need to pass through.

---

## 2. Win-probability gauge

### What it shows

A small line plot on the livetrace dashboard view, x-axis = turn
number, y-axis = `meta.win_pct` from each turn's `/decide` reply.
Updated each turn as the prediction lands.

### Where the data comes from

`/decide.meta.win_pct` (or top-level `win_pct` in the current
response shape). The trace already receives it; it just isn't
rendered anywhere.

### Trace integration

- On `/decide` reply: push `{turn, win_pct}` into a new field on the
  trace event, e.g. `ev["win_pct_history"]`.
- Or simpler: emit only the latest `{turn, win_pct}` per event; the
  dashboard maintains the rolling history client-side.

### Dashboard

New card on `dashboard/static/views/livetrace.html`:
- Header "Win Probability" + current value
- Tiny canvas/SVG plot, 0-100% y-axis, last 30 turns x-axis
- One line per match; resets on match-end.

Rendering owned by a new function in
`dashboard/static/js/livetrace.js`, called from the existing reply
handler.

### Server gap

None — `win_pct` is already in the contract.

---

## 3. Combined response shape (final)

After both M5 extensions:

```json
{
  "slot_a":     {"action": 7,  "probs": [...]},
  "slot_b":     {"action": 12, "probs": [...]},
  "opp_slot_a": {"action": 3,  "probs": [...]},   // M5.1, optional
  "opp_slot_b": {"action": 7,  "probs": [...]},   // M5.1, optional
  "win_pct":    0.42,                              // M5.2, optional but expected
  "meta": {
    "model_version": "...",
    "endpoint_impl": "...",
    "latency_ms":  38,
    "n_rollouts":  20
  }
}
```

Backward compatible — all M5 fields are optional. M1/M2/M3 trace
behavior unchanged if server doesn't yet provide them.

---

## 4. Rollout

### M5.1 — Opp prediction overlay
- Server: add `opp_slot_a` / `opp_slot_b` to `DecideResponse`.
- Trace: render decoded opp action on overlay + trace event.
- Tiny — single PR.

### M5.2 — Win-probability gauge
- Trace: ensure `win_pct` lands on the trace event (probably already).
- Dashboard: new "Win Probability" card on livetrace view; line plot.
- Tiny — one HTML/JS PR, no C++ changes.

Either can ship in either order; no dependency between them.

---

## 5. Out of scope

- **Top-k action display** — could surface the 3 highest-probability
  actions per slot. Useful for debugging but cluttered for normal
  play. Add later if needed.
- **Per-action EV breakdown** — `pair_scores` from MCTS shows
  expected win% per (own_a, own_b) pair. Already in
  `search.py::SearchResult.pair_scores`. Surfacing it would be
  a dashboard table; not high-impact.
- **Forfeit suggestion** — explicitly out of scope per grilling.
  We don't want a bot surrendering ranked matches automatically.
