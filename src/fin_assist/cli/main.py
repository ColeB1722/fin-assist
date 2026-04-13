"""CLI command dispatch for fin-assist client commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from coolname import generate_slug  # pyright: ignore[reportPrivateImportUsage]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fin_assist.cli.client import DiscoveredAgent, HubClient
from fin_assist.cli.display import (
    console,
    render_agents_list,
    render_auth_required,
    render_command,
    render_error,
    render_info,
    render_response,
    render_warnings,
)
from fin_assist.cli.interaction.approve import ApprovalAction, execute_command, run_approve_widget
from fin_assist.cli.interaction.chat import run_chat_loop
from fin_assist.cli.interaction.prompt import FinPrompt
from fin_assist.cli.server import (
    ServerStartupError,
    check_status,
    ensure_server_running,
    stop_server,
)
from fin_assist.config.loader import load_config
from fin_assist.hub.app import create_hub_app
from fin_assist.hub.logging import configure_logging
from fin_assist.paths import SESSIONS_DIR

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _get_session_path(agent: str, session_id: str) -> Path:
    return SESSIONS_DIR / agent / f"{session_id}.json"


def _load_session(agent: str, session_id: str) -> dict | None:
    path = _get_session_path(agent, session_id)
    if path.exists():
        return json.loads(path.read_text())
    return None


def _save_session(agent: str, session_id: str, context_id: str) -> None:
    path = _get_session_path(agent, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    session = {
        "session_id": session_id,
        "agent": agent,
        "context_id": context_id,
    }
    path.write_text(json.dumps(session, indent=2))


# ---------------------------------------------------------------------------
# Hub client context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _hub_client(config, config_path: Path | None = None) -> AsyncIterator[HubClient]:
    """Start the hub if needed, yield a connected client, close it on exit.

    Handles two error categories so commands don't have to:
    - ServerStartupError: hub failed to start — rendered and re-raised.
    - Any exception yielded from a hub call: rendered and re-raised.

    Commands catch the re-raised exceptions and return 1.
    """
    try:
        base_url = await ensure_server_running(config, config_path=config_path)
    except ServerStartupError as e:
        render_error(str(e))
        raise

    client = HubClient(base_url)
    try:
        yield client
    except Exception as e:
        render_error(f"Hub request failed: {e}")
        raise
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Agent lookup helper
# ---------------------------------------------------------------------------


async def _get_agent_or_error(
    client: HubClient, agent_name: str
) -> tuple[DiscoveredAgent | None, list[DiscoveredAgent]]:
    """Look up an agent by name. Returns (agent, all_agents). Agent is None if not found."""
    agents = await client.discover_agents()

    for agent in agents:
        if agent.name == agent_name:
            return agent, agents

    known = ", ".join(a.name for a in agents) or "none"
    render_error(f"Unknown agent '{agent_name}'. Available: {known}")
    return None, agents


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _serve_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist serve` — start the hub server in the foreground."""
    import errno
    import socket

    from fin_assist.agents.agent import ConfigAgent
    from fin_assist.credentials.store import CredentialStore
    from fin_assist.hub.pidfile import acquire as acquire_pidfile
    from fin_assist.paths import PID_FILE

    host = args.host or config.server.host
    port = args.port or config.server.port
    db_path = os.path.expanduser(args.db or config.server.db_path)
    log_path = Path(os.path.expanduser(config.server.log_path))

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(1)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            render_error(
                f"Port {port} is already in use. "
                f"Run [bold]fin stop[/bold] to stop the existing hub, "
                f"or use [bold]--port[/bold] to bind a different port."
            )
        elif exc.errno == errno.EACCES:
            render_error(
                f"Permission denied binding to port {port}. "
                f"Ports below 1024 require elevated privileges."
            )
        else:
            render_error(f"Could not bind to {host}:{port}: {exc}")
        return 1

    credentials = CredentialStore()
    configure_logging(log_file=log_path)

    pid_file = Path(args.pid_file) if args.pid_file else PID_FILE
    acquire_pidfile(pid_file)

    console.print(f"[dim]Logging to {log_path}[/dim]")
    agents = [
        ConfigAgent(name=name, agent_config=ac, config=config, credentials=credentials)
        for name, ac in config.agents.items()
        if ac.enabled
    ]
    app = create_hub_app(agents=agents, db_path=db_path, base_url=f"http://{host}:{port}")
    uvicorn_config = uvicorn.Config(app, host=host, port=port, log_config=None)
    server = uvicorn.Server(uvicorn_config)
    asyncio.run(server.serve(sockets=[sock]))
    return 0


