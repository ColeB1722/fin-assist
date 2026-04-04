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

from coolname import generate_slug  # pyright: ignore[reportPrivateImportUsage]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import uvicorn

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
from fin_assist.cli.server import ServerStartupError, ensure_server_running, stop_server
from fin_assist.config.loader import load_config
from fin_assist.hub.app import create_hub_app
from fin_assist.hub.logging import LOG_FILE, configure_logging

SESSIONS_DIR = Path("~/.local/share/fin/sessions").expanduser()


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
async def _hub_client(config) -> AsyncIterator[HubClient]:
    """Start the hub if needed, yield a connected client, close it on exit.

    Handles two error categories so commands don't have to:
    - ServerStartupError: hub failed to start — rendered and re-raised.
    - Any exception yielded from a hub call: rendered and re-raised.

    Commands catch the re-raised exceptions and return 1.
    """
    try:
        base_url = await ensure_server_running(config)
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


async def _do_command(args: argparse.Namespace, config) -> int:
    """Handle `fin-assist do <agent> <prompt>`."""
    try:
        async with _hub_client(config) as client:
            discovered, agents = await _get_agent_or_error(client, args.agent)
            if discovered is None:
                return 1

            fp = FinPrompt(agents=[a.name for a in agents])

            prompt = args.prompt
            while True:
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

                action, edited = await run_approve_widget(
                    command=result.output,
                    warnings=result.warnings,
                    supports_regenerate=discovered.card_meta.supports_regenerate,
                    regenerate_prompt=result.metadata.get("regenerate_prompt"),
                    prompt=fp,
                )

                if action == ApprovalAction.EXECUTE:
                    return execute_command(result.output)
                elif action == ApprovalAction.EDIT and edited:
                    prompt = edited
                    continue
                else:
                    render_info("Cancelled")
                    return 0
    except (ServerStartupError, Exception):
        return 1


async def _talk_command(args: argparse.Namespace, config) -> int:
    """Handle `fin-assist talk <agent>`."""
    if args.list_sessions:
        if not args.agent:
            render_error("Agent name required for --list")
            return 1
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
        if not args.agent:
            render_error("Agent name required for --resume")
            return 1
        session = _load_session(args.agent, args.resume)
        if session is None:
            render_error(f"Session {args.resume} not found")
            return 1
        context_id = session.get("context_id")
        render_info(f"Resuming session {args.resume}")

    if not args.agent:
        render_error("Agent name required for talk command")
        return 1

    try:
        async with _hub_client(config) as client:
            agents = await client.discover_agents()
            fp = FinPrompt(agents=[a.name for a in agents])
            final_context_id = await run_chat_loop(client.send_message, args.agent, context_id, fp)
    except (ServerStartupError, Exception):
        return 1

    if final_context_id and not args.resume:
        session_id = generate_slug(2)
        _save_session(args.agent, session_id, final_context_id)
        render_info(f"Session saved: {session_id}")

    return 0


async def _agents_command(args: argparse.Namespace, config) -> int:
    """Handle `fin-assist agents`."""
    try:
        async with _hub_client(config) as client:
            agents = await client.discover_agents()
    except (ServerStartupError, Exception):
        return 1

    render_agents_list(agents)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI client commands."""
    config = load_config()

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
    do_parser.add_argument("agent", help="Name of the agent to use.")
    do_parser.add_argument("prompt", help="The prompt to send.")

    talk_parser = subparsers.add_parser(
        "talk",
        help="Start a multi-turn chat session with an agent.",
    )
    talk_parser.add_argument("agent", nargs="?", help="Name of the agent to use.")
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

    subparsers.add_parser("stop", help="Stop the running agent hub server.")

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

    match args.command:
        case "agents":
            return asyncio.run(_agents_command(args, config))
        case "do":
            return asyncio.run(_do_command(args, config))
        case "talk":
            return asyncio.run(_talk_command(args, config))
        case "stop":
            if stop_server():
                render_info("Hub stopped.")
            else:
                render_error("No running hub found (no PID file or process already stopped).")
                return 1
            return 0
        case "serve":
            from fin_assist.agents import DefaultAgent, ShellAgent
            from fin_assist.credentials.store import CredentialStore

            host = args.host or config.server.host
            port = args.port or config.server.port
            db_path = os.path.expanduser(args.db or config.server.db_path)
            credentials = CredentialStore()
            # TODO: make agent list configurable via [agents.*] config
            # (see docs/architecture.md). Hardcoded until Phase 16 adds
            # optional agents that benefit from enable/disable.
            agents = [DefaultAgent(config, credentials), ShellAgent(config, credentials)]
            app = create_hub_app(agents=agents, db_path=db_path, base_url=f"http://{host}:{port}")
            configure_logging()
            console.print(f"[dim]Logging to {LOG_FILE}[/dim]")
            uvicorn.run(app, host=host, port=port, log_config=None)
            return 0
        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
