#!/usr/bin/env python3
"""
Spectate live Pokemon Showdown battles and save complete logs.

Connects as a guest, polls for active battles in Champions formats,
joins as spectator, and saves the full log when the battle ends.

Usage:
    python3 scripts/spectate_ps_battles.py                    # run until Ctrl+C
    python3 scripts/spectate_ps_battles.py --min-elo 1200     # only 1200+ rated
    python3 scripts/spectate_ps_battles.py --duration 3600    # run for 1 hour
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import string
import time
from pathlib import Path

import websockets

WS_URL = "wss://sim3.psim.us/showdown/websocket"

FORMATS = [
    "gen9championsvgc2026regma",
    "gen9championsbssregma",
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
INDEX_FILE = OUTPUT_DIR / "index.json"

# How often to poll for new battles (seconds)
POLL_INTERVAL = 15

# Max battles to spectate simultaneously (avoid overwhelming the connection)
MAX_CONCURRENT = 20


class BattleLog:
    """Accumulates log lines for a single battle."""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.lines: list[str] = []
        self.players: dict[str, str] = {}  # "p1" -> name
        self.ratings: dict[str, int] = {}  # "p1" -> rating
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

        elif cmd == "raw" and "rating:" in line.lower():
            # Parse rating changes: |raw|Player's rating: 1393 &rarr; <strong>1415</strong>
            pass

    @property
    def log_text(self) -> str:
        return "\n".join(self.lines)

    @property
    def rating(self) -> int:
        """Return the higher rating of the two players."""
        if self.ratings:
            return max(self.ratings.values())
        return 0


class ShowdownSpectator:
    """Connects to Pokemon Showdown and spectates live battles."""

    def __init__(self, min_elo: int = 0, formats: list[str] | None = None):
        self.min_elo = min_elo
        self.formats = formats or FORMATS
        self.ws = None
        self.logged_in = False
        self.battles: dict[str, BattleLog] = {}  # room_id -> BattleLog
        self.known_rooms: set[str] = set()  # rooms we've already joined or seen
        self.index: dict = {}
        self.stats = {"joined": 0, "saved": 0, "failed": 0}

        # Load existing index
        if INDEX_FILE.exists():
            self.index = json.loads(INDEX_FILE.read_text())

    async def run(self, duration: float | None = None):
        """Main loop: connect, login, poll, spectate."""
        start = time.time()

        async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=60) as ws:
            self.ws = ws
            print(f"Connected to {WS_URL}", flush=True)

            # Start message handler and poller concurrently
            handler = asyncio.create_task(self._message_handler())
            poller = asyncio.create_task(self._poll_loop())

            try:
                if duration:
                    await asyncio.wait_for(
                        asyncio.gather(handler, poller),
                        timeout=duration,
                    )
                else:
                    await asyncio.gather(handler, poller)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            finally:
                handler.cancel()
                poller.cancel()

        elapsed = time.time() - start
        print(f"\nSession ended after {elapsed/60:.1f} minutes", flush=True)
        print(f"  Battles joined: {self.stats['joined']}", flush=True)
        print(f"  Battles saved: {self.stats['saved']}", flush=True)

    async def _message_handler(self):
        """Process incoming WebSocket messages."""
        async for raw in self.ws:
            # Showdown sends room messages as: >roomid\nline1\nline2\n...
            # Global messages have no > prefix
            if raw.startswith(">"):
                lines = raw.split("\n")
                room_id = lines[0][1:]  # strip ">"
                for line in lines[1:]:
                    if line:
                        await self._handle_room_message(room_id, line)
            else:
                for line in raw.split("\n"):
                    if not line:
                        continue
                    if "|challstr|" in line:
                        await self._login()
                    elif "|updateuser|" in line and not self.logged_in:
                        self.logged_in = True
                        print("Logged in as guest", flush=True)
                    elif "|queryresponse|roomlist|" in line:
                        await self._handle_roomlist(line)

    async def _handle_room_message(self, room_id: str, line: str):
        """Handle a message from a battle room."""
        if room_id not in self.battles:
            self.battles[room_id] = BattleLog(room_id)

        battle = self.battles[room_id]
        battle.add_line(line)

        if battle.finished:
            await self._save_battle(battle)
            # Leave the room
            await self.ws.send(f"|/leave {room_id}")
            del self.battles[room_id]

    async def _login(self):
        """Login as a guest with a random name."""
        name = "Spec" + "".join(random.choices(string.digits, k=6))
        await self.ws.send(f"|/trn {name},0,")

    async def _poll_loop(self):
        """Periodically query for active battles and join new ones."""
        # Wait for login
        while not self.logged_in:
            await asyncio.sleep(0.5)

        while True:
            for fmt in self.formats:
                cmd = f"|/crq roomlist {fmt}"
                if self.min_elo:
                    cmd = f"|/crq roomlist {fmt},{self.min_elo}"
                await self.ws.send(cmd)
                await asyncio.sleep(1)

            await asyncio.sleep(POLL_INTERVAL)

    async def _handle_roomlist(self, msg: str):
        """Parse roomlist response and join new battles."""
        try:
            json_str = msg.split("|queryresponse|roomlist|", 1)[1]
            data = json.loads(json_str)
        except (IndexError, json.JSONDecodeError):
            return

        rooms = data.get("rooms", {})
        for room_id, info in rooms.items():
            # Don't exceed concurrent limit
            if len(self.battles) >= MAX_CONCURRENT:
                break

            if room_id in self.known_rooms:
                continue
            if room_id in self.battles:
                continue

            self.known_rooms.add(room_id)

            # Check min elo
            min_elo = info.get("minElo", 0)
            if isinstance(min_elo, str):
                continue  # "tour" or other non-numeric
            if self.min_elo and min_elo < self.min_elo:
                continue

            # Join as spectator
            await self.ws.send(f"|/join {room_id}")
            self.stats["joined"] += 1

            p1 = info.get("p1", "?")
            p2 = info.get("p2", "?")
            elo = info.get("minElo", "?")
            print(f"  Joined {room_id} ({p1} vs {p2}, elo≥{elo}) "
                  f"[{len(self.battles)} active]", flush=True)

            await asyncio.sleep(0.6)  # rate limit joins

    async def _save_battle(self, battle: BattleLog):
        """Save a completed battle log to disk."""
        # Determine format directory from room_id
        fmt_dir = None
        for fmt in self.formats:
            if fmt in battle.room_id:
                fmt_dir = OUTPUT_DIR / fmt
                break

        if fmt_dir is None:
            fmt_dir = OUTPUT_DIR / "unknown"

        fmt_dir.mkdir(parents=True, exist_ok=True)

        # Use room_id as filename (strip "battle-" prefix)
        replay_id = battle.room_id.replace("battle-", "")
        out_file = fmt_dir / f"{replay_id}.json"

        if out_file.exists():
            return

        # Build replay-compatible JSON
        replay_data = {
            "id": replay_id,
            "format": battle.format_id,
            "players": [battle.players.get("p1", ""), battle.players.get("p2", "")],
            "log": battle.log_text,
            "uploadtime": int(time.time()),
            "rating": battle.rating,
            "source": "spectated",
        }

        out_file.write_text(json.dumps(replay_data, indent=2))

        # Update index
        self.index[replay_id] = {
            "format": battle.format_id,
            "format_id": battle.room_id.split("-")[1] if "-" in battle.room_id else "",
            "players": replay_data["players"],
            "rating": battle.rating,
            "uploadtime": replay_data["uploadtime"],
        }
        INDEX_FILE.write_text(json.dumps(self.index, indent=2))

        self.stats["saved"] += 1
        print(f"  Saved {replay_id} (winner: {battle.winner}, rating: {battle.rating})", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Spectate live Pokemon Showdown battles")
    parser.add_argument("--min-elo", type=int, default=0,
                        help="Only spectate battles with min Elo >= this value")
    parser.add_argument("--duration", type=float, default=None,
                        help="Run for this many seconds, then stop")
    parser.add_argument("--formats", nargs="+", default=None,
                        help="Format IDs to spectate (default: Champions VGC + BSS)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    spectator = ShowdownSpectator(
        min_elo=args.min_elo,
        formats=args.formats,
    )

    print(f"Spectating: {', '.join(spectator.formats)}", flush=True)
    if args.min_elo:
        print(f"Min Elo: {args.min_elo}", flush=True)
    if args.duration:
        print(f"Duration: {args.duration}s", flush=True)
    print(flush=True)

    asyncio.run(spectator.run(duration=args.duration))


if __name__ == "__main__":
    main()
