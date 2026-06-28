""" Test config from file """

from __future__ import annotations

from pathlib import Path

import pytest

from chatserver.config import ServerConfig


def test_from_file_loads_server_section(tmp_path) -> None:
    config_path = Path(__file__).resolve().parents[2] / "examples" / "chatserver.toml"
    config = ServerConfig.from_file(config_path)
    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.engine == "threaded"
    assert config.handshake_timeout == 10.0
    assert config.event_retention_count == 10000


def test_rejects_invalid_port() -> None:
    with pytest.raises(ValueError, match="port must be between"):
        ServerConfig(port=70000)


def test_rejects_invalid_log_level() -> None:
    with pytest.raises(ValueError, match="log_level must be one of"):
        ServerConfig(log_level="VERBOSE")


def test_coerces_string_port(tmp_path) -> None:
    config = ServerConfig.from_mapping({"port": "9001"})
    assert config.port == 9001
