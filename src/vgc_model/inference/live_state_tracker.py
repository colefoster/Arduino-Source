"""Accumulate per-match state from SerialPrograms LiveDetectorTrace events.

The trace is event-driven and ephemeral (ring buffer on the Mac dev runner).
This tracker takes the stream as input and produces a longer-lived view:
who's alive, who just fainted, what turn we're on, and which match this is.

Inputs:  individual event dicts from /live-trace/recent
Outputs: snapshot() -> dict; iter_faints() -> list of (side, slot) since prev call

Match boundaries
----------------
A new match begins on:
  - first event with current_screen == "team_select" or "team_preview_selecting"
    when no match is in progress, OR
  - match_in_progress flips False -> True

Match ends on:
  - current_screen == "result_screen" or "post_match"
  - match_in_progress flips True -> False

State only updates on events where PokeballAliveDetector.status == "ok".

Pokeball states are "alive" / "fainted" / "empty" per slot. We only treat
alive -> fainted as a real transition. empty stays empty (not on the team
this match), and fainted -> alive is treated as noise (would imply a misread
or a new match where the prior state wasn't reset).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional


def _pokeball_dict(event: dict) -> Optional[dict]:
    pipeline = event.get("pipeline") or {}
    entry = pipeline.get("PokeballAliveDetector") or {}
    if entry.get("status") != "ok":
        return None
    out = entry.get("output") or {}
    own = out.get("own")
    opp = out.get("opp")
    if not isinstance(own, list) or not isinstance(opp, list):
        return None
    if len(own) != 6 or len(opp) != 6:
        return None
    return {"own": own, "opp": opp}


@dataclass
class FaintEvent:
    side: str          # "own" | "opp"
    slot: int          # 0..5
    server_seq: int    # event seq from the runner
    server_ts_ms: int  # event ts


@dataclass
class MatchState:
    """Per-match accumulated state."""
    match_id: int = 0
    started_seq: int = 0
    started_ts_ms: int = 0
    last_seq: int = 0
    last_ts_ms: int = 0
    last_screen: str = ""
    turn: int = 0
    # Slot states; updated only on valid PokeballAliveDetector readings.
    # Initialized lazily from the first valid reading after match start.
    own: list = field(default_factory=lambda: ["empty"] * 6)
    opp: list = field(default_factory=lambda: ["empty"] * 6)
    # Faint events recorded for this match.
    faints: list = field(default_factory=list)


def _alive_count(states: list) -> int:
    return sum(1 for s in states if s == "alive")


class LiveStateTracker:
    """Thread-safe accumulator for live-trace events.

    Typical use:

        tracker = LiveStateTracker()
        for ev in poll_live_trace(...):
            tracker.ingest(ev)
        snap = tracker.snapshot()

    The tracker is also fed by a background polling thread when used inside
    the dashboard; see start_polling_thread().
    """

    MATCH_START_SCREENS = {"team_select", "team_preview_selecting"}
    MATCH_END_SCREENS = {"result_screen", "post_match"}

    def __init__(self):
        self._lock = threading.Lock()
        self._match: Optional[MatchState] = None
        self._next_match_id = 1
        self._last_seq_seen = 0
        self._last_match_in_progress: Optional[bool] = None
        self._recent_faints_buffer: list = []  # capped, for snapshot consumers
        self._faints_buffer_max = 32

    # ─── Ingestion ──────────────────────────────────────────────────

    def ingest(self, event: dict) -> None:
        with self._lock:
            self._ingest_locked(event)

    def ingest_many(self, events: Iterable[dict]) -> None:
        with self._lock:
            for ev in events:
                self._ingest_locked(ev)

    def _ingest_locked(self, event: dict) -> None:
        seq = event.get("server_seq") or 0
        if seq <= self._last_seq_seen:
            return  # Already processed.
        self._last_seq_seen = seq

        screen = event.get("current_screen") or ""
        match_in_progress = event.get("match_in_progress")
        ts = event.get("server_ts_ms") or 0

        # Match boundary detection.
        if self._should_start_new_match(screen, match_in_progress):
            self._match = MatchState(
                match_id=self._next_match_id,
                started_seq=seq, started_ts_ms=ts,
            )
            self._next_match_id += 1
        elif self._should_end_match(screen, match_in_progress) and self._match is not None:
            # Stop accumulating but keep last snapshot until next match starts.
            pass

        if isinstance(match_in_progress, bool):
            self._last_match_in_progress = match_in_progress

        if self._match is None:
            return

        m = self._match
        m.last_seq = seq
        m.last_ts_ms = ts
        m.last_screen = screen

        # Turn counter from engine_view.field.turn if available.
        ev = event.get("engine_view") or {}
        f = ev.get("field") or {}
        t = f.get("turn")
        if isinstance(t, int) and t > m.turn:
            m.turn = t

        # Pokeball state update + faint detection.
        pb = _pokeball_dict(event)
        if pb is None:
            return
        for side in ("own", "opp"):
            current = pb[side]
            prev = m.own if side == "own" else m.opp
            for i in range(6):
                cur = current[i]
                old = prev[i]
                if old == "alive" and cur == "fainted":
                    fe = FaintEvent(side=side, slot=i, server_seq=seq, server_ts_ms=ts)
                    m.faints.append(fe)
                    self._recent_faints_buffer.append(fe)
                    if len(self._recent_faints_buffer) > self._faints_buffer_max:
                        self._recent_faints_buffer.pop(0)
                # Always advance to the latest reading. alive→empty (rare,
                # would mean lost the reading) and empty→alive (start of
                # match, mons appearing) are accepted; fainted→alive is
                # treated as a noisy reading and we keep "fainted".
                if old == "fainted" and cur == "alive":
                    continue
                prev[i] = cur

    def _should_start_new_match(self, screen: str, mip) -> bool:
        if self._match is None and (
            screen in self.MATCH_START_SCREENS or mip is True
        ):
            return True
        if isinstance(mip, bool) and self._last_match_in_progress is False and mip is True:
            return True
        return False

    def _should_end_match(self, screen: str, mip) -> bool:
        if screen in self.MATCH_END_SCREENS:
            return True
        if isinstance(mip, bool) and self._last_match_in_progress is True and mip is False:
            return True
        return False

    # ─── Snapshot ──────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-friendly picture of current state."""
        with self._lock:
            m = self._match
            if m is None:
                return {
                    "match_id": None,
                    "in_match": False,
                    "last_seq_seen": self._last_seq_seen,
                    "recent_faints": [],
                }
            return {
                "match_id": m.match_id,
                "in_match": True,
                "started_ts_ms": m.started_ts_ms,
                "last_seq": m.last_seq,
                "last_ts_ms": m.last_ts_ms,
                "last_screen": m.last_screen,
                "turn": m.turn,
                "own": list(m.own),
                "opp": list(m.opp),
                "own_alive_count": _alive_count(m.own),
                "opp_alive_count": _alive_count(m.opp),
                "faint_count": len(m.faints),
                "faints": [
                    {"side": fe.side, "slot": fe.slot, "seq": fe.server_seq, "ts_ms": fe.server_ts_ms}
                    for fe in m.faints
                ],
                "last_seq_seen": self._last_seq_seen,
                "recent_faints": [
                    {"side": fe.side, "slot": fe.slot, "seq": fe.server_seq, "ts_ms": fe.server_ts_ms}
                    for fe in self._recent_faints_buffer
                ],
            }

    # ─── Background polling (for dashboard) ─────────────────────────

    def start_polling_thread(self, runner_url: str, interval_sec: float = 1.0):
        """Spin up a daemon thread that polls the runner's live-trace ring
        and feeds events into this tracker."""
        import urllib.request, json
        stop = threading.Event()

        def loop():
            since = 0
            while not stop.is_set():
                try:
                    req = urllib.request.Request(
                        f"{runner_url}/live-trace/recent?since={since}&limit=100",
                        method="GET",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read())
                    events = data.get("events") or []
                    for ev in events:
                        self.ingest(ev)
                        s = ev.get("server_seq") or 0
                        if s > since:
                            since = s
                except Exception:
                    # Runner down or transient error; back off and retry.
                    pass
                if stop.wait(interval_sec):
                    break

        t = threading.Thread(target=loop, daemon=True, name="live-state-poller")
        t.start()
        return stop  # caller can .set() to terminate
