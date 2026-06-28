""" Test db backpressure """

from __future__ import annotations

import time

from chatserver.queues.db_jobs import DbJob
from conftest import connect_raw, read_until, running_server, send_frame


def test_reject_chat_policy_returns_server_busy(tmp_path) -> None:
    with running_server(tmp_path, db_backpressure_policy="reject_chat") as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        original = server.enqueue_db

        def reject_store_message(job: DbJob) -> bool:
            if job.job_type == "store_message":
                return False
            return original(job)

        server.enqueue_db = reject_store_message  # type: ignore[method-assign]
        send_frame(alice, {"type": "chat", "room": "general", "body": "should fail"})
        error = read_until(alice, "error")
        assert error["code"] == "server_busy"
        assert server.snapshot()["connected_clients"] == 1


def test_disconnect_policy_evicts_on_db_backlog(tmp_path) -> None:
    with running_server(tmp_path, db_backpressure_policy="disconnect") as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        original = server.enqueue_db

        def reject_store_message(job: DbJob) -> bool:
            if job.job_type == "store_message":
                return False
            return original(job)

        server.enqueue_db = reject_store_message  # type: ignore[method-assign]
        send_frame(alice, {"type": "chat", "room": "general", "body": "should evict"})
        error = read_until(alice, "error")
        assert error["code"] == "server_busy"
        deadline = time.monotonic() + 3.0
        while server.snapshot()["connected_clients"] > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.snapshot()["connected_clients"] == 0
