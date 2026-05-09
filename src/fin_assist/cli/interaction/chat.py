"""Multi-turn chat widget for interactive conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from rich.console import Console

from fin_assist.cli.display import render_session_list
from fin_assist.cli.interaction.prompt import SLASH_COMMANDS, FinPrompt, resolve_at_references
from fin_assist.cli.interaction.response import PostResponseAction, handle_post_response
from fin_assist.cli.interaction.streaming import render_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from typing import Any

    from fin_assist.cli.client import StreamEvent
    from fin_assist.cli.interaction.prompt import SlashCommand

# Pending-input dispatch mode for the first loop iteration:
#   "send" — submit unedited (fin talk <msg> / fin do <msg>)
#   "edit" — pre-fill the input panel so the user can revise (fin talk --edit)
_PendingMode = Literal["send", "edit"]

console = Console()

_CMD_LOOKUP: dict[str, SlashCommand] = {cmd.name: cmd for cmd in SLASH_COMMANDS}


def _print_help() -> None:
    console.print("[bold]Available commands:[/bold]")
    for cmd in SLASH_COMMANDS:
        console.print(f"  {cmd.name}  — {cmd.description}")
    console.print("  /skill:<name>  — Load a skill mid-session")


def _print_sessions(agent_name: str) -> None:
    render_session_list(agent_name)
    console.print(f"[dim]Resume with: fin talk {agent_name} --resume <slug>[/dim]")


async def _print_skills(
    agent_name: str,
    list_skills_fn: Callable[[str], Awaitable[list[dict[str, Any]]]] | None,
) -> None:
    if list_skills_fn is None:
        console.print("[dim]Skill listing not available.[/dim]")
        return
    try:
        skills = await list_skills_fn(agent_name)
    except Exception as e:
        console.print(f"[red]Failed to list skills: {e}[/red]")
        return
    if not skills:
        console.print("[dim]No skills configured for this agent.[/dim]")
        return
    console.print("[bold]Available skills:[/bold]")
    for skill in skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        tools = skill.get("tools", [])
        tools_str = f" (tools: {', '.join(tools)})" if tools else ""
        console.print(f"  [bold]{name}[/bold]{tools_str}")
        if desc:
            console.print(f"    {desc}")


async def run_chat_loop(
    stream_fn: Callable[..., AsyncIterator[StreamEvent]],
    agent_name: str,
    context_id: str | None = None,
    prompt: FinPrompt | None = None,
    *,
    initial_message: str | None = None,
    edit_message: str | None = None,
    show_thinking: bool = False,
    invoke_skill_fn: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
    list_skills_fn: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
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
        edit_message: Optional message to pre-fill the input panel with on the
                     first turn (instead of sending immediately).
        show_thinking: Whether to render agent thinking content.

    Returns:
        The final context_id if the conversation had one.
    """
    ctx_id = context_id

    console.print(f"[bold green]Starting chat with {agent_name}[/bold green]")
    console.print("[dim]Type /exit to end the conversation[/dim]\n")

    fp = prompt or FinPrompt()

    # Single pending-input slot: ``edit_message`` takes precedence over
    # ``initial_message`` (matches the prior two-variable semantics).
    pending: tuple[_PendingMode, str] | None
    if edit_message is not None:
        pending = ("edit", edit_message)
    elif initial_message is not None:
        pending = ("send", initial_message)
    else:
        pending = None

    while True:
        if pending is not None:
            mode, text = pending
            pending = None
            if mode == "edit":
                try:
                    user_input = (await fp.ask("> ", default=text)).strip()
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[dim]Exiting chat[/dim]")
                    break
            else:  # "send"
                user_input = text
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
                case "/skills":
                    await _print_skills(agent_name, list_skills_fn)
                    continue
                case _:
                    console.print(f"[yellow]Command {matched.name} is not yet implemented[/yellow]")
                    continue

        if user_input.startswith("/skill:"):
            skill_name = user_input[len("/skill:") :].strip()
            if skill_name and invoke_skill_fn is not None:
                try:
                    result = await invoke_skill_fn(agent_name, skill_name)
                    console.print(f"[green]Skill '{skill_name}' loaded.[/green]")
                    tools = result.get("tools", [])
                    if tools:
                        console.print(f"[dim]Tools now available: {', '.join(tools)}[/dim]")
                except Exception as e:
                    console.print(f"[red]Failed to load skill '{skill_name}': {e}[/red]")
            elif not skill_name:
                console.print("[yellow]Usage: /skill:<name> (e.g. /skill:commit)[/yellow]")
            elif invoke_skill_fn is None:
                console.print("[dim]Skill loading not available.[/dim]")
            continue

        if user_input.startswith("/"):
            console.print(f"[yellow]Unknown command: {user_input}[/yellow]")
            console.print("Type /help for available commands")
            continue

        # Blank line between the user's prompt and the agent's streaming
        # response so they don't visually merge.  ``render_stream`` does
        # not know what precedes it and starts printing immediately.
        console.print()

        resolved_input = resolve_at_references(user_input, context_settings=fp.context_settings)

        # --- Stream and render response ---
        try:
            result, deferred_calls = await render_stream(
                stream_fn(agent_name, resolved_input, ctx_id),
                show_thinking=show_thinking,
            )
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            continue

        ctx_id = result.context_id or ctx_id

        from fin_assist.cli.interaction.approve import run_approval_widget

        while deferred_calls:
            decisions = await run_approval_widget(deferred_calls)
            if decisions is not None:
                try:
                    result, deferred_calls = await render_stream(
                        stream_fn(
                            agent_name,
                            "",
                            ctx_id,
                            approval_decisions=decisions,
                        ),
                        show_thinking=show_thinking,
                    )
                    ctx_id = result.context_id or ctx_id
                except Exception as e:
                    console.print(f"[red]Error resuming: {e}[/red]")
                    break
            else:
                console.print("[dim]Tool call cancelled[/dim]")
                deferred_calls = []
                console.print()
                continue

        response = await handle_post_response(result)

        if response.action == PostResponseAction.AUTH_REQUIRED:
            console.print("[dim]Fix credentials and try again.[/dim]")
            break

        console.print()

    return ctx_id
