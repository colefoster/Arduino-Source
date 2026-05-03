# SV + HOME + Discord trade-bot loop

End-to-end pipeline that consumes a long list of Showdown sets, drives a public Discord gen-bot to produce each mon, and uses SerialPrograms to receive the trade and (eventually) park the result in HOME.

## Hardware / account assumptions

- **Legit Switch** (no CFW). Switch is a trade *client* only.
- **Public Discord gen-bot** (SysBot.NET-style). We're rate-limited and ban-prone.
- **Discord automation = full automation via Playwright on web Discord**, persistent browser profile (logged in once, no stored tokens). Lower detection risk than a discord.py selfbot since traffic looks like a real browser. Cole supervises first several runs before leaving it unattended.
- **Throwaway pool = 1–2 dedicated boxes** of disposable mons (Wooper farm or similar). Bot rotates through slots; when the pool is exhausted, program halts and notifies.

## Process layout

Three independent processes on the host PC, glued by a localhost TCP socket (or Unix socket):

```
┌────────────────────┐   events    ┌─────────────────────────┐
│ discord_watcher.py │ ──────────▶ │ SerialPrograms (C++)    │
│  - reads channel   │             │  PokemonSV_DiscordTrade │
│  - parses messages │ ◀────────── │  - drives Switch        │
│  - tracks queue    │   acks      │  - runs trade routine   │
└────────────────────┘             └─────────────────────────┘
        │
        ▼
   ┌──────────┐
   │ sets.db  │  SQLite: pending / submitted / queued / traded / failed
   └──────────┘
```

Optional 3rd loop: **HOME mover** — separate SerialPrograms routine (`PokemonHome_TransferFromSV`) that the user runs when the SV box fills up. Out of scope for v1.

## Wire protocol (newline-delimited JSON over TCP)

Listener → Switch program:

```json
{"type": "TRADE_READY",     "code": "12345678", "set_id": "abc123"}
{"type": "TRADE_CANCELLED", "set_id": "abc123", "reason": "illegal_set"}
{"type": "PING"}
```

Switch → Listener:

```json
{"type": "TRADE_COMPLETE", "set_id": "abc123"}
{"type": "TRADE_FAILED",   "set_id": "abc123", "reason": "partner_no_show"}
{"type": "READY"}
{"type": "PONG"}
```

The Switch program holds at most one pending `TRADE_READY` at a time. If a second arrives while busy, it's NACK'd and the listener re-queues.

## Switch-side state machine

Lives in `SerialPrograms/Source/PokemonSV/Programs/Trading/PokemonSV_DiscordTradeBot.{h,cpp}`.

Reuses `trade_current_pokemon()` (already handles black-screen → dialog mash → TradeDoneDetector). New work is **pre-trade** (Y-Comm → Link Trade → enter code → wait for partner) and **post-trade housekeeping** (advance counter, possibly move freshly traded mon to a different slot).

```
                   ┌─────────────────┐
                   │  IDLE_AT_BOX    │  ← always start/end here
                   └────────┬────────┘
                            │ TRADE_READY{code}
                            ▼
                   ┌─────────────────┐
                   │  OPEN_PORTAL    │  X → Y-Comm → Link Trade → Search w/ Code
                   └────────┬────────┘
                            ▼
                   ┌─────────────────┐
                   │  ENTER_CODE     │  drive 8-digit code via FastCodeEntry helper
                   └────────┬────────┘
                            ▼
                   ┌─────────────────┐
                   │  WAIT_PARTNER   │  detect "partner found" screen, timeout 90s
                   └────┬───────┬────┘
                        │ ok    │ timeout
                        ▼       ▼
                   ┌─────────────────┐    ┌──────────────────┐
                   │  PICK_THROWAWAY │    │  CANCEL_PORTAL   │
                   │ (cursor → slot) │    │ → IDLE → emit    │
                   └────────┬────────┘    │   TRADE_FAILED   │
                            ▼             └──────────────────┘
                   ┌─────────────────┐
                   │ trade_current_  │  existing routine: A-mash, dialog handling,
                   │ pokemon()       │  move-learn rejection, TradeDoneDetector
                   └────────┬────────┘
                            ▼
                   ┌─────────────────┐
                   │ POST_TRADE_MOVE │  move new mon out of slot 1 to next free slot
                   └────────┬────────┘
                            ▼
                   ┌─────────────────┐
                   │ IDLE_AT_BOX     │  emit TRADE_COMPLETE
                   └─────────────────┘
```

