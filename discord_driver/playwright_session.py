"""Playwright wrapper around web Discord (Klawf Cove).

Responsibilities, in order of trust:
  1. Launch Chromium with a persistent profile so login survives between runs.
  2. Navigate to a target server channel (for posting $trade requests).
  3. Open the KlawfAPP DM thread and scrape new messages.

Selectors target Discord's accessibility roles where possible; if Discord
ships a UI change that breaks them, the driver halts on first parse failure
(see driver.py) so we notice rather than silently dropping events.

First-run setup:
    pip install playwright
    playwright install chromium

Then launch with `headless=False` once and log into Discord manually. The
profile dir persists the session — subsequent runs can be headless.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScrapedMessage:
    """A single message extracted from a Discord channel/DM."""
    discord_id: str    # Discord's stable per-message DOM id (e.g. "chat-messages-...-1234")
    author: str        # Username displayed for the message
    body: str          # Plain-text body, newlines preserved


class DiscordSession:
    """Owns a Playwright browser context. Always use as a context manager."""

    DEFAULT_PROFILE_DIR = Path.home() / ".cache" / "klawfcove-driver-profile"

    def __init__(
        self,
        profile_dir: Path | str = DEFAULT_PROFILE_DIR,
        headless: bool = False,
    ):
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self) -> "DiscordSession":
        from playwright.sync_api import sync_playwright  # lazy import
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Reuse the first page if Chromium opened one, else make a fresh tab.
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("DiscordSession not entered")
        return self._page

    # --- navigation ---

    def goto_discord(self) -> None:
        """Navigate to Discord. Errors if not already logged in."""
        self.page.goto("https://discord.com/channels/@me", wait_until="domcontentloaded")
        # If we land on /login it means the persistent profile isn't authed.
        if "/login" in self.page.url:
            raise RuntimeError(
                "Not logged into Discord in this browser profile. "
                "Run once with headless=False and log in manually first."
            )

    def goto_url(self, url: str) -> None:
        """Direct navigation to a Discord channel/DM URL.

        Strongly preferred over name-based sidebar clicking — URLs are stable
        across UI changes, sidebar accessibility names are not.
        """
        if not url.startswith("https://discord.com/channels/"):
            raise ValueError(f"Expected a discord.com/channels URL, got {url!r}")
        self.page.goto(url, wait_until="domcontentloaded")
        if "/login" in self.page.url:
            raise RuntimeError("Not logged into Discord in this browser profile.")
        self.page.wait_for_load_state("networkidle")

    def goto_dm_with(self, username: str) -> None:
        """Open the DM thread with a given user (e.g. 'KlawfAPP').

        Discord lists DMs in a left sidebar under @me. The simplest approach
        that survives UI changes: click the DM list item whose accessible
        name contains the username.
        """
        self.goto_discord()
        # Sidebar DM entries are anchor elements with accessible names like
        # "KlawfAPP, 2 mentions" or just "KlawfAPP".
        self.page.get_by_role("link", name=username, exact=False).first.click()
        self.page.wait_for_load_state("networkidle")

    def goto_channel(self, server_name: str, channel_name: str) -> None:
        """Navigate to a channel inside a server by visible names.

        Brittle — Discord renames its sidebar items based on read-state, so we
        match by partial accessible name.
        """
        self.goto_discord()
        # Click the server icon.
        self.page.get_by_role("treeitem", name=server_name, exact=False).first.click()
        # Then the channel.
        self.page.get_by_role("link", name=channel_name, exact=False).first.click()
        self.page.wait_for_load_state("networkidle")

    # --- scraping ---

    def scrape_messages(self, author_filter: Optional[str] = None) -> List[ScrapedMessage]:
        """Return currently-visible messages in the open channel/DM thread.

        For KlawfAPP we have to handle two render modes:
          - Plain text messages: body lives in [id^="message-content-"]
          - Rich embed cards (most lifecycle messages): title/description live
            in nested embed nodes, NOT in message-content
        Cheapest robust capture: take inner_text() of the whole <li>, which
        includes text body + all embed content concatenated.

        author_filter does NOT pre-filter scraping — we let the parser decide
        what's a KlawfAPP template. The filter param is kept for API
        compatibility with MockSession but ignored here. Random user chatter
        in DMs won't match any KlawfAPP template, so the parser-as-filter
        approach is robust as long as we treat Unknown events as no-ops.
        """
        items = self.page.locator('li[id^="chat-messages-"]').all()
        out: List[ScrapedMessage] = []
        for item in items:
            try:
                discord_id = item.get_attribute("id") or ""
                body = item.inner_text()
                # Author label is best-effort; only set when the per-message
                # header is rendered. We don't depend on it for routing.
                aria = item.get_attribute("aria-label") or ""
                out.append(ScrapedMessage(
                    discord_id=discord_id,
                    author=aria,
                    body=body,
                ))
            except Exception as e:
                logger.warning("Failed to scrape one message: %s", e)
        return out

    # --- posting ---

    def post_message(self, body: str) -> None:
        """Send a message in the currently-open channel.

        Uses keyboard typing instead of fill() so multi-line Showdown sets
        send as a single message (Shift+Enter for newlines, Enter to send).
        """
        textbox = self.page.get_by_role("textbox").last
        textbox.click()
        lines = body.split("\n")
        for i, line in enumerate(lines):
            self.page.keyboard.type(line)
            if i < len(lines) - 1:
                self.page.keyboard.down("Shift")
                self.page.keyboard.press("Enter")
                self.page.keyboard.up("Shift")
        self.page.keyboard.press("Enter")


@contextmanager
def open_session(
    profile_dir: Path | str = DiscordSession.DEFAULT_PROFILE_DIR,
    headless: bool = False,
) -> Iterator[DiscordSession]:
    with DiscordSession(profile_dir=profile_dir, headless=headless) as s:
        yield s
