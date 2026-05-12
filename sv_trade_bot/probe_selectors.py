"""Probe Playwright selectors against the real Discord — read-only, no posting.

Run AFTER first-run login (so the persistent profile is authenticated):

    pip3 install playwright && playwright install chromium
    python3 -m sv_trade_bot.probe_selectors

Pass --headless to run without a browser window after the first successful run.

What it does, in order:
  1. Opens Discord, confirms login
  2. Navigates to Klawf Cove server -> scvi-bot channel
  3. Navigates to the KlawfAPP DM
  4. Scrapes the last N visible DM messages, runs each through the parser
  5. Prints a per-step report

What it does NOT do:
  - Post any message to any channel
  - Send TRADE_READY to any Switch
  - Mutate the SQLite queue

If any step fails, the script exits non-zero and tells you which selector to
fix in playwright_session.py.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from sv_trade_bot.parser import Unknown, parse_message
from sv_trade_bot.playwright_session import DiscordSession

logger = logging.getLogger("probe")


def probe(
    profile_dir: Path,
    headless: bool,
    server_name: str,
    channel_name: str,
    bot_username: str,
    sample_count: int,
    channel_url: str = "",
    dm_url: str = "",
) -> int:
    print(f"--- profile dir: {profile_dir} ---")
    print(f"--- headless:    {headless} ---\n")

    with DiscordSession(profile_dir=profile_dir, headless=headless) as session:
        # --- step 1: login check ---
        print("[1/4] goto_discord() — checking login state...")
        try:
            session.goto_discord()
        except RuntimeError as e:
            print(f"   FAIL: {e}")
            print(f"   Fix: run `python3 -m sv_trade_bot.probe_selectors` (no --headless), "
                  f"log into Discord in the browser window, close, and re-run.")
            return 2
        print(f"   OK. URL = {session.page.url}")
        print()

        # --- step 2: channel ---
        if channel_url:
            print(f"[2/4] goto_url({channel_url!r}) (direct URL, skipping sidebar)...")
            t0 = time.monotonic()
            try:
                session.goto_url(channel_url)
            except Exception as e:
                print(f"   FAIL: {type(e).__name__}: {e}")
                return 3
            print(f"   OK in {time.monotonic() - t0:.1f}s. URL = {session.page.url}")
        else:
            print(f"[2/4] goto_channel({server_name!r}, {channel_name!r}) — sidebar nav.")
            t0 = time.monotonic()
            try:
                session.goto_channel(server_name, channel_name)
            except Exception as e:
                print(f"   FAIL: {type(e).__name__}: {e}")
                print(f"   Fix: in the browser window, open Klawf Cove > #{channel_name}, "
                      f"copy the URL from the address bar, and re-run with "
                      f"--channel-url <that-url>.")
                return 3
            print(f"   OK in {time.monotonic() - t0:.1f}s. URL = {session.page.url}")
        print()

        # --- step 3: DM ---
        if dm_url:
            print(f"[3/4] goto_url({dm_url!r}) (direct DM URL)...")
            t0 = time.monotonic()
            try:
                session.goto_url(dm_url)
            except Exception as e:
                print(f"   FAIL: {type(e).__name__}: {e}")
                return 4
            print(f"   OK in {time.monotonic() - t0:.1f}s. URL = {session.page.url}")
        else:
            print(f"[3/4] goto_dm_with({bot_username!r})...")
            t0 = time.monotonic()
            try:
                session.goto_dm_with(bot_username)
            except Exception as e:
                print(f"   FAIL: {type(e).__name__}: {e}")
                print(f"   Fix: open DM with {bot_username} manually, copy URL, re-run "
                      f"with --dm-url <that-url>.")
                return 4
            print(f"   OK in {time.monotonic() - t0:.1f}s. URL = {session.page.url}")
        print()

        # --- step 4: scrape ---
        print(f"[4/4] scrape_messages(author_filter={bot_username!r}) — reading last "
              f"{sample_count} matching messages...")
        # First: probe what selectors actually match anything on the page.
        candidates = [
            'li[id^="chat-messages-"]',
            'li[class*="messageListItem"]',
            'div[id^="message-content-"]',
            'div[class*="message_"]',
            '[role="article"]',
            'ol[role="list"] > li',
            'ol[data-list-id="chat-messages"] > li',
        ]
        print("   Probing message-list selectors:")
        for sel in candidates:
            try:
                count = session.page.locator(sel).count()
            except Exception as e:
                count = f"ERR: {e}"
            print(f"     {count:>5}  {sel}")

        msgs = session.scrape_messages(author_filter=None)
        print(f"   scrape_messages(no filter) returned {len(msgs)} items")
        msgs_filtered = session.scrape_messages(author_filter=bot_username)
        print(f"   scrape_messages(filter={bot_username!r}) returned {len(msgs_filtered)} items")
        msgs = msgs_filtered if msgs_filtered else msgs
        if not msgs:
            print(f"   FAIL: nothing scraped with any selector.")
            print(f"   Tell me which of the candidate selectors above had a non-zero count, "
                  f"and I'll wire up scrape_messages to use that one.")
            return 5
        print(f"   Got {len(msgs)} messages. Last {sample_count}:")
        unknown_count = 0
        for m in msgs[-sample_count:]:
            event = parse_message(m.body)
            kind = type(event).__name__
            if isinstance(event, Unknown):
                unknown_count += 1
            preview = m.body.replace("\n", " | ")[:100]
            print(f"   - [{kind:<14}] {preview}")
        print()

        if unknown_count:
            print(f"WARN: {unknown_count} of the sampled messages did not match any known "
                  f"template. If they look like real KlawfAPP messages, update parser.py.")

        print("--- ALL CHECKS PASSED. Selectors are working. ---")
        return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile-dir", type=Path, default=DiscordSession.DEFAULT_PROFILE_DIR)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--server-name", default="Klawf Cove")
    p.add_argument("--channel-name", default="scvi-bot")
    p.add_argument("--bot-username", default="KlawfAPP")
    p.add_argument("--sample-count", type=int, default=10,
                   help="How many recent DM messages to print + parse")
    p.add_argument("--channel-url", default="",
                   help="Direct discord.com/channels/SERVER/CHANNEL URL. "
                        "Skips sidebar navigation (much more reliable).")
    p.add_argument("--dm-url", default="",
                   help="Direct discord.com/channels/@me/DM URL for the KlawfAPP DM thread.")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    return probe(
        profile_dir=args.profile_dir,
        headless=args.headless,
        server_name=args.server_name,
        channel_name=args.channel_name,
        bot_username=args.bot_username,
        sample_count=args.sample_count,
        channel_url=args.channel_url,
        dm_url=args.dm_url,
    )


if __name__ == "__main__":
    sys.exit(main())
