"""Parser tests against verbatim KlawfAPP DM samples (April 2026 transcript)."""

from discord_driver.parser import (
    CodeIssued, Queued, UpNext, LoadingTrade, Searching, PartnerFound,
    NoPartner, TooSlow, TradeFinished, TradeCanceled, Unknown,
    parse_message, is_go_signal, is_terminal,
)


# --- single-template fixtures ---

def test_code_issued():
    body = (
        "Here's your trade code!\n"
        "5459 0891\n"
        "Instructions\n"
        "Connect to the internet.\n"
        "Open the Poke Portal on your Nintendo Switch.\n"
        "Select Link Trade.\n"
        "Enter the trade code above to connect with the bot.\n"
        "Wait here for the next message to continue the trade."
    )
    assert parse_message(body) == CodeIssued(code="54590891")
    assert is_go_signal(parse_message(body)) is None


def test_queued_short_eta():
    body = (
        "Trade Request Queued\n"
        "Your trade request has been queued.\n"
        "Queue Position: 1\n"
        "Estimated wait time: Less than a minute"
    )
    assert parse_message(body) == Queued(position=1, eta_text="Less than a minute")


def test_queued_minutes_eta():
    body = (
        "Trade Request Queued\n"
        "Your trade request has been queued.\n"
        "Queue Position: 3\n"
        "Estimated wait time: 4.5 minutes"
    )
    assert parse_message(body) == Queued(position=3, eta_text="4.5 minutes")


def test_up_next():
    body = (
        "You're Up Next!\n"
        "Your trade will begin very soon. Please be ready!\n"
        "Get ready to connect!"
    )
    assert parse_message(body) == UpNext()


def test_loading_trade_is_go_signal():
    body = (
        "Loading the Trade Menu...\n"
        "Pokemon: Charizard\n"
        "Trade Code: 5459 0891\n"
        "\n"
        "Initializing trade (Charizard). Please be ready."
    )
    event = parse_message(body)
    assert event == LoadingTrade(species="Charizard", code="54590891")
    assert is_go_signal(event) == "54590891"
    assert not is_terminal(event)


def test_loading_trade_multiword_species():
    body = (
        "Loading the Trade Menu...\n"
        "Pokemon: Mr. Mime\n"
        "Trade Code: 1234 5678\n"
        "\n"
        "Initializing trade (Mr. Mime). Please be ready."
    )
    assert parse_message(body) == LoadingTrade(species="Mr. Mime", code="12345678")


def test_searching():
    body = (
        "Now Searching for you,\n"
        "Waiting For:  .colef\n"
        "My IGN: Klawf.net\n"
        "\n"
        "Insert your Trade Code!"
    )
    assert parse_message(body) == Searching(waiting_for=".colef", bot_ign="Klawf.net")


def test_partner_found():
    body = (
        "Notice...\n"
        "Found Link Trade partner: Cole. TID: 863442 SID: 3548 "
        "Waiting for a Pokémon..."
    )
    assert parse_message(body) == PartnerFound(
        partner_name="Cole", tid=863442, sid=3548,
    )


def test_no_partner():
    body = "Notice...\nNo trading partner found. Canceling the trade."
    assert parse_message(body) == NoPartner()


def test_too_slow_notice():
    body = "Notice...\nOops! Something happened. Canceling the trade: TrainerTooSlow."
    assert parse_message(body) == TooSlow()


def test_trade_canceled_no_partner_reason():
    body = (
        "Trade Canceled\n"
        "Your trade was canceled.\n"
        "Reason: NoTrainerFound"
    )
    assert parse_message(body) == TradeCanceled(reason="NoTrainerFound")
    assert is_terminal(parse_message(body))


def test_trade_canceled_too_slow_reason():
    body = (
        "Trade Canceled\n"
        "Your trade was canceled.\n"
        "Reason: TrainerTooSlow"
    )
    assert parse_message(body) == TradeCanceled(reason="TrainerTooSlow")


