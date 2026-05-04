"""Parse a single KlawfAPP DM body into a typed lifecycle event.

The Playwright layer extracts one message body at a time from the DOM and hands
it here. This module is pure regex over the message text — no I/O, no Discord
client. See memory/sv-trade-bot/protocol.md for the full lifecycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class CodeIssued:
    """First DM after a $trade request lands. Code is reserved but bot is not yet
    searching — do NOT drive the Switch on this event."""
    code: str  # 8 contiguous digits, spaces stripped


@dataclass(frozen=True)
class Queued:
    position: int
    eta_text: str  # e.g. "Less than a minute", "3 minutes", "4.5 minutes"


@dataclass(frozen=True)
class UpNext:
    pass


@dataclass(frozen=True)
class LoadingTrade:
    """The GO signal. Bot is opening Link Trade now — Switch should enter the
    code on receipt of this event."""
    species: str
    code: str  # 8 contiguous digits, spaces stripped


@dataclass(frozen=True)
class Searching:
    waiting_for: str  # the handle the bot is waiting on (Cole's IGN handle)
    bot_ign: str


@dataclass(frozen=True)
class PartnerFound:
    partner_name: str
    tid: int
    sid: int


@dataclass(frozen=True)
class NoPartner:
    """Switch failed to enter the code in time."""


@dataclass(frozen=True)
class TooSlow:
    """Switch connected but didn't finalize the trade fast enough."""


@dataclass(frozen=True)
class TradeFinished:
    pass


@dataclass(frozen=True)
class BatchTradeReady:
    """Bot's 'Trade N/M: Ready!' signal between batch trades. Tells the Switch
    to advance to the next box slot and offer it. Trade 1 is implicit in the
    initial LoadingTrade message — first BatchTradeReady is for trade 2."""
    index: int      # 1-based: which trade in the batch is now ready
    total: int


@dataclass(frozen=True)
class BatchTradeCompleted:
    """Per-trade completion within a batch: 'Trade N completed!'. Bot is
    preparing the next mon — Switch must NOT offer until BatchTradeReady."""
    index: int      # 1-based: which trade just finished
    total: int


@dataclass(frozen=True)
class BatchAllComplete:
    """Final terminal event: 'All batch trades completed!' Closes the batch."""


@dataclass(frozen=True)
class TradeAttachment:
    """The 'Here's what you traded me!' message that bundles the .pk9 attachment.
    Informational — no driver action needed."""


@dataclass(frozen=True)
class TradeCanceled:
    reason: str  # e.g. "NoTrainerFound", "TrainerTooSlow"


@dataclass(frozen=True)
class Unknown:
    """Message didn't match any known template. Driver should log + halt."""
    raw: str


Event = Union[
    CodeIssued, Queued, UpNext, LoadingTrade, Searching, PartnerFound,
    NoPartner, TooSlow, TradeFinished,
    BatchTradeReady, BatchTradeCompleted, BatchAllComplete,
    TradeAttachment, TradeCanceled, Unknown,
]


