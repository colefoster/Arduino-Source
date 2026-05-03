import socket
import time

import pytest

from discord_driver.switch_bridge import FakeSwitch, SwitchBridge


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def bridge():
    b = SwitchBridge(port=_free_port())
    b.start()
    yield b
    b.stop()


def _wait_connected(bridge: SwitchBridge, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if bridge.is_connected():
            return
        time.sleep(0.01)
    raise TimeoutError("bridge never registered the client connection")


def test_send_ready_round_trip(bridge):
    client = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        bridge.send_ready(code="59961930", set_id="abc")
        msg = client.recv()
        assert msg == {"type": "TRADE_READY", "code": "59961930", "set_id": "abc"}
    finally:
        client.close()


def test_client_event_reaches_driver_via_poll(bridge):
    client = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        client.send(type="TRADE_COMPLETE", set_id="abc")
        evt = bridge.poll(timeout=1.0)
        assert evt is not None
        assert evt.type == "TRADE_COMPLETE"
        assert evt.set_id == "abc"
        assert evt.reason is None
    finally:
        client.close()


def test_failure_event_carries_reason(bridge):
    client = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        client.send(type="TRADE_FAILED", set_id="abc", reason="partner_no_show")
        evt = bridge.poll(timeout=1.0)
        assert evt.type == "TRADE_FAILED"
        assert evt.reason == "partner_no_show"
    finally:
        client.close()


def test_send_without_client_raises(bridge):
    with pytest.raises(ConnectionError):
        bridge.send_ready(code="11112222", set_id="x")


def test_invalid_code_rejected(bridge):
    client = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        with pytest.raises(ValueError):
            bridge.send_ready(code="1234", set_id="x")
        with pytest.raises(ValueError):
            bridge.send_ready(code="1234 5678", set_id="x")
    finally:
        client.close()


def test_ping_pong(bridge):
    client = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        bridge.send_ping()
        assert client.recv() == {"type": "PING"}
        client.send(type="PONG")
        evt = bridge.poll(timeout=1.0)
        assert evt.type == "PONG"
    finally:
        client.close()


def test_malformed_line_dropped_not_crashed(bridge):
    client = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        client.sock.sendall(b"not-json-at-all\n")
        client.send(type="TRADE_COMPLETE", set_id="ok")
        evt = bridge.poll(timeout=1.0)
        assert evt is not None and evt.set_id == "ok"
    finally:
        client.close()


def test_reconnect_replaces_old_client(bridge):
    a = FakeSwitch("127.0.0.1", bridge.port)
    _wait_connected(bridge)
    a.close()
    # Brief settle so the bridge notices the EOF.
    time.sleep(0.1)
    b = FakeSwitch("127.0.0.1", bridge.port)
    try:
        _wait_connected(bridge)
        bridge.send_cancelled(set_id="x", reason="restart")
        msg = b.recv()
        assert msg["type"] == "TRADE_CANCELLED"
    finally:
        b.close()
