"""Fake Switch client — connects to a SwitchBridge and acks every TRADE_READY.

Use this to dry-run the full loop with zero hardware:

    Terminal 1:  python3 -m discord_driver --mock-discord --sets sets.txt \\
                     --min-seconds-between-posts 0
    Terminal 2:  python3 -m discord_driver.noop_switch --port 9988

The noop "Switch" sends READY on connect, then for every TRADE_READY it
receives waits `--trade-duration` seconds (simulating the trade) and replies
TRADE_COMPLETE. With --fail-rate it can also fake partner-no-show failures.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import socket
import sys
import time

logger = logging.getLogger("noop_switch")


def run(host: str, port: int, trade_duration: float, fail_rate: float) -> int:
    sock = socket.create_connection((host, port))
    logger.info("Connected to bridge at %s:%d", host, port)
    sock.sendall(b'{"type":"READY"}\n')

    buf = b""
    sock.settimeout(1.0)
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            logger.info("Interrupted, closing.")
            sock.close()
            return 0
        if not chunk:
            logger.info("Bridge closed connection.")
            return 0
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                logger.warning("Bad JSON from bridge: %r", line)
                continue

            if msg.get("type") == "TRADE_READY":
                set_id = msg.get("set_id", "")
                code = msg.get("code", "")
                logger.info("TRADE_READY set=%s code=%s — simulating %.1fs trade",
                            set_id, code, trade_duration)
                time.sleep(trade_duration)
                if random.random() < fail_rate:
                    reply = {"type": "TRADE_FAILED", "set_id": set_id,
                             "reason": "noop_simulated_failure"}
                else:
                    reply = {"type": "TRADE_COMPLETE", "set_id": set_id}
                sock.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                logger.info("Replied: %s", reply["type"])

            elif msg.get("type") == "PING":
                sock.sendall(b'{"type":"PONG"}\n')


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9988)
    p.add_argument("--trade-duration", type=float, default=3.0,
                   help="Seconds to sleep before replying TRADE_COMPLETE")
    p.add_argument("--fail-rate", type=float, default=0.0,
                   help="Probability [0,1] to reply TRADE_FAILED instead")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return run(args.host, args.port, args.trade_duration, args.fail_rate)


if __name__ == "__main__":
    sys.exit(main())
