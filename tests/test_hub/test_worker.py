"""Tests for FinAssistWorker — custom worker with auth-required support."""

from __future__ import annotations

import uuid
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fasta2a.schema import Task

from fin_assist.agents.base import MissingCredentialsError
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


def _make_agent_def(*, build_model_side_effect=None, build_model_return=None):
    """Create a mock BaseAgent (agent definition) with configurable build_model behaviour."""
    agent_def = MagicMock()
    if build_model_side_effect:
        agent_def.build_model.side_effect = build_model_side_effect
    elif build_model_return is not None:
        agent_def.build_model.return_value = build_model_return
    else:
        agent_def.build_model.return_value = MagicMock()  # a mock model
    return agent_def


class TestFinAssistWorkerAuthRequired:
    """When agent_def.build_model() raises MissingCredentialsError,
    FinAssistWorker should set task state to 'auth-required' with a
    descriptive message — not 'failed'.
    """

    async def test_sets_auth_required_on_missing_credentials(self) -> None:
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        pydantic_agent = MagicMock()
        agent_def = _make_agent_def(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        broker = MagicMock()

        worker = FinAssistWorker(
            pydantic_agent=pydantic_agent, broker=broker, storage=storage, agent_def=agent_def
        )
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        # Should have called update_task with auth-required, not failed
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

        pydantic_agent = MagicMock()
        agent_def = _make_agent_def(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        broker = MagicMock()

        worker = FinAssistWorker(
            pydantic_agent=pydantic_agent, broker=broker, storage=storage, agent_def=agent_def
        )
        # Should not raise
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

    async def test_auth_required_includes_message_in_history(self) -> None:
        """The worker should add an agent message explaining what's missing."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        pydantic_agent = MagicMock()
        agent_def = _make_agent_def(
            build_model_side_effect=MissingCredentialsError(providers=["anthropic"])
        )
        broker = MagicMock()

        worker = FinAssistWorker(
            pydantic_agent=pydantic_agent, broker=broker, storage=storage, agent_def=agent_def
        )
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        # Find the update_task call with auth-required
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
        # The text part should mention the missing provider
        text_parts = [p for p in msg["parts"] if p["kind"] == "text"]
        assert any("anthropic" in p["text"].lower() for p in text_parts)

    async def test_other_exceptions_still_set_failed(self) -> None:
        """Non-credential exceptions should still result in 'failed' state."""
        task = _make_submitted_task()
        storage = AsyncMock()
        storage.load_task.return_value = task
        storage.load_context.return_value = None

        agent_def = _make_agent_def()
        pydantic_agent = MagicMock()
        pydantic_agent.run = AsyncMock(side_effect=RuntimeError("something broke"))

        broker = MagicMock()

        worker = FinAssistWorker(
            pydantic_agent=pydantic_agent, broker=broker, storage=storage, agent_def=agent_def
        )
        with pytest.raises(RuntimeError, match="something broke"):
            await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        # Should have set state to failed
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

        result_mock = MagicMock()
        result_mock.all_messages.return_value = []
        result_mock.new_messages.return_value = []
        result_mock.output = "hello"

        agent_def = _make_agent_def()
        pydantic_agent = MagicMock()
        pydantic_agent.run = AsyncMock(return_value=result_mock)

        broker = MagicMock()

        worker = FinAssistWorker(
            pydantic_agent=pydantic_agent, broker=broker, storage=storage, agent_def=agent_def
        )
        await worker.run_task({"id": "task-1", "context_id": "ctx-1"})

        completed_calls = [
            c for c in storage.update_task.call_args_list if c.kwargs.get("state") == "completed"
        ]
        assert len(completed_calls) >= 1
