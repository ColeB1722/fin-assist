"""Tests for FinAssistWorker — custom Worker with auth-required support.

The worker uses ``agent.iter()`` + ``node.stream()`` for progressive output.
Tests that exercise the full ``run_task`` path mock the pydantic-ai iteration
graph via ``_make_iter_mock()``.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fasta2a.schema import Task

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.hub.worker import FinAssistWorker


def _make_submitted_task(task_id: str = "task-1", context_id: str = "ctx-1") -> Task:
    return cast(
        "Task",
        {
            "id": task_id,
            "context_id": context_id,
            "kind": "task",
            "status": {"state": "submitted"},
            "history": [],
        },
    )


def _make_agent(*, build_model_side_effect=None, build_model_return=None):
    """Create a mock BaseAgent with configurable build_model behaviour."""
    agent = MagicMock()
    if build_model_side_effect:
        agent.build_model.side_effect = build_model_side_effect
    elif build_model_return is not None:
        agent.build_model.return_value = build_model_return
    else:
        agent.build_model.return_value = MagicMock()
    return agent


def _make_iter_mock(
    *,
    result_output: str = "hello",
    new_messages: list | None = None,
    all_messages: list | None = None,
    iter_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock pydantic Agent that supports the ``iter()`` async graph.

    Returns a MagicMock agent where ``agent.iter(...)`` produces an async
    context manager yielding an ``AgentRun``-like async iterable with no
    nodes (empty graph — the worker's ``_run_with_streaming`` processes
    no stream events, which is fine for testing the surrounding logic).

    ``agent_run.result`` carries ``all_messages()``, ``new_messages()``,
    and ``.output``.
    """
    result_mock = MagicMock()
    result_mock.all_messages.return_value = all_messages or []
    result_mock.new_messages.return_value = new_messages or []
    result_mock.output = result_output

    # AgentRun — async iterable that yields no nodes (empty graph)
    agent_run = MagicMock()
    agent_run.result = result_mock

    async def _aiter_nodes(self_ignored=None):
        return
        yield  # noqa: F841 — makes this an async generator

    agent_run.__aiter__ = _aiter_nodes

    # agent.iter() is an async context manager returning agent_run
    iter_cm = MagicMock()
    if iter_side_effect is not None:
        iter_cm.__aenter__ = AsyncMock(side_effect=iter_side_effect)
    else:
        iter_cm.__aenter__ = AsyncMock(return_value=agent_run)
    iter_cm.__aexit__ = AsyncMock(return_value=False)

    pydantic_agent = MagicMock()
    pydantic_agent.__aenter__ = AsyncMock(return_value=pydantic_agent)
    pydantic_agent.__aexit__ = AsyncMock(return_value=False)
    pydantic_agent.iter.return_value = iter_cm

    return pydantic_agent


class TestFinAssistWorkerAuthRequired:
    """When agent.build_model() raises MissingCredentialsError,
    FinAssistWorker should set task state to 'auth-required' with a
    descriptive message — not 'failed'.
    """

    async def test_sets_auth_required_on_missing_credentials(self) -> None:
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        agent = _make_agent(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        update_calls = [
            c
            for c in storage.update_task.call_args_list
            if c.kwargs.get("state") == "auth-required"
        ]
        assert len(update_calls) >= 1

    async def test_does_not_reraise_missing_credentials(self) -> None:
        """MissingCredentialsError should be handled, not re-raised."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        agent = _make_agent(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

    async def test_auth_required_includes_message_in_history(self) -> None:
        """The worker should add an agent message explaining what's missing."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        agent = _make_agent(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        auth_call = next(
            c
            for c in storage.update_task.call_args_list
            if c.kwargs.get("state") == "auth-required"
        )
        messages = auth_call.kwargs.get("new_messages")
        assert messages is not None
        assert len(messages) >= 1

        msg = messages[0]
        assert msg["role"] == "agent"
        text_parts = [p for p in msg["parts"] if p["kind"] == "text"]
        assert any("anthropic" in p["text"].lower() for p in text_parts)

    async def test_other_exceptions_still_set_failed(self) -> None:
        """Non-credential exceptions should still result in 'failed' state."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        mock_model = MagicMock()
        pydantic_agent_mock = _make_iter_mock(
            iter_side_effect=RuntimeError("something broke"),
        )

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        with pytest.raises(RuntimeError, match="something broke"):
            await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        failed_calls = [
            c for c in storage.update_task.call_args_list if c.kwargs.get("state") == "failed"
        ]
        assert len(failed_calls) >= 1

    async def test_successful_task_still_completes(self) -> None:
        """Normal execution should still result in 'completed' state."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        mock_model = MagicMock()
        pydantic_agent_mock = _make_iter_mock(result_output="hello")

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        completed_calls = [
            c for c in storage.update_task.call_args_list if c.kwargs.get("state") == "completed"
        ]
        assert len(completed_calls) >= 1


