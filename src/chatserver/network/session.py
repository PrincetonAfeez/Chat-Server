from __future__ import annotations

import contextlib
import socket
from enum import StrEnum
from queue import Empty
from threading import Event, RLock, Thread, current_thread
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from chatserver.protocol.errors import ProtocolError, error_frame
from chatserver.protocol.framing import FrameDecoder, encode_frame
from chatserver.security.rate_limit import RateLimiter

if TYPE_CHECKING:
    from .server import ChatServer

# Bytes requested per recv(); TCP may return fewer (partial) or several frames'
# worth (merged) — the FrameDecoder handles both.
RECV_CHUNK = 65536
# Socket read/write timeout so loops can poll the close flag instead of blocking
# forever.
SOCKET_POLL_TIMEOUT = 0.5
# How long the writer waits for a queued message before re-checking close state.
OUTBOUND_POLL_TIMEOUT = 0.1


class ConnectionState(StrEnum):
    CONNECTED = "CONNECTED"
    HANDSHAKING = "HANDSHAKING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    IDLE_TIMED_OUT = "IDLE_TIMED_OUT"
    RATE_LIMITED = "RATE_LIMITED"
    SLOW_CLIENT_EVICTED = "SLOW_CLIENT_EVICTED"
    DB_BACKLOG = "DB_BACKLOG"
    KICKED = "KICKED"
    SOCKET_CLOSED = "SOCKET_CLOSED"
    SERVER_SHUTDOWN = "SERVER_SHUTDOWN"


class ClientSession:
    """One connected client: its socket, outbound queue, lifecycle, and threads.

    Each session owns a reader thread (recv -> decode -> dispatch) and a writer
    thread (drain outbound queue -> sendall), plus a rate limiter and the locks
    that keep its socket writes and close path race-free.
    """

    def __init__(self, sock: socket.socket, address: tuple[str, int], server: ChatServer) -> None:
        self.sock = sock
        self.address = address
        self.server = server
        self.session_id = f"s_{uuid4().hex[:12]}"
        self.user_id = f"u_{uuid4().hex[:12]}"
        self.nick: str | None = None
        self.state = ConnectionState.CONNECTED
        self.decoder = FrameDecoder(self.server.config.max_message_size)
        self.outbound = self.server.make_outbound_queue()
        self.close_event = Event()
        self.lock = RLock()
        # Serializes every sock.sendall so the writer thread and any
        # send_immediate caller (shutdown notice, fatal framing error) can never
        # interleave bytes on the wire and corrupt the JSON Lines stream.
        self.send_lock = RLock()
        self.rooms: set[str] = set()
        self.created_at = self.server.clock()
        self.last_seen = self.created_at
        self.last_pong_at = self.created_at
        self.last_ping_at = 0.0
        self.last_ping_nonce: str | None = None
        self.rate_limiter = RateLimiter(
            self.server.config.rate_limit_messages,
            self.server.config.rate_limit_window,
            clock=self.server.clock,
        )
        self.reader_thread = Thread(
            target=self._reader_loop,
            name=f"chatserver-reader-{self.session_id}",
            daemon=False,
        )
        self.writer_thread = Thread(
            target=self._writer_loop,
            name=f"chatserver-writer-{self.session_id}",
            daemon=False,
        )

    def start(self) -> None:
        self.state = ConnectionState.HANDSHAKING
        self.sock.settimeout(SOCKET_POLL_TIMEOUT)
        self.reader_thread.start()
        self.writer_thread.start()

    def enqueue(self, message: dict[str, Any]) -> bool:
        if self.close_event.is_set():
            return False
        if self.outbound.put_nowait(message):
            return True
        # Outbound queue is full: apply the configured backpressure policy so a
        # slow client never stalls delivery to everyone else.
        policy = self.server.config.outbound_backpressure_policy
        if policy == "drop_oldest":
            accepted = self.outbound.put_drop_oldest(message)
            self.server.stats.incr("dropped_messages")
            return accepted
        if policy == "drop_newest":
            self.server.stats.incr("dropped_messages")
            return False
        # default "disconnect": evict the slow client entirely.
        self.server.evict_slow_client(self)
        return False

    def send_error(self, error: ProtocolError) -> None:
        self.enqueue(error_frame(error.code, error.message, recoverable=error.recoverable, details=error.details))

    def send_immediate(self, message: dict[str, Any]) -> None:
        try:
            with self.send_lock:
                self.sock.sendall(encode_frame(message))
        except OSError:
            pass

    def close(self, reason: ConnectionState | str = ConnectionState.SOCKET_CLOSED) -> None:
        with self.lock:
            if self.close_event.is_set():
                return
            if isinstance(reason, ConnectionState):
                self.state = reason
            else:
                try:
                    self.state = ConnectionState(reason)
                except ValueError:
                    self.state = ConnectionState.CLOSING
            self.close_event.set()
            with contextlib.suppress(OSError):
                self.sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                self.sock.close()
        self.server.unregister_session(self, reason=str(reason))

    def join(self, timeout: float | None = None) -> None:
        current = current_thread()
        if self.reader_thread.is_alive() and self.reader_thread is not current:
            self.reader_thread.join(timeout)
        if self.writer_thread.is_alive() and self.writer_thread is not current:
            self.writer_thread.join(timeout)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "nick": self.nick,
            "state": str(self.state),
            "rooms": sorted(self.rooms),
            "queue_depth": self.outbound.qsize(),
            "last_seen": self.last_seen,
            "last_pong_at": self.last_pong_at,
            "address": f"{self.address[0]}:{self.address[1]}",
        }

    def _reader_loop(self) -> None:
        close_reason: ConnectionState | str = ConnectionState.SOCKET_CLOSED
        try:
            while not self.close_event.is_set() and not self.server.stopping.is_set():
                try:
                    data = self.sock.recv(RECV_CHUNK)
                except TimeoutError:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self.last_seen = self.server.clock()
                frames, errors = self.decoder.feed(data)
                for error in errors:
                    if not error.recoverable:
                        self.send_immediate(
                            error_frame(
                                error.code,
                                error.message,
                                recoverable=error.recoverable,
                                details=error.details,
                            )
                        )
                        close_reason = error.code.value
                        return
                    self.send_error(error)
                for frame in frames:
                    self.server.handle_frame(self, frame)
        finally:
            self.close(close_reason)

    def _writer_loop(self) -> None:
        try:
            while not self.close_event.is_set() or not self.outbound.empty():
                try:
                    message = self.outbound.get(timeout=OUTBOUND_POLL_TIMEOUT)
                except Empty:
                    if self.close_event.is_set():
                        break
                    continue
                try:
                    with self.send_lock:
                        self.sock.sendall(encode_frame(message))
                except TimeoutError:
                    self.server.evict_slow_client(self)
                    break
                except OSError:
                    break
        finally:
            if not self.close_event.is_set():
                self.close(ConnectionState.SOCKET_CLOSED)
