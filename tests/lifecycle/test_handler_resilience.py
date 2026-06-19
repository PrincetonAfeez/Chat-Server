from __future__ import annotations

from conftest import connect_raw, read_until, running_server, send_frame


def test_handler_exception_does_not_drop_connection(tmp_path, monkeypatch) -> None:
    with running_server(tmp_path) as server:

        def boom(_session: object) -> None:
            raise RuntimeError("intentional handler failure")

        monkeypatch.setattr(server, "send_rooms", boom)
        alice = connect_raw(server, "alice")

        send_frame(alice, {"type": "rooms"})
        error = read_until(alice, "error")
        assert error["code"] == "invalid_message"

        # The handler blew up, but the connection survived and still works.
        send_frame(alice, {"type": "who"})
        who = read_until(alice, "who")
        assert "alice" in who["users"]


def test_deeply_nested_json_does_not_crash_the_connection(tmp_path) -> None:
    with running_server(tmp_path, max_message_size=200_000) as server:
        alice = connect_raw(server, "alice")
        # A JSON bomb (thousands of nested arrays) raises RecursionError deep in
        # the parser; it must come back as a structured error, not a dropped
        # reader thread.
        bomb = ("[" * 6000 + "]" * 6000).encode("utf-8")
        alice.sendall(bomb + b"\n")
        error = read_until(alice, "error")
        assert error["code"] in {"invalid_message", "bad_json"}

        send_frame(alice, {"type": "who"})
        assert "alice" in read_until(alice, "who")["users"]
