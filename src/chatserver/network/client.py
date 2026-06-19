from __future__ import annotations

import contextlib
import json
import socket
import sys
from collections.abc import Callable
from threading import Event, Thread
from typing import Any, TextIO

from chatserver.protocol.errors import ErrorCode, ProtocolError
from chatserver.protocol.framing import FrameDecoder, encode_frame
from chatserver.protocol.validation import validate_nick, validate_room

RECV_CHUNK = 65536
CONNECT_TIMEOUT = 5.0
SOCKET_POLL_TIMEOUT = 0.5

HELP_TEXT = """commands:
  /join <room>         join a room (becomes your current room)
  /leave <room>        leave a room
  /rooms               list active rooms
  /who [room]          list users in a room, or everyone
  /msg <user> <text>   send a direct message
  /history [room] [n]  show recent history
  /nick <name>         change your nickname
  /help                show this help
  /quit                disconnect
plain text (no leading /) is sent to your current room."""


class ChatClient:
    """CLI chat client: a reader thread prints incoming frames while the main
    thread reads stdin and sends typed lines / slash commands."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        nick: str,
        output: TextIO = sys.stdout,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        max_message_size: int = 4096,
    ) -> None:
        self.host = host
        self.port = port
        self.nick = validate_nick(nick)
        self.output = output
        self.on_message = on_message
        # The per-message cap governs what the client *sends*; the server may
        # send larger aggregate frames (e.g. a history bundle), so the inbound
        # decoder uses a generous buffer.
        self.decoder = FrameDecoder(max(max_message_size, 1 << 20))
        self.sock: socket.socket | None = None
        self.stop_event = Event()
        self.reader_thread: Thread | None = None
        # The room plain (non-slash) lines are sent to; set by /join.
        self.current_room: str | None = None

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
        self.sock.settimeout(SOCKET_POLL_TIMEOUT)
        self.reader_thread = Thread(target=self._reader_loop, name="chatclient-reader", daemon=False)
        self.reader_thread.start()
        self.send({"type": "hello", "nick": self.nick})

    def close(self) -> None:
        self.stop_event.set()
        if self.sock:
            with contextlib.suppress(OSError):
                self.sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                self.sock.close()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(2.0)

    def send(self, message: dict[str, Any]) -> None:
        if self.sock is None:
            raise RuntimeError("client is not connected")
        self.sock.sendall(encode_frame(message))

    def send_line(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return True
        if line.startswith("/"):
            return self._send_command(line)
        if self.current_room is None:
            print("join a room first: /join <room>", file=self.output)
            return True
        self.send({"type": "chat", "room": self.current_room, "body": line})
        return True

    def run_interactive(self) -> int:
        self.connect()
        print(f"connecting to {self.host}:{self.port} as {self.nick} — type /help", file=self.output)
        try:
            for line in sys.stdin:
                if self.stop_event.is_set():
                    break
                try:
                    if not self.send_line(line):
                        return 0
                except OSError:
                    print("** not connected to server **", file=self.output)
                    break
        except KeyboardInterrupt:
            return 130
        finally:
            self.close()
        return 0

    def _send_command(self, line: str) -> bool:
        parts = line.split(" ", 2)
        command = parts[0].lower()
        try:
            if command == "/quit":
                return False
            if command == "/help":
                print(HELP_TEXT, file=self.output)
                return True
            if command == "/nick" and len(parts) >= 2:
                self.nick = validate_nick(parts[1])
                self.send({"type": "hello", "nick": self.nick})
                return True
            if command == "/join" and len(parts) >= 2:
                room = validate_room(parts[1])
                self.send({"type": "join", "room": room})
                self.current_room = room
                return True
            if command == "/leave" and len(parts) >= 2:
                room = validate_room(parts[1])
                self.send({"type": "leave", "room": room})
                if self.current_room == room:
                    self.current_room = None
                return True
            if command == "/rooms":
                self.send({"type": "rooms"})
                return True
            if command == "/who":
                who_room = parts[1] if len(parts) >= 2 else None
                message: dict[str, Any] = {"type": "who"}
                if who_room:
                    message["room"] = validate_room(who_room)
                self.send(message)
                return True
            if command == "/msg" and len(parts) == 3:
                target, body = parts[1], parts[2]
                self.send({"type": "dm", "to": validate_nick(target), "body": body})
                return True
            if command == "/history":
                args = line.split()
                room = validate_room(args[1]) if len(args) >= 2 else "general"
                limit = int(args[2]) if len(args) >= 3 else 25
                self.send({"type": "history", "room": room, "limit": limit})
                return True
        except (ProtocolError, ValueError) as exc:
            print(f"client error: {exc}", file=self.output)
            return True
        print("unknown command — type /help", file=self.output)
        return True

    def _reader_loop(self) -> None:
        assert self.sock is not None
        while not self.stop_event.is_set():
            try:
                data = self.sock.recv(RECV_CHUNK)
            except TimeoutError:
                continue
            except OSError:
                break
            if not data:
                break
            frames, errors = self.decoder.feed(data)
            for error in errors:
                print(f"protocol error: {error}", file=self.output)
            for frame in frames:
                try:
                    message = json.loads(frame)
                except json.JSONDecodeError:
                    print(f"< malformed frame: {frame!r}", file=self.output)
                    continue
                if message.get("type") == "ping":
                    self.send({"type": "pong", "nonce": message.get("nonce", "")})
                    continue
                if self.on_message:
                    self.on_message(message)
                else:
                    print(format_message(message), file=self.output)
        # Reached only when the server closed the connection (not a local /quit).
        if not self.stop_event.is_set():
            self.stop_event.set()
            print("\n** disconnected from server — press Enter to exit **", file=self.output)


def format_message(message: dict[str, Any]) -> str:
    msg_type = message.get("type")
    if msg_type == "welcome":
        return f"* connected as {message.get('nick')}"
    if msg_type == "chat":
        return f"[{message.get('room')}] {message.get('sender')}: {message.get('body')}"
    if msg_type == "dm":
        return f"[dm] {message.get('sender')} -> {message.get('to')}: {message.get('body')}"
    if msg_type == "system":
        room = message.get("room")
        prefix = f"[{room}] " if room else ""
        return f"* {prefix}{message.get('body')}"
    if msg_type == "history":
        messages = message.get("messages", [])
        if not messages:
            return f"* no recent history for {message.get('room')}"
        lines = [f"* history for {message.get('room')}:"]
        for item in messages:
            sender = item.get("sender", "system")
            lines.append(f"  {sender}: {item.get('body')}")
        return "\n".join(lines)
    if msg_type == "who":
        users = ", ".join(message.get("users", []))
        room = message.get("room")
        return f"* users in {room}: {users}" if room else f"* users: {users}"
    if msg_type == "rooms":
        rooms = message.get("rooms", [])
        if not rooms:
            return "* no active rooms"
        return "* rooms: " + ", ".join(f"{room['room']}({room['members']})" for room in rooms)
    if msg_type == "error":
        code = message.get("code", ErrorCode.INVALID_MESSAGE.value)
        return f"! {code}: {message.get('message')}"
    return f"< {message}"
