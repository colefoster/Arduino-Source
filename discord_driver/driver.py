"""Discord-driven trade orchestrator.

Glue between four components:
  - DiscordSession (playwright_session.py): scrapes DMs, posts in channel
  - SetQueue       (set_queue.py)         : tracks set lifecycle in SQLite
  - SwitchBridge   (switch_bridge.py)     : sends TRADE_READY to C++ side
  - parse_message  (parser.py)            : classifies KlawfAPP DM bodies

Designed so the loop body is pure-Python and testable: pass in fakes for
the session and bridge; run one tick; assert state.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol, Set

from discord_driver.parser import (
    BatchAllComplete, BatchTradeCompleted, BatchTradeReady,
    CodeIssued, LoadingTrade, NoPartner, TooSlow, TradeCanceled, TradeFinished,
    Unknown, parse_message,
)
from discord_driver.set_queue import SetQueue, TradeSet


logger = logging.getLogger(__name__)


class SessionLike(Protocol):
    def scrape_messages(self, author_filter: Optional[str] = None): ...
    def post_message(self, body: str) -> None: ...


class BridgeLike(Protocol):
    def is_connected(self) -> bool: ...
    def send_ready(self, code: str, set_id: str, batch_size: int = 1) -> None: ...
    def send_next_trade_ready(self, batch_id: str) -> None: ...


@dataclass
class DriverConfig:
    bot_username: str = "KlawfAPP"
    trade_command_prefix: str = "$trade"   # use "-batch trade" with batch_size > 1
    batch_size: int = 1                     # 1 = single-trade posts; >1 = -batch trade post w/ N sets joined by '---'
    batch_separator: str = "---"            # line between sets in a batch post
    max_in_flight: int = 1                  # how many of our trades may be queued at once
    poll_interval_seconds: float = 2.0

    # --- spam guards (always on, including in mock mode for parity) ---
    max_posts_per_session: int = 5          # halt loop after N posts; require restart to continue
    min_seconds_between_posts: float = 30.0 # hard floor regardless of state machine
    in_flight_stale_seconds: float = 600.0  # if any in-flight set hasn't moved in this long, halt


@dataclass
class DriverState:
    """Per-run state. Persisted set status lives in SetQueue; this only
    tracks ephemeral things like which Discord message ids we've already
    handled, so we don't re-emit events on every tick."""
    seen_message_ids: Set[str] = field(default_factory=set)
    posts_this_session: int = 0
    last_post_monotonic: float = 0.0
    halted: bool = False
    halt_reason: str = ""


