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
- Phoenix unreachable (graceful degradation)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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


def _make_request_context(*, task_id: str = "task-1", context_id: str = "ctx-1"):
    context = MagicMock()
    context.task_id = task_id
    context.context_id = context_id
    context.message = None
    return context


class TestSetupTracing:
    """Tests for setup_tracing() — these run without the tracing_setup fixture
    because setup_tracing() sets its own global TracerProvider.

    Note: OTel's set_tracer_provider() only allows setting once per process,
    so these tests verify structural properties rather than global state.
    """

    def test_noop_when_disabled(self):
        config = TracingSettings(enabled=False)
        setup_tracing(config)

    def test_setup_tracing_does_not_raise_with_unreachable_endpoint(self):
        config = TracingSettings(
            enabled=True,
            endpoint="http://localhost:9999",
        )
        setup_tracing(config)


class TestTaskSpanLifecycle:
    """The fin_assist.task span wraps the entire executor run."""

    async def test_task_span_created_on_execute(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend()
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="test-agent",
        )
        ctx = _make_request_context(task_id="task-abc", context_id="ctx-xyz")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1

    async def test_task_span_has_agent_name_attribute(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend()
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="git",
        )
        ctx = _make_request_context()
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(task_spans) == 1
        assert task_spans[0].attributes.get("gen_ai.agent.name") == "git"

    async def test_task_span_has_task_id_attribute(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend()
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="test",
        )
        ctx = _make_request_context(task_id="task-123")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("fin_assist.task.id") == "task-123"

    async def test_task_span_has_context_id_attribute(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend()
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = Executor(
            backend=backend,
            context_store=context_store,
            agent_name="test",
        )
        ctx = _make_request_context(context_id="ctx-456")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        task_spans = tracing_setup["get_spans"]("fin_assist.task")
        assert task_spans[0].attributes.get("fin_assist.context.id") == "ctx-456"

    async def test_task_span_is_ended(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend()
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
        assert len(task_spans) == 1
        assert task_spans[0].end_time is not None


class TestStepSpanLifecycle:
    """The fin_assist.step span wraps each step boundary."""

    async def test_step_span_created_for_step_start_end(self, tracing_setup):
        tracing_setup["clear"]()

        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        backend = _make_backend(events=events)
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

        step_spans = tracing_setup["get_spans"]("fin_assist.step")
        assert len(step_spans) == 1

    async def test_step_span_has_step_number_attribute(self, tracing_setup):
        tracing_setup["clear"]()

        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        backend = _make_backend(events=events)
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

        step_spans = tracing_setup["get_spans"]("fin_assist.step")
        assert step_spans[0].attributes.get("fin_assist.step.number") == 0

    async def test_multiple_steps_create_multiple_step_spans(self, tracing_setup):
        tracing_setup["clear"]()

        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
            StepEvent(kind="step_start", content=None, step=1),
            StepEvent(kind="text_delta", content="world", step=1),
            StepEvent(kind="step_end", content=None, step=1),
        ]
        backend = _make_backend(events=events)
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

        step_spans = tracing_setup["get_spans"]("fin_assist.step")
        assert len(step_spans) == 2
        assert step_spans[0].attributes.get("fin_assist.step.number") == 0
        assert step_spans[1].attributes.get("fin_assist.step.number") == 1


class TestToolExecutionSpan:
    """The fin_assist.tool_execution span wraps tool_call -> tool_result pairs."""

    async def test_tool_execution_span_created(self, tracing_setup):
        tracing_setup["clear"]()

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
        backend = _make_backend(events=events)
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

        tool_spans = tracing_setup["get_spans"]("fin_assist.tool_execution")
        assert len(tool_spans) == 1

    async def test_tool_execution_span_has_name_and_args_attributes(self, tracing_setup):
        tracing_setup["clear"]()

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
        backend = _make_backend(events=events)
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

        tool_spans = tracing_setup["get_spans"]("fin_assist.tool_execution")
        assert tool_spans[0].attributes.get("fin_assist.tool.name") == "git"
        assert tool_spans[0].attributes.get("fin_assist.tool.args") == "diff"


class TestApprovalSpan:
    """The fin_assist.approval span is created for deferred (approval-required) events."""

    async def test_approval_span_created_for_deferred_event(self, tracing_setup):
        tracing_setup["clear"]()

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
        backend = _make_backend(
            events=[deferred_event],
            run_result=RunResult(
                output=MagicMock(),
                serialized_history=b"[]",
            ),
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

        approval_spans = tracing_setup["get_spans"]("fin_assist.approval")
        assert len(approval_spans) == 1

    async def test_approval_span_has_decision_pending(self, tracing_setup):
        tracing_setup["clear"]()

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
        backend = _make_backend(
            events=[deferred_event],
            run_result=RunResult(
                output=MagicMock(),
                serialized_history=b"[]",
            ),
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

        approval_spans = tracing_setup["get_spans"]("fin_assist.approval")
        assert approval_spans[0].attributes.get("fin_assist.approval.decision") == "pending"
        assert approval_spans[0].attributes.get("fin_assist.tool.name") == "run_shell"


class TestSpanHierarchy:
    """All platform spans have correct parent-child relationships."""

    async def test_step_span_parent_is_task_span(self, tracing_setup):
        tracing_setup["clear"]()

        events = [
            StepEvent(kind="step_start", content=None, step=0),
            StepEvent(kind="text_delta", content="hello", step=0),
            StepEvent(kind="step_end", content=None, step=0),
        ]
        backend = _make_backend(events=events)
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
        step_spans = tracing_setup["get_spans"]("fin_assist.step")
        assert len(task_spans) == 1
        assert len(step_spans) == 1
        assert step_spans[0].parent.span_id == task_spans[0].context.span_id

    async def test_tool_execution_parent_is_step_span(self, tracing_setup):
        tracing_setup["clear"]()

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
        backend = _make_backend(events=events)
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

        step_spans = tracing_setup["get_spans"]("fin_assist.step")
        tool_spans = tracing_setup["get_spans"]("fin_assist.tool_execution")
        assert len(step_spans) == 1
        assert len(tool_spans) == 1
        assert tool_spans[0].parent.span_id == step_spans[0].context.span_id

    async def test_approval_span_parent_is_task_span(self, tracing_setup):
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
        assert len(task_spans) == 1
        assert len(approval_spans) == 1
        assert approval_spans[0].parent.span_id == task_spans[0].context.span_id


class TestTaskResultAttributes:
    """Task span gets result attributes after finalize."""

    async def test_task_span_has_result_type_on_finalize(self, tracing_setup):
        tracing_setup["clear"]()

        backend = _make_backend(
            run_result=RunResult(output="text response", serialized_history=b"[]"),
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
        assert len(task_spans) == 1
        attrs = task_spans[0].attributes
        assert attrs.get("fin_assist.task.result_type") == "str"

    async def test_task_span_paused_for_approval_attribute(self, tracing_setup):
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
        assert len(task_spans) == 1
        assert task_spans[0].attributes.get("fin_assist.task.paused_for_approval") is True
