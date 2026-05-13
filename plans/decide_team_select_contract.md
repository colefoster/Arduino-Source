# `/decide-team` Endpoint Contract — M4

Mirror of `plans/decide_endpoint_contract.md` for the **team / lead
selection** decision point. Different model, different endpoint,
different press site — kept separate so the two can evolve
independently.

Status: **design**. Trace currently picks teams via the
`LEAD_ORDER_SINGLES` / `LEAD_ORDER_DOUBLES` config strings; the
trained lead-advisor model is not yet called.

---

## 1. Where this fires in the trace

The `team_preview_selecting` screen is the only call site. Sequence:
1. Trace enters `team_preview` (all 12 mons visible — own 6 + opp 6).
2. `TeamPreviewReader` populates the tracker's own/opp species lists.
3. **Trace fires `POST /decide-team` once**, when both rosters are
   confirmed read (`marks_count` is in a stable state, opp_species has
   6 entries).
4. Reply lands within ~250ms.
5. **M4a (shadow):** log `model team: bring=[3,1,5,0] lead=[2,0]
   (Garchomp, Hydreigon)` to trace + overlay. Heuristic still uses
   `LEAD_ORDER_*` to press.
6. **M4b (driver):** new flag `Enable Model-Driven Team Pick`.
   When ON, `LEAD_ORDER_*` is overridden by the model's `bring` +
   `lead` output.

This is **per-match**, not per-turn. Stateless wrt the in-battle loop.

---

## 2. HTTP surface

### `POST /decide-team`

Request — `TeamSelectRequest`:
```json
{
  "own_team":  ["pikachu", "garchomp", "hydreigon", "tornadus", "amoonguss", "rillaboom"],
  "opp_team":  ["zamazenta", "ursaluna", "incineroar", "iron-hands", "rillaboom", "gholdengo"],
  "format":    "doubles",   // "singles" | "doubles"
  "regulation": "M-A"        // free-form; passed through for model conditioning
}
```

All 12 species are slugs. The format / regulation fields let the
server route to the right trained head (team-comp depends on format).

Response — `TeamSelectResponse`:
```json
{
  "bring":        [3, 1, 5, 0],
  "bring_scores": [0.83, 0.41, 0.79, 0.62, 0.91, 0.74],
  "lead":         [0, 2],
  "lead_scores":  [0.71, 0.18, 0.69, 0.04],
  "meta": {
    "model_version": "lead_advisor_L3",
    "endpoint_impl": "team_then_lead",
    "latency_ms": 28
  }
}
```

| Field | Meaning |
|---|---|
| `bring` | 4 indices into `own_team` (0-5), in send-out order. `bring[0]` = first out, etc. |
| `bring_scores` | 6 scores (one per `own_team` slot). 0..1; higher = more confident this mon should be brought. |
| `lead` | 2 indices **into the `bring` list** (0..3). `lead[0]` = slot the lead in position 0 on field. Singles: only `lead[0]` meaningful, `lead[1]` may be `-1` or unset. |
| `lead_scores` | 4 scores (one per `bring` slot). 0..1. |
| `meta` | Same shape as `/decide`'s meta block. |

### `GET /health` — extended

Trace pings at program start. Response should indicate whether the
team-select model is loaded separately from the in-battle model:
```json
{
  "status": "ok",
  "models": {
    "decide": "v2_seq_d192_l8_k8",
    "decide_team": "lead_advisor_L3"
  }
}
```

If `decide_team` is missing, the trace logs the gap and falls back
to `LEAD_ORDER_*` config (or random) — same fallback as today.

---

## 3. Press translation (M4b driver only)

The team_preview_selecting press loop already navigates a cursor over
the 6 own slots. To drive from the model:

| Step | Press |
|---|---|
| Cursor on `bring[0]` slot | A |
| Cursor on `bring[1]` slot | A |
| Cursor on `bring[2]` slot | A |
| Cursor on `bring[3]` slot | A |

The trace already has `m_tp_cursor_slot` from `TeamPreviewCursorReader`
and re-uses the same nav primitives that `LEAD_ORDER_*` uses. The
only delta is **the source list** — config string vs model output.

Lead order: the `LEAD_ORDER_*` config encodes own-team indices in
send-out order. The model's `bring` field has the same semantics.
Drop-in replacement.

---

## 4. Server-side implementation gaps

1. **Rename `/team-select` → `/decide-team`** (or alias both). Symmetry
   with `/decide`.
2. **Add `format` + `regulation` request fields** — current schema
   takes own + opp only.
3. **Add `meta` block** to the response.
4. **`/health` shape extension** — separate model version per endpoint.

---

## 5. Rollout milestones (M4-specific)

### M4a — Shadow
- `InferenceClient::decide_team_async()` added (mirrors `decide_async`).
- Called once on `team_preview_selecting` entry, after both rosters
  are read.
- Reply logged to trace event + overlay:
  `model team: bring=[Garchomp, Hydreigon, Amoonguss, Pikachu] lead=[Garchomp, Amoonguss]`.
- Heuristic continues to press `LEAD_ORDER_*`.

### M4b — Driver
- New option `Enable Model-Driven Team Pick` (default OFF).
- When ON: model's `bring` list replaces `LEAD_ORDER_*` as the press
  source.
- Fallback chain on failure: timeout → `LEAD_ORDER_*` → random.

---

## 6. Open questions

- Should `/decide-team` accept the user's own moveset for each mon
  (the team-paste data)? Today's lead-advisor reads species + the
  opp's revealed species; movesets are part of the prior. If the
  model improves to consume team data, request schema bumps.
- Casual vs Ranked — does the model differentiate? Probably not at
  team-select; the format string `singles` / `doubles` is the only
  axis that matters.
- Cached prediction lifecycle — if the user backs out of team_preview
  before pressing through (e.g. opens battle_info), do we refire or
  trust the cache? Default: trust the cache; species haven't changed.
