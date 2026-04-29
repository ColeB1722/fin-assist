"""CLI command dispatch for fin-assist client commands.

Heavy imports (``uvicorn``, ``coolname``, ``fin_assist.hub.app``,
``fin_assist.cli.interaction.*``, ``fin_assist.cli.client``) are
deferred into the command functions that need them so ``fin --help``
and similar lightweight invocations stay fast.  The ``pydantic_ai``
dependency chain alone costs ~1s at import time; pulling it in only
when a command actually talks to an agent hub keeps cold-start snappy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fin_assist.cli.client import DiscoveredAgent, HubClient

from fin_assist.cli.display import (
    console,
    render_agents_list,
    render_error,
    render_info,
    render_session_list,
)
from fin_assist.cli.server import (
    ServerStartupError,
    check_status,
    ensure_server_running,
    stop_server,
)
from fin_assist.config.loader import load_config
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
    from fin_assist.cli.client import HubClient  # deferred: pulls a2a-sdk (~0.5s)

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


def _resolve_workflow(
    agent_name: str,
    workflow_name: str | None,
    prompt: str,
    config,
) -> tuple[str, str | None]:
    """Resolve a workflow for an agent and return (effective_prompt, system_prompt_override).

    If ``workflow_name`` is given explicitly, look it up in the agent's config.
    If no workflow is given but ``prompt`` matches a workflow name, use that
    workflow's ``entry_prompt`` as the effective prompt.

    Returns (effective_prompt, system_prompt_override).  If no workflow matches,
    returns (prompt, None) — i.e. the prompt is used as-is with the default
    system prompt.
    """
    agent_cfg = config.agents.get(agent_name)
    if agent_cfg is None or not agent_cfg.workflows:
        return prompt, None

    target = workflow_name
    if target is None and prompt in agent_cfg.workflows:
        target = prompt

    if target is None or target not in agent_cfg.workflows:
        return prompt, None

    wf = agent_cfg.workflows[target]
    effective_prompt = wf.entry_prompt or prompt
    system_prompt_override = wf.prompt_template or None
    return effective_prompt, system_prompt_override


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _serve_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist serve` — start the hub server in the foreground."""
    import errno
    import socket

    import uvicorn

    from fin_assist.agents.spec import AgentSpec
    from fin_assist.credentials.store import CredentialStore
    from fin_assist.hub.app import create_hub_app
    from fin_assist.hub.logging import configure_logging
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

    from fin_assist.hub.tracing import setup_tracing

    setup_tracing(config.tracing)

    if config.tracing.enabled:
        from pydantic_ai import Agent

        Agent.instrument_all()

    pid_file = Path(args.pid_file) if args.pid_file else PID_FILE
    acquire_pidfile(pid_file)

    console.print(f"[dim]Logging to {log_path}[/dim]")
    agents = [
        AgentSpec(name=name, agent_config=ac, config=config, credentials=credentials)
        for name, ac in config.agents.items()
        if ac.enabled
    ]
    app = create_hub_app(
        agents=agents,
        db_path=db_path,
        base_url=f"http://{host}:{port}",
        context_settings=config.context,
    )

    if config.tracing.enabled:
        try:
            from opentelemetry.instrumentation.fastapi import (
                FastAPIInstrumentor,  # type: ignore[import-untyped]
            )

            FastAPIInstrumentor.instrument_app(app)
        except ImportError:
            pass

    uvicorn_config = uvicorn.Config(app, host=host, port=port, log_config=None)
    server = uvicorn.Server(uvicorn_config)
    asyncio.run(server.serve(sockets=[sock]))
    return 0


