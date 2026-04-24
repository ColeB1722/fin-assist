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
        final = await render_stream(events)
        assert final.success is True
        assert final.output == "hello world"

    async def test_returns_accumulated_text_when_no_terminal_event(self):
        events = _events(
            StreamEvent(kind="text_delta", text="partial"),
        )
        final = await render_stream(events)
        assert final.success is False
        assert final.output == "partial"

    async def test_returns_no_response_when_empty(self):
        events = _events()
        final = await render_stream(events)
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
        final = await render_stream(events)
        assert final.thinking == ["hmm...", "let me think"]

    async def test_thinking_not_overwritten_if_result_already_has_it(self):
        result = AgentResult(success=True, output="answer", thinking=["from result"])
        events = _events(
            StreamEvent(kind="thinking_delta", text="streamed"),
            StreamEvent(kind="text_delta", text="answer"),
            StreamEvent(kind="completed", result=result),
        )
        final = await render_stream(events)
        assert final.thinking == ["from result"]

    async def test_thinking_accumulated_when_show_thinking_false(self):
        result = AgentResult(success=True, output="answer")
        events = _events(
            StreamEvent(kind="thinking_delta", text="hmm..."),
            StreamEvent(kind="text_delta", text="answer"),
            StreamEvent(kind="completed", result=result),
        )
        final = await render_stream(events, show_thinking=False)
        assert final.thinking == ["hmm..."]


class TestRenderStreamFailed:
    async def test_failed_event_returns_result(self):
        result = AgentResult(success=False, output="something broke")
        events = _events(
            StreamEvent(kind="failed", result=result),
        )
        final = await render_stream(events)
        assert final.success is False
        assert final.output == "something broke"

    async def test_auth_required_event_returns_result(self):
        result = AgentResult(success=False, output="missing key", auth_required=True)
        events = _events(
            StreamEvent(kind="auth_required", result=result),
        )
        final = await render_stream(events)
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
        final = await render_stream(events)
        assert final.thinking == ["step 1", "step 2"]
        assert final.output == "the answer"
