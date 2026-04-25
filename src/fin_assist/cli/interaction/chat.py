"""Multi-turn chat widget for interactive conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from fin_assist.cli.display import render_session_list
from fin_assist.cli.interaction.prompt import SLASH_COMMANDS, FinPrompt
from fin_assist.cli.interaction.response import PostResponseAction, handle_post_response
from fin_assist.cli.interaction.streaming import render_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from fin_assist.cli.client import StreamEvent
    from fin_assist.cli.interaction.prompt import SlashCommand

console = Console()

_CMD_LOOKUP: dict[str, SlashCommand] = {cmd.name: cmd for cmd in SLASH_COMMANDS}


def _print_help() -> None:
    console.print("[bold]Available commands:[/bold]")
    for cmd in SLASH_COMMANDS:
        console.print(f"  {cmd.name}  — {cmd.description}")


def _print_sessions(agent_name: str) -> None:
    render_session_list(agent_name)
    console.print(f"[dim]Resume with: fin talk {agent_name} --resume <slug>[/dim]")


async def run_chat_loop(
    stream_fn: Callable[..., AsyncIterator[StreamEvent]],
    agent_name: str,
    context_id: str | None = None,
    prompt: FinPrompt | None = None,
    *,
    initial_message: str | None = None,
    show_thinking: bool = False,
) -> str | None:
    """Run an interactive chat loop.

    Args:
        stream_fn: Async generator that takes (agent_name, prompt, context_id)
                   and yields StreamEvent objects for progressive rendering.
        agent_name: Name of the agent to chat with.
        context_id: Optional context ID for resuming a conversation.
        prompt: Optional FinPrompt instance for input (created if not provided).
        initial_message: Optional message to send as the first turn before
                        entering the interactive prompt loop.
        show_thinking: Whether to render agent thinking content.

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
                    _print_sessions(agent_name)
                    continue
                case _:
                    console.print(f"[yellow]Command {matched.name} is not yet implemented[/yellow]")
                    continue

        if user_input.startswith("/"):
            console.print(f"[yellow]Unknown command: {user_input}[/yellow]")
            console.print("Type /help for available commands")
            continue

        # --- Stream and render response ---
        try:
            result, deferred_calls = await render_stream(
                stream_fn(agent_name, user_input, ctx_id),
                show_thinking=show_thinking,
            )
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        ctx_id = result.context_id or ctx_id

        if deferred_calls:
            from fin_assist.cli.interaction.approve import run_approval_widget

            decisions = await run_approval_widget(deferred_calls)
            if decisions is not None:
                try:
                    result, _ = await render_stream(
                        stream_fn(
                            agent_name,
                            "",
                            ctx_id,
                            approval_decisions=decisions,
                        ),
                        show_thinking=show_thinking,
                    )
                except Exception as e:
                    console.print(f"[red]Error resuming: {e}[/red]")
            else:
                console.print("[dim]Tool call cancelled[/dim]")
                console.print()
                continue

        response = await handle_post_response(result)

        if response.action == PostResponseAction.AUTH_REQUIRED:
            console.print("[dim]Fix credentials and try again.[/dim]")
            break

        console.print()

    return ctx_id