## Build status (2026-05-02)

| Component | Path | State |
|---|---|---|
| Parser | `discord_driver/parser.py` | ✅ 18 tests |
| Set queue (SQLite) | `discord_driver/set_queue.py` | ✅ 12 tests |
| Switch bridge (TCP, Python side) | `discord_driver/switch_bridge.py` | ✅ 8 tests |
| Driver orchestrator | `discord_driver/driver.py` | ✅ 9 tests |
| Playwright session | `discord_driver/playwright_session.py` | ⚠ untested (selectors only verified via type-check) |
| CLI entry | `discord_driver/__main__.py` | ⚠ imports clean, untested live |
| C++ trade routine | `PokemonSV_DiscordTradeBot.cpp` | ✅ builds |
| C++ TCP bridge client | `PokemonSV_DiscordTradeBridge.cpp` | ✅ builds |
| C++ program panel | `PokemonSV_DiscordTradeBotProgram.cpp` | ✅ builds |
| Panel registered | `PokemonSV_Panels.cpp` | ✅ builds |

**47 Python tests passing. SerialProgramsCommandLine builds.**

Next: dry-run with `playwright install chromium` + first manual login + watch what selectors break.

## What to build, in order

1. **`PokemonSV_DiscordTradeBot.h/.cpp`** — single-trade routine: takes a code, runs the state machine, returns success/failure. No Discord, no socket.
2. **Local CLI test** — run #1 with a hardcoded code against a friend's Switch or another instance. Validates the Switch-side state machine in isolation.
3. **`DiscordTradeListener` C++ class** — TCP server, parses the JSON protocol, owns a queue of pending codes, drives #1.
4. **Program panel** — wire #3 into a `MultiSwitchProgram` so it shows up in the SerialPrograms UI with start/stop and per-trade stats.
5. **`discord_driver/`** (Python + Playwright) — launches Chromium with a persistent profile, navigates to the target server/channel, and:
   - **Reads** new messages, regex-parses against known gen-bot templates (queued / ready+code / cancelled / illegal / completed)
   - **Posts** sets from the SQLite queue, respecting per-server cooldowns
   - **Sends** events to the C++ side over the JSON socket
   - Falls back to a "human attention needed" state if a message doesn't match any known pattern (logs raw text, halts loop)
6. **HOME mover** (separate routine, deferred) — SV → HOME box transfer when SV box fills.

## Discord parser spec (KlawfAPP)

Bot username = `KlawfAPP`. All messages below are from that user; ignore others. Messages arrive as separate Discord messages (sometimes batched into one block).

### Lifecycle of a single trade

