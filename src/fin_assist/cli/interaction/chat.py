"""Multi-turn chat widget for interactive conversations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console

from fin_assist.cli.display import render_auth_required
from fin_assist.cli.interaction.prompt import SLASH_COMMANDS, FinPrompt
from fin_assist.paths import SESSIONS_DIR

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fin_assist.cli.client import AgentResult
    from fin_assist.cli.interaction.prompt import SlashCommand

console = Console()

_CMD_LOOKUP: dict[str, SlashCommand] = {cmd.name: cmd for cmd in SLASH_COMMANDS}


def _print_help() -> None:
    console.print("[bold]Available commands:[/bold]")
    for cmd in SLASH_COMMANDS:
        console.print(f"  {cmd.name}  — {cmd.description}")


async def run_chat_loop(
    send_message_fn: Callable[[str, str, str | None], Awaitable[AgentResult]],
    agent_name: str,
    context_id: str | None = None,
    prompt: FinPrompt | None = None,
    *,
    initial_message: str | None = None,
) -> str | None:
    """Run an interactive chat loop.

    Args:
        send_message_fn: Async function that takes (agent_name, prompt, context_id)
                        and returns an AgentResult.
        agent_name: Name of the agent to chat with.
        context_id: Optional context ID for resuming a conversation.
        prompt: Optional FinPrompt instance for input (created if not provided).
        initial_message: Optional message to send as the first turn before
                        entering the interactive prompt loop.

    Returns:
        The final context_id if the conversation had one.
    """
    ctx_id = context_id

    console.print(f"[bold green]Starting chat with {agent_name}[/bold green]")
    console.print("[dim]Type /exit to end the conversation[/dim]\n")

    fp = prompt or FinPrompt()
    pending_message = initial_message

    while True:
        if pending_message is not None:
            user_input = pending_message
            pending_message = None
            console.print(f"> {user_input}")
        else:
            try:
                user_input = (await fp.ask("> ")).strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Exiting chat[/dim]")
                break

        if not user_input:
            continue

        matched = _CMD_LOOKUP.get(user_input.lower())

        if matched is not None:
            match matched.name:
                case "/exit":
                    console.print("[dim]Ending conversation[/dim]")
                    break
                case "/help":
                    _print_help()
                    continue
                case "/sessions":
                    sessions_dir = SESSIONS_DIR / agent_name
                    if sessions_dir.exists():
                        files = list(sessions_dir.glob("*.json"))
                        if files:
                            console.print(f"[bold]Saved sessions for {agent_name}:[/bold]")
                            for session_file in files:
                                session = json.loads(session_file.read_text())
                                sid = session.get("session_id", "unknown")
                                cid = session.get("context_id", "unknown")
                                cid_display = f"{cid[:8]}..." if len(cid) > 8 else cid
                                console.print(f"  {sid}  (context: {cid_display})")
                            console.print(
                                f"[dim]Resume with: fin talk {agent_name} --resume <slug>[/dim]"
                            )
                        else:
                            console.print(f"  No saved sessions for {agent_name}")
                    else:
                        console.print(f"  No saved sessions for {agent_name}")
                    continue
                case _:
                    console.print(f"[yellow]Command {matched.name} is not yet implemented[/yellow]")
                    continue

        if user_input.startswith("/"):
            console.print(f"[yellow]Unknown command: {user_input}[/yellow]")
            console.print("Type /help for available commands")
            continue

        try:
            result = await send_message_fn(agent_name, user_input, ctx_id)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        ctx_id = result.context_id or ctx_id

        if result.metadata.get("auth_required"):
            render_auth_required(result.output)
            console.print("[dim]Fix credentials and try again.[/dim]")
            break

        if result.success:
            console.print()
            console.print(result.output)
            if result.warnings:
                console.print(f"[yellow]{' '.join(result.warnings)}[/yellow]")
        else:
            console.print(f"[red]Error: {result.output or 'Unknown error'}[/red]")

        console.print()

    return ctx_id
