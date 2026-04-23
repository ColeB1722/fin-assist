"""Executor — a2a-sdk AgentExecutor for fin-assist agents.

Uses ``TaskUpdater`` for all state transitions (start_work, complete, failed,
requires_auth) and ``ContextStore`` for conversation history persistence.

The executor is framework-agnostic — it delegates all LLM interaction to
an ``AgentBackend`` (see ``agents/backend.py``).  The backend handles
streaming, message conversion, and history serialization.

A2A task storage is handled by ``InMemoryTaskStore`` while conversation
history lives in our ``ContextStore``.  Message conversion uses protobuf
types (``Part(text=...)``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from google.protobuf.struct_pb2 import Struct

from fin_assist.agents.metadata import MissingCredentialsError

if TYPE_CHECKING:
    from a2a.server.events import EventQueue

    from fin_assist.agents.backend import AgentBackend, RunResult
    from fin_assist.hub.context_store import ContextStore


class Executor(AgentExecutor):
    """AgentExecutor that runs a task via an AgentBackend.

    Takes an ``AgentBackend`` alongside a shared ``ContextStore`` for
    conversation history.  On each task:

    1. Calls ``backend.check_credentials()`` to detect missing API keys.
    2. Loads serialized history from ``ContextStore`` and deserializes
       via ``backend.deserialize_history()``.
    3. Converts A2A messages via ``backend.convert_history()``.
    4. Runs the backend with streaming via ``backend.run_stream()``.
    5. Sends streaming deltas (text and thinking) as A2A artifacts.
       Thinking deltas include ``metadata.type = "thinking"``.
    6. Saves updated history via ``ContextStore.save()`` with
       ``RunResult.serialized_history`` from the backend.
    7. If structured output, adds as a separate artifact.

    If ``check_credentials()`` returns missing providers, the task is set
    to ``auth-required`` with a helpful message instead of failing.
    """

    def __init__(
        self,
        *,
        backend: AgentBackend,
        context_store: ContextStore,
    ) -> None:
        self._backend = backend
        self._context_store = context_store

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
        )

        initial_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[context.message] if context.message else [],
        )
        await event_queue.enqueue_event(initial_task)
        await updater.start_work()

        # 1. Check credentials
        missing = self._backend.check_credentials()
        if missing:
            exc = MissingCredentialsError(providers=missing)
            auth_msg = updater.new_agent_message(parts=[Part(text=str(exc))])
            await updater.requires_auth(message=auth_msg)
            return

        # 2. Load conversation history
        raw_context_id = context.context_id
        serialized_history: bytes | None = (
            await self._context_store.load(raw_context_id) if raw_context_id else None
        )
        message_history: list[Any] = (
            self._backend.deserialize_history(serialized_history) if serialized_history else []
        )

        # 3. Convert A2A message → backend message history
        if context.message:
            a2a_history = [context.message]
            message_history.extend(self._backend.convert_history(a2a_history))

        # 4. Run backend with streaming
        artifact_id = str(uuid.uuid4())
        try:
            handle = self._backend.run_stream(messages=message_history)
            accumulated_text = ""
            async for delta in handle:
                if delta.kind == "thinking":
                    meta = Struct()
                    meta.update({"type": "thinking"})
                    await updater.add_artifact(
                        parts=[Part(text=delta.content, metadata=meta)],
                        artifact_id=artifact_id,
                        name="result",
                        append=True,
                        last_chunk=False,
                    )
                else:
                    accumulated_text += delta.content
                    await updater.add_artifact(
                        parts=[Part(text=delta.content)],
                        artifact_id=artifact_id,
                        name="result",
                        append=True,
                        last_chunk=False,
                    )
            # Final chunk signals completion
            await updater.add_artifact(
                parts=[Part(text="")],
                artifact_id=artifact_id,
                name="result",
                append=True,
                last_chunk=True,
            )
            result: RunResult = await handle.result()
        except Exception:
            await updater.failed()
            raise

        # 5. Save updated conversation history
        if raw_context_id:
            await self._context_store.save(raw_context_id, result.serialized_history)

        # 6. If structured output, add as a separate artifact
        if not isinstance(result.output, str):
            part = self._backend.convert_result_to_part(result.output)
            structured_artifact_id = str(uuid.uuid4())
            await updater.add_artifact(
                parts=[part],
                artifact_id=structured_artifact_id,
                name="result",
            )

        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id or str(uuid.uuid4()),
            context_id=context.context_id or str(uuid.uuid4()),
        )
        await updater.cancel()
