"""Tests for FinAssistExecutor — a2a-sdk AgentExecutor with streaming and auth-required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from a2a.types import TaskState

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.hub.executor import FinAssistExecutor


def _make_agent(*, build_model_side_effect=None, build_model_return=None):
    agent = MagicMock()
    if build_model_side_effect:
        agent.build_model.side_effect = build_model_side_effect
    elif build_model_return is not None:
        agent.build_model.return_value = build_model_return
    else:
        agent.build_model.return_value = MagicMock()
    return agent


async def _stream_text_deltas(*deltas: str):
    """Async generator yielding text deltas."""
    for delta in deltas:
        yield delta


def _make_stream_mock(
    *,
    result_output: str = "hello",
    new_messages: list | None = None,
    all_messages: list | None = None,
    run_side_effect: Exception | None = None,
) -> MagicMock:
    stream_mock = MagicMock()
    stream_mock.all_messages.return_value = all_messages or []
    stream_mock.new_messages.return_value = new_messages or []
    stream_mock.get_output = AsyncMock(return_value=result_output)
    stream_mock.stream_text.return_value = _stream_text_deltas(result_output)

    pydantic_agent = MagicMock()
    pydantic_agent.__aenter__ = AsyncMock(return_value=pydantic_agent)
    pydantic_agent.__aexit__ = AsyncMock(return_value=False)
    if run_side_effect is not None:
        pydantic_agent.run_stream = MagicMock(side_effect=run_side_effect)
    else:
        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=stream_mock)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        pydantic_agent.run_stream = MagicMock(return_value=stream_ctx)

    return pydantic_agent


def _make_request_context(*, task_id: str = "task-1", context_id: str = "ctx-1"):
    context = MagicMock()
    context.task_id = task_id
    context.context_id = context_id
    context.message = None
    return context


class TestFinAssistExecutorAuthRequired:
    async def test_sets_auth_required_on_missing_credentials(self) -> None:
        agent = _make_agent(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)

        executor = FinAssistExecutor(agent=agent, context_store=context_store)
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
        mock_model = MagicMock()
        pydantic_agent_mock = _make_stream_mock(
            run_side_effect=RuntimeError("something broke"),
        )

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)

        executor = FinAssistExecutor(agent=agent, context_store=context_store)
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
        mock_model = MagicMock()
        pydantic_agent_mock = _make_stream_mock(result_output="hello")

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = FinAssistExecutor(agent=agent, context_store=context_store)
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
        mock_model = MagicMock()
        pydantic_agent_mock = _make_stream_mock(result_output="hello")

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = FinAssistExecutor(agent=agent, context_store=context_store)
        ctx = _make_request_context(context_id="ctx-save-test")
        event_queue = MagicMock()
        event_queue.enqueue_event = AsyncMock()

        await executor.execute(ctx, event_queue)

        context_store.save.assert_called_once()
        call_args = context_store.save.call_args
        assert call_args[0][0] == "ctx-save-test"

    async def test_streaming_produces_artifact_chunks(self) -> None:
        mock_model = MagicMock()
        pydantic_agent_mock = _make_stream_mock(result_output="hello world")

        agent = _make_agent(build_model_return=mock_model)
        agent.build_pydantic_agent.return_value = pydantic_agent_mock
        context_store = MagicMock()
        context_store.load = AsyncMock(return_value=None)
        context_store.save = AsyncMock()

        executor = FinAssistExecutor(agent=agent, context_store=context_store)
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


class TestFinAssistExecutorCancel:
    async def test_cancel_publishes_canceled_status(self) -> None:
        agent = _make_agent()
        context_store = MagicMock()

        executor = FinAssistExecutor(agent=agent, context_store=context_store)
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
