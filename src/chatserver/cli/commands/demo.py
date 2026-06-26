"""`chatserver demo …` — runnable feature and teaching demos.

Each safe demo spins up a real ephemeral server, exercises one feature, prints
a JSON result, and tears the server down. The unsafe demos run the broken
pattern and print the failure next to the safe behavior.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import select
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from chatserver.protocol.framing import FrameDecoder, encode_frame
from chatserver.scheduling.clock import ManualClock

DEMO_NAMES = [
    "basic",
    "framing",
    "multi-client",
    "slow-client",
    "rate-limit",
    "idle-timeout",
    "db-writer",
    "graceful-shutdown",
    "all",
    "unsafe-framing",
    "unsafe-slow-client",
    "unsafe-room-race",
    "unsafe-db-blocking",
    "unsafe-shutdown",
]


def add_demo_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    demo = sub.add_parser("demo", help="run local teaching demos")
    demo.add_argument("demo_name", choices=DEMO_NAMES)


def demo(args: argparse.Namespace) -> int:
    name = args.demo_name
    if name == "all":
        for item in [
            "framing",
            "basic",
            "multi-client",
            "slow-client",
            "rate-limit",
            "idle-timeout",
            "db-writer",
            "graceful-shutdown",
        ]:
            print(f"== demo {item} ==")
            _run_demo(item)
        return 0
    _run_demo(name)
    return 0


def _run_demo(name: str) -> None:
    safe_demos = {
        "framing": demo_framing,
        "basic": demo_basic,
        "multi-client": demo_multi_client,
        "slow-client": demo_slow_client,
        "rate-limit": demo_rate_limit,
        "idle-timeout": demo_idle_timeout,
        "db-writer": demo_db_writer,
        "graceful-shutdown": demo_graceful_shutdown,
    }
    if name in safe_demos:
        safe_demos[name]()
        return
    unsafe_demos = {
        "unsafe-framing": "chatserver.teaching.unsafe_no_framing",
        "unsafe-slow-client": "chatserver.teaching.unsafe_slow_client",
        "unsafe-room-race": "chatserver.teaching.unsafe_no_locks",
        "unsafe-db-blocking": "chatserver.teaching.unsafe_direct_db_write",
        "unsafe-shutdown": "chatserver.teaching.unsafe_no_shutdown",
    }
    module = __import__(unsafe_demos[name], fromlist=["unsafe_example"])
    print(module.unsafe_example())


def demo_framing() -> None:
    decoder = FrameDecoder(4096)
    first = b'{"type":"hello","nick":"ada"}\n{"type":"rooms"}'
    second = b'\n{"type":"who"}\n'
    frames, errors = decoder.feed(first)
    more, more_errors = decoder.feed(second)
    print(
        json.dumps(
            {
                "explanation": "one logical frame was split across reads and three frames were merged; "
                "the decoder recovered all of them",
                "frames": frames + more,
                "errors": [str(e) for e in errors + more_errors],
            },
            indent=2,
        )
    )


def demo_basic() -> None:
    with _demo_server() as server:
        alice = _client(server)
        bob = _client(server)
        _send(alice, {"type": "hello", "nick": "alice"})
        _send(bob, {"type": "hello", "nick": "bob"})
        _read_until(alice, "welcome")
        _read_until(bob, "welcome")
        _send(alice, {"type": "join", "room": "general"})
        _send(bob, {"type": "join", "room": "general"})
        _read_until(alice, "history")
        _read_until(bob, "history")
        _read_until(alice, "system")
        _read_until(bob, "system")
        _send(alice, {"type": "chat", "room": "general", "body": "hello from demo"})
        delivered = _read_until(bob, "chat")
        print(json.dumps({"broadcast_reached_bob": delivered}, indent=2, sort_keys=True))
        alice.close()
        bob.close()


def demo_multi_client() -> None:
    """Two clients in one room — same flow as basic with explicit demo output."""
    with _demo_server() as server:
        alice = _client(server)
        bob = _client(server)
        _send(alice, {"type": "hello", "nick": "alice"})
        _send(bob, {"type": "hello", "nick": "bob"})
        _read_until(alice, "welcome")
        _read_until(bob, "welcome")
        _send(alice, {"type": "join", "room": "general"})
        _send(bob, {"type": "join", "room": "general"})
        _read_until(alice, "history")
        _read_until(bob, "history")
        _read_until(alice, "system")
        _read_until(bob, "system")
        _send(alice, {"type": "chat", "room": "general", "body": "hello from multi-client demo"})
        delivered = _read_until(bob, "chat")
        print(
            json.dumps(
                {
                    "demo": "multi-client",
                    "clients": 2,
                    "broadcast_reached_bob": delivered["body"] == "hello from multi-client demo",
                },
                indent=2,
                sort_keys=True,
            )
        )
        alice.close()
        bob.close()


def demo_slow_client() -> None:
    with _demo_server(
        outbound_queue_size=64,
        max_message_size=4096,
        rate_limit_messages=1_000_000,
        rate_limit_window=1000.0,
        db_queue_size=1_000_000,
    ) as server:
        slow = _client(server)
        sender = _client(server)
        for sock, nick in [(slow, "slow"), (sender, "sender")]:
            _send(sock, {"type": "hello", "nick": nick})
            _read_until(sock, "welcome")
            _send(sock, {"type": "join", "room": "general"})
            _read_until(sock, "system")

        # The sender is drained so only the never-read 'slow' client builds up
        # backpressure; the sender flooding proves it is not blocked by 'slow'.
        stop = threading.Event()

        def drain_sender() -> None:
            while not stop.is_set():
                ready, _, _ = select.select([sender], [], [], 0.1)
                if not ready:
                    continue
                try:
                    if not sender.recv(1 << 20):
                        break
                except OSError:
                    break

        drainer = threading.Thread(target=drain_sender, name="demo-sender-drain")
        drainer.start()
        body = "x" * 1800
        deadline = time.monotonic() + 8.0
        try:
            while time.monotonic() < deadline:
                for _ in range(5):
                    _send(sender, {"type": "chat", "room": "general", "body": body})
                if server.snapshot()["slow_client_evictions"] > 0:
                    break
                time.sleep(0.005)
        finally:
            stop.set()
            drainer.join(2.0)

        snap = server.snapshot()
        print(
            json.dumps(
                {
                    "slow_client_evictions": snap["slow_client_evictions"],
                    "evicted_clients": snap["evicted_clients"],
                    "recent_evictions": snap["recent_evictions"],
                    "note": "the drained sender kept flooding while the slow client was evicted",
                },
                indent=2,
                sort_keys=True,
            )
        )
        with contextlib.suppress(OSError):
            slow.close()


def demo_rate_limit() -> None:
    with _demo_server(rate_limit_messages=5, rate_limit_window=60.0) as server:
        sock = _client(server)
        _send(sock, {"type": "hello", "nick": "noisy"})
        _read_until(sock, "welcome")
        _send(sock, {"type": "join", "room": "general"})
        _read_until(sock, "system")
        for i in range(20):
            _send(sock, {"type": "chat", "room": "general", "body": f"msg {i}"})
        error = _read_until(sock, "error")
        snap = server.snapshot()
        print(
            json.dumps(
                {
                    "first_error_code": error["code"],
                    "rate_limit_rejections": snap["rate_limit_rejections"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        sock.close()


def demo_idle_timeout() -> None:
    clock = ManualClock()
    with _demo_server(idle_timeout=10.0, clock=clock) as server:
        sock = _client(server)
        _send(sock, {"type": "hello", "nick": "ghost"})
        _read_until(sock, "welcome")
        before = server.snapshot()["connected_clients"]
        clock.advance(11.0)
        server.evict_idle_sessions()
        snap = server.snapshot()
        print(
            json.dumps(
                {
                    "connected_before": before,
                    "connected_after": snap["connected_clients"],
                    "idle_timeout_evictions": snap["idle_timeout_evictions"],
                    "note": "eviction driven by an injected clock, no real waiting",
                },
                indent=2,
                sort_keys=True,
            )
        )
        sock.close()


def demo_db_writer() -> None:
    with _demo_server() as server:
        sock = _client(server)
        _send(sock, {"type": "hello", "nick": "writer"})
        _read_until(sock, "welcome")
        _send(sock, {"type": "join", "room": "general"})
        _read_until(sock, "system")
        for i in range(10):
            _send(sock, {"type": "chat", "room": "general", "body": f"persist {i}"})
            _read_until(sock, "chat")
        deadline = time.monotonic() + 3.0
        while server.db_writer.backlog() > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        stored = server.store.recent_room_messages("general", 50)
        snap = server.snapshot()
        print(
            json.dumps(
                {
                    "db_write_successes": snap["db_write_successes"],
                    "db_writer_backlog": snap["db_writer_backlog"],
                    "stored_chat_bodies": [m["body"] for m in stored if m.get("sender") == "writer"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        sock.close()


def demo_graceful_shutdown() -> None:
    with _demo_server() as server:
        sock = _client(server)
        _send(sock, {"type": "hello", "nick": "alice"})
        _read_until(sock, "welcome")
        _send(sock, {"type": "join", "room": "general"})
        _read_until(sock, "system")
        before = server.snapshot()
        server.stop()
        after = server.snapshot()
        print(
            json.dumps(
                {
                    "connected_before": before["connected_clients"],
                    "connected_after": after["connected_clients"],
                    "rooms_after": after["rooms"],
                    "note": "registries cleared and workers joined on shutdown",
                },
                indent=2,
                sort_keys=True,
            )
        )
        with contextlib.suppress(OSError):
            sock.close()


# --- demo helpers ---------------------------------------------------------


class _DemoServer:
    def __init__(self, **overrides: Any) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        clock = overrides.pop("clock", None)
        config = ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(Path(self._tmp.name) / "chat.db"),
            heartbeat_interval=overrides.pop("heartbeat_interval", 1000.0),
            idle_timeout=overrides.pop("idle_timeout", 5000.0),
            stats_interval=0.0,
            **overrides,
        )
        self.server = ChatServer(config, clock=clock) if clock else ChatServer(config)

    def __enter__(self) -> ChatServer:
        self.server.start()
        return self.server

    def __exit__(self, *exc: object) -> None:
        self.server.stop()
        self._tmp.cleanup()


def _demo_server(**overrides: Any) -> _DemoServer:
    return _DemoServer(**overrides)


def _client(server: ChatServer) -> socket.socket:
    sock = socket.create_connection(server.address, timeout=2.0)
    sock.settimeout(2.0)
    return sock


def _send(sock: socket.socket, message: dict[str, Any]) -> None:
    sock.sendall(encode_frame(message))


def _read_until(sock: socket.socket, msg_type: str) -> dict[str, Any]:
    decoder = FrameDecoder(1 << 20)
    while True:
        data = sock.recv(65536)
        if not data:
            raise RuntimeError("socket closed during demo")
        frames, _errors = decoder.feed(data)
        for frame in frames:
            message: dict[str, Any] = json.loads(frame)
            if message.get("type") == msg_type:
                return message
