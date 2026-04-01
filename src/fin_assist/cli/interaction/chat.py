"""Multi-turn chat widget for interactive conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from fin_assist.cli.interaction.prompt import FinPrompt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fin_assist.cli.client import AgentResult

console = Console()


async def run_chat_loop(
    send_message_fn: Callable[[str, str, str | None], Awaitable[AgentResult]],
    agent_name: str,
    context_id: str | None = None,
    prompt: FinPrompt | None = None,
) -> str | None:
    """Run an interactive chat loop.

    Args:
        send_message_fn: Async function that takes (agent_name, prompt, context_id)
                        and returns an AgentResult.
        agent_name: Name of the agent to chat with.
        context_id: Optional context ID for resuming a conversation.
        prompt: Optional FinPrompt instance for input (created if not provided).

    Returns:
        The final context_id if the conversation had one.
    """
    ctx_id = context_id

    console.print(f"[bold green]Starting chat with {agent_name}[/bold green]")
    console.print("[dim]Type /exit to end the conversation[/dim]\n")

    fp = prompt or FinPrompt()

    while True:
        try:
            user_input = (await fp.ask("[bold]>[/bold] ")).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting chat[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit", "/q"):
            console.print("[dim]Ending conversation[/dim]")
            break

        if user_input.startswith("/"):
            console.print(f"[yellow]Unknown command: {user_input}[/yellow]")
            console.print("Available: /exit")
            continue

        try:
            result = await send_message_fn(agent_name, user_input, ctx_id)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        ctx_id = result.context_id or ctx_id

        if result.success:
            console.print()
            console.print(result.output)
            if result.warnings:
                console.print(f"[yellow]{' '.join(result.warnings)}[/yellow]")
        else:
            console.print(f"[red]Error: {result.output or 'Unknown error'}[/red]")

        console.print()

    return ctx_id
