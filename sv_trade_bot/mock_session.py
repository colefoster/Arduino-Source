"""Scripted mock that satisfies the SessionLike protocol without touching Discord.

Use via `--mock-discord` to dry-run the full pipeline (driver → switch_bridge →
C++ DiscordTradeBot → real Switch) without any browser, network call to Discord,
or risk of posting to a real channel.

The mock impersonates KlawfAPP. When the driver "posts" a set, the mock starts
feeding back a scripted DM lifecycle on a wall clock — same templates as the
parser tests, same timings as real KlawfAPP (compressed for dry runs).

Scenarios:
  success         — the happy path
  no_partner      — bot times out waiting for the Switch to enter the code
  too_slow        — Switch connects but doesn't finalize the trade
  illegal_set     — bot rejects the set up front
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from sv_trade_bot.playwright_session import ScrapedMessage


@dataclass
class _PendingMessage:
    """A DM the mock will surface once `time.monotonic() >= release_at`."""
    release_at: float
    body: str


@dataclass
class MockSession:
    """In-process stand-in for DiscordSession. Drop-in via SessionLike protocol."""
    scenario: str = "success"
    delay_loading: float = 3.0       # secs from post → "Loading the Trade Menu"
    delay_partner: float = 5.0       # secs from loading → "Found Link Trade partner"
    delay_finished: float = 12.0     # secs from loading → terminal event
    next_id: int = 0
    inbox: List[ScrapedMessage] = field(default_factory=list)
    _pending: List[_PendingMessage] = field(default_factory=list)
    _in_flight_code: Optional[str] = None

    # --- SessionLike ---

    def scrape_messages(self, author_filter: Optional[str] = None) -> List[ScrapedMessage]:
        self._release_due()
        return list(self.inbox)

    def post_message(self, body: str) -> None:
        # Pull the species off the Showdown set first line for the bot to echo back.
        species = self._species_from_post(body)
        code = self._next_code()
        self._in_flight_code = code

        now = time.monotonic()

        if self.scenario == "illegal_set":
            self._enqueue(now + 0.5,
                f"Notice...\nThat set is illegal: bad ability for {species}. Skipping.")
            self._enqueue(now + 1.0,
                "Trade Canceled\nYour trade was canceled.\nReason: IllegalSet")
            return

        # Code issued shortly after posting.
        formatted_code = f"{code[:4]} {code[4:]}"
        self._enqueue(now + 0.5,
            f"Here's your trade code!\n{formatted_code}\nInstructions")
        self._enqueue(now + 1.0,
            "Trade Request Queued\nQueue Position: 1\n"
            "Estimated wait time: Less than a minute")

        # Loading the Trade Menu — the GO signal.
        loading_t = now + self.delay_loading
        self._enqueue(loading_t,
            f"Loading the Trade Menu...\nPokemon: {species}\nTrade Code: {formatted_code}\n\n"
            f"Initializing trade ({species}). Please be ready.")
        self._enqueue(loading_t + 0.5,
            f"Now Searching for you,\nWaiting For:  .colef\nMy IGN: Klawf.net\n\n"
            f"Insert your Trade Code!")

        if self.scenario == "no_partner":
            # Switch never connected.
            self._enqueue(loading_t + self.delay_partner,
                "Notice...\nNo trading partner found. Canceling the trade.")
            self._enqueue(loading_t + self.delay_partner + 1.5,
                "Trade Canceled\nYour trade was canceled.\nReason: NoTrainerFound")
            return

        # Both 'success' and 'too_slow' have the partner-found event.
        self._enqueue(loading_t + self.delay_partner,
            "Notice...\nFound Link Trade partner: Cole. TID: 863442 SID: 3548 "
            "Waiting for a Pokémon...")

        if self.scenario == "too_slow":
            self._enqueue(loading_t + self.delay_finished,
                "Notice...\nOops! Something happened. Canceling the trade: TrainerTooSlow.")
            self._enqueue(loading_t + self.delay_finished + 1.5,
                "Trade Canceled\nYour trade was canceled.\nReason: TrainerTooSlow")
            return

        # success
        self._enqueue(loading_t + self.delay_finished,
            "Trade finished. Enjoy!\nHere's what you traded me!")

    # --- scripting helpers ---

    def _enqueue(self, release_at: float, body: str) -> None:
        self._pending.append(_PendingMessage(release_at=release_at, body=body))

    def _release_due(self) -> None:
        now = time.monotonic()
        still_pending = []
        for pm in self._pending:
            if now >= pm.release_at:
                self.inbox.append(ScrapedMessage(
                    discord_id=f"mock-{self.next_id}",
                    author="KlawfAPP",
                    body=pm.body,
                ))
                self.next_id += 1
            else:
                still_pending.append(pm)
        self._pending = still_pending

    def _next_code(self) -> str:
        # Deterministic-ish but unique per call.
        n = 10000000 + self.next_id * 13 + int(time.monotonic() * 1000) % 1000
        return f"{n:08d}"[-8:]

    @staticmethod
    def _species_from_post(body: str) -> str:
        # Body is "$trade Vaporeon @ Leftovers\n..." — pull the species off line 1.
        first = body.strip().splitlines()[0]
        first = re.sub(r"^\$(?:trade|t|bt)\s+", "", first, flags=re.IGNORECASE)
        head = first.split("@", 1)[0].strip()
        m = re.search(r"\(([^)]+)\)", head)
        if m and m.group(1) not in ("M", "F"):
            return m.group(1).strip()
        return head.split()[0] if head else "Unknown"
