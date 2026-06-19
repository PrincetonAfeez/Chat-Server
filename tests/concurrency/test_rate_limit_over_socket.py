from __future__ import annotations

from conftest import connect_raw, read_until, running_server, send_frame


def test_noisy_client_gets_rate_limited_over_the_socket(tmp_path) -> None:
    with running_server(tmp_path, rate_limit_messages=3, rate_limit_window=60.0) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "system")
        for i in range(15):
            send_frame(alice, {"type": "chat", "room": "general", "body": f"msg {i}"})
        error = read_until(alice, "error")
        assert error["code"] == "rate_limited"
        assert server.snapshot()["rate_limit_rejections"] >= 1
