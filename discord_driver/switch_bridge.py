"""JSON-over-TCP bridge between this Python driver and the C++ SerialPrograms
DiscordTradeBot module.

Wire protocol: newline-delimited JSON, one message per line.

Python -> C++:
    {"type": "TRADE_READY",     "code": "12345678", "set_id": "abc"}
    {"type": "TRADE_CANCELLED", "set_id": "abc", "reason": "..."}
    {"type": "PING"}

C++ -> Python:
    {"type": "READY"}                                       (sent on connect)
    {"type": "TRADE_COMPLETE", "set_id": "abc"}
    {"type": "TRADE_FAILED",   "set_id": "abc", "reason": "..."}
    {"type": "PONG"}

The bridge holds at most one connected client (the C++ program). If a TRADE_READY
arrives while no client is connected, send_ready() raises — the caller should
back the set out of 'loading' status.

This file is exercised in two modes:
  * Real:  bind on a localhost port, accept a long-lived C++ connection.
  * Fake:  in-process loopback for tests; see FakeSwitch.
"""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Optional


@dataclass
class SwitchEvent:
    type: str
    set_id: Optional[str] = None
    reason: Optional[str] = None

    @classmethod
    def from_json(cls, line: str) -> "SwitchEvent":
        obj = json.loads(line)
        return cls(
            type=obj["type"],
            set_id=obj.get("set_id"),
            reason=obj.get("reason"),
        )


class SwitchBridge:
    """TCP server that holds one connection from the C++ program at a time."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9988):
        self.host = host
        self.port = port
        self._server_sock: Optional[socket.socket] = None
        self._client_sock: Optional[socket.socket] = None
        self._client_lock = threading.Lock()
        self._inbound: Queue[SwitchEvent] = Queue()
        self._accept_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # --- lifecycle ---

    def start(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(1)
        s.settimeout(0.5)  # so accept loop can notice _stop
        self._server_sock = s
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="switch-bridge-accept", daemon=True,
        )
        self._accept_thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._client_lock:
            if self._client_sock:
                try:
                    self._client_sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._client_sock.close()
                self._client_sock = None
        if self._server_sock:
            self._server_sock.close()
            self._server_sock = None

    # --- producer side (driver calls these) ---

    def is_connected(self) -> bool:
        with self._client_lock:
            return self._client_sock is not None

    def send_ready(self, code: str, set_id: str) -> None:
        if not (code.isdigit() and len(code) == 8):
            raise ValueError(f"trade code must be 8 digits, got {code!r}")
        self._send({"type": "TRADE_READY", "code": code, "set_id": set_id})

    def send_cancelled(self, set_id: str, reason: str) -> None:
        self._send({"type": "TRADE_CANCELLED", "set_id": set_id, "reason": reason})

    def send_ping(self) -> None:
        self._send({"type": "PING"})

    # --- consumer side ---

    def poll(self, timeout: float = 0.0) -> Optional[SwitchEvent]:
        try:
            return self._inbound.get(timeout=timeout) if timeout > 0 else self._inbound.get_nowait()
        except Empty:
            return None

    # --- internals ---

    def _send(self, obj: dict) -> None:
        line = (json.dumps(obj) + "\n").encode("utf-8")
        with self._client_lock:
            if not self._client_sock:
                raise ConnectionError("no Switch client connected")
            self._client_sock.sendall(line)

    def _accept_loop(self) -> None:
        import logging
        log = logging.getLogger("switch_bridge")
        assert self._server_sock is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            log.info("CLIENT CONNECTED from %s", addr)
            with self._client_lock:
                # Replace any prior connection (C++ side reconnected).
                if self._client_sock:
                    log.info("Replacing prior client connection")
                    try:
                        self._client_sock.close()
                    except OSError:
                        pass
                self._client_sock = conn
            self._reader_thread = threading.Thread(
                target=self._read_loop, args=(conn,),
                name="switch-bridge-reader", daemon=True,
            )
            self._reader_thread.start()

    def _read_loop(self, conn: socket.socket) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = SwitchEvent.from_json(line.decode("utf-8"))
                except (ValueError, KeyError):
                    continue  # malformed — drop
                self._inbound.put(evt)
        with self._client_lock:
            if self._client_sock is conn:
                self._client_sock = None
                import logging
                logging.getLogger("switch_bridge").info("CLIENT DISCONNECTED")


class FakeSwitch:
    """In-process client for tests: connects to a SwitchBridge and lets the
    test drive both sides of the conversation."""

    def __init__(self, host: str, port: int):
        self.sock = socket.create_connection((host, port))
        self._buf = b""
        self.sock.settimeout(2.0)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, **kwargs) -> None:
        self.sock.sendall((json.dumps(kwargs) + "\n").encode("utf-8"))

    def recv(self) -> dict:
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("bridge closed connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))
