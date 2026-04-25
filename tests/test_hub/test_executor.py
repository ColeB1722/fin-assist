"""Tests for Executor — a2a-sdk AgentExecutor with step-driven dispatch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from a2a.types import Message, Part, Role, TaskState
from google.protobuf.struct_pb2 import Struct

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
        event_list = events if events is not None else ["hello"]
        handle = _FakeStepHandle(
            events=_as_text_events(event_list),
            run_result=result,
        )
        backend.run_steps.return_value = handle

    backend.convert_history.return_value = []
    backend.deserialize_history.return_value = []
    backend.convert_result_to_part.return_value = MagicMock()
    backend.build_deferred_results.return_value = None

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


class TestExecutorDeferredApproval:
    async def test_deferred_event_sets_input_required(self) -> None:
        from fin_assist.agents.tools import DeferredToolCall

        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command execution requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend = _make_backend(
            events=[deferred_event],
            run_result=RunResult(
                output=MagicMock(),
                serialized_history=b"[]",
                new_message_parts=[],
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

        input_required_updates = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        ]
        assert len(input_required_updates) >= 1

    async def test_deferred_event_emits_artifact_with_metadata(self) -> None:
        from google.protobuf.json_format import MessageToDict

        from fin_assist.agents.tools import DeferredToolCall

        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command execution requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend = _make_backend(
            events=[deferred_event],
            run_result=RunResult(
                output=MagicMock(),
                serialized_history=b"[]",
                new_message_parts=[],
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

        artifact_calls = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        deferred_artifacts = []
        for call in artifact_calls:
            event = call.args[0]
            for part in event.artifact.parts:
                meta_dict = (
                    MessageToDict(part.metadata, preserving_proto_field_name=True)
                    if part.HasField("metadata")
                    else {}
                )
                if meta_dict.get("type") == "deferred":
                    deferred_artifacts.append((part, meta_dict))

        assert len(deferred_artifacts) == 1
        part, meta = deferred_artifacts[0]
        assert meta["tool_name"] == "run_shell"
        assert meta["tool_call_id"] == "call_1"
        assert meta["reason"] == "Shell command execution requires approval"

    async def test_deferred_saves_context_before_pausing(self) -> None:
        from fin_assist.agents.tools import DeferredToolCall

        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "ls"},
                reason="requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend = _make_backend(
            events=[deferred_event],
            run_result=RunResult(
                output=MagicMock(),
                serialized_history=b'{"deferred": true}',
                new_message_parts=[],
            ),
        )
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context(context_id="ctx-deferred")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        context_store.save.assert_called_once_with("ctx-deferred", b'{"deferred": true}')

    async def test_deferred_does_not_complete_task(self) -> None:
        from fin_assist.agents.tools import DeferredToolCall

        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "ls"},
            ),
            step=0,
            tool_name="run_shell",
        )
        backend = _make_backend(
            events=[deferred_event],
            run_result=RunResult(
                output=MagicMock(),
                serialized_history=b"[]",
                new_message_parts=[],
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

        completed_updates = [
            call
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "status")
            and call.args[0].status.state == TaskState.TASK_STATE_COMPLETED
        ]
        assert len(completed_updates) == 0


class TestExecutorExtractApprovalResults:
    def test_returns_none_when_no_message(self) -> None:
        backend = _make_backend()
        context_store = MagicMock()
        executor = Executor(backend=backend, context_store=context_store)
        result = executor._extract_approval_results(None)
        assert result is None

    def test_returns_none_when_no_parts(self) -> None:
        from a2a.types import Message

        backend = _make_backend()
        context_store = MagicMock()
        executor = Executor(backend=backend, context_store=context_store)
        msg = Message(message_id="m1", role=Role.ROLE_USER, parts=[])
        result = executor._extract_approval_results(msg)
        assert result is None

    def test_returns_none_when_no_approval_result_metadata(self) -> None:
        from a2a.types import Message

        backend = _make_backend()
        context_store = MagicMock()
        executor = Executor(backend=backend, context_store=context_store)
        msg = Message(
            message_id="m1",
            role=Role.ROLE_USER,
            parts=[Part(text="just a regular message")],
        )
        result = executor._extract_approval_results(msg)
        assert result is None

    def test_extracts_approval_decisions_and_calls_build_deferred_results(self) -> None:
        from a2a.types import Message

        from google.protobuf.struct_pb2 import Struct

        backend = _make_backend()
        mock_deferred_results = MagicMock()
        backend.build_deferred_results.return_value = mock_deferred_results
        context_store = MagicMock()
        executor = Executor(backend=backend, context_store=context_store)

        meta = Struct()
        meta.update(
            {
                "type": "approval_result",
                "decisions": [
                    {
                        "tool_call_id": "call_1",
                        "approved": True,
                    },
                    {
                        "tool_call_id": "call_2",
                        "approved": False,
                        "denial_reason": "User denied",
                    },
                ],
            }
        )
        msg = Message(
            message_id="m1",
            role=Role.ROLE_USER,
            parts=[Part(text="", metadata=meta)],
        )
        result = executor._extract_approval_results(msg)

        backend.build_deferred_results.assert_called_once()
        decisions = backend.build_deferred_results.call_args[0][0]
        assert len(decisions) == 2
        assert decisions[0].tool_call_id == "call_1"
        assert decisions[0].approved is True
        assert decisions[1].tool_call_id == "call_2"
        assert decisions[1].approved is False
        assert decisions[1].denial_reason == "User denied"
        assert result is mock_deferred_results

    def test_ignores_non_approval_result_parts(self) -> None:
        from a2a.types import Message

        backend = _make_backend()
        context_store = MagicMock()
        executor = Executor(backend=backend, context_store=context_store)

        thinking_meta = Struct()
        thinking_meta.update({"type": "thinking"})
        msg = Message(
            message_id="m1",
            role=Role.ROLE_USER,
            parts=[Part(text="thinking text", metadata=thinking_meta)],
        )
        result = executor._extract_approval_results(msg)
        assert result is None


class TestExecutorResumeWithApprovalResults:
    async def test_resume_calls_run_steps_with_deferred_tool_results(self) -> None:
        mock_deferred_results = MagicMock()
        backend = _make_backend()
        backend.build_deferred_results.return_value = mock_deferred_results
        backend.deserialize_history.return_value = [MagicMock()]
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=b"[serialized]")
        context_store.save = AsyncMock()

        meta = Struct()
        meta.update(
            {
                "type": "approval_result",
                "decisions": [
                    {"tool_call_id": "call_1", "approved": True},
                ],
            }
        )
        resume_message = Message(
            message_id="m2",
            role=Role.ROLE_USER,
            parts=[Part(text="", metadata=meta)],
        )

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context(context_id="ctx-resume")
        ctx.message = resume_message
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        backend.run_steps.assert_called_once()
        call_kwargs = backend.run_steps.call_args.kwargs
        assert "deferred_tool_results" in call_kwargs
        assert call_kwargs["deferred_tool_results"] is mock_deferred_results


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


class TestExecutorToolCallDispatch:
    async def test_tool_call_event_emits_artifact_with_metadata(self) -> None:
        from google.protobuf.json_format import MessageToDict

        tool_call_event = StepEvent(
            kind="tool_call",
            content=MagicMock(),
            step=0,
            tool_name="read_file",
            metadata={"args": {"path": "test.py"}},
        )
        backend = _make_backend(events=[tool_call_event])
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
        tool_call_artifacts = []
        for call in artifact_calls:
            event = call.args[0]
            for part in event.artifact.parts:
                meta_dict = (
                    MessageToDict(part.metadata, preserving_proto_field_name=True)
                    if part.HasField("metadata")
                    else {}
                )
                if meta_dict.get("type") == "tool_call":
                    tool_call_artifacts.append((part, meta_dict))

        assert len(tool_call_artifacts) == 1
        part, meta = tool_call_artifacts[0]
        assert meta["tool_name"] == "read_file"
        assert "path" in part.text

    async def test_tool_result_event_emits_artifact_with_metadata(self) -> None:
        from google.protobuf.json_format import MessageToDict

        mock_content = MagicMock()
        mock_content.content = "file contents here"
        tool_result_event = StepEvent(
            kind="tool_result",
            content=mock_content,
            step=0,
            tool_name="read_file",
        )
        backend = _make_backend(events=[tool_result_event])
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
        tool_result_artifacts = []
        for call in artifact_calls:
            event = call.args[0]
            for part in event.artifact.parts:
                meta_dict = (
                    MessageToDict(part.metadata, preserving_proto_field_name=True)
                    if part.HasField("metadata")
                    else {}
                )
                if meta_dict.get("type") == "tool_result":
                    tool_result_artifacts.append((part, meta_dict))

        assert len(tool_result_artifacts) == 1
        part, meta = tool_result_artifacts[0]
        assert meta["tool_name"] == "read_file"
        assert part.text == "file contents here"


class TestExecutorArtifactAppendSemantics:
    """Verify that the first artifact chunk uses append=False and subsequent
    chunks use append=True.  This ensures the A2A TaskManager correctly
    stores artifacts instead of silently dropping the first chunk.
    """

    async def test_first_artifact_uses_append_false(self) -> None:
        backend = _make_backend(events=["hello"])
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        artifact_events = [
            call.args[0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        assert len(artifact_events) >= 1
        assert artifact_events[0].append is False

    async def test_subsequent_artifacts_use_append_true(self) -> None:
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
            call.args[0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        assert len(artifact_events) >= 2
        assert artifact_events[0].append is False
        for evt in artifact_events[1:]:
            assert evt.append is True

    async def test_thinking_first_then_text_uses_correct_append(self) -> None:
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

        artifact_events = [
            call.args[0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        assert len(artifact_events) >= 2
        assert artifact_events[0].append is False
        assert artifact_events[1].append is True

    async def test_no_events_final_chunk_uses_append_false(self) -> None:
        backend = _make_backend(events=[])
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(backend=backend, context_store=context_store)
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        artifact_events = [
            call.args[0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        assert len(artifact_events) >= 1
        final_chunk = artifact_events[-1]
        assert final_chunk.append is False
        assert final_chunk.last_chunk is True

    async def test_structured_output_artifact_uses_append_false(self) -> None:
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

        artifact_events = [
            call.args[0]
            for call in event_queue.enqueue_event.call_args_list
            if hasattr(call.args[0], "artifact")
        ]
        artifact_ids = [evt.artifact.artifact_id for evt in artifact_events]
        assert len(set(artifact_ids)) >= 2
        structured_event = next(
            evt
            for evt in artifact_events
            if any(p.text == "structured output" for p in evt.artifact.parts)
        )
        assert structured_event.append is False
