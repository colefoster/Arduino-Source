"""End-to-end-ish driver tests with fakes for Discord + Switch bridge."""

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from discord_driver.driver import Driver, DriverConfig
from discord_driver.playwright_session import ScrapedMessage
from discord_driver.set_queue import SetQueue


VAPOREON = "Vaporeon @ Leftovers\nAbility: Water Absorb"
LUCARIO = "Lucario (M) @ Life Orb\nAbility: Inner Focus"


# --- fakes ---

@dataclass
class FakeSession:
    inbox: List[ScrapedMessage] = field(default_factory=list)
    posts: List[str] = field(default_factory=list)

    def scrape_messages(self, author_filter: Optional[str] = None):
        return list(self.inbox)

    def post_message(self, body: str) -> None:
        self.posts.append(body)


@dataclass
class FakeBridge:
    connected: bool = True
    sent: List[tuple] = field(default_factory=list)  # (code, set_id)

    def is_connected(self) -> bool:
        return self.connected

    def send_ready(self, code: str, set_id: str) -> None:
        self.sent.append((code, set_id))


def _msg(idx: int, body: str) -> ScrapedMessage:
    return ScrapedMessage(discord_id=f"chat-messages-x-{idx}", author="KlawfAPP", body=body)


@pytest.fixture
def setup(tmp_path):
    queue = SetQueue(tmp_path / "test.db")
    session = FakeSession()
    bridge = FakeBridge()
    # Relax safety caps for the existing happy-path tests; they're verified
    # in their own dedicated cases below.
    config = DriverConfig(
        max_posts_per_session=100,
        min_seconds_between_posts=0.0,
    )
    driver = Driver(session, queue, bridge, config)
    yield driver, session, queue, bridge
    queue.close()


# --- tests ---

def test_pending_set_gets_posted_with_prefix(setup):
    driver, session, queue, _ = setup
    s = queue.add_set(VAPOREON)
    driver.tick()
    assert len(session.posts) == 1
    assert session.posts[0].startswith("$trade Vaporeon")
    assert queue.get(s.set_id).status == "submitted"


def test_max_in_flight_enforced(setup):
    driver, session, queue, _ = setup
    queue.add_set(VAPOREON)
    queue.add_set(LUCARIO)
    driver.tick()  # posts Vaporeon
    driver.tick()  # should NOT post Lucario yet (Vaporeon is submitted)
    assert len(session.posts) == 1


def test_code_issued_assigns_to_oldest_submitted(setup):
    driver, session, queue, _ = setup
    s = queue.add_set(VAPOREON)
    driver.tick()  # posts → submitted

    session.inbox.append(_msg(1, "Here's your trade code!\n5996 1930\nInstructions"))
    driver.tick()

    refreshed = queue.get(s.set_id)
    assert refreshed.status == "queued"
    assert refreshed.code == "59961930"


def test_loading_trade_emits_to_bridge_and_marks_loading(setup):
    driver, session, queue, bridge = setup
    s = queue.add_set(VAPOREON)
    driver.tick()
    session.inbox.append(_msg(1, "Here's your trade code!\n5996 1930\nInstructions"))
    driver.tick()

    session.inbox.append(_msg(2,
        "Loading the Trade Menu...\nPokemon: Vaporeon\nTrade Code: 5996 1930\n\n"
        "Initializing trade (Vaporeon). Please be ready."
    ))
    driver.tick()

    assert bridge.sent == [("59961930", s.set_id)]
    assert queue.get(s.set_id).status == "loading"


def test_trade_finished_marks_traded(setup):
    driver, session, queue, bridge = setup
    s = queue.add_set(VAPOREON)
    driver.tick()
    session.inbox.append(_msg(1, "Here's your trade code!\n5996 1930\nInstructions"))
    driver.tick()
    session.inbox.append(_msg(2,
        "Loading the Trade Menu...\nPokemon: Vaporeon\nTrade Code: 5996 1930"
    ))
    driver.tick()
    session.inbox.append(_msg(3, "Trade finished. Enjoy!"))
    driver.tick()

    assert queue.get(s.set_id).status == "traded"


def test_no_partner_failure_path(setup):
    driver, session, queue, bridge = setup
    s = queue.add_set(VAPOREON)
    driver.tick()
    session.inbox.append(_msg(1, "Here's your trade code!\n5459 0891\nInstructions"))
    driver.tick()
    session.inbox.append(_msg(2,
        "Loading the Trade Menu...\nPokemon: Vaporeon\nTrade Code: 5459 0891"
    ))
    driver.tick()
    session.inbox.append(_msg(3, "Notice...\nNo trading partner found. Canceling the trade."))
    driver.tick()

    refreshed = queue.get(s.set_id)
    assert refreshed.status == "failed"
    assert refreshed.failure_reason == "no_partner"


def test_loading_with_disconnected_bridge_marks_failed(setup):
    """If C++ disconnects mid-trade (after the post, before LoadingTrade
    arrives), the loading event should mark the set failed."""
    driver, session, queue, bridge = setup
    s = queue.add_set(VAPOREON)
    driver.tick()  # bridge connected, set posted
    session.inbox.append(_msg(1, "Here's your trade code!\n5996 1930\nInstructions"))
    driver.tick()
    # Now the C++ side disconnects (program stopped, crashed, etc).
    bridge.connected = False
    session.inbox.append(_msg(2,
        "Loading the Trade Menu...\nPokemon: Vaporeon\nTrade Code: 5996 1930"
    ))
    driver.tick()

    refreshed = queue.get(s.set_id)
    assert refreshed.status == "failed"
    assert refreshed.failure_reason == "switch_bridge_disconnected"
    assert bridge.sent == []


