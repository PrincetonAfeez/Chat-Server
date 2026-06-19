from __future__ import annotations

import contextlib
import json
import socket
from collections import deque
from collections.abc import Callable
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from typing import Any

from chatserver.cache.history_cache import HistoryCache
from chatserver.config import ServerConfig
from chatserver.observability.events import (
    CACHE_EVICT,
    CACHE_WARMUP,
    CONNECT,
    DISCONNECT,
    DM_SENT,
    HANDSHAKE_REJECT,
    HANDSHAKE_SUCCESS,
    IDLE_TIMEOUT_EVICT,
    JOIN,
    KICK,
    LEAVE,
    MESSAGE_ACCEPTED,
    MESSAGE_ROUTED,
    RATE_LIMIT_REJECT,
    SERVER_SHUTDOWN,
    SERVER_START,
    SLOW_CLIENT_EVICT,
    STATS_REPORT,
)
from chatserver.observability.logging import get_logger, log_event
from chatserver.observability.stats import ServerStats
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.persistence.writer import DbWriter
from chatserver.protocol.errors import ErrorCode, ProtocolError, error_frame
from chatserver.protocol.framing import encode_frame
from chatserver.protocol.messages import (
    chat_frame,
    dm_frame,
    history_frame,
    new_message_id,
    ping_frame,
    room_system_message,
    rooms_frame,
    system_message,
    utc_timestamp,
    welcome_frame,
    who_frame,
)
from chatserver.protocol.validation import validate_client_message
from chatserver.queues.db_jobs import DbJob
from chatserver.queues.outbound import OutboundQueue
from chatserver.routing.rooms import RoomDirectory
from chatserver.scheduling.scheduler import PeriodicScheduler

from .admin import AdminServer
from .session import ClientSession, ConnectionState


