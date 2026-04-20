"""Rich-based output formatting for CLI display.

Progressive output
~~~~~~~~~~~~~~~~~~
The ``ProgressiveDisplay`` context manager drives the live UX for
streaming agent responses.  It composites a thinking spinner (with
token count) and incremental text output using Rich's ``Live`` display.

When thinking is in progress, a spinner line like ``⠋ Thinking... (847
tokens)`` is shown.  Once output text arrives, the spinner collapses to
a dim summary line (``▸ 1,247 tokens thinking``) and the output text
streams below it progressively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text

from fin_assist.paths import CREDENTIALS_FILE

if TYPE_CHECKING:
    from fin_assist.agents.metadata import AgentCardMeta
    from fin_assist.cli.client import AgentResult, DiscoveredAgent


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


def render_thinking(thinking: list[str]) -> None:
    """Render agent thinking/reasoning content in a dim italic style."""
    if not thinking:
        return
    for block in thinking:
        console.print(
            Panel(
                Text(block, style="dim italic"), title="Thinking", border_style="dim", expand=False
            )
        )
    console.print()


def render_markdown(text: str) -> None:
    """Render text as markdown without a panel wrapper."""
    console.print(Markdown(text))


def render_agent_output(
    result: AgentResult,
    card_meta: AgentCardMeta | None = None,
    *,
    show_thinking: bool = False,
    mode: str = "do",
) -> None:
    """Render an agent result using the shared widget pipeline.

    Composes thinking, auth, command, text, and warning widgets based on
    ``AgentResult`` and ``AgentCardMeta``.  ``mode`` controls the text
    wrapper (Panel for ``do``, Markdown for ``talk``) but does not affect
    which widgets render.

    When ``card_meta`` is ``None``, renders as Markdown (talk) or Panel
    (do) with standard warning panels — the same output as the card_meta
    path when ``requires_approval`` is ``False``.
    """
    if show_thinking and result.thinking:
        render_thinking(result.thinking)

    if result.metadata.get("auth_required"):
        render_auth_required(result.output)
        return

    if not result.success:
        render_error(result.output or "Unknown error")
        return

    if card_meta is not None and card_meta.requires_approval:
        render_command(result.output, result.warnings, result.metadata)
        return

    if mode == "talk":
        render_markdown(result.output)
    else:
        render_response(result.output, agent_name="agent")

    if result.warnings:
        render_warnings(result.warnings)


class ProgressiveDisplay:
    """Context manager for progressive agent output rendering.

    Drives a Rich ``Live`` display that transitions through phases:

    1. **Thinking** — animated spinner with token count
    2. **Collapsed thinking + streaming text** — dim summary line,
       output text rendered incrementally as Markdown
    3. **Final** — live display stops, final output rendered normally

    Usage::

        async with ProgressiveDisplay(console) as display:
            async for result in client.stream_message(...):
                display.update(result)

    """

    def __init__(self, target_console: Console | None = None) -> None:
        self._console = target_console or console
        self._live: Live | None = None
        self._thinking_tokens = 0
        self._output_text = ""
        self._thinking_done = False
        self._spinner = Spinner("dots", style="dim")

    def start(self) -> None:
        """Start the live display."""
        self._live = Live(
            self._build_renderable(),
            console=self._console,
            refresh_per_second=12,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live display."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def update(self, result: AgentResult) -> None:
        """Update the display with a new partial or final result.

        Called once per ``AgentResult`` yielded by ``stream_message()``.
        """
        if result.partial:
            self._thinking_tokens = result.thinking_token_count
            if result.output:
                self._thinking_done = True
                self._output_text = result.output
        else:
            # Final result — mark thinking as done, capture final output
            self._thinking_done = True
            if result.thinking:
                # Use actual thinking token count from final result
                total = sum(len(t.split()) for t in result.thinking)
                self._thinking_tokens = total
            self._output_text = result.output

        if self._live is not None:
            self._live.update(self._build_renderable())

    def _build_renderable(self) -> Group:
        """Build the composite renderable for the current state."""
        parts: list[Text | Spinner | Markdown] = []

        if not self._thinking_done:
            # Phase 1: thinking spinner with token count
            label = f" Thinking... ({self._thinking_tokens} tokens)"
            self._spinner.update(text=Text(label, style="dim"))
            parts.append(self._spinner)
        else:
            # Phase 2+: collapsed thinking summary
            if self._thinking_tokens > 0:
                parts.append(
                    Text(
                        f"▸ {self._thinking_tokens} tokens thinking",
                        style="dim italic",
                    )
                )

            # Streaming or final output text
            if self._output_text:
                parts.append(Markdown(self._output_text))

        return Group(*parts)

    def __enter__(self) -> ProgressiveDisplay:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


def render_collapsed_thinking(token_count: int) -> None:
    """Render a collapsed thinking summary line (non-live)."""
    if token_count > 0:
        console.print(Text(f"▸ {token_count} tokens thinking", style="dim italic"))


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
