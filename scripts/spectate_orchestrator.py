#!/usr/bin/env python3
"""
Single-process orchestrator for spectating Pokemon Showdown battles.

Manages N WebSocket connections from one process with centralized room
assignment — each battle is joined by exactly one connection, with failover
if a connection dies.

Usage:
    python3 scripts/spectate_orchestrator.py                     # 8 connections
    python3 scripts/spectate_orchestrator.py --connections 4      # fewer connections
    python3 scripts/spectate_orchestrator.py --min-elo 1200       # only 1200+
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import json
import os
import random
import signal
import string
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import websockets

WS_URL = "wss://sim3.psim.us/showdown/websocket"

FORMATS = [
    "gen9championsvgc2026regma",
    "gen9championsbssregma",
]

# Hour-bucketed replay layout (Phase 1 of pipeline redesign).
# data/replays/<format>/YYYY-MM-DD/HH/<replay_id>.json
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "replays"
INDEX_FILE = OUTPUT_DIR / "index.json"
STATUS_FILE = OUTPUT_DIR / ".orchestrator_status.json"

POLL_INTERVAL = 15
MAX_PER_CONN = 45
ELO_SLICES = [0, 1200, 1400]
DRAIN_TIMEOUT = 90
JOIN_DELAY = 0.5


# ---------------------------------------------------------------------------
# BattleLog — accumulates log lines for a single battle
# ---------------------------------------------------------------------------

class BattleLog:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.lines: list[str] = []
        self.players: dict[str, str] = {}
        self.ratings: dict[str, int] = {}
        self.format_id: str = ""
        self.finished: bool = False
        self.winner: str = ""

    def add_line(self, line: str):
        self.lines.append(line)
        parts = line.split("|")
        if len(parts) < 2:
            return
        cmd = parts[1]
        if cmd == "player" and len(parts) >= 4:
            player = parts[2]
            name = parts[3]
            if name:
                self.players[player] = name
            if len(parts) >= 6 and parts[5]:
                try:
                    self.ratings[player] = int(parts[5])
                except ValueError:
                    pass
        elif cmd == "tier" and len(parts) >= 3:
            self.format_id = parts[2].strip()
        elif cmd == "win" and len(parts) >= 3:
            self.winner = parts[2]
            self.finished = True

    @property
    def log_text(self) -> str:
        return "\n".join(self.lines)

    @property
    def rating(self) -> int:
        return max(self.ratings.values()) if self.ratings else 0


# ---------------------------------------------------------------------------
# RoomInfo — lightweight room metadata from roomlist queries
# ---------------------------------------------------------------------------

@dataclass
class RoomInfo:
    room_id: str
    rating: int
    p1: str
    p2: str
    format_id: str


# ---------------------------------------------------------------------------
# ManagedConnection — wraps one WebSocket connection
# ---------------------------------------------------------------------------

class ConnState(enum.Enum):
    CONNECTING = "connecting"
    READY = "ready"
    DRAINING = "draining"
    DEAD = "dead"


class ManagedConnection:
    def __init__(self, conn_id: int):
        self.id = conn_id
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.state = ConnState.DEAD
        self.logged_in = False
        self.joined_rooms: set[str] = set()
        self.room_join_times: dict[str, float] = {}  # room_id -> join timestamp
        self.battles: dict[str, BattleLog] = {}
        self._join_lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        if self.state != ConnState.READY:
            return 0
        return MAX_PER_CONN - len(self.joined_rooms)

    async def run(self, orchestrator: Orchestrator):
        """Run connection with auto-reconnect."""
        while not orchestrator.shutting_down:
            try:
                self.state = ConnState.CONNECTING
                self.logged_in = False
                async with websockets.connect(
                    WS_URL, ping_interval=30, ping_timeout=60,
                ) as ws:
                    self.ws = ws
                    await self._read_loop(orchestrator)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"  [conn {self.id}] Error: {type(e).__name__}: {e}", flush=True)

            # Connection died
            old_rooms = list(self.joined_rooms)
            self.state = ConnState.DEAD
            self.ws = None
            self.joined_rooms.clear()
            self.room_join_times.clear()
            self.battles.clear()
            self.logged_in = False

            if old_rooms:
                orchestrator.on_connection_died(self, old_rooms)

            if orchestrator.shutting_down:
                break

            delay = 5 + random.uniform(0, 5)
            print(f"  [conn {self.id}] Reconnecting in {delay:.0f}s...", flush=True)
            await asyncio.sleep(delay)

    async def _read_loop(self, orchestrator: Orchestrator):
        """Process messages from WebSocket."""
        async for raw in self.ws:
            try:
                if raw.startswith(">"):
                    lines = raw.split("\n")
                    room_id = lines[0][1:]
                    for line in lines[1:]:
                        if line:
                            self._handle_room_message(room_id, line, orchestrator)
                else:
                    for line in raw.split("\n"):
                        if not line:
                            continue
                        if "|challstr|" in line:
                            await self._login()
                        elif "|updateuser|" in line and not self.logged_in:
                            self.logged_in = True
                            self.state = ConnState.READY
                            print(f"  [conn {self.id}] Ready", flush=True)
                        elif "|queryresponse|roomlist|" in line:
                            orchestrator.on_roomlist(line)
            except websockets.exceptions.ConnectionClosed:
                raise
            except Exception as e:
                print(f"  [conn {self.id}] Message error: {e}", flush=True)

    def _handle_room_message(self, room_id: str, line: str, orchestrator: Orchestrator):
        """Process a message from a battle room."""
        if room_id not in self.battles:
            self.battles[room_id] = BattleLog(room_id)

        battle = self.battles[room_id]
        battle.add_line(line)

        if battle.finished:
            orchestrator.on_battle_finished(self, battle)
            del self.battles[room_id]
            self.joined_rooms.discard(room_id)
            self.room_join_times.pop(room_id, None)

    async def _login(self):
        name = "Spec" + "".join(random.choices(string.digits, k=6))
        await self.ws.send(f"|/trn {name},0,")

    async def join_room(self, room_id: str):
        """Join a room with per-connection rate limiting."""
        async with self._join_lock:
            if self.ws and self.state == ConnState.READY:
                await self.ws.send(f"|/join {room_id}")
                self.joined_rooms.add(room_id)
                self.room_join_times[room_id] = time.time()
                await asyncio.sleep(JOIN_DELAY)

    async def leave_room(self, room_id: str):
        if self.ws:
            try:
                await self.ws.send(f"|/leave {room_id}")
            except Exception:
                pass
        self.joined_rooms.discard(room_id)
        self.room_join_times.pop(room_id, None)


# ---------------------------------------------------------------------------
# Orchestrator — central coordinator
# ---------------------------------------------------------------------------

class Orchestrator:
    def __init__(
        self,
        n_connections: int = 8,
        min_elo: int = 0,
        formats: list[str] | None = None,
    ):
        self.n_connections = n_connections
        self.min_elo = min_elo
        self.formats = formats or FORMATS

        self.connections = [ManagedConnection(i) for i in range(n_connections)]
        self.known_rooms: set[str] = set()
        self.pending_rooms: list[RoomInfo] = []
        self.active_battles: dict[str, ManagedConnection] = {}

        self._index: dict = {}
        self._index_dirty = False
        self._draining = False
        self._drain_start: float = 0
        self._start_time = time.time()
        self._last_save_time = time.time()
        self.shutting_down = False
        self.stats = {"joined": 0, "saved": 0, "failed": 0, "failovers": 0, "watchdog_resets": 0}

        # Load existing index
        if INDEX_FILE.exists():
            try:
                self._index = json.loads(INDEX_FILE.read_text())
            except Exception:
                self._index = {}

    async def run(self, duration: float | None = None):
        """Main entry point."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._start_drain)

        print(f"Orchestrator starting: {self.n_connections} connections", flush=True)
        print(f"Formats: {', '.join(self.formats)}", flush=True)
        if self.min_elo:
            print(f"Min ELO: {self.min_elo}", flush=True)
        print(flush=True)

        tasks = []

        # Start all connections
        for conn in self.connections:
            tasks.append(asyncio.create_task(conn.run(self)))

        # Start orchestrator loops
        tasks.append(asyncio.create_task(self._discovery_loop()))
        tasks.append(asyncio.create_task(self._assignment_loop()))
        tasks.append(asyncio.create_task(self._index_flush_loop()))
        tasks.append(asyncio.create_task(self._status_writer_loop()))
        tasks.append(asyncio.create_task(self._drain_watcher()))
        tasks.append(asyncio.create_task(self._watchdog_loop()))

        try:
            if duration:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=duration)
            else:
                await asyncio.gather(*tasks)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        finally:
            for t in tasks:
                t.cancel()
            # Final index flush
            self._flush_index()
            # Final status write
            self._write_status()

        elapsed = time.time() - self._start_time
        print(f"\nOrchestrator stopped after {elapsed / 60:.1f} minutes", flush=True)
        print(f"  Joined: {self.stats['joined']}", flush=True)
        print(f"  Saved: {self.stats['saved']}", flush=True)
        print(f"  Failovers: {self.stats['failovers']}", flush=True)

    # -- Signal handling --

    def _start_drain(self):
        if self._draining:
            total_rooms = sum(len(c.joined_rooms) for c in self.connections)
            print(f"\n  Forced exit — {total_rooms} battles lost", flush=True)
            sys.exit(1)
        self._draining = True
        self._drain_start = time.time()
        total_rooms = sum(len(c.joined_rooms) for c in self.connections)
        print(f"\n  Draining {total_rooms} in-progress battles...", flush=True)

    # -- Room discovery --

    async def _discovery_loop(self):
        """Poll PS for active battles using ELO-sliced queries."""
        # Wait for at least one connection to be ready
        while not any(c.state == ConnState.READY for c in self.connections):
            if self._draining:
                return
            await asyncio.sleep(0.5)

        while not self._draining:
            try:
                conn = self._pick_ready_conn()
                if conn and conn.ws:
                    for fmt in self.formats:
                        for elo in ELO_SLICES:
                            threshold = max(elo, self.min_elo)
                            cmd = f"|/crq roomlist {fmt},{threshold}" if threshold else f"|/crq roomlist {fmt}"
                            await conn.ws.send(cmd)
                            await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  [discovery] Error: {e}", flush=True)

            await asyncio.sleep(POLL_INTERVAL)

    def _pick_ready_conn(self) -> ManagedConnection | None:
        ready = [c for c in self.connections if c.state == ConnState.READY and c.ws]
        return ready[0] if ready else None

    def on_roomlist(self, msg: str):
        """Called by connection when a roomlist response arrives."""
        try:
            json_str = msg.split("|queryresponse|roomlist|", 1)[1]
            data = json.loads(json_str)
        except (IndexError, json.JSONDecodeError):
            return

        rooms = data.get("rooms", {})
        for room_id, info in rooms.items():
            if room_id in self.known_rooms:
                continue

            min_elo = info.get("minElo", 0)
            if isinstance(min_elo, str):
                continue
            if self.min_elo and min_elo < self.min_elo:
                continue

            self.known_rooms.add(room_id)
            self.pending_rooms.append(RoomInfo(
                room_id=room_id,
                rating=min_elo if isinstance(min_elo, int) else 0,
                p1=info.get("p1", "?"),
                p2=info.get("p2", "?"),
                format_id=room_id.split("-")[1] if "-" in room_id else "",
            ))

    # -- Room assignment --

    async def _assignment_loop(self):
        """Assign pending rooms to connections with spare capacity."""
        while not self._draining:
            if self.pending_rooms:
                # Sort by rating descending
                self.pending_rooms.sort(key=lambda r: r.rating, reverse=True)

                # Round-robin assign across connections
                assigned_any = True
                while assigned_any and self.pending_rooms:
                    assigned_any = False
                    for conn in self.connections:
                        if not self.pending_rooms:
                            break
                        if conn.state != ConnState.READY or conn.capacity <= 0:
                            continue

                        room = self.pending_rooms.pop(0)

                        # Double-check not already assigned
                        if room.room_id in self.active_battles:
                            continue

                        self.active_battles[room.room_id] = conn
                        self.stats["joined"] += 1
                        asyncio.create_task(self._do_join(conn, room))
                        assigned_any = True

            await asyncio.sleep(1)

    async def _do_join(self, conn: ManagedConnection, room: RoomInfo):
        """Join a room and log it."""
        await conn.join_room(room.room_id)
        total_rooms = sum(len(c.joined_rooms) for c in self.connections)
        print(
            f"  [conn {conn.id}] Joined {room.room_id} "
            f"({room.p1} vs {room.p2}, elo>={room.rating}) "
            f"[{len(conn.joined_rooms)}/{MAX_PER_CONN} rooms, {total_rooms} total]",
            flush=True,
        )

    # -- Battle completion --

    def on_battle_finished(self, conn: ManagedConnection, battle: BattleLog):
        """Called when a battle ends. Save replay and clean up."""
        self._save_battle(battle)
        self.active_battles.pop(battle.room_id, None)

        # Leave the room
        if conn.ws:
            asyncio.create_task(conn.leave_room(battle.room_id))

    def _save_battle(self, battle: BattleLog):
        """Save a completed battle to disk in hour-bucketed layout.

        Layout: data/replays/<format>/YYYY-MM-DD/HH/<replay_id>.json (UTC).
        Bucket key is the spectate-time, within seconds of the replay's actual
        end. Out-of-order saves into stale buckets are fine — Layer 1's parse
        cron is idempotent.
        """
        fmt = None
        for f in self.formats:
            if f in battle.room_id:
                fmt = f
                break
        if fmt is None:
            fmt = "unknown"

        upload_ts = int(time.time())
        bucket_dt = datetime.fromtimestamp(upload_ts, tz=timezone.utc)
        bucket_dir = (
            OUTPUT_DIR / fmt
            / bucket_dt.strftime("%Y-%m-%d")
            / bucket_dt.strftime("%H")
        )
        bucket_dir.mkdir(parents=True, exist_ok=True)

        replay_id = battle.room_id.replace("battle-", "")
        out_file = bucket_dir / f"{replay_id}.json"

        if out_file.exists():
            return

        replay_data = {
            "id": replay_id,
            "format": battle.format_id,
            "players": [battle.players.get("p1", ""), battle.players.get("p2", "")],
            "log": battle.log_text,
            "uploadtime": upload_ts,
            "rating": battle.rating,
            "source": "spectated",
        }

        out_file.write_text(json.dumps(replay_data, indent=2))

        self._index[replay_id] = {
            "format": battle.format_id,
            "format_id": battle.room_id.split("-")[1] if "-" in battle.room_id else "",
            "players": replay_data["players"],
            "rating": battle.rating,
            "uploadtime": replay_data["uploadtime"],
        }
        self._index_dirty = True
        self.stats["saved"] += 1
        self._last_save_time = time.time()
        print(f"  Saved {replay_id} (winner: {battle.winner}, rating: {battle.rating})", flush=True)

    # -- Connection failure --

    def on_connection_died(self, conn: ManagedConnection, lost_rooms: list[str]):
        """Re-queue orphaned rooms for reassignment."""
        self.stats["failovers"] += 1
        for room_id in lost_rooms:
            self.active_battles.pop(room_id, None)
            # Re-queue — PS sends full log on re-join
            self.pending_rooms.append(RoomInfo(
                room_id=room_id, rating=0, p1="?", p2="?", format_id="",
            ))
        print(
            f"  [conn {conn.id}] Died — re-queued {len(lost_rooms)} rooms for failover",
            flush=True,
        )

    # -- Drain --

    async def _drain_watcher(self):
        while True:
            await asyncio.sleep(2)
            if not self._draining:
                continue

            total_rooms = sum(len(c.joined_rooms) for c in self.connections)
            if total_rooms == 0:
                print("  Drain complete — all battles saved", flush=True)
                self.shutting_down = True
                raise asyncio.CancelledError

            elapsed = time.time() - self._drain_start
            if elapsed > DRAIN_TIMEOUT:
                print(f"  Drain timeout — {total_rooms} battles lost", flush=True)
                self.shutting_down = True
                raise asyncio.CancelledError

    # -- Watchdog --

    WATCHDOG_INTERVAL = 120       # check every 2 minutes
    SAVE_TIMEOUT = 1800           # 30 min without saves → reset connections
    STALE_ROOM_TIMEOUT = 3600    # 60 min in a room → prune it (games never last this long)

    async def _watchdog_loop(self):
        """Detect stuck connections and stale rooms, force-reset when needed."""
        while not self._draining:
            await asyncio.sleep(self.WATCHDOG_INTERVAL)
            if self._draining:
                return

            now = time.time()
            since_last_save = now - self._last_save_time
            total_rooms = sum(len(c.joined_rooms) for c in self.connections)

            # Prune stale rooms (joined too long ago — battle is probably over
            # but we missed the end message)
            stale_pruned = 0
            for conn in self.connections:
                stale = [rid for rid, join_time in conn.room_join_times.items()
                         if now - join_time > self.STALE_ROOM_TIMEOUT]
                for rid in stale:
                    conn.joined_rooms.discard(rid)
                    conn.room_join_times.pop(rid, None)
                    conn.battles.pop(rid, None)
                    self.active_battles.pop(rid, None)
                    stale_pruned += 1

            if stale_pruned:
                print(f"  [watchdog] Pruned {stale_pruned} stale rooms (>{self.STALE_ROOM_TIMEOUT}s old)", flush=True)

            # If no saves for SAVE_TIMEOUT and we have rooms, force-reset all connections
            if since_last_save > self.SAVE_TIMEOUT and total_rooms > 0:
                self.stats["watchdog_resets"] += 1
                print(f"  [watchdog] No saves for {since_last_save:.0f}s with {total_rooms} rooms — force-resetting connections", flush=True)
                for conn in self.connections:
                    old_rooms = list(conn.joined_rooms)
                    conn.joined_rooms.clear()
                    conn.room_join_times.clear()
                    conn.battles.clear()
                    for rid in old_rooms:
                        self.active_battles.pop(rid, None)
                    # Close the websocket to trigger reconnect
                    if conn.ws:
                        try:
                            await conn.ws.close()
                        except Exception:
                            pass
                self._last_save_time = now  # reset timer to avoid immediate re-trigger
                print(f"  [watchdog] All connections reset — will reconnect automatically", flush=True)

    # -- Index flush --

    async def _index_flush_loop(self):
        """Batch-write index.json every 10 seconds."""
        while True:
            await asyncio.sleep(10)
            self._flush_index()

    def _flush_index(self):
        if self._index_dirty:
            try:
                INDEX_FILE.write_text(json.dumps(self._index, indent=2))
                self._index_dirty = False
            except Exception as e:
                print(f"  [index] Flush error: {e}", flush=True)

    # -- Status file --

    async def _status_writer_loop(self):
        """Write orchestrator status for dashboard consumption."""
        while True:
            self._write_status()
            await asyncio.sleep(5)

    def _write_status(self):
        ready = [c for c in self.connections if c.state == ConnState.READY]
        total_rooms = sum(len(c.joined_rooms) for c in self.connections)
        status = {
            "pid": os.getpid(),
            "connections": len(ready),
            "total_connections": self.n_connections,
            "rooms_in_use": total_rooms,
            "capacity": len(ready) * MAX_PER_CONN,
            "pending": len(self.pending_rooms),
            "known_rooms": len(self.known_rooms),
            "draining": self._draining,
            "stats": self.stats,
            "uptime_sec": round(time.time() - self._start_time),
            "per_connection": [
                {
                    "id": c.id,
                    "state": c.state.value,
                    "rooms": len(c.joined_rooms),
                }
                for c in self.connections
            ],
        }
        try:
            STATUS_FILE.write_text(json.dumps(status))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Spectator orchestrator")
    parser.add_argument("--connections", type=int, default=8,
                        help="Number of WebSocket connections (default: 8)")
    parser.add_argument("--min-elo", type=int, default=0,
                        help="Only spectate battles with min Elo >= this value")
    parser.add_argument("--duration", type=float, default=None,
                        help="Run for this many seconds, then stop")
    parser.add_argument("--formats", nargs="+", default=None,
                        help="Format IDs to spectate")
    args = parser.parse_args()

    orchestrator = Orchestrator(
        n_connections=args.connections,
        min_elo=args.min_elo,
        formats=args.formats,
    )

    try:
        asyncio.run(orchestrator.run(duration=args.duration))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
