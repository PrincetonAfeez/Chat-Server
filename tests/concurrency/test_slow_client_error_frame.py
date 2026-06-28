""" Test slow client error frame """

from __future__ import annotations

from conftest import connect_raw, read_until, running_server, send_frame


def test_evict_slow_client_emits_slow_client_error_frame(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        session = next(item for item in server.sessions.values() if item.nick == "alice")
        server.evict_slow_client(session)
        error = read_until(alice, "error")
        assert error["code"] == "slow_client"
