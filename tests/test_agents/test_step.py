"""Tests for StepEvent and StepHandle — platform-level step event types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from fin_assist.agents.step import StepEvent, StepHandle


class TestStepEvent:
    def test_text_delta_event(self) -> None:
        event = StepEvent(kind="text_delta", content="hello", step=0)
        assert event.kind == "text_delta"
        assert event.content == "hello"
        assert event.step == 0
        assert event.tool_name is None
        assert event.metadata == {}

    def test_thinking_delta_event(self) -> None:
        event = StepEvent(kind="thinking_delta", content="hmm...", step=0)
        assert event.kind == "thinking_delta"

    def test_tool_call_event(self) -> None:
        event = StepEvent(
            kind="tool_call",
            content={"tool": "read_file", "args": {"path": "/tmp/x"}},
            step=1,
            tool_name="read_file",
        )
        assert event.tool_name == "read_file"

    def test_tool_result_event(self) -> None:
        event = StepEvent(
            kind="tool_result",
            content="file contents here",
            step=1,
            tool_name="read_file",
        )
        assert event.kind == "tool_result"

    def test_step_start_event(self) -> None:
        event = StepEvent(kind="step_start", content=None, step=2)
        assert event.kind == "step_start"

    def test_step_end_event(self) -> None:
        event = StepEvent(kind="step_end", content=None, step=2)
        assert event.kind == "step_end"

    def test_deferred_event(self) -> None:
        event = StepEvent(
            kind="deferred",
            content=None,
            step=1,
            tool_name="rm",
            metadata={"reason": "destructive operation"},
        )
        assert event.kind == "deferred"
        assert event.metadata["reason"] == "destructive operation"

    def test_metadata_defaults_to_empty_dict(self) -> None:
        event = StepEvent(kind="text_delta", content="x", step=0)
        assert event.metadata == {}
        event.metadata["key"] = "val"
        other = StepEvent(kind="text_delta", content="y", step=0)
        assert other.metadata == {}


class _FakeStepHandle:
    def __init__(self, events: list[StepEvent], final_result: Any) -> None:
        self._events = events
        self._result = final_result

    async def __aiter__(self) -> AsyncIterator[StepEvent]:
        for event in self._events:
            yield event

    async def result(self) -> Any:
        return self._result


class TestStepHandle:
    def test_fake_step_handle_satisfies_protocol(self) -> None:
        handle = _FakeStepHandle(events=[], final_result=None)
        assert isinstance(handle, StepHandle)

    @pytest.mark.asyncio
    async def test_iteration_yields_events(self) -> None:
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hi", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        handle = _FakeStepHandle(events=events, final_result="done")
        collected = [e async for e in handle]
        assert len(collected) == 3
        assert collected[0].kind == "step_start"
        assert collected[1].content == "hi"

    @pytest.mark.asyncio
    async def test_result_returns_final_value(self) -> None:
        handle = _FakeStepHandle(events=[], final_result="output")
        result = await handle.result()
        assert result == "output"
