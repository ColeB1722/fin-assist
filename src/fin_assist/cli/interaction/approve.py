"""Approval widget for deferred tool calls.

When the Executor pauses a task for human approval (``input_required``
event), the client presents the deferred tool calls and collects the
user's decisions.  The decisions are sent back via ``approval_result``
Part metadata to resume the task.
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

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
    deferred_calls: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Show the approval widget for deferred tool calls and return decisions.

    Presents each deferred tool call with its arguments and reason,
    then shows Approve/Deny as an arrow-key selection.

    Args:
        deferred_calls: List of deferred tool call dicts from the
            ``input_required`` StreamEvent.  Each has ``tool_name``,
            ``tool_call_id``, ``args``, and ``reason``.

    Returns:
        A list of decision dicts suitable for ``approval_decisions``
        parameter of ``HubClient.stream_agent()``, or ``None`` if the
        user cancelled (denies all).
    """
    for call in deferred_calls:
        tool_name = call.get("tool_name", "unknown")
        args = call.get("args", {})
        reason = call.get("reason", "")

        args_display = ", ".join(f"{k}={v!r}" for k, v in args.items())
        content = Text()
        content.append("Tool: ", style="bold")
        content.append(f"{tool_name}\n")
        if args_display:
            content.append("Args: ", style="bold")
            content.append(f"{args_display}\n")
        if reason:
            content.append("Reason: ", style="bold")
            content.append(f"{reason}")

        console.print(Panel(content, title="Approval Required", border_style="yellow"))

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
        approved = False

    decisions = []
    for call in deferred_calls:
        decisions.append(
            {
                "tool_call_id": call.get("tool_call_id", ""),
                "approved": approved,
                "denial_reason": None if approved else "Denied by user",
            }
        )

    if not approved:
        return None

    return decisions