def test_no_posts_until_bridge_connects(setup):
    """Driver must not post when bridge is disconnected — otherwise the
    bot's lifecycle would fire before C++ could pick up the GO signal."""
    driver, session, queue, bridge = setup
    bridge.connected = False
    queue.add_set(VAPOREON)
    for _ in range(5):
        driver.tick()
    assert session.posts == []
    # Once bridge connects, post happens.
    bridge.connected = True
    driver.tick()
    assert len(session.posts) == 1


def test_seen_message_ids_prevent_double_processing(setup):
    driver, session, queue, _ = setup
    s = queue.add_set(VAPOREON)
    driver.tick()  # posts

    session.inbox.append(_msg(1, "Here's your trade code!\n1111 2222\nInstructions"))
    driver.tick()
    # Second tick with the same inbox should not re-process the message.
    driver.tick()

    assert queue.get(s.set_id).code == "11112222"
    # No accidental status flip — still 'queued'.
    assert queue.get(s.set_id).status == "queued"


def test_max_posts_per_session_halts_driver(tmp_path):
    queue = SetQueue(tmp_path / "halt.db")
    try:
        for _ in range(5):
            queue.add_set(VAPOREON)
        config = DriverConfig(
            max_posts_per_session=2,
            min_seconds_between_posts=0.0,
            max_in_flight=10,  # prevent in-flight cap from masking the post cap
        )
        session = FakeSession()
        driver = Driver(session, queue, FakeBridge(), config)
        for _ in range(10):
            driver.tick()
        assert len(session.posts) == 2
        assert driver.state.halted
        assert "posts_per_session" in driver.state.halt_reason
    finally:
        queue.close()


def test_min_seconds_between_posts_enforced(tmp_path, monkeypatch):
    queue = SetQueue(tmp_path / "cooldown.db")
    try:
        queue.add_set(VAPOREON)
        queue.add_set(LUCARIO)
        config = DriverConfig(
            max_posts_per_session=10,
            min_seconds_between_posts=60.0,
            max_in_flight=10,
        )
        session = FakeSession()
        driver = Driver(session, queue, FakeBridge(), config)

        fake_now = [1000.0]
        monkeypatch.setattr("discord_driver.driver.time.monotonic",
                            lambda: fake_now[0])

        driver.tick()
        assert len(session.posts) == 1
        # Next tick 30s later — under the 60s floor, must NOT post.
        fake_now[0] += 30
        driver.tick()
        assert len(session.posts) == 1
        # 31s after that (61s total) — now allowed.
        fake_now[0] += 31
        driver.tick()
        assert len(session.posts) == 2
    finally:
        queue.close()


def test_in_flight_stale_halts_driver(tmp_path, monkeypatch):
    queue = SetQueue(tmp_path / "stale.db")
    try:
        s = queue.add_set(VAPOREON)
        config = DriverConfig(
            max_posts_per_session=10,
            min_seconds_between_posts=0.0,
            in_flight_stale_seconds=60.0,
        )
        session = FakeSession()
        driver = Driver(session, queue, FakeBridge(), config)
        driver.tick()  # → submitted
        assert queue.get(s.set_id).status == "submitted"

        # Pretend wall-clock time advanced past the stale threshold without
        # any DM activity (bot ghosted us).
        real_time = __import__("time")
        original = real_time.time
        monkeypatch.setattr("discord_driver.driver.time.time",
                            lambda: original() + 120)

        driver.tick()
        assert driver.state.halted
        assert "stuck" in driver.state.halt_reason
    finally:
        queue.close()


def test_pipelined_two_sets_match_loading_by_code(setup):
    """Bot can pipeline: two of our trades queued, two distinct codes.
    LoadingTrade events must match back by code, not by submission order."""
    driver, session, queue, bridge = setup
    a = queue.add_set(VAPOREON)
    b = queue.add_set(LUCARIO)
    driver.config.max_in_flight = 2
    driver.tick()  # posts a
    driver.tick()  # posts b

    session.inbox.append(_msg(1, "Here's your trade code!\n1111 1111\nInstructions"))
    driver.tick()  # → assigns code to a (oldest submitted)
    session.inbox.append(_msg(2, "Here's your trade code!\n2222 2222\nInstructions"))
    driver.tick()  # → assigns code to b

    # Now bot loads b *first* (out of order). Must still match correctly.
    session.inbox.append(_msg(3,
        "Loading the Trade Menu...\nPokemon: Lucario\nTrade Code: 2222 2222"
    ))
    driver.tick()
    assert bridge.sent == [("22222222", b.set_id)]
    assert queue.get(b.set_id).status == "loading"
    assert queue.get(a.set_id).status == "queued"  # still waiting

    session.inbox.append(_msg(4,
        "Loading the Trade Menu...\nPokemon: Vaporeon\nTrade Code: 1111 1111"
    ))
    driver.tick()
    assert bridge.sent[-1] == ("11111111", a.set_id)
