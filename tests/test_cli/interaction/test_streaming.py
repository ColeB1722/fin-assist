"""Tests for cli/interaction/streaming.py — render_stream."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from fin_assist.agents.metadata import AgentResult
from fin_assist.agents.tools import DeferredToolCall
from fin_assist.cli.client import StreamEvent
from fin_assist.cli.interaction.streaming import (
    _format_thinking_block,
    _format_tool_call,
    _format_tool_result,
    render_stream,
)


async def _events(*events: StreamEvent) -> AsyncIterator[StreamEvent]:
    for event in events:
        yield event


class TestRenderStreamTextOnly:
    async def test_returns_result_from_completed_event(self):
        result = AgentResult(success=True, output="hello world")
        events = _events(
            StreamEvent(kind="text_delta", text="hello "),
            StreamEvent(kind="text_delta", text="world"),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.success is True
        assert final.output == "hello world"

    async def test_returns_accumulated_text_when_no_terminal_event(self):
        events = _events(
            StreamEvent(kind="text_delta", text="partial"),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.success is False
        assert final.output == "partial"

    async def test_returns_no_response_when_empty(self):
        events = _events()
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.success is False
        assert "No response" in final.output


class TestRenderStreamThinking:
    async def test_thinking_accumulated_into_result(self):
        result = AgentResult(success=True, output="answer")
        events = _events(
            StreamEvent(kind="thinking_delta", text="hmm..."),
            StreamEvent(kind="thinking_delta", text="let me think"),
            StreamEvent(kind="text_delta", text="answer"),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.thinking == ["hmm...", "let me think"]

    async def test_thinking_not_overwritten_if_result_already_has_it(self):
        result = AgentResult(success=True, output="answer", thinking=["from result"])
        events = _events(
            StreamEvent(kind="thinking_delta", text="streamed"),
            StreamEvent(kind="text_delta", text="answer"),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.thinking == ["from result"]

    async def test_thinking_accumulated_when_show_thinking_false(self):
        result = AgentResult(success=True, output="answer")
        events = _events(
            StreamEvent(kind="thinking_delta", text="hmm..."),
            StreamEvent(kind="text_delta", text="answer"),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events, show_thinking=False)
        assert deferred == []
        assert final.thinking == ["hmm..."]


class TestRenderStreamFailed:
    async def test_failed_event_returns_result(self):
        result = AgentResult(success=False, output="something broke")
        events = _events(
            StreamEvent(kind="failed", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.success is False
        assert final.output == "something broke"

    async def test_auth_required_event_returns_result(self):
        result = AgentResult(success=False, output="missing key", auth_required=True)
        events = _events(
            StreamEvent(kind="auth_required", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.auth_required is True


class TestRenderStreamInterleaved:
    async def test_interleaved_thinking_and_text(self):
        result = AgentResult(success=True, output="the answer")
        events = _events(
            StreamEvent(kind="thinking_delta", text="step 1"),
            StreamEvent(kind="text_delta", text="partial "),
            StreamEvent(kind="thinking_delta", text="step 2"),
            StreamEvent(kind="text_delta", text="answer"),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.thinking == ["step 1", "step 2"]
        assert final.output == "the answer"


class TestRenderStreamInputRequired:
    async def test_input_required_returns_deferred_calls(self):
        result = AgentResult(success=False, output="waiting", context_id="ctx-1")
        events = _events(
            StreamEvent(kind="text_delta", text="thinking about it..."),
            StreamEvent(
                kind="input_required",
                result=result,
                deferred_calls=[
                    DeferredToolCall(
                        tool_name="run_shell",
                        tool_call_id="call_1",
                        args={"command": "ls"},
                    )
                ],
            ),
        )
        final, deferred = await render_stream(events)
        assert len(deferred) == 1
        assert deferred[0].tool_name == "run_shell"

    async def test_input_required_returns_result(self):
        result = AgentResult(success=False, output="waiting", context_id="ctx-1")
        events = _events(
            StreamEvent(
                kind="input_required",
                result=result,
                deferred_calls=[],
            ),
        )
        final, deferred = await render_stream(events)
        assert final.context_id == "ctx-1"

    async def test_input_required_with_no_result_uses_accumulated_text(self):
        events = _events(
            StreamEvent(kind="text_delta", text="partial response"),
            StreamEvent(
                kind="input_required",
                deferred_calls=[
                    DeferredToolCall(tool_name="run_shell", tool_call_id="c1", args={})
                ],
            ),
        )
        final, deferred = await render_stream(events)
        assert len(deferred) == 1
        assert "partial" in final.output


class TestFormatToolCall:
    def test_run_shell_shows_command(self):
        event = StreamEvent(
            kind="tool_call",
            tool_name="run_shell",
            tool_args={"command": "ls -F"},
        )
        rendered = _format_tool_call(event)
        plain = rendered.plain
        assert "run_shell" in plain
        assert "ls -F" in plain

    def test_read_file_shows_path(self):
        event = StreamEvent(
            kind="tool_call",
            tool_name="read_file",
            tool_args={"path": "treefmt.toml"},
        )
        rendered = _format_tool_call(event)
        plain = rendered.plain
        assert "read_file" in plain
        assert "treefmt.toml" in plain

    def test_unknown_tool_uses_fallback_icon(self):
        event = StreamEvent(
            kind="tool_call",
            tool_name="custom_tool",
            tool_args={"query": "search"},
        )
        rendered = _format_tool_call(event)
        plain = rendered.plain
        assert "custom_tool" in plain
        assert "🔧" in plain

    def test_git_diff_no_key_arg(self):
        event = StreamEvent(
            kind="tool_call",
            tool_name="git_diff",
            tool_args={},
        )
        rendered = _format_tool_call(event)
        plain = rendered.plain
        assert "git_diff" in plain
        assert ":" not in plain.split("git_diff", 1)[1]


class TestFormatToolResult:
    def test_single_line_result(self):
        event = StreamEvent(
            kind="tool_result",
            text="No uncommitted changes",
            tool_name="git_diff",
        )
        rendered = _format_tool_result(event)
        plain = rendered.plain
        assert "No uncommitted changes" in plain

    def test_multiline_result_shows_line_count(self):
        event = StreamEvent(
            kind="tool_result",
            text="line1\nline2\nline3",
            tool_name="run_shell",
        )
        rendered = _format_tool_result(event)
        plain = rendered.plain
        assert "3 lines" in plain
        assert "line1" in plain

    def test_empty_result_produces_no_output(self):
        event = StreamEvent(
            kind="tool_result",
            text="",
            tool_name="run_shell",
        )
        rendered = _format_tool_result(event)
        assert rendered.plain == ""

    def test_long_single_line_truncated(self):
        event = StreamEvent(
            kind="tool_result",
            text="x" * 200,
            tool_name="run_shell",
        )
        rendered = _format_tool_result(event)
        plain = rendered.plain
        assert "…" in plain
        assert len(plain) < 200


class TestRenderStreamToolEvents:
    async def test_tool_call_and_result_interleaved_with_text(self):
        result = AgentResult(success=True, output="the answer")
        events = _events(
            StreamEvent(kind="text_delta", text="Let me check...\n"),
            StreamEvent(
                kind="tool_call",
                tool_name="run_shell",
                tool_args={"command": "ls -F"},
            ),
            StreamEvent(
                kind="tool_result",
                text="AGENTS.md  README.md",
                tool_name="run_shell",
            ),
            StreamEvent(kind="text_delta", text="Here's what I found."),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events)
        assert deferred == []
        assert final.success is True

    async def test_tool_call_event_does_not_pollute_text(self):
        result = AgentResult(success=True, output="done")
        events = _events(
            StreamEvent(
                kind="tool_call",
                tool_name="read_file",
                tool_args={"path": "config.toml"},
            ),
            StreamEvent(
                kind="tool_result",
                text="[global]\nexcludes = []",
                tool_name="read_file",
            ),
            StreamEvent(kind="text_delta", text="The config is fine."),
            StreamEvent(kind="completed", result=result),
        )
        final, deferred = await render_stream(events)
        assert final.success is True
        assert "config.toml" not in final.output


class TestFormatThinkingBlock:
    def test_empty_buffer_returns_none(self):
        assert _format_thinking_block("") is None
        assert _format_thinking_block("   \n  \n") is None

    def test_prefixes_first_line_with_emoji(self):
        block = _format_thinking_block("let me think")
        assert block is not None
        assert block.markup.startswith("> 💭 ")

    def test_each_line_prefixed_with_quote_marker(self):
        block = _format_thinking_block("line one\nline two\nline three")
        assert block is not None
        # Every line in the rendered markdown should be a blockquote line.
        for line in block.markup.splitlines():
            assert line.startswith(">"), f"unquoted line: {line!r}"

    def test_single_emoji_on_first_line_only(self):
        block = _format_thinking_block("first\nsecond")
        assert block is not None
        # 💭 should only appear once, on the first line.
        assert block.markup.count("💭") == 1

    def test_uses_dim_style(self):
        block = _format_thinking_block("thought")
        assert block is not None
        # Rich Markdown exposes style via its constructor; confirm dim set.
        assert block.style == "dim"