# Order matters: more specific patterns first. LoadingTrade must beat
# CodeIssued because both contain a code; LoadingTrade has the literal
# "Loading the Trade Menu" prefix.
_RE_LOADING = re.compile(
    r"Loading the Trade Menu\.\.\.\s*\n\s*"
    r"Pokemon:\s*(?P<species>.+?)\s*\n\s*"
    r"Trade Code:\s*(?P<code>\d{4}\s+\d{4})",
    re.IGNORECASE,
)
_RE_CODE_ISSUED = re.compile(
    r"Here's your trade code!\s*\n\s*(?P<code>\d{4}\s+\d{4})",
    re.IGNORECASE,
)
_RE_QUEUED = re.compile(
    r"Trade Request Queued.*?Queue Position:\s*(?P<pos>\d+).*?"
    r"Estimated wait time:\s*(?P<eta>.+?)(?:\s*[•·­]|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
_RE_UP_NEXT = re.compile(r"You're Up Next!", re.IGNORECASE)
_RE_SEARCHING = re.compile(
    r"Now Searching for you,\s*\n\s*"
    r"Waiting For:\s*(?P<handle>\S+)\s*\n\s*"
    r"My IGN:\s*(?P<ign>\S+)",
    re.IGNORECASE,
)
_RE_PARTNER_FOUND = re.compile(
    r"Found Link Trade partner:\s*(?P<name>.+?)\.\s*"
    r"TID:\s*(?P<tid>\d+)\s*"
    r"SID:\s*(?P<sid>\d+)",
    re.IGNORECASE,
)
_RE_NO_PARTNER = re.compile(r"No trading partner found", re.IGNORECASE)
_RE_TOO_SLOW = re.compile(
    r"Canceling the trade(?::|\.)\s*TrainerTooSlow", re.IGNORECASE,
)
_RE_TRADE_FINISHED = re.compile(r"Trade finished\.?\s*Enjoy!?", re.IGNORECASE)
_RE_TRADE_ATTACHMENT = re.compile(r"Here's what you traded me!", re.IGNORECASE)
_RE_TRADE_CANCELED = re.compile(
    r"Trade Canceled.*?Reason:\s*(?P<reason>\w+)", re.IGNORECASE | re.DOTALL,
)
# Batch lifecycle. Match "All batch trades completed" BEFORE BatchTradeCompleted
# (the singular pattern would otherwise hit on the All... line via "trades completed").
_RE_BATCH_ALL_COMPLETE = re.compile(
    r"All batch trades completed", re.IGNORECASE,
)
_RE_BATCH_TRADE_READY = re.compile(
    r"Trade\s+(?P<idx>\d+)/(?P<total>\d+):\s*Ready!",
    re.IGNORECASE,
)
_RE_BATCH_TRADE_COMPLETED = re.compile(
    r"Trade\s+(?P<idx>\d+)\s+completed!.*?Preparing your next Pok.*?\((?P<next>\d+)/(?P<total>\d+)\)",
    re.IGNORECASE | re.DOTALL,
)


def _strip_code(code: str) -> str:
    return re.sub(r"\s+", "", code)


def parse_message(body: str) -> Event:
    """Classify a single DM body. Returns Unknown if no template matches."""
    text = body.strip()

    # Batch events: check before LoadingTrade/TradeFinished because their
    # bodies can co-occur in a single message; specific batch markers win.
    if _RE_BATCH_ALL_COMPLETE.search(text):
        return BatchAllComplete()
    if m := _RE_BATCH_TRADE_READY.search(text):
        return BatchTradeReady(index=int(m["idx"]), total=int(m["total"]))
    if m := _RE_BATCH_TRADE_COMPLETED.search(text):
        return BatchTradeCompleted(index=int(m["idx"]), total=int(m["total"]))

    if m := _RE_LOADING.search(text):
        return LoadingTrade(species=m["species"].strip(), code=_strip_code(m["code"]))
    if m := _RE_CODE_ISSUED.search(text):
        return CodeIssued(code=_strip_code(m["code"]))
    if m := _RE_QUEUED.search(text):
        return Queued(position=int(m["pos"]), eta_text=m["eta"].strip())
    if _RE_UP_NEXT.search(text):
        return UpNext()
    if m := _RE_SEARCHING.search(text):
        return Searching(waiting_for=m["handle"], bot_ign=m["ign"])
    if m := _RE_PARTNER_FOUND.search(text):
        return PartnerFound(
            partner_name=m["name"].strip(),
            tid=int(m["tid"]), sid=int(m["sid"]),
        )
    if _RE_NO_PARTNER.search(text):
        return NoPartner()
    if _RE_TOO_SLOW.search(text):
        return TooSlow()
    if m := _RE_TRADE_CANCELED.search(text):
        return TradeCanceled(reason=m["reason"])
    if _RE_TRADE_FINISHED.search(text):
        return TradeFinished()
    if _RE_TRADE_ATTACHMENT.search(text):
        return TradeAttachment()

    return Unknown(raw=body)


def is_go_signal(event: Event) -> Optional[str]:
    """Convenience: return the code if this event means 'drive the Switch now'."""
    if isinstance(event, LoadingTrade):
        return event.code
    return None


def is_terminal(event: Event) -> bool:
    """Trade is fully resolved — driver may release the trade slot."""
    return isinstance(event, (TradeFinished, TradeCanceled))
