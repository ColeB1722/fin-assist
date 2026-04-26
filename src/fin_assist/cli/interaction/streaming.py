"""Shared streaming renderer for ``fin talk`` and ``fin do``.

``render_stream`` consumes a ``StreamEvent`` async iterator.  Only the
growing Markdown answer is tracked inside a Rich ``Live`` region that
repaints in place.  Everything else — tool call/result lines and
thinking blocks — is printed directly to the console (outside the
``Live`` region) so it commits to terminal scrollback as permanent
history.

This split avoids a Rich ``Live`` overflow bug where a tall renderable
grows past the visible region and causes previous frames to duplicate
in scrollback on each refresh.  With ``vertical_overflow="visible"``,
``Live`` cannot scroll back above the scrollback boundary to overwrite
old frames, so each refresh re-emits the whole group below the old
one.  Keeping the live-tracked renderable bounded (just the answer
Markdown) sidesteps the problem entirely.

Returns the terminal ``AgentResult`` with accumulated thinking injected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
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
    line.append(f"{icon} ", style="dim")
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
    line.append("  → ", style="dim")

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


def _format_thinking_block(buffered: str) -> Markdown | None:
    """Format a buffered thinking block as a dim Markdown blockquote.

    Each line of ``buffered`` is prefixed with ``"> "`` so that Rich
    renders the result as a Markdown blockquote with its native leftbar
    indent.  A ``💭`` emoji is prepended to the first line to mark the
    block as thinking.  The whole block is styled ``dim`` so it visually
    recedes compared to the agent's actual answer.

    Returns ``None`` when the buffer is empty.
    """
    trimmed = buffered.strip()
    if not trimmed:
        return None
    # Preserve paragraph breaks (blank lines) so the blockquote reads as
    # multiple stanzas rather than one long run-on line.
    lines = trimmed.split("\n")
    quoted = ["> 💭 " + lines[0]] + ["> " + line for line in lines[1:]]
    return Markdown("\n".join(quoted), style="dim")


async def render_stream(
    events: AsyncIterator[StreamEvent],
    *,
    show_thinking: bool = False,
    console: Console | None = None,
) -> tuple[AgentResult, list[dict[str, Any]]]:
    """Consume streaming events and render them via Rich ``Live``.

    Only the growing Markdown answer is tracked inside the ``Live``
    region.  Tool call/result lines and thinking blocks are printed
    directly to the console (outside ``Live``) so they commit to
    terminal scrollback as permanent history and do not cause the live
    region to grow unbounded.

    Thinking deltas typically arrive as many small chunks.  We buffer
    them and flush the buffer as a single dimmed paragraph whenever a
    non-thinking event arrives (text_delta, tool_call, tool_result,
    terminal) or the stream ends.  This keeps thinking output readable
    and free of mid-word line breaks.

    Args:
        events: Async iterator of ``StreamEvent`` from ``HubClient.stream_agent``.
        show_thinking: Whether to render thinking deltas to the console.
            When ``False``, thinking is silently accumulated into the
            result's ``thinking`` list but not displayed.
        console: Optional Rich ``Console`` to print on.  When ``None``,
            a default console is used (test-friendly).

    Returns:
        A tuple of ``(AgentResult, deferred_calls)``.  ``deferred_calls``
        is non-empty when the task was paused for approval (``input_required``
        event).  The caller should present an approval widget and, if the
        user approves, resume by calling ``stream_agent`` again with
        ``approval_decisions``.
    """
    accumulated_text = ""
    accumulated_thinking: list[str] = []
    thinking_buffer = ""
    final_result: AgentResult | None = None
    deferred_calls: list[dict[str, Any]] = []
    # Tracks whether we've printed anything to scrollback so we can decide
    # whether to precede a new block with a blank separator line.  Rich's
    # ``Markdown`` yields its own leading blank line (the implicit top
    # margin) before content, while plain ``Text`` does not.  We emit an
    # explicit separator only for ``Text`` followers so that every two
    # adjacent rendered blocks are separated by exactly one blank line.
    # ``tool_call`` + its ``tool_result`` are treated as a tight pair with
    # no separator between them.
    something_printed = False
    just_printed_tool_call = False

    if console is None:
        console = Console()

    def _build_display() -> Markdown | Status:
        if accumulated_text:
            return Markdown(accumulated_text)
        return Status("Processing…")

    def _separator_before_text(live: Live) -> None:
        """Emit a blank line before a Text-kind renderable if needed."""
        if something_printed:
            live.console.print()

    def _flush_thinking(live: Live) -> None:
        nonlocal thinking_buffer, something_printed, just_printed_tool_call
        if not thinking_buffer:
            return
        if show_thinking:
            block = _format_thinking_block(thinking_buffer)
            if block is not None:
                # Markdown supplies its own leading blank line, so we do
                # not emit a separator before it.
                live.console.print(block)
                something_printed = True
                just_printed_tool_call = False
        thinking_buffer = ""

    with Live(
        Status("Processing…"),
        console=console,
        refresh_per_second=8,
        vertical_overflow="visible",
    ) as live:
        async for event in events:
            if event.kind == "text_delta":
                _flush_thinking(live)
                # ``text_delta`` enters the Live-tracked Markdown region.
                # Live does not pad above itself, so emit a blank line if
                # anything was already printed to scrollback.
                if something_printed and not accumulated_text:
                    live.console.print()
                    something_printed = False  # the separator is the new baseline
                accumulated_text += event.text
                live.update(_build_display())
            elif event.kind == "thinking_delta":
                accumulated_thinking.append(event.text)
                thinking_buffer += event.text
            elif event.kind == "tool_call":
                _flush_thinking(live)
                # Tool call is plain Text — emit a leading blank unless we
                # are at the very top or this tool call immediately follows
                # another tool result (rare but keeps consecutive tool
                # runs visually grouped).
                _separator_before_text(live)
                live.console.print(_format_tool_call(event))
                something_printed = True
                just_printed_tool_call = True
            elif event.kind == "tool_result":
                _flush_thinking(live)
                formatted = _format_tool_result(event)
                if formatted.plain:
                    # When a tool_result immediately follows its tool_call
                    # we skip the separator so the pair reads as one unit.
                    if not just_printed_tool_call:
                        _separator_before_text(live)
                    live.console.print(formatted)
                    something_printed = True
                    just_printed_tool_call = False
            elif event.kind == "input_required":
                _flush_thinking(live)
                deferred_calls.extend(event.deferred_calls)
                if event.result is not None:
                    final_result = event.result
            elif event.result is not None:
                _flush_thinking(live)
                final_result = event.result

        # Final flush for any trailing thinking not followed by another event.
        _flush_thinking(live)

        # Rich's ``Live`` commits its last rendered frame to scrollback on
        # exit (unless ``transient=True``).  When no ``text_delta`` events
        # arrived — e.g. the stream paused for approval, or the agent
        # replied only via tools — we are still rendering the initial
        # ``Status("Processing…")`` spinner, which would otherwise leave
        # a stray spinner frame in the terminal.  Replace the live
        # renderable with empty ``Text`` so nothing is committed.
        if not accumulated_text:
            live.update(Text(""), refresh=True)

    if final_result is not None:
        if accumulated_thinking and not final_result.thinking:
            final_result.thinking = accumulated_thinking
        return final_result, deferred_calls

    return (
        AgentResult(success=False, output=accumulated_text or "No response from agent"),
        deferred_calls,
    )
