"""Approval widget for shell agent command execution."""

from __future__ import annotations

import subprocess
from enum import StrEnum

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
from prompt_toolkit.styles import Style
from rich.console import Console

console = Console()


class ApprovalAction(StrEnum):
    """Actions available after viewing a shell command."""

    EXECUTE = "execute"
    CANCEL = "cancel"


def _build_key_bindings() -> KeyBindings:
    """Build extra key bindings for the approval widget.

    Adds Escape and Ctrl+D as cancel shortcuts (in addition to the
    built-in Ctrl+C handling from ChoiceInput).
    """
    kb = KeyBindings()

    @kb.add("escape", eager=True)
    @kb.add("c-d", eager=True)
    def _cancel(event) -> None:  # noqa: ANN001
        event.app.exit(result=ApprovalAction.CANCEL)

    return kb


_STYLE = Style.from_dict(
    {
        "selected-option": "bold #ansibrightgreen",
        "number": "#ansibrightgreen",
    }
)


async def run_approve_widget(
    command: str,
    warnings: list[str] | None = None,
) -> ApprovalAction:
    """Show the approval widget and return the user's choice.

    Presents Execute/Cancel as an arrow-key selection (no text input).
    Enter confirms, Escape/Ctrl+C/Ctrl+D cancels.

    Args:
        command: The shell command to approve.
        warnings: Any warnings associated with the command.

    Returns:
        ApprovalAction.EXECUTE or ApprovalAction.CANCEL.
    """
    console.print()

    try:
        result = await ChoiceInput(
            message="Action:",
            options=[
                (ApprovalAction.EXECUTE, "Execute"),
                (ApprovalAction.CANCEL, "Cancel"),
            ],
            default=ApprovalAction.EXECUTE,
            style=_STYLE,
            key_bindings=_build_key_bindings(),
        ).prompt_async()
    except KeyboardInterrupt:
        return ApprovalAction.CANCEL

    return result


def execute_command(command: str) -> int:
    """Execute a shell command and return the exit code."""
    console.print(f"[dim]$ {command}[/dim]")
    result = subprocess.run(command, shell=True)
    return result.returncode
