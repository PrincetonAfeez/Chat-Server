"""`chatserver serve` — build config from flags and run the engine."""

from __future__ import annotations

import argparse
import sys

from chatserver.config import (
    DB_BACKPRESSURE_POLICIES,
    OUTBOUND_BACKPRESSURE_POLICIES,
    ServerConfig,
)
from chatserver.engines import create_engine
from chatserver.network.shutdown import install_signal_handlers


def add_serve_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    serve = sub.add_parser("serve", help="run the threaded TCP server")
    serve.add_argument("--config")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--db", dest="db_path")
    serve.add_argument("--engine")
    serve.add_argument("--max-connections", type=int)
    serve.add_argument("--max-message-size", type=int)
    serve.add_argument("--outbound-queue-size", type=int)
    serve.add_argument("--outbound-backpressure-policy", choices=sorted(OUTBOUND_BACKPRESSURE_POLICIES))
    serve.add_argument("--db-queue-size", type=int)
    serve.add_argument("--db-backpressure-policy", choices=sorted(DB_BACKPRESSURE_POLICIES))
    serve.add_argument("--heartbeat-interval", type=float)
    serve.add_argument("--idle-timeout", type=float)
    serve.add_argument("--history-limit", type=int)
    serve.add_argument("--history-retention-count", type=int)
    serve.add_argument("--room-cache-messages", type=int)
    serve.add_argument("--max-cached-rooms", type=int)
    serve.add_argument("--cache-ttl", type=float)
    serve.add_argument("--rate-limit-messages", type=int)
    serve.add_argument("--rate-limit-window", type=float)
    serve.add_argument("--stats-interval", type=float)
    serve.add_argument("--shutdown-timeout", type=float)
    serve.add_argument("--admin-host")
    serve.add_argument("--admin-port", type=int, help="enable the localhost admin control socket on this port")
    serve.add_argument("--log-level")


def _config_from_args(args: argparse.Namespace) -> ServerConfig:
    config = ServerConfig.from_file(args.config) if args.config else ServerConfig()
    overrides = {
        "host": args.host,
        "port": args.port,
        "db_path": args.db_path,
        "engine": args.engine,
        "max_connections": args.max_connections,
        "max_message_size": args.max_message_size,
        "outbound_queue_size": args.outbound_queue_size,
        "outbound_backpressure_policy": args.outbound_backpressure_policy,
        "db_queue_size": args.db_queue_size,
        "db_backpressure_policy": args.db_backpressure_policy,
        "heartbeat_interval": args.heartbeat_interval,
        "idle_timeout": args.idle_timeout,
        "history_limit": args.history_limit,
        "history_retention_count": args.history_retention_count,
        "room_cache_messages": args.room_cache_messages,
        "max_cached_rooms": args.max_cached_rooms,
        "cache_ttl": args.cache_ttl,
        "rate_limit_messages": args.rate_limit_messages,
        "rate_limit_window": args.rate_limit_window,
        "stats_interval": args.stats_interval,
        "shutdown_timeout": args.shutdown_timeout,
        "admin_host": args.admin_host,
        "log_level": args.log_level,
    }
    if args.admin_port is not None:
        overrides["admin_enabled"] = True
        overrides["admin_port"] = args.admin_port
    return config.merged(overrides)


def serve(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args)
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if config.engine != "threaded":
        print("only the threaded engine is implemented in this build", file=sys.stderr)
        return 2

    print("warning: localhost binding is intended for learning; public exposure needs auth and TLS")
    engine = create_engine(config)
    install_signal_handlers(engine.stop)
    try:
        engine.start()
    except OSError as exc:
        print(f"failed to bind {config.host}:{config.port}: {exc}", file=sys.stderr)
        engine.stop()
        return 1
    try:
        # Report the *bound* addresses, which differ from config when port 0 was
        # requested (the OS assigns an ephemeral port).
        host, port = engine.address
        print(f"serving on {host}:{port} using {config.engine}")
        admin_addr = engine.admin_address
        if admin_addr:
            print(f"admin control socket on {admin_addr[0]}:{admin_addr[1]}")
        engine.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        engine.stop()
    return 0
