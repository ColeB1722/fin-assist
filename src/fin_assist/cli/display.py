"""Rich-based output formatting for CLI display."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from fin_assist.paths import CREDENTIALS_FILE, SESSIONS_DIR

if TYPE_CHECKING:
    from fin_assist.cli.client import DiscoveredAgent


console = Console()


def render_response(
    text: str,
    agent_name: str = "agent",
) -> None:
    """Render a general agent text response with Markdown formatting."""
    panel = Panel(
        Markdown(text),
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


def render_info(message: str) -> None:
    """Render an informational message."""
    console.print(f"[dim]{message}[/dim]")


def render_thinking(thinking: list[str]) -> None:
    """Render agent thinking/reasoning content with Markdown formatting."""
    if not thinking:
        return
    for block in thinking:
        console.print(
            Panel(
                Markdown(block),
                title="Thinking",
                border_style="dim",
                expand=False,
            )
        )
    console.print()


def render_agent_card(agent: DiscoveredAgent) -> None:
    """Render a single agent card for the agents list."""

    name = f"[bold cyan]{agent.name}[/bold cyan]"
    desc = agent.description

    capability_parts = [f"[dim]{mode}[/dim]" for mode in agent.card_meta.serving_modes]
    constraint_parts = []

    chip_parts = capability_parts + constraint_parts
    chip_str = "  |  ".join(chip_parts)

    console.print(f"{name}  —  {desc}")
    console.print(f"  {chip_str}")


def render_agents_list(agents: list[DiscoveredAgent]) -> None:
    """Render a list of available agents."""
    console.print("[bold]Available agents:[/bold]\n")
    for agent in agents:
        render_agent_card(agent)
        console.print()


def render_session_list(agent_name: str) -> None:
    """Render saved sessions for an agent, most-recent first."""
    sessions_dir = SESSIONS_DIR / agent_name
    if not sessions_dir.exists():
        console.print(f"  No saved sessions for {agent_name}")
        return
    files = sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        console.print(f"  No saved sessions for {agent_name}")
        return
    console.print(f"[bold]Saved sessions for {agent_name}:[/bold]")
    for session_file in files:
        try:
            session = json.loads(session_file.read_text())
        except (json.JSONDecodeError, OSError):
            console.print(f"  [dim]{session_file.stem}  (corrupted)[/dim]")
            continue
        sid = session.get("session_id", "unknown")
        cid = session.get("context_id", "unknown")
        cid_display = f"{cid[:8]}..." if len(cid) > 8 else cid
        console.print(f"  {sid}  (context: {cid_display})")
