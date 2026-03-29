"""CLI entry point for fin-assist.

Commands
--------
fin-assist serve          Start the agent hub server (host/port/db from config).
fin-assist agents         List available agents (Phase 8).
fin-assist ask <agent>    One-shot query to an agent (Phase 8).
fin-assist chat <agent>   Multi-turn session (Phase 8).
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from fin_assist.config.loader import load_config
from fin_assist.hub.app import create_hub_app


def main(argv: list[str] | None = None) -> None:
    config = load_config()

    parser = argparse.ArgumentParser(
        prog="fin-assist",
        description="Expandable personal AI agent platform for terminal workflows.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the agent hub server.")
    serve_parser.add_argument(
        "--host",
        default=None,
        help=f"Bind host (config default: {config.server.host}).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Bind port (config default: {config.server.port}).",
    )
    serve_parser.add_argument(
        "--db",
        default=None,
        help=f"SQLite storage path (config default: {config.server.db_path}).",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "serve":
        _cmd_serve(args, config)
        return

    parser.print_help()


def _cmd_serve(args, config) -> None:
    import os

    # CLI flags take precedence; fall back to config values
    host = args.host or config.server.host
    port = args.port or config.server.port
    db_path = os.path.expanduser(args.db or config.server.db_path)

    base_url = f"http://{host}:{port}"
    app = create_hub_app(db_path=db_path, base_url=base_url)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
