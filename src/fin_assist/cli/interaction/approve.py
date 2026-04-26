"""Approval widget for deferred tool calls.

When the Executor pauses a task for human approval (``input_required``
event), the client presents the deferred tool calls and collects the
user's decisions.  The decisions are sent back via ``approval_result``
Part metadata to resume the task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from fin_assist.agents.tools import DeferredToolCall

console = Console()

_STYLE = Style.from_dict(
    {
        "selected-option": "bold #ansibrightgreen",
        "number": "#ansibrightgreen",
    }
)


def _build_key_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("escape", eager=True)
    @kb.add("c-d", eager=True)
    def _cancel(event) -> None:  # noqa: ANN001
        event.app.exit(result=False)

    return kb


async def run_approval_widget(
    deferred_calls: list[DeferredToolCall],
) -> list[dict[str, Any]] | None:
    """Show the approval widget for deferred tool calls and return decisions.

    Presents each deferred tool call with its arguments and reason,
    then shows Approve/Deny as an arrow-key selection.

    Args:
        deferred_calls: Typed deferred tool calls from the
            ``input_required`` StreamEvent.

    Returns:
        A list of decision dicts suitable for ``approval_decisions``
        parameter of ``HubClient.stream_agent()``, or ``None`` if the
        user cancelled (e.g. Ctrl-C) without making a selection.
    """
    # Leading blank so the panel visually separates from the tool_call
    # line printed by ``render_stream`` just before this widget ran.
    console.print()

    for call in deferred_calls:
        args_display = ", ".join(f"{k}={v!r}" for k, v in call.args.items())
        content = Text()
        content.append("Tool: ", style="bold")
        content.append(f"{call.tool_name}\n")
        if args_display:
            content.append("Args: ", style="bold")
            content.append(f"{args_display}\n")
        if call.reason:
            content.append("Reason: ", style="bold")
            content.append(call.reason)

        console.print(Panel(content, title="Approval Required", border_style="yellow"))

    # Blank between the panel and the Approve/Deny prompt so they don't
    # visually merge.
    console.print()

    try:
        approved = await ChoiceInput(
            message="Approve this tool call?",
            options=[
                (True, "Approve"),
                (False, "Deny"),
            ],
            default=True,
            style=_STYLE,
            key_bindings=_build_key_bindings(),
        ).prompt_async()
    except KeyboardInterrupt:
        return None

    # Blank line after the user's selection so the resumed stream's first
    # printed line (typically the re-announced tool call) has visual
    # separation from the approval widget.
    console.print()

    return [
        {
            "tool_call_id": call.tool_call_id,
            "approved": approved,
            "denial_reason": None if approved else "Denied by user",
        }
        for call in deferred_calls
    ]
