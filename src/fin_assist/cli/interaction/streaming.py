"""Shared streaming renderer for ``fin talk`` and ``fin do``.

``render_stream`` consumes a ``StreamEvent`` async iterator and renders
progressive output using Rich ``Live``.  It shows a ``Status("Processing…")``
spinner while waiting for the first delta, then transitions to a
Markdown-rendered answer area (optionally preceded by a thinking panel
when ``show_thinking=True``).

Tool call/result lines are printed directly to the console (outside the
``Live`` region) so they commit to terminal scrollback as permanent
history.  This avoids a Rich ``Live`` overflow bug where a tall
``Group`` grows past the visible region and causes previous frames to
duplicate in scrollback on each refresh.

Returns the terminal ``AgentResult`` with accumulated thinking injected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status
from rich.text import Text

from fin_assist.agents.metadata import AgentResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fin_assist.cli.client import StreamEvent


_TOOL_ICONS: dict[str, str] = {
    "run_shell": "⚡",
    "read_file": "📄",
    "git_diff": "📋",
    "git_log": "📋",
    "shell_history": "📜",
}

_MAX_RESULT_PREVIEW = 120


def _format_tool_call(event: StreamEvent) -> Text:
    """Format a tool_call event as a dimmed inline line.

    Produces lines like::

        ⚡ run_shell: ls -F
        📄 read_file: treefmt.toml
        📋 git_diff
    """
    tool_name = event.tool_name
    icon = _TOOL_ICONS.get(tool_name, "🔧")
    args = event.tool_args

    line = Text()
    line.append(f"  {icon} ", style="dim")
    line.append(tool_name, style="bold dim")

    key_arg = _key_arg_for_tool(tool_name, args)
    if key_arg:
        line.append(f": {key_arg}", style="dim")

    return line


def _key_arg_for_tool(tool_name: str, args: dict[str, Any]) -> str:
    """Return the most informative arg value for inline display."""
    if tool_name == "run_shell" and "command" in args:
        return str(args["command"])
    if tool_name == "read_file" and "path" in args:
        return str(args["path"])
    if tool_name == "shell_history" and "query" in args and args["query"]:
        return str(args["query"])
    return ""


def _format_tool_result(event: StreamEvent) -> Text:
    """Format a tool_result event as a brief summary line.

    Produces lines like::

        → AGENTS.md  README.md  config.toml  ...
        → 28 lines
        → No uncommitted changes
    """
    text = event.text.strip()
    if not text:
        return Text()

    lines = text.splitlines()
    first_line = lines[0].rstrip()

    line = Text()
    line.append("    → ", style="dim")

    if len(lines) == 1:
        if len(first_line) > _MAX_RESULT_PREVIEW:
            line.append(first_line[:_MAX_RESULT_PREVIEW] + "…", style="dim")
        else:
            line.append(first_line, style="dim")
    else:
        preview = first_line[:80]
        if len(first_line) > 80:
            preview += "…"
        line.append(f"{preview}  ({len(lines)} lines)", style="dim")

    return line


async def render_stream(
    events: AsyncIterator[StreamEvent],
    *,
    show_thinking: bool = False,
    console: Console | None = None,
) -> tuple[AgentResult, list[dict[str, Any]]]:
    """Consume streaming events and render them via Rich ``Live``.

    Text deltas (and optionally thinking deltas) are accumulated and
    rendered inside a ``Live`` region that repaints in place.  Tool
    call/result lines are printed directly to the console *outside*
    ``Live`` so they commit to terminal scrollback as permanent history
    and do not cause the live region to grow unbounded.

    Args:
        events: Async iterator of ``StreamEvent`` from ``HubClient.stream_agent``.
        show_thinking: Whether to render thinking deltas in a visible panel.
            When ``False``, thinking deltas are silently accumulated into the
            result's ``thinking`` list but not displayed.
        console: Optional Rich ``Console`` to print tool lines on.  When
            ``None``, a default console is used (test-friendly).

    Returns:
        A tuple of ``(AgentResult, deferred_calls)``.  ``deferred_calls``
        is non-empty when the task was paused for approval (``input_required``
        event).  The caller should present an approval widget and, if the
        user approves, resume by calling ``stream_agent`` again with
        ``approval_decisions``.
    """
    accumulated_text = ""
    accumulated_thinking: list[str] = []
    final_result: AgentResult | None = None
    deferred_calls: list[dict[str, Any]] = []

    if console is None:
        console = Console()

    def _build_display() -> Group | Status:
        parts: list = []
        if show_thinking and accumulated_thinking:
            thinking_text = "\n\n".join(accumulated_thinking)
            parts.append(
                Panel(
                    Markdown(thinking_text),
                    title="Thinking",
                    border_style="dim",
                    expand=False,
                )
            )
        if accumulated_text:
            parts.append(Markdown(accumulated_text))

        if not parts:
            return Status("Processing…")
        return Group(*parts)

    with Live(
        Status("Processing…"),
        console=console,
        refresh_per_second=8,
        vertical_overflow="visible",
    ) as live:
        async for event in events:
            if event.kind == "text_delta":
                accumulated_text += event.text
                live.update(_build_display())
            elif event.kind == "thinking_delta":
                accumulated_thinking.append(event.text)
                if show_thinking:
                    live.update(_build_display())
            elif event.kind == "tool_call":
                # Print outside Live so the line commits to scrollback and
                # the Live region doesn't grow unbounded.
                live.console.print(_format_tool_call(event))
            elif event.kind == "tool_result":
                formatted = _format_tool_result(event)
                if formatted.plain:
                    live.console.print(formatted)
            elif event.kind == "input_required":
                deferred_calls.extend(event.deferred_calls)
                if event.result is not None:
                    final_result = event.result
            elif event.result is not None:
                final_result = event.result

    if final_result is not None:
        if accumulated_thinking and not final_result.thinking:
            final_result.thinking = accumulated_thinking
        return final_result, deferred_calls

    return (
        AgentResult(success=False, output=accumulated_text or "No response from agent"),
        deferred_calls,
    )