class TestFinAssistWorkerStreaming:
    """Tests for progressive output via _run_with_streaming."""

    async def test_thinking_deltas_flushed_to_storage(self) -> None:
        """Thinking tokens above the flush interval trigger intermediate updates."""
        from pydantic_ai import PartDeltaEvent, ThinkingPartDelta

        from fin_assist.hub.worker import _THINKING_FLUSH_INTERVAL

        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        # Build a mock that streams thinking deltas above the flush threshold
        thinking_events = [
            PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta="x "))
            for _ in range(_THINKING_FLUSH_INTERVAL + 1)
        ]

        result_mock = MagicMock()
        result_mock.all_messages.return_value = []
        result_mock.new_messages.return_value = []
        result_mock.output = "done"

        # Build request_stream mock (async iterable of events)
        async def _stream_events():
            for ev in thinking_events:
                yield ev

        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=_stream_events())
        stream_cm.__aexit__ = AsyncMock(return_value=False)

        # ModelRequestNode mock
        node = MagicMock()
        node.stream.return_value = stream_cm

        # AgentRun mock — yields the single model request node
        agent_run = MagicMock()
        agent_run.result = result_mock
        agent_run.ctx = MagicMock()

        async def _aiter_nodes(_self=None):
            yield node

        agent_run.__aiter__ = _aiter_nodes

        # Make PydanticAgent.is_model_request_node return True for our node
        iter_cm = MagicMock()
        iter_cm.__aenter__ = AsyncMock(return_value=agent_run)
        iter_cm.__aexit__ = AsyncMock(return_value=False)

        pydantic_agent = MagicMock()
        pydantic_agent.__aenter__ = AsyncMock(return_value=pydantic_agent)
        pydantic_agent.__aexit__ = AsyncMock(return_value=False)
        pydantic_agent.iter.return_value = iter_cm

        mock_model = MagicMock()
        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)

        # Patch is_model_request_node to return True for our node
        from unittest.mock import patch

        from pydantic_ai import Agent as PA

        with patch.object(PA, "is_model_request_node", return_value=True):
            await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        # Should have at least one intermediate "working" flush for thinking
        working_calls = [
            c
            for c in storage.update_task.call_args_list
            if c.kwargs.get("state") == "working" and c.kwargs.get("new_messages") is not None
        ]
        # First call is state="working" with no messages (task start),
        # subsequent calls are thinking flushes
        thinking_flushes = [
            c
            for c in working_calls
            if c.kwargs.get("new_messages")
            and any(
                p.get("metadata", {}).get("type") == "thinking_delta"
                for msg in c.kwargs["new_messages"]
                for p in msg.get("parts", [])
            )
        ]
        assert len(thinking_flushes) >= 1

    async def test_completed_with_output_artifacts(self) -> None:
        """After streaming, final completion still writes artifacts."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        mock_model = MagicMock()
        pydantic_agent_mock = _make_iter_mock(result_output="the answer")

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        completed_calls = [
            c for c in storage.update_task.call_args_list if c.kwargs.get("state") == "completed"
        ]
        assert len(completed_calls) == 1
        artifacts = completed_calls[0].kwargs.get("new_artifacts", [])
        assert len(artifacts) >= 1
        # Artifact should contain the output text
        text_parts = [p for a in artifacts for p in a.get("parts", []) if p.get("kind") == "text"]
        assert any("the answer" in p.get("text", "") for p in text_parts)


class TestFinAssistWorkerCancelTask:
    async def test_cancel_submitted_task(self) -> None:
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task

        agent = _make_agent()
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.cancel_task({"id": "task-1"})

        storage.update_task.assert_called_once_with("task-1", state="canceled")

    async def test_cancel_completed_task_is_noop(self) -> None:
        completed_task = cast(
            "Task",
            {
                "id": "task-1",
                "kind": "task",
                "status": {"state": "completed"},
            },
        )
        storage = AsyncMock()
        storage.load_task.return_value = completed_task

        agent = _make_agent()
        broker = MagicMock()

        worker = FinAssistWorker(agent=agent, broker=broker, storage=storage)
        await worker.cancel_task({"id": "task-1"})

        storage.update_task.assert_not_called()