| Order | Template (key phrase) | Meaning | Driver action |
|---|---|---|---|
| 1 | `Here's your trade code!\n<XXXX XXXX>\nInstructions` | Trade enqueued, code assigned | Record code, mark set as `queued`. **Do NOT drive Switch yet.** |
| 2 | `Trade Request Queued ... Queue Position: N ... Estimated wait time: ...` | Confirmation + ETA | Update set status, log ETA |
| 3 | `You're Up Next! ... Get ready to connect!` | ~30s warning (sometimes skipped if Q=1) | Wake Switch, ensure at SV box |
| 4 | `Loading the Trade Menu...\nPokemon: <name>\nTrade Code: <XXXX XXXX>\nInitializing trade (<name>). Please be ready.` | **GO signal.** Bot is opening Link Trade now. | **Emit `TRADE_READY{code}` to Switch.** Switch enters Link Trade and types code. |
| 5 | `Now Searching for you,\nWaiting For: <handle>\nMy IGN: <ign>\n\nInsert your Trade Code!` | Bot is now waiting in code-entry | Confirms #4; no action needed |
| 6a | `Notice...\nFound Link Trade partner: <name>. TID: ... SID: ... Waiting for a Pokémon...` | Connected successfully | Switch should already be confirming the trade |
| 6b | `Notice...\nNo trading partner found. Canceling the trade.` | We never connected (Switch failed to enter code in time) | Emit `TRADE_FAILED{reason: "NoTrainerFound"}`, return Switch to box |
| 6c | `Notice...\nOops! Something happened. Canceling the trade: TrainerTooSlow.` | Connected but didn't complete trade fast enough | Emit `TRADE_FAILED{reason: "TrainerTooSlow"}` |
| 7-success | `Trade finished. Enjoy!` + `Here's what you traded me!` + `.pk9` attachment | Done | Emit `TRADE_COMPLETE`, advance throwaway cursor |
| 7-fail | `Trade Canceled\nYour trade was canceled.\nReason: <NoTrainerFound\|TrainerTooSlow\|...>` | Final failure confirmation | Reconcile with 6b/6c reason if not already failed |

### Regex sketches

```python
RE_CODE_ISSUED   = r"Here's your trade code!\s*\n\s*(\d{4}\s+\d{4})"
RE_QUEUED        = r"Queue Position:\s*(\d+).*Estimated wait time:\s*(.+?)(?:•|$)"
RE_UP_NEXT       = r"You're Up Next!"
RE_LOADING       = r"Loading the Trade Menu\.\.\.\s*\nPokemon:\s*(.+?)\s*\nTrade Code:\s*(\d{4}\s+\d{4})"
RE_SEARCHING     = r"Now Searching for you,\s*\nWaiting For:\s*(\S+)"
RE_PARTNER_FOUND = r"Found Link Trade partner:\s*(\S+?)\."
RE_NO_PARTNER    = r"No trading partner found"
RE_TOO_SLOW      = r"Canceling the trade:\s*TrainerTooSlow"
RE_TRADE_DONE    = r"Trade finished\. Enjoy!"
RE_TRADE_CANCEL  = r"Trade Canceled\s*\n.*Reason:\s*(\w+)"
```

Strip the `XXXX XXXX` space before sending the code to the C++ side — Switch input is 8 contiguous digits.

### Concurrency notes

- The bot pipelines: a 2nd `Here's your trade code!` can arrive while a 1st trade is mid-flight. Driver maintains a list of (code, set_id, status) and only emits `TRADE_READY` when the matching `Loading the Trade Menu` arrives.
- Match `Loading the Trade Menu` back to a queued set by **code string** (or by Pokémon species as a tiebreaker if codes ever collide, which they shouldn't in 8 digits).
- If a `Trade Canceled` arrives without a prior matched `Loading the Trade Menu`, log loud — means the parser missed an event.

## Open questions

- **Which Discord server / which gen-bot variant?** Determines the message regex and command syntax for the watcher. Need a sample of 5–10 real bot messages (queued / ready / completed / failed / illegal) to write the parser.
- **Trade code source.** Public bots usually generate the code themselves; we read it from the message. Some let the user pick — confirm.
- **Per-trade cooldown.** Most servers cap trades/day. The Python side should enforce, but the Switch program should also refuse to spam if codes arrive too fast.
- **Throwaway depletion behavior.** When the throwaway boxes run dry, halt + Discord-DM-self? Or auto-pause and wait for a "throwaways refilled" command?
- **Playwright fragility.** Discord ships UI updates that may break selectors. Mitigation: prefer accessibility roles (`getByRole('textbox', { name: 'Message #channel' })`) over CSS selectors, and snapshot the DOM on every parser failure for fast diagnosis.