async def _do_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist do <agent> <prompt>`."""
    from fin_assist.cli.interaction.prompt import FinPrompt, resolve_at_references
    from fin_assist.cli.interaction.response import handle_post_response
    from fin_assist.cli.interaction.streaming import render_stream

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

            prompt = args.prompt

            if prompt is None:
                fp = FinPrompt(
                    agents=[a.name for a in agents],
                    context_settings=config.context,
                )
                try:
                    prompt = (await fp.ask("> ")).strip()
                except (KeyboardInterrupt, EOFError):
                    render_info("Cancelled")
                    return 0
                if not prompt:
                    return 0
            elif args.edit:
                fp = FinPrompt(
                    agents=[a.name for a in agents],
                    context_settings=config.context,
                )
                try:
                    prompt = (await fp.ask("> ", default=prompt)).strip()
                except (KeyboardInterrupt, EOFError):
                    render_info("Cancelled")
                    return 0
                if not prompt:
                    return 0

            if not prompt:
                return 0

            prompt, system_prompt_override = _resolve_workflow(
                args.agent,
                args.workflow,
                prompt,
                config,
            )

            if system_prompt_override:
                from fin_assist.agents.registry import SYSTEM_PROMPTS

                override_text = SYSTEM_PROMPTS.get(system_prompt_override, system_prompt_override)
                prompt = f"[Workflow context]\n{override_text}\n\n[Request]\n{prompt}"

            prompt = resolve_at_references(prompt, context_settings=config.context)
            result, deferred_calls = await render_stream(
                client.stream_agent(args.agent, prompt),
                show_thinking=args.show_thinking,
            )

            while deferred_calls:
                from fin_assist.cli.interaction.approve import run_approval_widget

                decisions = await run_approval_widget(deferred_calls)
                if decisions is not None:
                    result, deferred_calls = await render_stream(
                        client.stream_agent(
                            args.agent,
                            "",
                            context_id=result.context_id,
                            approval_decisions=decisions,
                        ),
                        show_thinking=args.show_thinking,
                    )
                else:
                    render_info("Tool call cancelled")
                    return 0

            response = await handle_post_response(result)
            return response.exit_code
    except Exception:
        return 1


async def _talk_command(args: argparse.Namespace, config, config_path: Path | None = None) -> int:
    """Handle `fin-assist talk <agent>`."""
    from coolname import generate_slug  # pyright: ignore[reportPrivateImportUsage]

    from fin_assist.cli.interaction.chat import run_chat_loop
    from fin_assist.cli.interaction.prompt import FinPrompt

    if args.list_sessions:
        render_session_list(args.agent)
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

            fp = FinPrompt(
                agents=[a.name for a in agents],
                context_settings=config.context,
            )
            message = args.message

            if message:
                message, system_prompt_override = _resolve_workflow(
                    args.agent,
                    args.workflow,
                    message,
                    config,
                )
                if system_prompt_override:
                    from fin_assist.agents.registry import SYSTEM_PROMPTS

                    override_text = SYSTEM_PROMPTS.get(
                        system_prompt_override, system_prompt_override
                    )
                    message = f"[Workflow context]\n{override_text}\n\n[Request]\n{message}"

            final_context_id = await run_chat_loop(
                client.stream_agent,
                args.agent,
                context_id,
                fp,
                initial_message=message if not args.edit else None,
                edit_message=message if args.edit else None,
                show_thinking=args.show_thinking,
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


def _list_command(args: argparse.Namespace, config) -> int:
    """Handle `fin-assist list <resource>` — show platform registry contents."""
    resource = args.resource

    if resource == "tools":
        from fin_assist.agents.tools import create_default_registry

        registry = create_default_registry(context_settings=config.context)
        tools = registry.list_tools()
        if not tools:
            render_info("No tools registered.")
            return 0
        for tool in tools:
            approval = " (approval required)" if tool.approval_policy else ""
            console.print(f"  [bold]{tool.name}[/bold]{approval}")
            console.print(f"    {tool.description}")
        return 0

    if resource == "prompts":
        from fin_assist.agents.registry import SYSTEM_PROMPTS

        if not SYSTEM_PROMPTS:
            render_info("No prompts registered.")
            return 0
        for name, prompt_text in SYSTEM_PROMPTS.items():
            first_line = prompt_text.strip().split("\n", 1)[0]
            console.print(f"  [bold]{name}[/bold]")
            console.print(f"    {first_line[:80]}")
        return 0

    if resource == "output-types":
        from fin_assist.agents.registry import OUTPUT_TYPES

        if not OUTPUT_TYPES:
            render_info("No output types registered.")
            return 0
        for name, type_obj in OUTPUT_TYPES.items():
            console.print(f"  [bold]{name}[/bold]  →  {type_obj.__name__}")
        return 0

    render_error(f"Unknown resource '{resource}'. Choose from: tools, prompts, output-types")
    return 1


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
        "--agent",
        default=None,
        help="Name of the agent to use (default: from config or 'default').",
    )
    do_parser.add_argument("prompt", nargs="?", help="The prompt to send.")
    do_parser.add_argument(
        "--edit",
        action="store_true",
        help="Open input panel pre-filled with prompt for editing before sending.",
    )
    do_parser.add_argument(
        "--show-thinking",
        action="store_true",
        help="Show agent thinking/reasoning in the output.",
    )
    do_parser.add_argument(
        "--workflow",
        default=None,
        help="Name of a workflow defined in the agent's config (e.g. commit, pr, summarize).",
    )

    talk_parser = subparsers.add_parser(
        "talk",
        help="Start a multi-turn chat session with an agent.",
    )
    talk_parser.add_argument(
        "--agent",
        default=None,
        help="Name of the agent to use (default: from config or 'default').",
    )
    talk_parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Optional initial message to send as the first turn.",
    )
    talk_parser.add_argument(
        "--edit",
        action="store_true",
        help="Open input panel pre-filled with message for editing before sending.",
    )
    talk_parser.add_argument(
        "--list",
        dest="list_sessions",
        action="store_true",
        help="List saved sessions for the agent.",
    )
    talk_parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="Resume a saved session.",
    )
    talk_parser.add_argument(
        "--show-thinking",
        action="store_true",
        help="Show agent thinking/reasoning in the chat output.",
    )
    talk_parser.add_argument(
        "--workflow",
        default=None,
        help="Name of a workflow defined in the agent's config.",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List platform capabilities (tools, prompts, output-types).",
    )
    list_parser.add_argument(
        "resource",
        choices=["tools", "prompts", "output-types"],
        help="Which platform resource to list.",
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

    if args.command in ("do", "talk") and args.agent is None:
        agent = config.general.default_agent
        if agent is None:
            if not config.agents:
                render_error(
                    "No agents configured. "
                    "Add an [agents.*] section to config.toml.\n"
                    "Example:\n\n"
                    "  [agents.default]\n"
                    '  system_prompt = "chain-of-thought"\n'
                    '  tools = ["read_file", "git", "run_shell"]'
                )
            else:
                names = ", ".join(config.agents)
                render_error(
                    "No default agent set. Specify --agent or set "
                    "[general] default_agent in config.toml.\n"
                    f"Available agents: {names}"
                )
            return 1
        args.agent = agent

    match args.command:
        case "agents":
            return asyncio.run(_agents_command(args, config, config_path))
        case "do":
            return asyncio.run(_do_command(args, config, config_path))
        case "talk":
            return asyncio.run(_talk_command(args, config, config_path))
        case "list":
            return _list_command(args, config)
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
