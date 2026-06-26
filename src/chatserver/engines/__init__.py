""" Engines module for the chat server library """

from chatserver.config import ServerConfig

from .base import ServerEngine
from .threaded import ThreadedEngine

__all__ = ["ServerEngine", "ThreadedEngine", "create_engine"]


def create_engine(config: ServerConfig) -> ServerEngine:
    """Build the engine named by ``config.engine`` (only 'threaded' is implemented)."""
    if config.engine == "threaded":
        return ThreadedEngine(config)
    raise NotImplementedError(f"engine {config.engine!r} is not implemented; only 'threaded' is available")