async def _do_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist do <agent> <prompt>`."""
    try:
        async with _hub_client(config, config_path) as client:
            discovered, agents = await _get_agent_or_error(client, args.agent)
            if discovered is None:
                return 1

            if "do" not in discovered.card_meta.serving_modes:
                render_error(
                    f"Agent '{discovered.name}' does not support one-shot (do) mode. "
                    f"Available modes: {', '.join(discovered.card_meta.serving_modes)}"
                )
                return 1

            prompt = " ".join(args.prompt)
            result = await client.run_agent(args.agent, prompt)

            if result.metadata.get("auth_required"):
                render_auth_required(result.output)
                return 1

            if not discovered.card_meta.requires_approval:
                render_response(result.output, agent_name=discovered.name)
                if result.warnings:
                    render_warnings(result.warnings)
                return 0

            render_command(result.output, result.warnings, result.metadata)

            action = await run_approve_widget(
                command=result.output,
                warnings=result.warnings,
            )

            if action == ApprovalAction.EXECUTE:
                return execute_command(result.output)
            else:
                render_info("Cancelled")
                return 0
    except Exception:
        return 1


async def _talk_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist talk <agent>`."""
    if args.list_sessions:
        sessions_dir = SESSIONS_DIR / args.agent
        if sessions_dir.exists():
            for session_file in sessions_dir.glob("*.json"):
                session = json.loads(session_file.read_text())
                sid = session.get("session_id", "unknown")
                cid = session.get("context_id", "unknown")
                console.print(f"  {sid}  (context: {cid[:8]}...)")
        else:
            console.print(f"  No sessions for {args.agent}")
        return 0

    context_id: str | None = None
    if args.resume:
        session = _load_session(args.agent, args.resume)
        if session is None:
            render_error(f"Session {args.resume} not found")
            return 1
        context_id = session.get("context_id")
        render_info(f"Resuming session {args.resume}")

    try:
        async with _hub_client(config, config_path) as client:
            discovered, agents = await _get_agent_or_error(client, args.agent)
            if discovered is None:
                return 1

            if "talk" not in discovered.card_meta.serving_modes:
                render_error(
                    f"Agent '{discovered.name}' does not support multi-turn (talk) mode. "
                    f"Available modes: {', '.join(discovered.card_meta.serving_modes)}"
                )
                return 1

            fp = FinPrompt(agents=[a.name for a in agents])
            initial_message = " ".join(args.message) if args.message else None
            final_context_id = await run_chat_loop(
                client.send_message,
                args.agent,
                context_id,
                fp,
                initial_message=initial_message,
            )
    except Exception:
        return 1

    if final_context_id and not args.resume:
        session_id = generate_slug(2)
        _save_session(args.agent, session_id, final_context_id)
        render_info(f"Session saved: {session_id}")

    return 0


async def _agents_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist agents`."""
    try:
        async with _hub_client(config, config_path) as client:
            agents = await client.discover_agents()
    except Exception:
        return 1

    render_agents_list(agents)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI client commands."""
    config, config_path = load_config()

    parser = argparse.ArgumentParser(
        prog="fin-assist",
        description="Expandable personal AI agent platform for terminal workflows.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("agents", help="List available agents.")

    do_parser = subparsers.add_parser(
        "do",
        help="Run a one-shot query to an agent (no memory).",
    )
    do_parser.add_argument(
        "agent", nargs="?", default="default", help="Name of the agent to use (default: 'default')."
    )
    do_parser.add_argument("prompt", nargs="+", help="The prompt to send.")

    talk_parser = subparsers.add_parser(
        "talk",
        help="Start a multi-turn chat session with an agent.",
    )
    talk_parser.add_argument(
        "agent", nargs="?", default="default", help="Name of the agent to use (default: 'default')."
    )
    talk_parser.add_argument(
        "message",
        nargs="*",
        help="Optional initial message to send as the first turn.",
    )
    talk_parser.add_argument(
        "--list",
        dest="list_sessions",
        action="store_true",
        help="List saved sessions for the agent.",
    )
    talk_parser.add_argument(
        "--resume",
        dest="resume",
        metavar="SESSION_ID",
        help="Resume a saved session.",
    )

    subparsers.add_parser("start", help="Start the agent hub server in the background.")
    subparsers.add_parser("stop", help="Stop the running agent hub server.")
    subparsers.add_parser("status", help="Check if the agent hub server is running.")

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
    serve_parser.add_argument(
        "--pid-file",
        default=None,
        help="Path to PID file (written and locked by the server process).",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    match args.command:
        case "agents":
            return asyncio.run(_agents_command(args, config, config_path))
        case "do":
            return asyncio.run(_do_command(args, config, config_path))
        case "talk":
            return asyncio.run(_talk_command(args, config, config_path))
        case "start":
            try:
                base_url = asyncio.run(ensure_server_running(config, config_path))
                render_info(f"Hub running at {base_url}")
                return 0
            except ServerStartupError as e:
                render_error(str(e))
                return 1
        case "stop":
            if stop_server(port=config.server.port):
                render_info("Hub stopped.")
            else:
                render_error("No running hub found (no PID file or process already stopped).")
                return 1
            return 0
        case "status":
            status = asyncio.run(check_status(config))
            if status.healthy:
                pid_info = f", PID {status.pid}" if status.pid else ""
                note = ""
                if not status.pid_file_exists and status.pid:
                    note = " [yellow](PID file missing — orphaned server)[/yellow]"
                render_info(f"Hub running at {status.base_url}{pid_info}{note}")
            else:
                render_info("Hub is not running.")
            return 0
        case "serve":
            return _serve_command(args, config, config_path)
        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
