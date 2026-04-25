"""Shared streaming renderer for ``fin talk`` and ``fin do``.

``render_stream`` consumes a ``StreamEvent`` async iterator and renders
progressive output using Rich ``Live``.  It shows a ``Status("Processing…")``
spinner while waiting for the first delta, then transitions to a ``Group``
containing an optional thinking panel (when ``show_thinking=True``) and a
Markdown-rendered answer area.

Returns the terminal ``AgentResult`` with accumulated thinking injected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status

from fin_assist.agents.metadata import AgentResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fin_assist.cli.client import StreamEvent


async def render_stream(
    events: AsyncIterator[StreamEvent],
    *,
    show_thinking: bool = False,
) -> tuple[AgentResult, list[dict[str, Any]]]:
    """Consume streaming events and render them via Rich ``Live``.

    Args:
        events: Async iterator of ``StreamEvent`` from ``HubClient.stream_agent``.
        show_thinking: Whether to render thinking deltas in a visible panel.
            When ``False``, thinking deltas are silently accumulated into the
            result's ``thinking`` list but not displayed.

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

    with Live(Status("Processing…"), refresh_per_second=8, vertical_overflow="visible") as live:
        async for event in events:
            if event.kind == "text_delta":
                accumulated_text += event.text
                live.update(_build_display())
            elif event.kind == "thinking_delta":
                accumulated_thinking.append(event.text)
                if show_thinking:
                    live.update(_build_display())
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
