from __future__ import annotations

from collections import defaultdict
from threading import RLock


class RoomDirectory:
    def __init__(self) -> None:
        self._lock = RLock()
        self._members: dict[str, set[str]] = defaultdict(set)

    def join(self, room: str, session_id: str) -> None:
        with self._lock:
            self._members[room].add(session_id)

    def leave(self, room: str, session_id: str) -> bool:
        with self._lock:
            members = self._members.get(room)
            if not members or session_id not in members:
                return False
            members.remove(session_id)
            if not members:
                self._members.pop(room, None)
            return True

    def remove_from_all(self, session_id: str) -> list[str]:
        left: list[str] = []
        with self._lock:
            for room in list(self._members):
                members = self._members[room]
                if session_id in members:
                    members.remove(session_id)
                    left.append(room)
                if not members:
                    self._members.pop(room, None)
        return left

    def snapshot_members(self, room: str) -> set[str]:
        with self._lock:
            return set(self._members.get(room, set()))

    def room_names(self) -> list[str]:
        with self._lock:
            return sorted(self._members)

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {room: len(members) for room, members in sorted(self._members.items())}