class ChatServer:
    """Thread-per-connection chat server: accept loop, connection registry,
    rooms, routing, cache, the DB writer, the scheduler, and graceful shutdown.

    This is the library's core; the CLI, engines, and admin socket all drive it.
    An injectable ``clock`` keeps heartbeat/idle-timeout tests deterministic.
    """

    def __init__(
        self,
        config: ServerConfig | None = None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.config = config or ServerConfig()
        if self.config.engine != "threaded":
            raise NotImplementedError(f"engine {self.config.engine!r} is not implemented; only 'threaded' is available")
        self.clock = clock
        self.stats = ServerStats()
        self.store = SQLiteStore(self.config.db_path)
        self.db_writer = DbWriter(self.store, maxsize=self.config.db_queue_size, stats=self.stats)
        self.history_cache = HistoryCache(
            max_rooms=self.config.max_cached_rooms,
            messages_per_room=self.config.room_cache_messages,
            ttl_seconds=self.config.cache_ttl,
            clock=self.clock,
        )
        self.rooms = RoomDirectory()
        self.sessions: dict[str, ClientSession] = {}
        self.nicks: dict[str, ClientSession] = {}
        self.lock = RLock()
        self.stopping = Event()
        self.ready = Event()
        self._server_socket: socket.socket | None = None
        self._accept_thread: Thread | None = None
        tick = max(0.05, min(0.5, self.config.heartbeat_interval / 4))
        self.scheduler = PeriodicScheduler(clock=self.clock, tick_seconds=tick, on_tick=self._scheduler_tick)
        self.logger = get_logger("chatserver")
        self.bound_host = self.config.host
        self.bound_port = self.config.port
        self.recent_evictions: deque[dict[str, Any]] = deque(maxlen=50)
        self.admin: AdminServer | None = None
        if self.config.admin_enabled:
            self.admin = AdminServer(self, host=self.config.admin_host, port=self.config.admin_port)

    @property
    def address(self) -> tuple[str, int]:
        return self.bound_host, self.bound_port

    @property
    def admin_address(self) -> tuple[str, int] | None:
        return self.admin.address if self.admin else None

    def make_outbound_queue(self) -> OutboundQueue:
        return OutboundQueue(self.config.outbound_queue_size)

    def start(self) -> None:
        if self._accept_thread and self._accept_thread.is_alive():
            return
        self.stopping.clear()
        self.db_writer.start()
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.config.host, self.config.port))
        self._server_socket.listen()
        self._server_socket.settimeout(0.5)
        self.bound_host, self.bound_port = self._server_socket.getsockname()[:2]
        self.scheduler.add_job("heartbeat", self.config.heartbeat_interval, self.send_heartbeats)
        self.scheduler.add_job("idle-timeout", max(0.1, self.config.heartbeat_interval / 2), self.evict_idle_sessions)
        self.scheduler.add_job("cache-cleanup", max(1.0, self.config.cache_ttl / 4), self.cleanup_cache)
        self.scheduler.add_job("history-pruning", 60.0, self.prune_history)
        if self.config.stats_interval > 0:
            self.scheduler.add_job("stats-report", self.config.stats_interval, self.report_stats)
        self.scheduler.start()
        if self.admin:
            self.admin.start()
        self._accept_thread = Thread(target=self._accept_loop, name="chatserver-accept", daemon=False)
        self._accept_thread.start()
        self.ready.set()
        admin_addr = self.admin_address
        log_event(
            self.logger,
            SERVER_START,
            host=self.bound_host,
            port=self.bound_port,
            admin=f"{admin_addr[0]}:{admin_addr[1]}" if admin_addr else None,
        )

    def serve_forever(self) -> None:
        self.start()
        try:
            while not self.stopping.wait(0.5):
                continue
        finally:
            self.stop()

    def stop(self) -> None:
        if self.stopping.is_set():
            return
        self.stopping.set()
        log_event(self.logger, SERVER_SHUTDOWN)
        if self.admin:
            self.admin.stop()
        if self._server_socket:
            with contextlib.suppress(OSError):
                self._server_socket.close()
        with self.lock:
            sessions = list(self.sessions.values())
        shutdown_notice = system_message("server shutting down")
        for session in sessions:
            session.send_immediate(shutdown_notice)
        for session in sessions:
            session.close(ConnectionState.SERVER_SHUTDOWN)
        for session in sessions:
            session.join(self.config.shutdown_timeout)
        if self._accept_thread and self._accept_thread.is_alive() and self._accept_thread is not current_thread():
            self._accept_thread.join(self.config.shutdown_timeout)
        self.scheduler.stop()
        self.scheduler.join(self.config.shutdown_timeout)
        self.db_writer.stop(drain=True)
        self.db_writer.join(self.config.shutdown_timeout)
        with self.lock:
            self.sessions.clear()
            self.nicks.clear()
        self.stats.set_gauge("connected_clients", 0)
        self.stats.set_gauge("active_rooms", 0)

    def handle_frame(self, session: ClientSession, frame: str) -> None:
        """Validate one decoded frame, enforce handshake/rate limits, and dispatch it."""
        try:
            message = validate_client_message(frame, handshaken=session.state == ConnectionState.ACTIVE)
        except ProtocolError as exc:
            session.send_error(exc)
            self.stats.incr("rejected_messages")
            return

        if self.stopping.is_set():
            session.send_error(
                ProtocolError(ErrorCode.SERVER_SHUTTING_DOWN, "Server is shutting down", recoverable=False)
            )
            return

        msg_type = message["type"]
        if msg_type == "hello":
            if session.state == ConnectionState.ACTIVE:
                self.rename(session, message["nick"])
            else:
                self.handshake(session, message["nick"])
            return

        if msg_type == "pong":
            # Only credit a pong that answers our outstanding ping. General
            # liveness is already covered by last_seen (updated on any recv), so
            # an unsolicited/stale pong simply isn't counted here.
            if session.last_ping_nonce is not None and message["nonce"] == session.last_ping_nonce:
                session.last_pong_at = self.clock()
                session.last_ping_nonce = None
            return

        if not session.rate_limiter.allow():
            session.send_error(ProtocolError(ErrorCode.RATE_LIMITED, "Message rate limit exceeded"))
            self.stats.incr("rate_limit_rejections")
            self.stats.incr("rejected_messages")
            log_event(self.logger, RATE_LIMIT_REJECT, nick=session.nick, session_id=session.session_id)
            return

        if msg_type == "join":
            self.join_room(session, message["room"])
        elif msg_type == "leave":
            self.leave_room(session, message["room"])
        elif msg_type == "chat":
            self.chat(session, message["room"], message["body"])
        elif msg_type == "dm":
            self.direct_message(session, message["to"], message["body"])
        elif msg_type == "history":
            self.send_history(session, message["room"], message["limit"])
        elif msg_type == "who":
            self.send_who(session, message.get("room"))
        elif msg_type == "rooms":
            self.send_rooms(session)

    def handshake(self, session: ClientSession, nick: str) -> None:
        with self.lock:
            taken = nick in self.nicks
            if not taken:
                session.nick = nick
                session.state = ConnectionState.ACTIVE
                self.nicks[nick] = session
        # Reject I/O (send + close) happens OUTSIDE the lock so a slow socket can
        # never stall the global registry on a nick collision.
        if taken:
            session.state = ConnectionState.REJECTED
            session.send_immediate(error_frame(ErrorCode.NICK_TAKEN, "Nickname is already active", recoverable=False))
            log_event(self.logger, HANDSHAKE_REJECT, nick=nick, reason="nick_taken")
            session.close(ConnectionState.REJECTED)
            return
        self.enqueue_db(DbJob("upsert_user", {"nick": nick}))
        session.enqueue(welcome_frame(user_id=session.user_id, nick=nick))
        log_event(self.logger, HANDSHAKE_SUCCESS, nick=nick, session_id=session.session_id)

    def rename(self, session: ClientSession, new_nick: str) -> None:
        old_nick = session.nick
        if old_nick is None:
            session.send_error(ProtocolError(ErrorCode.UNAUTHORIZED, "Handshake required"))
            return
        with self.lock:
            if new_nick in self.nicks and self.nicks[new_nick] is not session:
                session.send_error(ProtocolError(ErrorCode.NICK_TAKEN, "Nickname is already active"))
                return
            self.nicks.pop(old_nick, None)
            self.nicks[new_nick] = session
            session.nick = new_nick
        self.enqueue_db(DbJob("upsert_user", {"nick": new_nick}))
        session.enqueue(welcome_frame(user_id=session.user_id, nick=new_nick))
        for room in list(session.rooms):
            notice = self._room_system(room, f"{old_nick} renamed to {new_nick}")
            self._persist_system_message(notice)
            self.history_cache.append(room, notice)
            self.broadcast_room(room, notice)

    def join_room(self, session: ClientSession, room: str) -> None:
        if not session.nick:
            session.send_error(ProtocolError(ErrorCode.UNAUTHORIZED, "Handshake required"))
            return
        with self.lock:
            self.rooms.join(room, session.session_id)
            session.rooms.add(room)
        self.stats.set_gauge("active_rooms", len(self.rooms.room_names()))
        self.enqueue_db(DbJob("create_room", {"room": room}))
        self.enqueue_db(DbJob("record_join", {"nick": session.nick, "room": room}, priority=3))
        log_event(self.logger, JOIN, nick=session.nick, room=room)
        self.send_history(session, room, self.config.history_limit)
        notice = self._room_system(room, f"{session.nick} joined {room}")
        self._persist_system_message(notice)
        self.history_cache.append(room, notice)
        self.broadcast_room(room, notice)

    def leave_room(self, session: ClientSession, room: str) -> None:
        with self.lock:
            in_room = room in session.rooms
            if in_room:
                session.rooms.discard(room)
                self.rooms.leave(room, session.session_id)
        if not in_room:
            session.send_error(ProtocolError(ErrorCode.ROOM_NOT_FOUND, "You are not in that room"))
            return
        self.stats.set_gauge("active_rooms", len(self.rooms.room_names()))
        if session.nick:
            self.enqueue_db(DbJob("record_leave", {"nick": session.nick, "room": room}, priority=3))
            notice = self._room_system(room, f"{session.nick} left {room}")
            self._persist_system_message(notice)
            self.history_cache.append(room, notice)
            self.broadcast_room(room, notice)
            log_event(self.logger, LEAVE, nick=session.nick, room=room)

    def chat(self, session: ClientSession, room: str, body: str) -> None:
        if room not in session.rooms:
            session.send_error(ProtocolError(ErrorCode.ROOM_NOT_FOUND, "Join the room before chatting"))
            self.stats.incr("rejected_messages")
            return
        assert session.nick is not None
        message = chat_frame(
            message_id=new_message_id(),
            room=room,
            sender=session.nick,
            body=body,
            session_id=session.session_id,
        )
        if not self.enqueue_db(DbJob("store_message", {"message": message})):
            self._reject_for_db_backlog(session)
            return
        self.history_cache.append(room, message)
        self.stats.mark_message()
        log_event(self.logger, MESSAGE_ACCEPTED, message_id=message["message_id"], room=room, sender=session.nick)
        self.broadcast_room(room, message)
        log_event(self.logger, MESSAGE_ROUTED, message_id=message["message_id"], room=room)

    def direct_message(self, session: ClientSession, target_nick: str, body: str) -> None:
        assert session.nick is not None
        with self.lock:
            target = self.nicks.get(target_nick)
        if target is None:
            session.send_error(ProtocolError(ErrorCode.USER_NOT_FOUND, "User is not connected"))
            self.stats.incr("rejected_messages")
            return
        message = dm_frame(
            message_id=new_message_id(),
            sender=session.nick,
            to=target_nick,
            body=body,
            session_id=session.session_id,
        )
        # DMs are best-effort live delivery only — they are not persisted (room
        # history is the durable record). A structured dm_sent log is the audit
        # trail, without storing private message bodies in the DB.
        self.stats.mark_message()
        session.enqueue(message)
        if target is not session:
            target.enqueue(message)
        log_event(self.logger, DM_SENT, message_id=message["message_id"], sender=session.nick, recipient=target_nick)

    def send_history(self, session: ClientSession, room: str, limit: int) -> None:
        # Warm the cache with a full window regardless of this request's limit,
        # so a small /history N never under-fills the cache for later readers.
        cached = self.history_cache.get(room)
        if cached is None:
            warm_count = max(limit, self.config.room_cache_messages)
            cached = self.store.recent_room_messages(room, warm_count)
            self.history_cache.warm(room, cached)
            self.stats.incr("cache_misses")
            self.stats.incr("cache_warmups")
            log_event(self.logger, CACHE_WARMUP, room=room, count=len(cached))
        else:
            self.stats.incr("cache_hits")
        session.enqueue(history_frame(room=room, messages=cached[-limit:]))

    def send_who(self, session: ClientSession, room: str | None) -> None:
        if room:
            member_ids = self.rooms.snapshot_members(room)
            with self.lock:
                users = sorted(s.nick for sid, s in self.sessions.items() if sid in member_ids and s.nick is not None)
            session.enqueue(who_frame(users=users, room=room))
            return
        with self.lock:
            users = sorted(self.nicks)
        session.enqueue(who_frame(users=users))

    def send_rooms(self, session: ClientSession) -> None:
        counts = self.rooms.counts()
        rooms = [{"room": room, "members": count} for room, count in counts.items()]
        session.enqueue(rooms_frame(rooms=rooms))

    def broadcast_room(self, room: str, message: dict[str, Any]) -> None:
        """Enqueue a message to every current room member (snapshot under lock, then enqueue)."""
        member_ids = self.rooms.snapshot_members(room)
        with self.lock:
            sessions = [self.sessions[sid] for sid in member_ids if sid in self.sessions]
        for target in sessions:
            target.enqueue(message)

    def broadcast_system(self, body: str) -> None:
        message = system_message(body)
        with self.lock:
            # Only handshaken clients; a HANDSHAKING session has not received
            # welcome yet and must not see traffic before it.
            sessions = [s for s in self.sessions.values() if s.state == ConnectionState.ACTIVE]
        for session in sessions:
            session.enqueue(message)

    def send_heartbeats(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
        now = self.clock()
        for session in sessions:
            if session.state == ConnectionState.ACTIVE and not session.close_event.is_set():
                nonce = f"p_{int(now * 1000)}_{session.session_id}"
                session.last_ping_at = now
                session.last_ping_nonce = nonce
                session.enqueue(ping_frame(nonce=nonce))

    def evict_idle_sessions(self) -> None:
        now = self.clock()
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            if session.state != ConnectionState.ACTIVE:
                continue
            idle_for = now - max(session.last_seen, session.last_pong_at)
            if idle_for >= self.config.idle_timeout:
                self.stats.incr("idle_timeout_evictions")
                self.stats.incr("evicted_clients")
                self._note_eviction(session, ConnectionState.IDLE_TIMED_OUT.value)
                log_event(self.logger, IDLE_TIMEOUT_EVICT, nick=session.nick, session_id=session.session_id)
                session.close(ConnectionState.IDLE_TIMED_OUT)

    def evict_slow_client(self, session: ClientSession) -> None:
        if session.close_event.is_set():
            return
        self.stats.incr("slow_client_evictions")
        self.stats.incr("evicted_clients")
        self._note_eviction(session, ConnectionState.SLOW_CLIENT_EVICTED.value)
        self.enqueue_db(
            DbJob(
                "record_eviction",
                {"nick": session.nick, "reason": ConnectionState.SLOW_CLIENT_EVICTED.value},
                priority=2,
            )
        )
        log_event(self.logger, SLOW_CLIENT_EVICT, nick=session.nick, session_id=session.session_id)
        session.close(ConnectionState.SLOW_CLIENT_EVICTED)

    def kick(self, nick: str) -> bool:
        """Admin action: forcibly disconnect a connected user by nickname."""
        with self.lock:
            target = self.nicks.get(nick)
        if target is None:
            return False
        self.stats.incr("evicted_clients")
        self._note_eviction(target, ConnectionState.KICKED.value)
        self.enqueue_db(DbJob("record_eviction", {"nick": nick, "reason": ConnectionState.KICKED.value}, priority=2))
        log_event(self.logger, KICK, nick=nick, session_id=target.session_id)
        target.send_immediate(error_frame(ErrorCode.UNAUTHORIZED, "Kicked by admin", recoverable=False))
        target.close(ConnectionState.KICKED)
        return True

    def _note_eviction(self, session: ClientSession, reason: str) -> None:
        self.recent_evictions.append(
            {
                "nick": session.nick,
                "session_id": session.session_id,
                "reason": reason,
                "at": utc_timestamp(),
            }
        )

    def _reject_for_db_backlog(self, session: ClientSession) -> None:
        self.stats.incr("rejected_messages")
        if self.config.db_backpressure_policy == "disconnect":
            session.send_immediate(error_frame(ErrorCode.SERVER_BUSY, "DB writer backlog is full", recoverable=False))
            self._note_eviction(session, ConnectionState.DB_BACKLOG.value)
            self.stats.incr("evicted_clients")
            self.enqueue_db(
                DbJob(
                    "record_eviction",
                    {"nick": session.nick, "reason": ConnectionState.DB_BACKLOG.value},
                    priority=2,
                )
            )
            session.close(ConnectionState.DB_BACKLOG)
        else:
            session.send_error(ProtocolError(ErrorCode.SERVER_BUSY, "DB writer backlog is full"))

    def unregister_session(self, session: ClientSession, *, reason: str) -> None:
        left_rooms: list[str]
        nick = session.nick
        with self.lock:
            if session.session_id not in self.sessions:
                return
            self.sessions.pop(session.session_id, None)
            if nick and self.nicks.get(nick) is session:
                self.nicks.pop(nick, None)
            left_rooms = self.rooms.remove_from_all(session.session_id)
            session.rooms.clear()
            self.stats.set_gauge("connected_clients", len(self.sessions))
            self.stats.set_gauge("active_rooms", len(self.rooms.room_names()))
        if nick:
            self.enqueue_db(DbJob("record_disconnect", {"nick": nick, "reason": reason}, priority=2))
            for room in left_rooms:
                notice = self._room_system(room, f"{nick} left {room}")
                self._persist_system_message(notice)
                self.history_cache.append(room, notice)
                self.broadcast_room(room, notice)
        log_event(self.logger, DISCONNECT, nick=nick, reason=reason, session_id=session.session_id)

    def cleanup_cache(self) -> None:
        evicted = self.history_cache.cleanup_expired()
        if evicted:
            self.stats.incr("cache_evictions", evicted)
            log_event(self.logger, CACHE_EVICT, count=evicted)

    def prune_history(self) -> None:
        # One job prunes every room known to the DB (including rooms that have
        # since gone idle), not just the rooms with live members right now.
        self.enqueue_db(
            DbJob(
                "prune_history",
                {"keep_count": self.config.history_retention_count},
                priority=1,
            )
        )

    def report_stats(self) -> None:
        snapshot = self.stats.snapshot(
            {
                "rooms": self.rooms.counts(),
                "db_writer_backlog": self.db_writer.backlog(),
                "cache": self.history_cache.snapshot(),
            }
        )
        log_event(self.logger, STATS_REPORT, **snapshot)

    def snapshot(self) -> dict[str, Any]:
        """Full diagnostics snapshot: stats, rooms, clients, queue depths, DB backlog, cache."""
        with self.lock:
            clients = [session.snapshot() for session in self.sessions.values()]
        cache_stats = self.history_cache.snapshot()
        extra = {
            "host": self.bound_host,
            "port": self.bound_port,
            "rooms": self.rooms.counts(),
            "clients": clients,
            "outbound_queue_depths": {
                client["nick"] or client["session_id"]: client["queue_depth"] for client in clients
            },
            "db_writer_backlog": self.db_writer.backlog(),
            "db_failures": list(self.db_writer.failures)[-10:],
            "recent_evictions": list(self.recent_evictions),
            "cache": cache_stats,
        }
        return self.stats.snapshot(extra)

    def enqueue_db(self, job: DbJob) -> bool:
        return self.db_writer.enqueue(job)

    def _accept_loop(self) -> None:
        assert self._server_socket is not None
        while not self.stopping.is_set():
            try:
                client_sock, address = self._server_socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with self.lock:
                full = len(self.sessions) >= self.config.max_connections
                if not full:
                    session = ClientSession(client_sock, address, self)
                    self.sessions[session.session_id] = session
                    self.stats.set_gauge("connected_clients", len(self.sessions))
            # Do the reject I/O (a blocking send) OUTSIDE the lock so a slow
            # client at capacity can never stall the whole server.
            if full:
                self._reject_connection(client_sock, ErrorCode.SERVER_FULL, "Server connection limit reached")
                continue
            log_event(self.logger, CONNECT, session_id=session.session_id, address=f"{address[0]}:{address[1]}")
            session.start()

    def _reject_connection(self, client_sock: socket.socket, code: ErrorCode, message: str) -> None:
        try:
            client_sock.settimeout(1.0)
            client_sock.sendall(encode_frame(error_frame(code, message, recoverable=False)))
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                client_sock.close()

    def _scheduler_tick(self) -> None:
        self.stats.incr("scheduler_ticks")

    def _room_system(self, room: str, body: str) -> dict[str, Any]:
        return room_system_message(room=room, body=body, message_id=new_message_id())

    def _persist_system_message(self, message: dict[str, Any]) -> None:
        self.enqueue_db(DbJob("store_message", {"message": message}, priority=2))
        self.enqueue_db(
            DbJob(
                "store_system_event",
                {
                    "event_type": "system",
                    "room": message.get("room"),
                    "details": {"body": message.get("body"), "message_id": message.get("message_id")},
                },
                priority=1,
            )
        )

    def pretty_snapshot(self) -> str:
        return json.dumps(self.snapshot(), indent=2, sort_keys=True, default=str)
