"""Tests for cli/interaction/streaming.py — render_stream."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from fin_assist.agents.metadata import AgentResult
from fin_assist.cli.client import StreamEvent
from fin_assist.cli.interaction.streaming import render_stream


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
                    {"tool_name": "run_shell", "tool_call_id": "call_1", "args": {"command": "ls"}}
                ],
            ),
        )
        final, deferred = await render_stream(events)
        assert len(deferred) == 1
        assert deferred[0]["tool_name"] == "run_shell"

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
                deferred_calls=[{"tool_name": "run_shell", "tool_call_id": "c1"}],
            ),
        )
        final, deferred = await render_stream(events)
        assert len(deferred) == 1
        assert "partial" in final.output
