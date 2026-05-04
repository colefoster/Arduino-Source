"""CLI entry point.

    python -m discord_driver \
        --sets sets.txt \
        --bot-username KlawfAPP \
        --channel-server "Klawf Cove" \
        --channel-name scvi-bot \
        --bridge-port 9988

First-run: omit --headless and log into Discord manually in the launched browser.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from discord_driver.driver import Driver, DriverConfig
from discord_driver.playwright_session import DiscordSession
from discord_driver.set_queue import SetQueue, load_sets_from_file
from discord_driver.switch_bridge import SwitchBridge


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sets", type=Path, help="Path to a file of blank-line-separated Showdown sets to enqueue")
    p.add_argument("--db", type=Path, default=Path("trade_sets.db"))
    p.add_argument("--profile-dir", type=Path, default=DiscordSession.DEFAULT_PROFILE_DIR)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--bot-username", default="KlawfAPP")
    p.add_argument("--channel-server", default="Klawf Cove")
    p.add_argument("--channel-name", help="e.g. scvi-bot. Required unless --mock-discord or --channel-url.")
    p.add_argument("--channel-url", default="",
                   help="Direct discord.com/channels/SERVER/CHANNEL URL. Bypasses sidebar nav.")
    p.add_argument("--dm-url", default="",
                   help="Direct discord.com/channels/@me/DM URL for the bot DM thread.")
    p.add_argument("--bridge-host", default="127.0.0.1")
    p.add_argument("--bridge-port", type=int, default=9988)
    p.add_argument("--max-in-flight", type=int, default=1)
    p.add_argument("--mock-discord", action="store_true",
                   help="Replace Playwright with an in-process mock that scripts "
                        "KlawfAPP responses. No real browser, no real Discord.")
    p.add_argument("--mock-scenario",
                   choices=["success", "no_partner", "too_slow", "illegal_set"],
                   default="success",
                   help="Lifecycle to script when --mock-discord is set.")
    p.add_argument("--max-posts-per-session", type=int, default=5)
    p.add_argument("--min-seconds-between-posts", type=float, default=30.0)
    p.add_argument("--trade-command-prefix", default="$trade",
                   help="Command prefix posted to the channel. Use '-trade' for dash-prefix bots, "
                        "or '-batch trade' when --batch-size > 1.")
    p.add_argument("--batch-size", type=int, default=1,
                   help="If >1, post N pending sets as a single -batch trade message "
                        "(joined by '---'). Requires --trade-command-prefix to match the "
                        "bot's batch command.")
    args = p.parse_args()
    if not args.mock_discord and not args.channel_name and not args.channel_url:
        p.error("--channel-name or --channel-url is required unless --mock-discord is set")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("discord_driver")

    queue = SetQueue(args.db)
    if args.sets:
        bodies = load_sets_from_file(args.sets)
        before = queue.counts_by_status()
        for b in bodies:
            queue.add_set(b)
        after = queue.counts_by_status()
        log.info("Ingested %d sets from %s. Queue: %s -> %s",
                 len(bodies), args.sets, before, after)

    bridge = SwitchBridge(host=args.bridge_host, port=args.bridge_port)
    bridge.start()
    log.info("Switch bridge listening on %s:%d", args.bridge_host, args.bridge_port)
    log.info("Waiting for SerialPrograms DiscordTradeBot to connect...")

    config = DriverConfig(
        bot_username=args.bot_username,
        max_in_flight=args.max_in_flight,
        max_posts_per_session=args.max_posts_per_session,
        min_seconds_between_posts=args.min_seconds_between_posts,
        trade_command_prefix=args.trade_command_prefix,
        batch_size=args.batch_size,
    )

    try:
        if args.mock_discord:
            from discord_driver.mock_session import MockSession
            log.info("MOCK MODE: scenario=%s. Discord will not be touched.",
                     args.mock_scenario)
            session = MockSession(scenario=args.mock_scenario)
            driver = Driver(session=session, queue=queue, bridge=bridge, config=config)
            try:
                driver.run_forever()
            except KeyboardInterrupt:
                log.info("Interrupted, shutting down.")
        else:
            with DiscordSession(profile_dir=args.profile_dir, headless=args.headless) as session:
                if args.channel_url:
                    session.goto_url(args.channel_url)
                    log.info("Open channel via URL.")
                else:
                    session.goto_channel(args.channel_server, args.channel_name)
                    log.info("Open channel #%s.", args.channel_name)

                if args.dm_url:
                    session.goto_url(args.dm_url)
                    log.info("Open DM via URL. Driver entering main loop.")
                else:
                    session.goto_dm_with(args.bot_username)
                    log.info("Open DM with %s. Driver entering main loop.", args.bot_username)

                driver = Driver(session=session, queue=queue, bridge=bridge, config=config)
                try:
                    driver.run_forever()
                except KeyboardInterrupt:
                    log.info("Interrupted, shutting down.")
    finally:
        bridge.stop()
        queue.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
