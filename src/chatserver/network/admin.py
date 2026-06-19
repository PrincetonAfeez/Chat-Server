from __future__ import annotations

import contextlib
import socket
from threading import Event, Thread
from typing import TYPE_CHECKING, Any

from chatserver.observability.logging import get_logger, log_event
from chatserver.protocol.framing import FrameDecoder, decode_json_frame, encode_frame

if TYPE_CHECKING:
    from .server import ChatServer

ADMIN_COMMANDS = {"stats", "clients", "rooms", "queues", "cache", "evictions", "kick", "broadcast"}


class AdminServer:
    """Tiny localhost control socket so the CLI can drive a running server.

    One newline-delimited JSON request per connection, one JSON response back.
    Every command calls the public ChatServer API; no server behavior lives
    here. Bind to localhost only — there is no authentication.
    """

    def __init__(self, server: ChatServer, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self.server = server
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._thread: Thread | None = None
        self._stop = Event()
        self._logger = get_logger("chatserver.admin")
        self.bound_host = host
        self.bound_port = port

    @property
    def address(self) -> tuple[str, int]:
        return self.bound_host, self.bound_port

    def start(self) -> None:
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen()
        self._sock.settimeout(0.5)
        self.bound_host, self.bound_port = self._sock.getsockname()[:2]
        self._thread = Thread(target=self._accept_loop, name="chatserver-admin", daemon=False)
        self._thread.start()

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop.set()
        if self._sock:
            with contextlib.suppress(OSError):
                self._sock.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                self._handle(conn)
            except Exception as exc:  # noqa: BLE001 - one bad admin call must not kill the loop
                log_event(self._logger, "admin_error", error=str(exc))
            finally:
                with contextlib.suppress(OSError):
                    conn.close()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        decoder = FrameDecoder(65536)
        request: dict[str, Any] | None = None
        while request is None:
            try:
                data = conn.recv(65536)
            except TimeoutError:
                break
            if not data:
                break
            frames, _errors = decoder.feed(data)
            if frames:
                request = decode_json_frame(frames[0])
        if request is None:
            conn.sendall(encode_frame({"ok": False, "error": "no request frame received"}))
            return
        response = self._dispatch(request)
        conn.sendall(encode_frame(response))

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command")
        if command not in ADMIN_COMMANDS:
            return {"ok": False, "error": f"unknown admin command: {command!r}"}
        # kick/broadcast act on the server; only the diagnostic commands need a
        # (relatively expensive) snapshot, so compute it lazily.
        if command == "kick":
            nick = request.get("nick")
            if not isinstance(nick, str):
                return {"ok": False, "error": "kick requires a 'nick' string"}
            kicked = self.server.kick(nick)
            return {"ok": kicked, "result": {"nick": nick, "kicked": kicked}}
        if command == "broadcast":
            message = request.get("message")
            if not isinstance(message, str):
                return {"ok": False, "error": "broadcast requires a 'message' string"}
            self.server.broadcast_system(message)
            return {"ok": True, "result": {"broadcast": message}}
        snapshot = self.server.snapshot()
        if command == "stats":
            return {"ok": True, "result": snapshot}
        if command == "clients":
            return {"ok": True, "result": snapshot.get("clients", [])}
        if command == "rooms":
            return {"ok": True, "result": snapshot.get("rooms", {})}
        if command == "queues":
            return {
                "ok": True,
                "result": {
                    "outbound_queue_depths": snapshot.get("outbound_queue_depths", {}),
                    "db_writer_backlog": snapshot.get("db_writer_backlog", 0),
                    "db_jobs_enqueued": snapshot.get("db_jobs_enqueued", 0),
                    "db_jobs_dropped": snapshot.get("db_jobs_dropped", 0),
                },
            }
        if command == "cache":
            return {"ok": True, "result": snapshot.get("cache", {})}
        if command == "evictions":
            return {
                "ok": True,
                "result": {
                    "recent_evictions": snapshot.get("recent_evictions", []),
                    "evicted_clients": snapshot.get("evicted_clients", 0),
                    "slow_client_evictions": snapshot.get("slow_client_evictions", 0),
                    "idle_timeout_evictions": snapshot.get("idle_timeout_evictions", 0),
                    "rate_limit_rejections": snapshot.get("rate_limit_rejections", 0),
                },
            }
        return {"ok": False, "error": f"unhandled admin command: {command!r}"}
