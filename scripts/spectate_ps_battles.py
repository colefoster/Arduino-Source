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
import signal
import string
import sys
import time
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

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "replays"
# Index lives at the format-root (one per format), not inside an hour bucket.
INDEX_FILE = OUTPUT_DIR / "index.json"

# How often to poll for new battles (seconds)
POLL_INTERVAL = 15

# Max battles to spectate simultaneously (Showdown kicks at ~50 rooms)
MAX_CONCURRENT = 45


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
        self.joined_rooms: set[str] = set()  # rooms currently joined (for concurrency limit)
        self.known_rooms: set[str] = set()  # rooms we've already seen (don't re-join)
        self.index: dict = {}
        self.stats = {"joined": 0, "saved": 0, "failed": 0}
        self._draining = False  # True = stop joining, wait for in-progress battles to finish

        # Load existing index
        if INDEX_FILE.exists():
            self.index = json.loads(INDEX_FILE.read_text())

    async def run(self, duration: float | None = None):
        """Main loop with auto-reconnect."""
        start = time.time()
        remaining = duration

        # Install signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._start_drain)

        while True:
            if self._draining and not self.joined_rooms:
                break

            try:
                await self._session(remaining)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"\n  Session error: {type(e).__name__}: {e}", flush=True)

            if self._draining:
                break

            # Check if we should stop
            if duration:
                elapsed = time.time() - start
                remaining = duration - elapsed
                if remaining <= 0:
                    break

            print(f"  Reconnecting in 15s...", flush=True)
            await asyncio.sleep(15)
            self.logged_in = False
            self.battles.clear()
            self.joined_rooms.clear()
            self.known_rooms.clear()

        elapsed = time.time() - start
        print(f"\nSession ended after {elapsed/60:.1f} minutes", flush=True)
        print(f"  Battles joined: {self.stats['joined']}", flush=True)
        print(f"  Battles saved: {self.stats['saved']}", flush=True)

    def _start_drain(self):
        """Signal handler — stop joining new battles, drain in-progress ones."""
        if self._draining:
            # Second signal = hard exit
            print(f"\n  Forced exit — {len(self.joined_rooms)} battles lost", flush=True)
            sys.exit(1)
        self._draining = True
        print(f"\n  Draining {len(self.joined_rooms)} in-progress battles...", flush=True)

    async def _session(self, timeout: float | None = None):
        """Single websocket session."""
        async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=60) as ws:
            self.ws = ws
            print(f"Connected to {WS_URL}", flush=True)

            handler = asyncio.create_task(self._message_handler())
            poller = asyncio.create_task(self._poll_loop())
            drainer = asyncio.create_task(self._drain_watcher())

            try:
                if timeout:
                    await asyncio.wait_for(
                        asyncio.gather(handler, poller, drainer),
                        timeout=timeout,
                    )
                else:
                    await asyncio.gather(handler, poller, drainer)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            finally:
                handler.cancel()
                poller.cancel()
                drainer.cancel()

    async def _drain_watcher(self):
        """Wait for drain to complete, then stop the session."""
        while True:
            await asyncio.sleep(2)
            if self._draining:
                if not self.joined_rooms:
                    print("  Drain complete — all battles saved", flush=True)
                    raise asyncio.CancelledError
                # Hard timeout: 90s after drain starts, give up
                if not hasattr(self, "_drain_start"):
                    self._drain_start = time.time()
                elif time.time() - self._drain_start > 90:
                    print(f"  Drain timeout — {len(self.joined_rooms)} battles lost", flush=True)
                    raise asyncio.CancelledError

    async def _message_handler(self):
        """Process incoming WebSocket messages."""
        async for raw in self.ws:
            try:
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
            except websockets.exceptions.ConnectionClosed:
                raise  # let the reconnect logic handle this
            except Exception as e:
                print(f"  [warn] Message handler error: {e}", flush=True)

    async def _handle_room_message(self, room_id: str, line: str):
        """Handle a message from a battle room."""
        if room_id not in self.battles:
            self.battles[room_id] = BattleLog(room_id)

        battle = self.battles[room_id]
        battle.add_line(line)

        if battle.finished:
            await self._save_battle(battle)
            # Leave the room to free up a slot
            await self.ws.send(f"|/leave {room_id}")
            del self.battles[room_id]
            self.joined_rooms.discard(room_id)

    async def _login(self):
        """Login as a guest with a random name."""
        name = "Spec" + "".join(random.choices(string.digits, k=6))
        await self.ws.send(f"|/trn {name},0,")

    async def _poll_loop(self):
        """Periodically query for active battles and join new ones.

        Queries at multiple ELO thresholds to work around the PS 100-room cap.
        """
        # Wait for login
        while not self.logged_in:
            await asyncio.sleep(0.5)

        if self._draining:
            return

        # ELO slices — each query returns up to 100 rooms at or above the threshold.
        # Higher slices surface battles hidden by the cap in the base query.
        elo_slices = [0, 1200, 1400]

        while True:
            try:
                for fmt in self.formats:
                    for elo in elo_slices:
                        threshold = max(elo, self.min_elo)
                        cmd = f"|/crq roomlist {fmt},{threshold}" if threshold else f"|/crq roomlist {fmt}"
                        await self.ws.send(cmd)
                        await asyncio.sleep(0.5)
            except websockets.exceptions.ConnectionClosed:
                raise
            except Exception as e:
                print(f"  [warn] Poll error: {e}", flush=True)

            if self._draining:
                return
            await asyncio.sleep(POLL_INTERVAL)

    async def _handle_roomlist(self, msg: str):
        """Parse roomlist response and join new battles."""
        if self._draining:
            return
        try:
            json_str = msg.split("|queryresponse|roomlist|", 1)[1]
            data = json.loads(json_str)
        except (IndexError, json.JSONDecodeError):
            return

        rooms = data.get("rooms", {})
        # Sort by rating descending — prioritize high-rated battles.
        # Bucket into ~50-point tiers and shuffle within each tier so
        # multiple instances naturally spread across different rooms.
        room_items = list(rooms.items())
        random.shuffle(room_items)
        room_items.sort(
            key=lambda x: (x[1].get("minElo", 0) if isinstance(x[1].get("minElo", 0), int) else 0) // 50,
            reverse=True,
        )
        for room_id, info in room_items:
            # Don't exceed concurrent limit
            if len(self.joined_rooms) >= MAX_CONCURRENT:
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
            self.joined_rooms.add(room_id)
            self.stats["joined"] += 1

            p1 = info.get("p1", "?")
            p2 = info.get("p2", "?")
            elo = info.get("minElo", "?")
            print(f"  Joined {room_id} ({p1} vs {p2}, elo>={elo}) "
                  f"[{len(self.joined_rooms)} rooms]", flush=True)

            await asyncio.sleep(0.5)  # rate limit joins — too fast gets kicked

    async def _save_battle(self, battle: BattleLog):
        """Save a completed battle log to disk in hour-bucketed layout.

        Layout: data/replays/<format>/YYYY-MM-DD/HH/<replay_id>.json
        Bucket key is the spectate-time (now), which is within seconds of the
        replay's actual end. UTC.
        """
        # Determine format from room_id
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

        # Use room_id as filename (strip "battle-" prefix)
        replay_id = battle.room_id.replace("battle-", "")
        out_file = bucket_dir / f"{replay_id}.json"

        if out_file.exists():
            return

        # Build replay-compatible JSON
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

    try:
        asyncio.run(spectator.run(duration=args.duration))
    except KeyboardInterrupt:
        pass  # signal handler manages graceful shutdown
    except Exception as e:
        print(f"\nError: {e}", flush=True)


if __name__ == "__main__":
    main()
