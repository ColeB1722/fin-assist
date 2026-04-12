"""Rich-based output formatting for CLI display."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from fin_assist.paths import CREDENTIALS_FILE

if TYPE_CHECKING:
    from fin_assist.cli.client import DiscoveredAgent


console = Console()


def render_command(
    command: str,
    warnings: list[str] | None = None,
    metadata: dict | None = None,
) -> None:
    """Render a shell command result as a highlighted code block."""
    syntax = Syntax(command, "bash", theme="monokai", line_numbers=False)
    panel = Panel(
        syntax,
        title="Generated Command",
        border_style="green",
        expand=False,
    )
    console.print(panel)

    if warnings:
        render_warnings(warnings)

    if metadata:
        accept_action = metadata.get("accept_action")
        if accept_action == "insert_command":
            console.print(
                "[dim]Press Enter or click [bold]execute[/bold] to run this command[/dim]"
            )


def render_response(
    text: str,
    agent_name: str = "agent",
) -> None:
    """Render a general agent text response."""
    panel = Panel(
        text,
        title=f"[bold]{agent_name}[/bold]",
        border_style="blue",
        expand=False,
    )
    console.print(panel)


def render_warnings(warnings: list[str]) -> None:
    """Render a list of warnings in a styled panel."""
    if not warnings:
        return

    warning_text = Text()
    for i, warning in enumerate(warnings):
        if i > 0:
            warning_text.append("\n")
        warning_text.append(f"  {warning}", style="yellow")

    panel = Panel(
        warning_text,
        title="[yellow]Warnings[/yellow]",
        border_style="yellow",
        expand=False,
    )
    console.print(panel)


def render_auth_required(provider_info: str) -> None:
    """Render an authentication-required message with remediation hints.

    Displayed when an agent returns ``auth-required`` because API keys
    are missing.  Visually distinct from a generic error — uses a yellow
    panel with specific env-var hints.
    """
    lines = [
        f"[bold]Authentication required:[/bold] {provider_info}",
        "",
        "[dim]To fix, set the matching environment variable(s):[/dim]",
    ]
    for name in provider_info.replace(",", " ").split():
        name = name.strip()
        if name:
            lines.append(f"  export {name.upper()}_API_KEY=<your-key>")
    lines.append("")
    lines.append(f"[dim]Or write credentials to {CREDENTIALS_FILE}[/dim]")

    text = Text.from_markup("\n".join(lines))
    panel = Panel(text, border_style="yellow", expand=False)
    console.print(panel)


def render_error(message: str) -> None:
    """Render an error message."""
    console.print(f"[bold red]Error:[/bold red] {message}")


def render_success(message: str) -> None:
    """Render a success message."""
    console.print(f"[bold green]Success:[/bold green] {message}")


def render_info(message: str) -> None:
    """Render an informational message."""
    console.print(f"[dim]{message}[/dim]")


def render_agent_card(agent: DiscoveredAgent) -> None:
    """Render a single agent card for the agents list."""

    name = f"[bold cyan]{agent.name}[/bold cyan]"
    desc = agent.description

    meta_parts = []
    if not agent.card_meta.multi_turn:
        meta_parts.append("[dim]one-shot[/dim]")
    if agent.card_meta.requires_approval:
        meta_parts.append("[yellow]requires approval[/yellow]")

    meta_str = "  |  ".join(meta_parts) if meta_parts else ""

    console.print(f"{name}  —  {desc}")
    if meta_str:
        console.print(f"  {meta_str}")


def render_agents_list(agents: list[DiscoveredAgent]) -> None:
    """Render a list of available agents."""
    console.print("[bold]Available agents:[/bold]\n")
    for agent in agents:
        render_agent_card(agent)
        console.print()
