# Per-Turn Sequence Tokens

## Hypothesis

Replace the single LSTM-collapsed history token with **K separate turn tokens**
attached to the main transformer. The model attends to each prior turn directly
instead of reading a compressed summary.

The history token is the only encoding lever that has moved val_loss
(-1.0 vs no-history). The compression to a single d-dim vector is the obvious
bottleneck — a transformer can route attention to the *relevant* past turn
(e.g. "what did opp lead with on turn 1" vs "what's on the field now") instead
of forcing the LSTM to memorize all of it.

## Current state (baseline)

`overnight_meta_off_history`: d=192, l=6, K=8 history window, single LSTM
hidden -> 1 token concatenated alongside 8 slot tokens + 1 field token.

- Best val_loss 1.749
- val_full_a 0.598, val_move_a 0.671, val_type_a 0.937

## Change

1. **Encoder**: no change. `_build_prev_seq` already emits per-turn rows
   (species/hp/action_types/action_moves), shape `(K, 4)` each.

2. **Model** (`src/vgc_model/model/action_model.py`):
   - Drop the `history_lstm`. Keep `history_step_proj` (it builds one token
     per turn out of the per-turn fields) — that's exactly what we need.
   - Build `step` exactly as today: `(B, K, d_model)` after `history_step_proj`.
   - Add a learned **turn-position embedding** `(K, d_model)` so the model
     can distinguish recency.
   - Concatenate all K turn tokens into the transformer input alongside the
     8 slot tokens + 1 field token: total seq len `8 + 1 + K = 17` (was 10).
   - Padding mask: turns earlier than the actual game start should be masked
     out. Encoder already pads with index 0; flag padded turns via a new
     field `prev_seq_valid_mask` of shape `(B, K)` bool.

3. **Encoder change** (`src/vgc_model/data/encoder.py`):
   - Add `prev_seq_valid_mask`: `True` for real turns, `False` for left-pad.
     Trivial — derive from whether the original `history` window was shorter
     than `HISTORY_K`.

4. **CLI**: new flag `--seq-history` (mutually exclusive with `--use-history`,
   which keeps the LSTM path so we can A/B against it).

## Success criteria

Match d=192, l=6, K=8, meta-off, same data shard. Compare on val_loss at
epoch 60.

| outcome | val_loss vs 1.749 | decision |
|---|---|---|
| < 1.70 | >0.05 better | pursue: try larger K, deeper transformer |
| 1.70–1.75 | flat | the LSTM compression wasn't the bottleneck; pivot to reveal channel |
| > 1.75 | worse | revert; the K extra tokens are confusing attention |

Watch for: train_loss should drop *more* than val (more capacity) — if val
diverges, dial back K or add dropout on turn tokens.

## Run command

```bash
ssh unraid 'curl -s -X POST http://localhost:8422/run -H "Content-Type: application/json" -d "{
  \"job_id\": \"seq_history_d192_l6_k8\",
  \"command\": \"cd /workspace && python -m vgc_model.training.train --version v4 --seq-history --shard-mode meta-off --d-model 192 --n-layers 6 --epochs 60 --run-name seq_history_d192_l6_k8\"
}"'
```

## Risk / time

- ~1 day of code (model + encoder field + CLI + smoke test)
- 1 train epoch should complete in ~250s (similar to LSTM path; K turn tokens
  are cheap, transformer seq len 10->17 is sub-quadratic at this size)
- ~4h for a full 60-epoch run on 4060

## Out of scope for this plan

- Cross-turn attention masks (e.g. "this turn's opp moves can attend to last
  turn's opp moves but not own moves"). Defer until baseline lands.
- Increasing K beyond 8 (do that as a follow-up if v1 is positive).
- Replacing the per-turn step builder with a richer per-turn encoder
  (currently averages 4 slot species/moves into one summary). Same: defer.
