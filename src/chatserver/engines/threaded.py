from __future__ import annotations

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer

from .base import SERVE_POLL_INTERVAL, ServerEngine


class ThreadedEngine(ServerEngine):
    """Thread-per-connection engine (one reader + one writer thread per client)."""

    def __init__(self, config: ServerConfig) -> None:
        self.server = ChatServer(config)

    def start(self) -> None:
        self.server.start()

    def stop(self) -> None:
        self.server.stop()

    def wait(self) -> None:
        while not self.server.stopping.wait(SERVE_POLL_INTERVAL):
            continue

    @property
    def address(self) -> tuple[str, int]:
        return self.server.address

    @property
    def admin_address(self) -> tuple[str, int] | None:
        return self.server.admin_address
