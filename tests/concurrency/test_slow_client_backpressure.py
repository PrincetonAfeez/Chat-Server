from __future__ import annotations

import select
import socket
import threading
import time

from chatserver.queues.outbound import OutboundQueue
from conftest import connect_raw, read_until, running_server, send_frame


def test_bounded_outbound_queue_reports_overflow() -> None:
    outbound = OutboundQueue(maxsize=1)
    assert outbound.put_nowait({"type": "system", "body": "one"})
    assert not outbound.put_nowait({"type": "system", "body": "two"})


def test_slow_client_is_evicted_without_blocking_others(tmp_path) -> None:
    # Large queue + no rate/DB limits so the only backpressure is the slow
    # client's own un-drained socket. The big queue gives the drained sender
    # ample headroom (it can never self-evict), while the slow client is still
    # evicted by its writer's sendall timeout once its OS buffer fills.
    with running_server(
        tmp_path,
        outbound_queue_size=256,
        max_message_size=4096,
        rate_limit_messages=1_000_000,
        rate_limit_window=1000.0,
        db_queue_size=1_000_000,
    ) as server:
        slow = connect_raw(server, "slow")
        sender = connect_raw(server, "sender")
        send_frame(slow, {"type": "join", "room": "general"})
        send_frame(sender, {"type": "join", "room": "general"})

        # Drain the sender via select so its socket timeout (used by sendall)
        # is never altered; the 'slow' client is never read from.
        stop = threading.Event()

        def drain(sock: socket.socket) -> None:
            while not stop.is_set():
                ready, _, _ = select.select([sock], [], [], 0.1)
                if not ready:
                    continue
                try:
                    if not sock.recv(1 << 20):
                        break
                except OSError:
                    break

        drainer = threading.Thread(target=drain, args=(sender,), name="test-sender-drain")
        drainer.start()

        body = "x" * 1800
        deadline = time.monotonic() + 10.0
        try:
            while time.monotonic() < deadline:
                for _ in range(5):
                    send_frame(sender, {"type": "chat", "room": "general", "body": body})
                if server.snapshot()["slow_client_evictions"] >= 1:
                    break
                time.sleep(0.005)
        finally:
            stop.set()
            drainer.join(2.0)

        snap = server.snapshot()
        # The sender streamed its whole flood (it was never blocked by 'slow'),
        # and the non-reading slow client was evicted by backpressure.
        assert snap["slow_client_evictions"] >= 1, "the non-reading slow client should be evicted"
        assert any(e["reason"] == "SLOW_CLIENT_EVICTED" for e in snap["recent_evictions"])

        # The room still accepts and delivers for a fresh, healthy client.
        reader = connect_raw(server, "reader")
        send_frame(reader, {"type": "join", "room": "afterward"})
        read_until(reader, "system")
        send_frame(reader, {"type": "chat", "room": "afterward", "body": "after-eviction"})
        delivered = read_until(reader, "chat")
        assert delivered["body"] == "after-eviction"
        try:
            slow.close()
        except OSError:
            pass


def test_drop_oldest_policy_drops_without_evicting(tmp_path) -> None:
    with running_server(
        tmp_path,
        outbound_queue_size=8,
        max_message_size=4096,
        outbound_backpressure_policy="drop_oldest",
        rate_limit_messages=1_000_000,
        rate_limit_window=1000.0,
        db_queue_size=1_000_000,
    ) as server:
        slow = connect_raw(server, "slow")
        sender = connect_raw(server, "sender")
        send_frame(slow, {"type": "join", "room": "general"})
        send_frame(sender, {"type": "join", "room": "general"})

        stop = threading.Event()

        def drain(sock: socket.socket) -> None:
            while not stop.is_set():
                ready, _, _ = select.select([sock], [], [], 0.1)
                if not ready:
                    continue
                try:
                    if not sock.recv(1 << 20):
                        break
                except OSError:
                    break

        drainer = threading.Thread(target=drain, args=(sender,), name="test-drop-drain")
        drainer.start()

        body = "x" * 1800
        deadline = time.monotonic() + 10.0
        try:
            while time.monotonic() < deadline:
                for _ in range(5):
                    send_frame(sender, {"type": "chat", "room": "general", "body": body})
                if server.snapshot()["dropped_messages"] > 0:
                    break
                time.sleep(0.005)
        finally:
            stop.set()
            drainer.join(2.0)

        snap = server.snapshot()
        # The meaningful, race-free signal that drop_oldest is active: overflow
        # SHEDS messages. (The disconnect policy never drops — it evicts on the
        # first overflow. A wedged socket may still be evicted later by the
        # writer's sendall timeout regardless of policy, so we don't assert on
        # eviction count here.)
        assert snap["dropped_messages"] > 0, "overflow should drop messages under drop_oldest"
        try:
            slow.close()
        except OSError:
            pass
