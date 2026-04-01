"""Approval widget for shell agent command execution."""

from __future__ import annotations

import asyncio
import subprocess
from enum import StrEnum

from rich.console import Console

from fin_assist.cli.interaction.prompt import FinPrompt

console = Console()


class ApprovalAction(StrEnum):
    """Actions available after viewing a shell command."""

    EXECUTE = "execute"
    EDIT = "edit"
    CANCEL = "cancel"


def run_approve_widget(
    command: str,
    warnings: list[str] | None = None,
    supports_regenerate: bool = True,
    regenerate_prompt: str | None = None,
    prompt: FinPrompt | None = None,
) -> tuple[ApprovalAction, str | None]:
    """Show the approval widget and return the user's choice.

    Args:
        command: The shell command to approve.
        warnings: Any warnings associated with the command.
        supports_regenerate: Whether to show the regenerate option.
        regenerate_prompt: The original prompt for regeneration.
        prompt: Optional FinPrompt instance for input.

    Returns:
        A tuple of (action, edited_command_or_prompt).
        - (EXECUTE, None) — user approved, CLI should run the command
        - (EDIT, prompt) — user wants to edit and resubmit
        - (CANCEL, None) — user cancelled
    """
    options = ["execute", "cancel"]
    if supports_regenerate:
        options.insert(1, "regenerate")

    prompt_text = " ".join(f"[{opt}]" for opt in options)

    fp = prompt or FinPrompt()

    while True:
        console.print()
        choice = asyncio.run(fp.ask(f"[bold]Action:[/bold] {prompt_text} ")).strip()

        match choice:
            case "execute":
                return (ApprovalAction.EXECUTE, None)
            case "cancel":
                return (ApprovalAction.CANCEL, None)
            case "regenerate":
                if regenerate_prompt:
                    return (ApprovalAction.EDIT, regenerate_prompt)
                console.print("[yellow]Regenerate not available (no original prompt)[/yellow]")
            case _:
                if choice:
                    console.print(f"[yellow]Unknown choice: {choice}[/yellow]")
                console.print(f"Valid options: {' '.join(options)}")


def execute_command(command: str) -> int:
    """Execute a shell command and return the exit code."""
    console.print(f"[dim]$ {command}[/dim]")
    result = subprocess.run(command, shell=True)
    return result.returncode
