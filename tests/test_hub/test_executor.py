"""Tests for Executor — a2a-sdk AgentExecutor with step-driven dispatch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from a2a.types import TaskState

from fin_assist.agents.backend import RunResult
from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.step import StepEvent
from fin_assist.hub.executor import Executor


class _FakeStepHandle:
    def __init__(self, events: list[StepEvent], run_result: RunResult) -> None:
        self._events = events
        self._run_result = run_result

    async def __aiter__(self) -> AsyncIterator[StepEvent]:
        for event in self._events:
            yield event

    async def result(self) -> RunResult:
        return self._run_result


def _as_text_events(items: list[str] | list[StepEvent]) -> list[StepEvent]:
    """Lift plain strings into text_delta StepEvents; pass StepEvents through."""
    return [
        e if isinstance(e, StepEvent) else StepEvent(kind="text_delta", content=e, step=0)
        for e in items
    ]


def _make_backend(
    *,
    missing_providers: list[str] | None = None,
    events: list[str] | list[StepEvent] | None = None,
    run_result: RunResult | None = None,
    run_side_effect: Exception | None = None,
) -> MagicMock:
    backend = MagicMock()

    if missing_providers is not None:
        backend.check_credentials.return_value = missing_providers
    else:
        backend.check_credentials.return_value = []

    if run_side_effect is not None:
        backend.run_steps.side_effect = run_side_effect
    else:
        result = run_result or RunResult(
            output="hello",
            serialized_history=b"[]",
            new_message_parts=[],
        )
        handle = _FakeStepHandle(
            events=_as_text_events(events or ["hello"]),
            run_result=result,
        )
        backend.run_steps.return_value = handle

    backend.convert_history.return_value = []
    backend.deserialize_history.return_value = []
    backend.convert_result_to_part.return_value = MagicMock()

    return backend


def _make_request_context(*, task_id: str = "task-1", context_id: str = "ctx-1"):
    context = MagicMock()
    context.task_id = task_id
    context.context_id = context_id
    context.message = None
    return context


class TestExecutorAuthRequired:
    async def test_sets_auth_required_on_missing_credentials(self) -> None:
        backend = _make_backend(missing_providers=["anthropic"])
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        status_updates = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_AUTH_REQUIRED
        ]
        assert len(status_updates) >= 1
        msg = status_updates[0].args[0].status.message
        assert len(msg.parts) >= 1
        assert any("anthropic" in p.text.lower() for p in msg.parts if p.text)

    async def test_other_exceptions_still_set_failed(self) -> None:
        backend = _make_backend(run_side_effect=RuntimeError("something broke"))
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        with pytest.raises(RuntimeError, match="something broke"):
            await executor.execute(ctx, event_queue)

        failed_updates = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_FAILED
        ]
        assert len(failed_updates) >= 1

    async def test_successful_task_completes(self) -> None:
        backend = _make_backend()
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        completed_updates = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_COMPLETED
        ]
        assert len(completed_updates) >= 1

    async def test_saves_context_after_success(self) -> None:
        backend = _make_backend(
            run_result=RunResult(
                output="hello",
                serialized_history=b'{"serialized": true}',
                new_message_parts=[],
            ),
        )
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context(context_id="ctx-save-test")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        context_store.save.assert_called_once()
        call_args = context_store.save.call_args
        assert call_args[0][0] == "ctx-save-test"
        assert call_args[0][1] == b'{"serialized": true}'

    async def test_streaming_produces_artifact_chunks(self) -> None:
        backend = _make_backend(events=["hel", "lo"])
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        artifact_events = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        assert len(artifact_events) >= 2

    async def test_loads_and_deserializes_history(self) -> None:
        serialized = b'["history_data"]'
        deserialized = [MagicMock()]

        backend = _make_backend()
        backend.deserialize_history.return_value = deserialized
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=serialized)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context(context_id="ctx-with-history")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        backend.deserialize_history.assert_called_once_with(serialized)
        context_store.load.assert_called_once_with("ctx-with-history")

    async def test_structured_output_creates_artifact(self) -> None:
        from a2a.types import Part

        result_part = Part(text="structured output")
        backend = _make_backend(
            run_result=RunResult(
                output={"command": "ls"},
                serialized_history=b"[]",
                new_message_parts=[],
            ),
        )
        backend.convert_result_to_part.return_value = result_part
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        backend.convert_result_to_part.assert_called_once_with({"command": "ls"})

    async def test_no_working_status_updates_for_message_parts(self) -> None:
        from a2a.types import Part

        thinking_part = Part(text="thinking...")
        backend = _make_backend(
            run_result=RunResult(
                output="hello",
                serialized_history=b"[]",
                new_message_parts=[thinking_part],
            ),
        )
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        working_with_message = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_WORKING
            and call.args[0].status.HasField("message")
        ]
        assert len(working_with_message) == 0


class TestExecutorThinkingViaArtifacts:
    """Thinking deltas route through add_artifact with metadata, not status-update messages."""

    async def test_thinking_delta_produces_artifact_with_metadata(self) -> None:
        from google.protobuf.json_format import MessageToDict

        thinking_event = StepEvent(kind="thinking_delta", content="hmm...", step=0)
        text_event = StepEvent(kind="text_delta", content="answer", step=0)
        backend = _make_backend(events=[thinking_event, text_event])
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        artifact_calls = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        thinking_artifacts = []
        for call in artifact_calls:
            event = call.args[0]
            for part in event.artifact.parts:
                meta_dict = (
                    MessageToDict(part.metadata, preserving_proto_field_name=True)
                    if part.HasField("metadata")
                    else {}
                )
                if meta_dict.get("type") == "thinking":
                    thinking_artifacts.append(part)

        assert len(thinking_artifacts) == 1
        assert thinking_artifacts[0].text == "hmm..."

    async def test_text_delta_artifact_has_no_thinking_metadata(self) -> None:
        from google.protobuf.json_format import MessageToDict

        text_event = StepEvent(kind="text_delta", content="answer", step=0)
        backend = _make_backend(events=[text_event])
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        artifact_calls = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        for call in artifact_calls:
            event = call.args[0]
            for part in event.artifact.parts:
                if not part.text:
                    continue
                meta_dict = (
                    MessageToDict(part.metadata, preserving_proto_field_name=True)
                    if part.HasField("metadata")
                    else {}
                )
                assert meta_dict.get("type") != "thinking"


class TestExecutorCancel:
    async def test_cancel_publishes_canceled_status(self) -> None:
        backend = _make_backend()
        context_store = MagicMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.cancel(ctx, event_queue)

        cancel_updates = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_CANCELED
        ]
        assert len(cancel_updates) == 1
