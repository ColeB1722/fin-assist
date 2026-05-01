"""Phase 3 — approval polish tests.

Three deltas from the pre-Phase-3 executor behavior:

1. **``fin_assist.task.state`` attribute** (finite enum) is the one
   source of truth for task lifecycle on the ``fin_assist.task``
   span.  Distinguishes ``running`` / ``paused_for_approval`` /
   ``resumed_from_approval`` / ``completed`` / ``failed``.
2. **``ContextStore.save_pause_state``** persists the original
   user_input alongside trace context.  Without this, a resume sees
   ``context.message == ""`` and the hub trace's ``input.value``
   attribute is empty.
3. **``fin_assist.cli.invocation_id`` from baggage** — the executor
   reads OTel baggage in ``_setup_task`` and stamps the id on the
   ``fin_assist.task`` span so CLI and hub traces join via that one
   attribute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from fin_assist.agents.backend import RunResult
from fin_assist.agents.step import StepEvent
from fin_assist.agents.tools import DeferredToolCall
from fin_assist.hub.executor import Executor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _FakeStepHandle:
    def __init__(self, events: list[StepEvent], run_result: RunResult) -> None:
        self._events = events
        self._run_result = run_result

    async def __aiter__(self) -> AsyncIterator[StepEvent]:
        for event in self._events:
            yield event

    async def result(self) -> RunResult:
        return self._run_result


def _make_backend(events=None, run_result=None):
    backend = MagicMock()
    backend.check_credentials.return_value = []
    backend.convert_history.return_value = []
    backend.deserialize_history.return_value = []
    backend.build_deferred_results.return_value = None
    backend.convert_result_to_part.return_value = MagicMock()
    result = run_result or RunResult(output="hello", serialized_history=b"[]")
    event_list = events or [StepEvent(kind="text_delta", content="hello", step=0)]
    backend.run_steps.return_value = _FakeStepHandle(events=event_list, run_result=result)
    return backend


def _make_context_store():
    store = MagicMock()
    store.load = AsyncMock(return_value=None)
    store.save = AsyncMock()
    store.save_pause_state = AsyncMock()
    store.load_pause_state = AsyncMock(return_value=None)
    return store


def _make_request_context(*, task_id="t-1", context_id="ctx-1", user_input=""):
    """Build a MagicMock ``RequestContext``.

    When ``user_input`` is given:
      * Attach a real a2a ``Message`` — ``_setup_task`` builds a real
        ``a2a.types.Task(history=[context.message])`` and protobuf
        refuses to embed a MagicMock there.
      * Stub ``context.get_user_input`` to return the string — the
        executor calls it on the RequestContext (not on the message),
        matching the real a2a-sdk API.
    """
    ctx = MagicMock()
    ctx.task_id = task_id
    ctx.context_id = context_id
    if user_input:
        from a2a.types import Message, Part, Role

        ctx.message = Message(
            message_id="m",
            role=Role.ROLE_USER,
            parts=[Part(text=user_input)],
        )
        ctx.get_user_input = lambda *args, **kw: user_input
    else:
        ctx.message = None
    return ctx


class TestTaskStateAttribute:
    """``fin_assist.task.state`` enum reflects the final state of a
    task on its span.  One attribute, one well-known set of values,
    Phoenix queries become trivial."""

    async def test_completed_task_gets_state_completed(self, tracing_setup):
        tracing_setup["clear"]()
        backend = _make_backend()
        store = _make_context_store()
        executor = Executor(backend=backend, context_store=store, agent_name="t")
        ctx = _make_request_context()
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()
        await executor.execute(ctx, eq)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(spans) == 1
        assert spans[0].attributes.get("fin_assist.task.state") == "completed"

    async def test_paused_task_gets_state_paused_for_approval(self, tracing_setup):
        tracing_setup["clear"]()
        deferred = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="c1",
                args={"command": "ls"},
                reason="requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend = _make_backend(
            events=[deferred],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        store = _make_context_store()
        executor = Executor(backend=backend, context_store=store, agent_name="t")
        ctx = _make_request_context()
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()
        await executor.execute(ctx, eq)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(spans) == 1
        assert spans[0].attributes.get("fin_assist.task.state") == "paused_for_approval"

    async def test_failed_task_gets_state_failed(self, tracing_setup):
        tracing_setup["clear"]()
        backend = MagicMock()
        backend.check_credentials.return_value = []
        backend.convert_history.return_value = []
        backend.deserialize_history.return_value = []
        backend.run_steps.side_effect = RuntimeError("boom")

        store = _make_context_store()
        executor = Executor(backend=backend, context_store=store, agent_name="t")
        ctx = _make_request_context()
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()

        with pytest.raises(RuntimeError):
            await executor.execute(ctx, eq)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(spans) == 1
        assert spans[0].attributes.get("fin_assist.task.state") == "failed"

    async def test_resumed_task_gets_state_resumed_from_approval_then_completed(
        self, tracing_setup
    ):
        """A resumed task transitions running → resumed_from_approval →
        completed.  Only the final state ends up on the span attribute
        (OTel attributes are last-write-wins), so we assert the final
        value is ``completed``.  The intermediate ``resumed_from_approval``
        gets observed via the ``fin_assist.approval_decided`` span that
        already exists.
        """
        from google.protobuf.struct_pb2 import Struct

        from a2a.types import Message, Part, Role
        from fin_assist.hub.context_store import ContextStore

        tracing_setup["clear"]()

        # Pause phase.
        deferred = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="c1",
                args={"command": "ls"},
                reason="requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend1 = _make_backend(
            events=[deferred],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        store = ContextStore(db_path=":memory:")
        ex1 = Executor(backend=backend1, context_store=store, agent_name="t")
        ctx1 = _make_request_context(task_id="t-1", context_id="ctx-hitl")
        eq1 = MagicMock()
        eq1.enqueue_event = AsyncMock()
        await ex1.execute(ctx1, eq1)

        tracing_setup["clear"]()

        # Resume phase.
        backend2 = _make_backend(
            events=[StepEvent(kind="text_delta", content="done", step=0)],
            run_result=RunResult(output="done", serialized_history=b"[]"),
        )
        backend2.build_deferred_results.return_value = MagicMock()
        backend2.deserialize_history.return_value = [MagicMock()]
        meta = Struct()
        meta.update(
            {
                "type": "approval_result",
                "decisions": [{"tool_call_id": "c1", "approved": True}],
            }
        )
        msg = Message(message_id="m", role=Role.ROLE_USER, parts=[Part(text="", metadata=meta)])
        ex2 = Executor(backend=backend2, context_store=store, agent_name="t")
        ctx2 = _make_request_context(task_id="t-2", context_id="ctx-hitl")
        ctx2.message = msg
        eq2 = MagicMock()
        eq2.enqueue_event = AsyncMock()
        await ex2.execute(ctx2, eq2)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(spans) == 1
        # The resumed task completed normally; the span's final state
        # reflects that.  ``resumed_from_approval`` is captured on the
        # companion ``approval_decided`` span, not the task span.
        assert spans[0].attributes.get("fin_assist.task.state") == "completed"


class TestInvocationIdFromBaggage:
    """CLI→hub join: the hub executor must read
    ``fin_assist.cli.invocation_id`` from OTel baggage (injected by the
    CLI tracer over HTTP) and stamp it onto the task span as an
    attribute.  That one attribute is the join key between the two
    traces in Phoenix.
    """

    async def test_task_span_carries_invocation_id_from_baggage(self, tracing_setup):
        from opentelemetry import baggage, context

        tracing_setup["clear"]()

        backend = _make_backend()
        store = _make_context_store()
        executor = Executor(backend=backend, context_store=store, agent_name="t")
        ctx = _make_request_context()
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()

        # Simulate the hub request arriving with baggage set.  The real
        # chain is: CLI sets baggage → httpx propagator injects →
        # FastAPI instrumentor extracts → the executor code runs with
        # the extracted context as current.
        token = context.attach(baggage.set_baggage("fin_assist.cli.invocation_id", "abc123"))
        try:
            await executor.execute(ctx, eq)
        finally:
            context.detach(token)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(spans) == 1
        assert spans[0].attributes.get("fin_assist.cli.invocation_id") == "abc123"

    async def test_task_span_has_no_invocation_id_without_baggage(self, tracing_setup):
        """When no baggage is present (e.g. direct hub request without
        CLI tracing), the attribute is absent — not set to an empty
        string — so Phoenix queries filtering on it don't match rows
        that simply lack the join key."""
        tracing_setup["clear"]()
        backend = _make_backend()
        store = _make_context_store()
        executor = Executor(backend=backend, context_store=store, agent_name="t")
        ctx = _make_request_context()
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()
        await executor.execute(ctx, eq)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert "fin_assist.cli.invocation_id" not in (spans[0].attributes or {})


class TestSavePauseState:
    """``ContextStore.save_pause_state`` replaces ``save_trace_context``
    by also persisting the original user_input.  On resume, the
    executor hydrates ``input.value`` from this so Phoenix shows the
    prompt that kicked off the whole flow, not an empty string."""

    async def test_save_pause_state_roundtrip(self):
        from fin_assist.hub.context_store import ContextStore

        store = ContextStore(db_path=":memory:")
        await store.save_pause_state(
            context_id="ctx-x",
            trace_id=0xAA,
            span_id=0xBB,
            trace_flags=0x01,
            user_input="list files please",
        )
        loaded = await store.load_pause_state("ctx-x")
        assert loaded is not None
        assert loaded.trace_id == 0xAA
        assert loaded.span_id == 0xBB
        assert loaded.trace_flags == 0x01
        assert loaded.user_input == "list files please"

    async def test_load_pause_state_none_when_missing(self):
        from fin_assist.hub.context_store import ContextStore

        store = ContextStore(db_path=":memory:")
        assert await store.load_pause_state("never-paused") is None

    async def test_pause_persists_user_input(self, tracing_setup):
        """End-to-end: executor pauses a task, then ``load_pause_state``
        returns the original user_input the run was started with."""
        tracing_setup["clear"]()

        from fin_assist.hub.context_store import ContextStore

        deferred = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="c1",
                args={"command": "ls"},
                reason="requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend = _make_backend(
            events=[deferred],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        store = ContextStore(db_path=":memory:")
        executor = Executor(backend=backend, context_store=store, agent_name="t")
        ctx = _make_request_context(context_id="ctx-p", user_input="original prompt")
        eq = MagicMock()
        eq.enqueue_event = AsyncMock()
        await executor.execute(ctx, eq)

        loaded = await store.load_pause_state("ctx-p")
        assert loaded is not None
        assert loaded.user_input == "original prompt"

    async def test_resume_hydrates_input_value_from_pause_state(self, tracing_setup):
        """After a resume, the new task span's ``input.value`` should be
        the original paused prompt, not the empty approval-result
        message.  This is the UX bug that ``load_pause_state`` fixes."""
        from google.protobuf.struct_pb2 import Struct

        from a2a.types import Message, Part, Role
        from fin_assist.hub.context_store import ContextStore

        tracing_setup["clear"]()

        # Pause with a real user_input.
        deferred = StepEvent(
            kind="deferred",
            content=DeferredToolCall(
                tool_name="run_shell",
                tool_call_id="c1",
                args={"command": "ls"},
                reason="requires approval",
            ),
            step=0,
            tool_name="run_shell",
        )
        backend1 = _make_backend(
            events=[deferred],
            run_result=RunResult(output=MagicMock(), serialized_history=b"[]"),
        )
        store = ContextStore(db_path=":memory:")
        ex1 = Executor(backend=backend1, context_store=store, agent_name="t")
        ctx1 = _make_request_context(
            task_id="t-1", context_id="ctx-resume", user_input="original prompt"
        )
        eq1 = MagicMock()
        eq1.enqueue_event = AsyncMock()
        await ex1.execute(ctx1, eq1)

        tracing_setup["clear"]()

        # Resume with an empty message (approval_result part only).
        backend2 = _make_backend(
            events=[StepEvent(kind="text_delta", content="ok", step=0)],
            run_result=RunResult(output="ok", serialized_history=b"[]"),
        )
        backend2.build_deferred_results.return_value = MagicMock()
        backend2.deserialize_history.return_value = [MagicMock()]
        meta = Struct()
        meta.update(
            {
                "type": "approval_result",
                "decisions": [{"tool_call_id": "c1", "approved": True}],
            }
        )
        resume_msg = Message(
            message_id="m2",
            role=Role.ROLE_USER,
            parts=[Part(text="", metadata=meta)],
        )
        ex2 = Executor(backend=backend2, context_store=store, agent_name="t")
        ctx2 = _make_request_context(task_id="t-2", context_id="ctx-resume")
        ctx2.message = resume_msg
        eq2 = MagicMock()
        eq2.enqueue_event = AsyncMock()
        await ex2.execute(ctx2, eq2)

        spans = tracing_setup["get_spans"]("fin_assist.task")
        assert len(spans) == 1
        # The resumed task span's input.value should hydrate from the
        # pause state, not be the empty resume-message.
        assert spans[0].attributes.get("input.value") == "original prompt"
