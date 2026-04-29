"""Tests for OTel tracing in the fin-assist hub.

Uses InMemorySpanExporter to assert on span emission, hierarchy, and
attributes without needing a running Phoenix or OTLP backend.

Tests are structured around the Executor's lifecycle:
- setup_tracing() initialization
- Task span lifecycle (fin_assist.task)
- Step span lifecycle (fin_assist.step)
- Tool execution span (fin_assist.tool_execution)
- Approval span (fin_assist.approval)
- Span hierarchy (parent-child relationships)
- OpenInference semantic conventions (span kinds, input/output, session)
- Phoenix unreachable (graceful degradation)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from opentelemetry.trace import StatusCode

from fin_assist.agents.backend import RunResult
from fin_assist.agents.step import StepEvent
from fin_assist.agents.tools import DeferredToolCall
from fin_assist.config.schema import TracingSettings
from fin_assist.hub.executor import Executor
from fin_assist.hub.tracing import setup_tracing


class _FakeStepHandle:
    def __init__(self, events: list[StepEvent], run_result: RunResult) -> None:
        self._events = events
        self._run_result = run_result

    async def __aiter__(self) -> AsyncIterator[StepEvent]:
        for event in self._events:
            yield event

    async def result(self) -> RunResult:
        return self._run_result


def _make_backend(
    *,
    events: list[StepEvent] | None = None,
    run_result: RunResult | None = None,
    missing_providers: list[str] | None = None,
) -> MagicMock:
    backend = MagicMock()
    backend.check_credentials.return_value = missing_providers or []
    backend.convert_history.return_value = []
    backend.deserialize_history.return_value = []
    backend.build_deferred_results.return_value = None
    backend.convert_result_to_part.return_value = MagicMock()

    result = run_result or RunResult(output="hello", serialized_history=b"[]")
    event_list = events or [StepEvent(kind="text_delta", content="hello", step=0)]
    handle = _FakeStepHandle(events=event_list, run_result=result)
    backend.run_steps.return_value = handle
    return backend


def _make_request_context(
    *, task_id: str = "task-1", context_id: str = "ctx-1", user_input: str = ""
):
    context = MagicMock()
    context.task_id = task_id
    context.context_id = context_id
    if user_input:
        msg = MagicMock()
        msg.parts = []
        msg.get_user_input.return_value = user_input
        context.message = msg
    else:
        context.message = None
    return context


@pytest.fixture
async def execute_with_tracing(tracing_setup):
    """Factory fixture that runs the executor with tracing and returns the tracing_setup dict."""

    async def _run(
        *,
        events: list[StepEvent] | None = None,
        run_result: RunResult | None = None,
        agent_name: str = "test",
        task_id: str = "task-1",
        context_id: str = "ctx-1",
        user_input: str = "",
    ):
        tracing_setup["clear"]()

        backend = _make_backend(events=events, run_result=run_result)
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name=agent_name,
        )
        ctx = _make_request_context(task_id=task_id, context_id=context_id, user_input=user_input)
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)
        return tracing_setup

    return _run


class TestSetupTracing:
    """Tests for setup_tracing() — these run without the tracing_setup fixture
    because setup_tracing() sets its own global TracerProvider.

    Note: OTel's set_tracer_provider() only allows setting once per process,
    so these tests verify structural properties rather than global state.
    """

    def test_noop_when_disabled(self):
        config = TracingSettings(enabled=False)
        assert setup_tracing(config) is None

    def test_setup_tracing_does_not_raise_with_unreachable_endpoint(self):
        config = TracingSettings(
            enabled=True,
            endpoint="http://localhost:9999",
        )
        try:
            assert setup_tracing(config) is None
        finally:
            from opentelemetry.trace import get_tracer_provider

            provider = get_tracer_provider()
            for method in ("force_flush", "shutdown"):
                fn = getattr(provider, method, None)
                if fn:
                    try:
                        fn(1) if method == "force_flush" else fn()
                    except Exception:
                        pass
            from opentelemetry.trace import ProxyTracerProvider

            import opentelemetry.trace as _trace_mod

            _trace_mod._TRACER_PROVIDER = ProxyTracerProvider()


class TestTaskSpanLifecycle:
    """The fin_assist.task span wraps the entire executor run."""

    async def test_task_span_created_on_execute(self, execute_with_tracing):
        ts = await execute_with_tracing(
            agent_name="test-agent", task_id="task-abc", context_id="ctx-xyz"
        )
        task_spans = ts["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1

    async def test_task_span_has_agent_name_attribute(self, execute_with_tracing):
        ts = await execute_with_tracing(agent_name="git")
        task_spans = ts["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1
        assert task_spans[0].attributes.get("gen_ai.agent.name") == "git"

    async def test_task_span_has_task_id_attribute(self, execute_with_tracing):
        ts = await execute_with_tracing(task_id="task-123")
        task_spans = ts["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("fin_assist.task.id") == "task-123"

    async def test_task_span_has_context_id_attribute(self, execute_with_tracing):
        ts = await execute_with_tracing(context_id="ctx-456")
        task_spans = ts["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("fin_assist.context.id") == "ctx-456"

    async def test_task_span_is_ended(self, execute_with_tracing):
        ts = await execute_with_tracing()
        task_spans = ts["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1
        assert task_spans[0].end_time is not None

    async def test_task_span_has_error_status_on_exception(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend()
        backend.run_steps.side_effect = RuntimeError("test error")

        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="test",
        )
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        with pytest.raises(RuntimeError, match="test error"):
            await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1
        assert task_spans[0].status.status_code == StatusCode.ERROR


class TestOpenInferenceAttributes:
    """OpenInference semantic conventions for Phoenix rendering."""

    async def test_task_span_has_agent_kind(self, execute_with_tracing):
        ts = await execute_with_tracing()
        task_spans = ts["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("openinference.span.kind") == "AGENT"

    async def test_task_span_has_input_value(self, execute_with_tracing):
        ts = await execute_with_tracing()
        task_spans = ts["get_spans"]("fin_assist.task")
        assert "input.value" in task_spans[0].attributes

    async def test_task_span_has_output_value_on_success(self, execute_with_tracing):
        ts = await execute_with_tracing(
            run_result=RunResult(output="here are the files", serialized_history=b"[]"),
        )
        task_spans = ts["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("output.value") == "here are the files"

    async def test_task_span_has_partial_output_on_error(self, tracing_setup):
        tracing_setup["clear"]()

        class _FailingHandle:
            async def __aiter__(self):
                yield StepEvent(kind="text_delta", content="partial ", step=0)
                yield StepEvent(kind="text_delta", content="response", step=0)

            async def result(self):
                raise RuntimeError("broke")

        backend = MagicMock()
        backend.check_credentials.return_value = []
        backend.convert_history.return_value = []
        backend.deserialize_history.return_value = []
        backend.run_steps.return_value = _FailingHandle()

        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="test",
        )
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        with pytest.raises(RuntimeError, match="broke"):
            await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("output.value") == "partial response"

    async def test_task_span_has_session_id(self, execute_with_tracing):
        ts = await execute_with_tracing(context_id="session-abc")
        task_spans = ts["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("session.id") == "session-abc"

    async def test_step_span_has_chain_kind(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        step_spans = ts["get_spans"]("fin_assist.step")
        assert step_spans[0].attributes.get("openinference.span.kind") == "CHAIN"

    async def test_tool_span_has_tool_kind(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="git",
                metadata={"args": {"subcommand": "diff"}},
            ),
            StepEvent(
                kind="tool_result",
                content="M file.py",
                step=0,
                tool_name="git",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert tool_spans[0].attributes.get("openinference.span.kind") == "TOOL"

    async def test_tool_span_has_tool_name(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="run_shell",
                metadata={"args": {"command": "ls"}},
            ),
            StepEvent(
                kind="tool_result",
                content="file1.txt\nfile2.txt",
                step=0,
                tool_name="run_shell",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert tool_spans[0].attributes.get("tool.name") == "run_shell"

    async def test_tool_span_has_input_value(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="git",
                metadata={"args": {"subcommand": "status"}},
            ),
            StepEvent(
                kind="tool_result",
                content="clean",
                step=0,
                tool_name="git",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert tool_spans[0].attributes.get("input.value") is not None
        assert tool_spans[0].attributes.get("input.mime_type") == "json"

    async def test_tool_span_has_output_value(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="git",
                metadata={"args": "diff"},
            ),
            StepEvent(
                kind="tool_result",
                content="M file.py",
                step=0,
                tool_name="git",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert tool_spans[0].attributes.get("output.value") == "M file.py"

    async def test_approval_span_has_tool_kind(self, execute_with_tracing):
        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        ts = await execute_with_tracing(
            events=[deferred_event],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        approval_spans = ts["get_spans"]("fin_assist.approval")
        assert approval_spans[0].attributes.get("openinference.span.kind") == "TOOL"

    async def test_approval_span_has_tool_name(self, execute_with_tracing):
        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        ts = await execute_with_tracing(
            events=[deferred_event],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        approval_spans = ts["get_spans"]("fin_assist.approval")
        assert approval_spans[0].attributes.get("tool.name") == "run_shell"

    async def test_approval_span_has_input_value(self, execute_with_tracing):
        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        ts = await execute_with_tracing(
            events=[deferred_event],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        approval_spans = ts["get_spans"]("fin_assist.approval")
        assert approval_spans[0].attributes.get("input.value") is not None
        assert approval_spans[0].attributes.get("input.mime_type") == "json"


class TestStepSpanLifecycle:
    """The fin_assist.step span wraps each step boundary."""

    async def test_step_span_created_for_step_start_end(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        step_spans = ts["get_spans"]("fin_assist.step")
        assert len(step_spans) == 1

    async def test_step_span_has_step_number_attribute(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        step_spans = ts["get_spans"]("fin_assist.step")
        assert step_spans[0].attributes.get("fin_assist.step.number") == 0

    async def test_multiple_steps_create_multiple_step_spans(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
            StepEvent(kind="step_start", content=None, step=1),
            StepEvent(kind="text_delta", content="world", step=1),
            StepEvent(kind="step_end", content=None, step=1),
        ]
        ts = await execute_with_tracing(events=events)
        step_spans = ts["get_spans"]("fin_assist.step")
        assert len(step_spans) == 2
        assert step_spans[0].attributes.get("fin_assist.step.number") == 0
        assert step_spans[1].attributes.get("fin_assist.step.number") == 1


class TestToolExecutionSpan:
    """The fin_assist.tool_execution span wraps tool_call -> tool_result pairs."""

    async def test_tool_execution_span_created(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="git",
                metadata={"args": "diff"},
            ),
            StepEvent(
                kind="tool_result",
                content="diff output",
                step=0,
                tool_name="git",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert len(tool_spans) == 1

    async def test_tool_execution_span_has_name_and_args_attributes(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="git",
                metadata={"args": "diff"},
            ),
            StepEvent(
                kind="tool_result",
                content="output",
                step=0,
                tool_name="git",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert tool_spans[0].attributes.get("fin_assist.tool.name") == "git"
        assert tool_spans[0].attributes.get("fin_assist.tool.args") is not None


class TestApprovalSpan:
    """The fin_assist.approval span is created for deferred (approval-required) events."""

    async def test_approval_span_created_for_deferred_event(self, execute_with_tracing):
        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        ts = await execute_with_tracing(
            events=[deferred_event],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        approval_spans = ts["get_spans"]("fin_assist.approval")
        assert len(approval_spans) == 1

    async def test_approval_span_has_decision_pending(self, execute_with_tracing):
        deferred_event = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="call_1",
                args={"command": "rm -rf /tmp/x"},
                reason="Shell command requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        ts = await execute_with_tracing(
            events=[deferred_event],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        approval_spans = ts["get_spans"]("fin_assist.approval")
        assert approval_spans[0].attributes.get("fin_assist.approval.decision") == "pending"
        assert approval_spans[0].attributes.get("fin_assist.tool.name") == "run_shell"


class TestSpanHierarchy:
    """All platform spans have correct parent-child relationships."""

    async def test_step_span_parent_is_task_span(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        task_spans = ts["get_spans"]("fin_assist.task")
        step_spans = ts["get_spans"]("fin_assist.step")
        assert len(task_spans) == 1
        assert len(step_spans) == 1
        assert step_spans[0].parent.span_id == task_spans[0].context.span_id

    async def test_tool_execution_parent_is_step_span(self, execute_with_tracing):
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(
                kind="tool_call",
                content=MagicMock(),
                step=0,
                tool_name="git",
                metadata={"args": "diff"},
            ),
            StepEvent(
                kind="tool_result",
                content="output",
                step=0,
                tool_name="git",
            ),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(events=events)
        step_spans = ts["get_spans"]("fin_assist.step")
        tool_spans = ts["get_spans"]("fin_assist.tool_execution")
        assert len(step_spans) == 1
        assert len(tool_spans) == 1
        assert tool_spans[0].parent.span_id == step_spans[0].context.span_id

    async def test_approval_span_parent_is_step_span_when_step_active(self, execute_with_tracing):
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
        events = [
            StepEvent(kind="step_start", content=None, step=0),
            deferred_event,
            StepEvent(kind="step_end", content=None, step=0),
        ]
        ts = await execute_with_tracing(
            events=events,
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        step_spans = ts["get_spans"]("fin_assist.step")
        approval_spans = ts["get_spans"]("fin_assist.approval")
        assert len(approval_spans) == 1
        assert approval_spans[0].parent.span_id == step_spans[0].context.span_id

    async def test_approval_span_parent_is_task_span_when_no_step(self, tracing_setup):
        tracing_setup["clear"]()

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
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="test",
        )
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        approval_spans = tracing_setup["get_spans"]("fin_assist.approval")
        assert len(approval_spans) == 1
        assert approval_spans[0].parent.span_id == task_spans[0].context.span_id


class TestTaskResultAttributes:
    """Task span gets result attributes after finalize."""

    async def test_task_span_has_result_type_on_finalize(self, execute_with_tracing):
        ts = await execute_with_tracing(
            run_result=RunResult(output="text response", serialized_history=b"[]"),
        )
        task_spans = ts["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1
        attrs = task_spans[0].attributes
        assert attrs.get("fin_assist.task.result_type") == "str"

    async def test_task_span_paused_for_approval_attribute(self, execute_with_tracing):
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
        ts = await execute_with_tracing(
            events=[deferred_event],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        task_spans = ts["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1
        assert task_spans[0].attributes.get("fin_assist.task.paused_for_approval") is True