def test_trade_finished():
    body = (
        "Trade finished. Enjoy!\n"
        "Here's what you traded me!"
    )
    event = parse_message(body)
    assert event == TradeFinished()
    assert is_terminal(event)


def test_unknown_message():
    body = "Some new template the bot started sending"
    event = parse_message(body)
    assert isinstance(event, Unknown)
    assert event.raw == body


# --- end-to-end lifecycle replay ---

def test_full_successful_trade_sequence():
    """Replay the 2:45 PM Charizard trade from the transcript."""
    messages = [
        "Here's your trade code!\n5996 1930\nInstructions",
        "Trade Request Queued\nQueue Position: 1\nEstimated wait time: Less than a minute",
        "Loading the Trade Menu...\nPokemon: Charizard\nTrade Code: 5996 1930\n\nInitializing trade (Charizard). Please be ready.",
        "Now Searching for you,\nWaiting For:  .colef\nMy IGN: Klawf.net\n\nInsert your Trade Code!",
        "Notice...\nFound Link Trade partner: Cole. TID: 863442 SID: 3548 Waiting for a Pokémon...",
        "Trade finished. Enjoy!\nHere's what you traded me!",
    ]
    events = [parse_message(m) for m in messages]

    assert events[0] == CodeIssued(code="59961930")
    assert events[1] == Queued(position=1, eta_text="Less than a minute")
    assert events[2] == LoadingTrade(species="Charizard", code="59961930")
    assert isinstance(events[3], Searching)
    assert isinstance(events[4], PartnerFound)
    assert events[5] == TradeFinished()

    # Code in the GO signal matches the original code.
    assert is_go_signal(events[2]) == events[0].code


def test_no_trainer_found_failure_sequence():
    """The 2:41 PM Charizard trade where Cole's Switch never connected."""
    messages = [
        "Here's your trade code!\n5459 0891\nInstructions",
        "Trade Request Queued\nQueue Position: 1\nEstimated wait time: Less than a minute",
        "You're Up Next!\nGet ready to connect!",
        "Loading the Trade Menu...\nPokemon: Charizard\nTrade Code: 5459 0891\n\nInitializing trade (Charizard). Please be ready.",
        "Now Searching for you,\nWaiting For:  .colef\nMy IGN: Klawf.net\n\nInsert your Trade Code!",
        "Notice...\nNo trading partner found. Canceling the trade.",
    ]
    events = [parse_message(m) for m in messages]
    assert events[2] == UpNext()
    assert events[5] == NoPartner()


def test_trainer_too_slow_failure_sequence():
    """The 2:56 PM Sneasler trade where Cole connected but didn't finalize."""
    messages = [
        "Loading the Trade Menu...\nPokemon: Sneasler\nTrade Code: 8068 4133\n\nInitializing trade (Sneasler). Please be ready.",
        "Notice...\nFound Link Trade partner: Cole. TID: 863442 SID: 3548 Waiting for a Pokémon...",
        "Trade Canceled\nYour trade was canceled.\nReason: TrainerTooSlow",
    ]
    events = [parse_message(m) for m in messages]
    assert isinstance(events[0], LoadingTrade)
    assert isinstance(events[1], PartnerFound)
    assert events[2] == TradeCanceled(reason="TrainerTooSlow")
    assert is_terminal(events[2])


def test_archaludon_oops_then_canceled():
    """The 8:44 AM Archaludon trade: Notice...Oops + then Trade Canceled.
    Both events should be parsed as their respective types."""
    notice = "Notice...\nOops! Something happened. Canceling the trade: TrainerTooSlow."
    canceled = "Trade Canceled\nYour trade was canceled.\nReason: TrainerTooSlow"
    assert parse_message(notice) == TooSlow()
    assert parse_message(canceled) == TradeCanceled(reason="TrainerTooSlow")
