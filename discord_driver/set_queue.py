"""SQLite-backed queue of Showdown sets to trade.

A "set" is the Showdown-format text body of a single trade request (the part
after `$trade `). The queue tracks one row per set as it moves through the
trade lifecycle:

    pending   -> not yet posted in Discord
    submitted -> posted, awaiting code from bot
    queued    -> bot replied with "Trade Request Queued" + code
    loading   -> bot replied with "Loading the Trade Menu" (GO signal sent to Switch)
    traded    -> bot replied with "Trade finished. Enjoy!"
    failed    -> bot canceled (with reason)

Lookups by code (set during 'queued') are how the Discord driver matches
later lifecycle events back to the originating set.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


VALID_STATUSES = {"pending", "submitted", "queued", "loading", "traded", "failed"}


@dataclass
class TradeSet:
    set_id: str
    species: str  # parsed from first line of set body, used for human-readable logging
    body: str
    status: str
    code: Optional[str]      # 8 contiguous digits once 'queued'
    failure_reason: Optional[str]
    created_at: float
    updated_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_sets (
    set_id          TEXT PRIMARY KEY,
    species         TEXT NOT NULL,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL,
    code            TEXT,
    failure_reason  TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status ON trade_sets(status);
CREATE INDEX IF NOT EXISTS idx_code   ON trade_sets(code);
"""


def _species_from_body(body: str) -> str:
    """First line of a Showdown set: 'Species @ Item' or 'Nickname (Species) (M) @ Item'."""
    first = body.strip().splitlines()[0] if body.strip() else "Unknown"
    head = first.split("@", 1)[0].strip()
    # Nickname (Species) (Gender)? form — first parenthetical is the species,
    # unless it's a bare gender marker (which means there's no nickname).
    if "(" in head:
        open_idx = head.index("(")
        close_idx = head.index(")", open_idx)
        inside = head[open_idx + 1 : close_idx].strip()
        if inside not in ("M", "F"):
            return inside
    # Drop trailing gender marker if present.
    return head.rsplit(" ", 1)[0] if head.endswith((" (M)", " (F)")) else head


class SetQueue:
    """Thin wrapper over SQLite. One connection per instance."""

    def __init__(self, db_path: Path | str = "trade_sets.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # --- ingest ---

    def add_set(self, body: str, set_id: Optional[str] = None) -> TradeSet:
        sid = set_id or uuid.uuid4().hex[:12]
        now = time.time()
        species = _species_from_body(body)
        with self._tx() as c:
            c.execute(
                "INSERT INTO trade_sets "
                "(set_id, species, body, status, code, failure_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', NULL, NULL, ?, ?)",
                (sid, species, body, now, now),
            )
        return self.get(sid)  # type: ignore[return-value]

    def add_many(self, bodies: list[str]) -> list[TradeSet]:
        return [self.add_set(b) for b in bodies]

    # --- queries ---

    def get(self, set_id: str) -> Optional[TradeSet]:
        row = self._conn.execute(
            "SELECT * FROM trade_sets WHERE set_id = ?", (set_id,)
        ).fetchone()
        return _row_to_set(row) if row else None

    def get_by_code(self, code: str) -> Optional[TradeSet]:
        """Find an in-flight set by its assigned trade code. Used by the
        Discord driver to match Loading/Searching/Canceled events back to a set."""
        row = self._conn.execute(
            "SELECT * FROM trade_sets WHERE code = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (code,),
        ).fetchone()
        return _row_to_set(row) if row else None

    def next_pending(self) -> Optional[TradeSet]:
        """Oldest set still waiting to be posted in Discord."""
        row = self._conn.execute(
            "SELECT * FROM trade_sets WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return _row_to_set(row) if row else None

    def in_flight(self) -> list[TradeSet]:
        """All sets between submitted and traded — for sanity checks / restart recovery."""
        rows = self._conn.execute(
            "SELECT * FROM trade_sets WHERE status IN ('submitted','queued','loading') "
            "ORDER BY updated_at ASC"
        ).fetchall()
        return [_row_to_set(r) for r in rows]

    def counts_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM trade_sets GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # --- transitions ---

    def mark_submitted(self, set_id: str) -> None:
        self._transition(set_id, "submitted")

    def mark_queued(self, set_id: str, code: str) -> None:
        if not (code.isdigit() and len(code) == 8):
            raise ValueError(f"trade code must be 8 digits, got {code!r}")
        with self._tx() as c:
            c.execute(
                "UPDATE trade_sets SET status='queued', code=?, updated_at=? "
                "WHERE set_id=?",
                (code, time.time(), set_id),
            )

    def mark_loading(self, set_id: str) -> None:
        self._transition(set_id, "loading")

    def mark_traded(self, set_id: str) -> None:
        self._transition(set_id, "traded")

    def mark_failed(self, set_id: str, reason: str) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE trade_sets SET status='failed', failure_reason=?, updated_at=? "
                "WHERE set_id=?",
                (reason, time.time(), set_id),
            )

    def _transition(self, set_id: str, new_status: str) -> None:
        if new_status not in VALID_STATUSES:
            raise ValueError(new_status)
        with self._tx() as c:
            n = c.execute(
                "UPDATE trade_sets SET status=?, updated_at=? WHERE set_id=?",
                (new_status, time.time(), set_id),
            ).rowcount
        if n == 0:
            raise KeyError(f"no set with id {set_id!r}")


def _row_to_set(row: sqlite3.Row) -> TradeSet:
    return TradeSet(
        set_id=row["set_id"],
        species=row["species"],
        body=row["body"],
        status=row["status"],
        code=row["code"],
        failure_reason=row["failure_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def load_sets_from_file(path: Path | str) -> list[str]:
    """Parse a flat file of Showdown sets separated by blank lines."""
    text = Path(path).read_text(encoding="utf-8")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return blocks
