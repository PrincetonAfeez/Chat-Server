"""Reusable raw TCP chat server package."""

from .config import ServerConfig
from .engines import ServerEngine, ThreadedEngine, create_engine
from .network.client import ChatClient
from .network.server import ChatServer
from .network.session import ConnectionState
from .protocol.errors import ErrorCode, ProtocolError

__all__ = [
    "ChatClient",
    "ChatServer",
    "ConnectionState",
    "ErrorCode",
    "ProtocolError",
    "ServerConfig",
    "ServerEngine",
    "ThreadedEngine",
    "create_engine",
]

__version__ = "0.1.0"