class Driver:
    def __init__(
        self,
        session: SessionLike,
        queue: SetQueue,
        bridge: BridgeLike,
        config: DriverConfig = DriverConfig(),
    ):
        self.session = session
        self.queue = queue
        self.bridge = bridge
        self.config = config
        self.state = DriverState()

    def tick(self) -> None:
        """One pass: process new DMs, then post next pending set if there's room.

        Note: even when halted (post-cap reached or stale state), we still
        process incoming DMs so in-flight sets can drain to a terminal state.
        Halt only suppresses NEW posts.
        """
        self._process_new_dms()
        if self.state.halted:
            return
        if self._check_stale_in_flight():
            return
        self._post_next_if_room()

    def halt(self, reason: str) -> None:
        if not self.state.halted:
            self.state.halted = True
            self.state.halt_reason = reason
            logger.error("Driver HALTED: %s", reason)

    def _check_stale_in_flight(self) -> bool:
        in_flight = self.queue.in_flight()
        if not in_flight:
            return False
        oldest_age = time.time() - min(s.updated_at for s in in_flight)
        if oldest_age > self.config.in_flight_stale_seconds:
            self.halt(
                f"in-flight set has been stuck {oldest_age:.0f}s "
                f"(> {self.config.in_flight_stale_seconds:.0f}s)"
            )
            return True
        return False

    def run_forever(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:
                logger.exception("Driver tick failed")
            time.sleep(self.config.poll_interval_seconds)

    # --- DM ingestion ---

    def _process_new_dms(self) -> None:
        messages = self.session.scrape_messages(author_filter=self.config.bot_username)
        for msg in messages:
            if msg.discord_id in self.state.seen_message_ids:
                continue
            self.state.seen_message_ids.add(msg.discord_id)
            self._handle_dm(msg.body)

    def _handle_dm(self, body: str) -> None:
        event = parse_message(body)

        if isinstance(event, CodeIssued):
            # Match by oldest 'submitted' set with no code yet — bot processes
            # in submit order, so this is correct as long as we don't post the
            # next set until the previous one has its code assigned.
            target = self._oldest_with_status("submitted")
            if target is None:
                logger.warning("CodeIssued for unknown set (no submitted set pending). code=%s", event.code)
                return
            if target.batch_id:
                # One code applies to every set in this batch.
                self.queue.mark_batch_queued(target.batch_id, event.code)
                batch = self.queue.in_batch(target.batch_id)
                logger.info("Batch %s (%d sets) queued with code %s",
                            target.batch_id, len(batch), event.code)
            else:
                self.queue.mark_queued(target.set_id, event.code)
                logger.info("Set %s queued with code %s", target.set_id, event.code)
            return

        if isinstance(event, LoadingTrade):
            target = self.queue.get_by_code(event.code)
            if target is None:
                logger.warning("LoadingTrade for unknown code %s", event.code)
                return

            if target.batch_id:
                # Mark every set in the batch as loading; send ONE TRADE_READY
                # carrying the batch_size. C++ will A-mash into trade 1 and
                # then wait for NEXT_TRADE_READY before advancing slot.
                batch = self.queue.in_batch(target.batch_id)
                for s in batch:
                    if s.status == "queued":
                        self.queue.mark_loading(s.set_id)
                if not self.bridge.is_connected():
                    logger.error("LoadingTrade for batch %s but Switch bridge not connected; batch will be missed",
                                 target.batch_id)
                    for s in batch:
                        self.queue.mark_failed(s.set_id, "switch_bridge_disconnected")
                    return
                # set_id of the first set in the batch — C++ uses this to
                # correlate any TRADE_FAILED back to the originating row.
                first = batch[0]
                self.bridge.send_ready(code=event.code, set_id=first.set_id, batch_size=len(batch))
                logger.info("Sent TRADE_READY (batch %s, size %d) to Switch starting at set %s",
                            target.batch_id, len(batch), first.set_id)
                return

            self.queue.mark_loading(target.set_id)
            if not self.bridge.is_connected():
                logger.error("LoadingTrade arrived but Switch bridge not connected; trade will be missed")
                self.queue.mark_failed(target.set_id, "switch_bridge_disconnected")
                return
            self.bridge.send_ready(code=event.code, set_id=target.set_id)
            logger.info("Sent TRADE_READY to Switch for set %s", target.set_id)
            return

        if isinstance(event, BatchTradeCompleted):
            # Trade `event.index` of `event.total` just completed on the bot
            # side. Mark the matching row in the active batch as traded.
            batch = self._active_batch()
            if batch is None:
                logger.warning("BatchTradeCompleted %d/%d with no active batch",
                               event.index, event.total)
                return
            if event.index < 1 or event.index > len(batch):
                logger.warning("BatchTradeCompleted %d/%d out of range for batch of %d",
                               event.index, event.total, len(batch))
                return
            target = batch[event.index - 1]  # batch is ordered by batch_index ASC
            if target.status != "loading":
                logger.warning("BatchTradeCompleted %d but set %s already in status=%s",
                               event.index, target.set_id, target.status)
                return
            self.queue.mark_traded(target.set_id)
            logger.info("Batch trade %d/%d done — marked set %s (%s) traded",
                        event.index, event.total, target.set_id, target.species)
            return

        if isinstance(event, BatchTradeReady):
            # Bot says "Trade N/M: Ready!" — tell C++ to advance to next slot.
            batch = self._active_batch()
            if batch is None:
                logger.warning("BatchTradeReady %d/%d with no active batch",
                               event.index, event.total)
                return
            if not self.bridge.is_connected():
                logger.error("BatchTradeReady but Switch bridge not connected")
                return
            self.bridge.send_next_trade_ready(batch_id=batch[0].batch_id or "")
            logger.info("Sent NEXT_TRADE_READY to Switch (trade %d/%d)",
                        event.index, event.total)
            return

        if isinstance(event, BatchAllComplete):
            # Final terminal event. Close any remaining loading sets in the
            # most recent batch — there shouldn't be many (just the last one,
            # since BatchTradeCompleted closes them as we go), but the bot
            # doesn't always send a per-trade completion for the final mon.
            batch = self._active_batch()
            if batch is None:
                logger.warning("BatchAllComplete with no active batch")
                return
            closed = 0
            for s in batch:
                if s.status == "loading":
                    self.queue.mark_traded(s.set_id)
                    closed += 1
            logger.info("Batch %s fully complete — closed %d remaining loading set(s)",
                        batch[0].batch_id, closed)
            return

        if isinstance(event, TradeFinished):
            # No code in this message; close the most recent 'loading' set.
            target = self._newest_with_status("loading")
            if target is None:
                logger.warning("TradeFinished with no loading set in flight")
                return
            self.queue.mark_traded(target.set_id)
            logger.info("Set %s marked traded", target.set_id)
            return

        if isinstance(event, (NoPartner, TooSlow)):
            target = self._newest_with_status("loading")
            reason = "no_partner" if isinstance(event, NoPartner) else "too_slow"
            if target is None:
                logger.warning("%s with no loading set in flight", reason)
                return
            self.queue.mark_failed(target.set_id, reason)
            return

        if isinstance(event, TradeCanceled):
            # Final confirmation. If we already marked the set failed via the
            # earlier preamble (NoPartner/TooSlow), this is a no-op. Otherwise
            # find the most recent in-flight set and fail it.
            target = (self._newest_with_status("loading")
                      or self._newest_with_status("queued")
                      or self._newest_with_status("submitted"))
            if target is None:
                logger.warning("TradeCanceled with no in-flight set, reason=%s", event.reason)
                return
            if target.status != "failed":
                self.queue.mark_failed(target.set_id, event.reason)
            return

        if isinstance(event, Unknown):
            logger.error("Unknown DM body — halting loop is up to caller. raw=%r", event.raw[:200])
            return

        # CodeIssued/Queued/UpNext/Searching/PartnerFound: informational, no action.

    # --- posting ---

    def _post_next_if_room(self) -> None:
        # Don't post if the Switch bridge isn't connected — the bot's lifecycle
        # would fire (and "Loading the Trade Menu" would be missed) before the
        # C++ side could pick it up. Wait for connection.
        if not self.bridge.is_connected():
            return

        if self.state.posts_this_session >= self.config.max_posts_per_session:
            self.halt(
                f"posts_per_session cap hit ({self.config.max_posts_per_session})"
            )
            return

        now = time.monotonic()
        since_last = now - self.state.last_post_monotonic
        if self.state.last_post_monotonic > 0 and since_last < self.config.min_seconds_between_posts:
            return  # cooldown not elapsed; will retry next tick

        in_flight = len(self.queue.in_flight())
        if in_flight >= self.config.max_in_flight:
            return

        if self.config.batch_size > 1:
            self._post_batch(now)
        else:
            self._post_single(now)

    def _post_single(self, now: float) -> None:
        nxt = self.queue.next_pending()
        if nxt is None:
            return
        body = f"{self.config.trade_command_prefix} {nxt.body}"
        self.session.post_message(body)
        self.queue.mark_submitted(nxt.set_id)
        self.state.posts_this_session += 1
        self.state.last_post_monotonic = now
        logger.info("Posted set %s (%s) — post %d/%d this session",
                    nxt.set_id, nxt.species,
                    self.state.posts_this_session, self.config.max_posts_per_session)

    def _post_batch(self, now: float) -> None:
        n = self.config.batch_size
        sets = self.queue.next_pending_batch(n)
        if not sets:
            return
        # Don't post a partial batch — wait until N pending are available, so
        # the bot's "5 Pokémon" queue confirmation matches what we sent.
        if len(sets) < n:
            logger.info("Holding batch post: only %d/%d pending sets available", len(sets), n)
            return

        sep = f"\n{self.config.batch_separator}\n"
        body = (
            f"{self.config.trade_command_prefix}\n"
            + sep.join(s.body.strip() for s in sets)
        )
        batch_id = uuid.uuid4().hex[:12]
        self.session.post_message(body)
        self.queue.mark_batch_submitted([s.set_id for s in sets], batch_id)
        self.state.posts_this_session += 1
        self.state.last_post_monotonic = now
        logger.info("Posted batch %s (%d sets: %s) — post %d/%d this session",
                    batch_id, len(sets),
                    ", ".join(s.species for s in sets),
                    self.state.posts_this_session, self.config.max_posts_per_session)

    # --- queue helpers ---

    def _active_batch(self) -> Optional[list]:
        """The currently in-flight batch (by most-recently-touched set), or None.
        Returns the full ordered list of sets in that batch."""
        in_flight = self.queue.in_flight()
        batched = [s for s in in_flight if s.batch_id]
        if not batched:
            return None
        # Most recently touched batch wins.
        latest = max(batched, key=lambda s: s.updated_at)
        return self.queue.in_batch(latest.batch_id)

    def _oldest_with_status(self, status: str) -> Optional[TradeSet]:
        rows = [s for s in self.queue.in_flight() if s.status == status]
        return min(rows, key=lambda s: s.updated_at) if rows else None

    def _newest_with_status(self, status: str) -> Optional[TradeSet]:
        rows = [s for s in self.queue.in_flight() if s.status == status]
        return max(rows, key=lambda s: s.updated_at) if rows else None
