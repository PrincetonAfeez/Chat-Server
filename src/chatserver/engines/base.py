""" Base engine for the chat server library """

from __future__ import annotations

from abc import ABC, abstractmethod

# How often the blocking serve loop re-checks the stop flag.
SERVE_POLL_INTERVAL = 0.5


class ServerEngine(ABC):
    """A runnable server engine behind one wire protocol.

    The CLI talks only to this interface, so a future selectors/asyncio engine
    can be dropped in without touching command code — the same protocol, client,
    persistence, cache, and admin layers are reused. ``threaded`` is the only
    implementation in this build.
    """

    @abstractmethod
    def start(self) -> None:
        """Bind, start workers, and begin accepting clients."""

    @abstractmethod
    def stop(self) -> None:
        """Stop accepting, notify clients, drain workers, release resources."""

    @abstractmethod
    def wait(self) -> None:
        """Block until the engine is asked to stop."""

    @property
    @abstractmethod
    def address(self) -> tuple[str, int]:
        """The bound (host, port) — meaningful only after start()."""

    @property
    @abstractmethod
    def admin_address(self) -> tuple[str, int] | None:
        """The bound admin (host, port), or None when admin is disabled."""
