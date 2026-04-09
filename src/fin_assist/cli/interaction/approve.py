"""Approval widget for shell agent command execution."""

from __future__ import annotations

import subprocess
from enum import StrEnum

from rich.console import Console

from fin_assist.cli.interaction.prompt import FinPrompt

console = Console()


class ApprovalAction(StrEnum):
    """Actions available after viewing a shell command."""

    EXECUTE = "execute"
    CANCEL = "cancel"


async def run_approve_widget(
    command: str,
    warnings: list[str] | None = None,
    prompt: FinPrompt | None = None,
) -> ApprovalAction:
    """Show the approval widget and return the user's choice.

    Args:
        command: The shell command to approve.
        warnings: Any warnings associated with the command.
        prompt: Optional FinPrompt instance for input.

    Returns:
        ApprovalAction.EXECUTE or ApprovalAction.CANCEL.
    """
    options = ["execute", "cancel"]
    prompt_text = " ".join(f"[{opt}]" for opt in options)

    fp = prompt or FinPrompt()

    while True:
        console.print()
        try:
            choice = (await fp.ask(f"Action: {prompt_text} ")).strip()
        except (KeyboardInterrupt, EOFError):
            return ApprovalAction.CANCEL

        match choice:
            case "execute":
                return ApprovalAction.EXECUTE
            case "cancel":
                return ApprovalAction.CANCEL
            case _:
                if choice:
                    console.print(f"[yellow]Unknown choice: {choice}[/yellow]")
                console.print(f"Valid options: {' '.join(options)}")


def execute_command(command: str) -> int:
    """Execute a shell command and return the exit code."""
    console.print(f"[dim]$ {command}[/dim]")
    result = subprocess.run(command, shell=True)
    return result.returncode
