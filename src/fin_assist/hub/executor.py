"""Executor — a2a-sdk AgentExecutor for fin-assist agents.

Uses ``TaskUpdater`` for all state transitions (start_work, complete, failed,
requires_auth, requires_input) and ``ContextStore`` for conversation history
persistence.

The executor is framework-agnostic — it delegates all LLM interaction to
an ``AgentBackend`` (see ``agents/backend.py``).  The backend handles
streaming, message conversion, and history serialization.

A2A task storage is handled by ``InMemoryTaskStore`` while conversation
history lives in our ``ContextStore``.  Message conversion uses protobuf
types (``Part(text=...)``).

Step-driven dispatch
~~~~~~~~~~~~~~~~~~~~
The Executor iterates a ``StepHandle`` and dispatches based on
``StepEvent.kind``:

- ``text_delta`` / ``thinking_delta`` → streaming artifacts
- ``tool_call`` → tool call artifact
- ``tool_result`` → tool result artifact
- ``step_start`` / ``step_end`` → step boundary markers (future: OTel spans)
- ``deferred`` → task pauses for human approval via ``requires_input()``

Deferred tool approval
~~~~~~~~~~~~~~~~~~~~~~
When a tool requires approval, the backend emits a ``deferred`` StepEvent.
The Executor:

1. Emits the deferred tool call as an artifact with ``metadata.type =
   "deferred"``.
2. Saves conversation history so the resume can pick up where it left off.
3. Calls ``updater.requires_input()`` to pause the task.

Resume detection: when a new ``SendMessage`` arrives with the same
``context_id`` and the incoming message contains an ``approval_result``
Part (``metadata.type = "approval_result"``), the Executor reconstructs
``DeferredToolResults`` and re-invokes the backend with
``deferred_tool_results`` to continue from where it paused.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.tools import ApprovalDecision

if TYPE_CHECKING:
    from a2a.server.events import EventQueue

    from fin_assist.agents.backend import AgentBackend, RunResult
    from fin_assist.agents.step import StepEvent
    from fin_assist.hub.context_store import ContextStore


def _struct_to_dict(struct) -> dict[str, Any]:
    if not struct or not struct.fields:
        return {}
    return MessageToDict(struct, preserving_proto_field_name=True)


class Executor(AgentExecutor):
    """AgentExecutor that runs a task via an AgentBackend.

    Takes an ``AgentBackend`` alongside a shared ``ContextStore`` for
    conversation history.  On each task:

    1. Calls ``backend.check_credentials()`` to detect missing API keys.
    2. Loads serialized history from ``ContextStore`` and deserializes
       via ``backend.deserialize_history()``.
    3. Checks for resume: if the incoming message contains an
       ``approval_result`` part, reconstructs deferred tool results
       and re-invokes the backend with them.
    4. Otherwise, converts A2A messages via ``backend.convert_history()``
       and runs a fresh backend invocation.
    5. Sends streaming deltas (text and thinking) as A2A artifacts.
       Thinking deltas include ``metadata.type = "thinking"``.
    6. On ``deferred`` StepEvent: emits artifact, saves history, calls
       ``requires_input()`` to pause the task.
    7. Saves updated history via ``ContextStore.save()`` with
       ``RunResult.serialized_history`` from the backend.
    8. If structured output, adds as a separate artifact.

    Artifact append semantics
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    The A2A TaskManager requires the first ``add_artifact`` call for a
    given ``artifact_id`` to use ``append=False`` (to create the
    artifact).  Subsequent calls use ``append=True`` (to extend it).
    The executor tracks created artifacts in a ``set[str]`` and uses
    ``_emit_artifact`` to enforce this invariant.  Using ``append=True``
    for a nonexistent artifact causes the chunk to be silently dropped.

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

        # 3. Check for resume (approval_result in incoming message)
        deferred_results = self._extract_approval_results(context.message)

        # 4. Run backend with step-driven dispatch
        artifact_id = str(uuid.uuid4())
        created_artifacts: set[str] = set()
        has_deferred = False
        try:
            if deferred_results is not None and message_history:
                handle = self._backend.run_steps(
                    messages=message_history,
                    deferred_tool_results=deferred_results,
                )
            else:
                if context.message:
                    a2a_history = [context.message]
                    message_history.extend(self._backend.convert_history(a2a_history))
                handle = self._backend.run_steps(messages=message_history)
            async for event in handle:
                if event.kind == "deferred":
                    has_deferred = True
                await self._dispatch_step_event(event, updater, artifact_id, created_artifacts)

            if has_deferred:
                result: RunResult = await handle.result()
                if raw_context_id:
                    await self._context_store.save(raw_context_id, result.serialized_history)
                deferred_msg = updater.new_agent_message(parts=[Part(text="Waiting for approval")])
                await updater.requires_input(message=deferred_msg)
                return

            append = artifact_id in created_artifacts
            await updater.add_artifact(
                parts=[Part(text="")],
                artifact_id=artifact_id,
                name="result",
                append=append,
                last_chunk=True,
            )
            created_artifacts.add(artifact_id)
            result = await handle.result()
        except Exception:
            await updater.failed()
            raise

        # 5. Save updated conversation history
        if raw_context_id:
            await self._context_store.save(raw_context_id, result.serialized_history)

        # 6. If structured output, add as a separate artifact
        if not isinstance(result.output, str):
            part = self._backend.convert_result_to_part(result.output)
            await self._emit_artifact(
                updater,
                str(uuid.uuid4()),
                [part],
                created_artifacts,
            )

        await updater.complete()

    async def _dispatch_step_event(
        self,
        event: StepEvent,
        updater: TaskUpdater,
        artifact_id: str,
        created_artifacts: set[str],
    ) -> None:
        """Route a ``StepEvent`` to the appropriate A2A artifact or state transition."""
        match event.kind:
            case "text_delta":
                await self._emit_artifact(
                    updater,
                    artifact_id,
                    [Part(text=event.content)],
                    created_artifacts,
                    last_chunk=False,
                )
            case "thinking_delta":
                meta = Struct()
                meta.update({"type": "thinking"})
                await self._emit_artifact(
                    updater,
                    artifact_id,
                    [Part(text=event.content, metadata=meta)],
                    created_artifacts,
                    last_chunk=False,
                )
            case "tool_call":
                tool_meta = Struct()
                tool_meta.update(
                    {
                        "type": "tool_call",
                        "tool_name": event.tool_name or "",
                        **event.metadata,
                    }
                )
                args_text = str(event.metadata.get("args", {}))
                await self._emit_artifact(
                    updater,
                    artifact_id,
                    [Part(text=args_text, metadata=tool_meta)],
                    created_artifacts,
                    last_chunk=False,
                )
            case "tool_result":
                result_meta = Struct()
                result_meta.update(
                    {
                        "type": "tool_result",
                        "tool_name": event.tool_name or "",
                    }
                )
                if hasattr(event.content, "content"):
                    result_text = str(event.content.content)
                elif isinstance(event.content, str):
                    result_text = event.content
                else:
                    result_text = str(event.content)
                await self._emit_artifact(
                    updater,
                    artifact_id,
                    [Part(text=result_text, metadata=result_meta)],
                    created_artifacts,
                    last_chunk=False,
                )
            case "step_start" | "step_end":
                pass
            case "deferred":
                await self._handle_deferred_event(event, updater, artifact_id, created_artifacts)

    async def _emit_artifact(
        self,
        updater: TaskUpdater,
        artifact_id: str,
        parts: list[Part],
        created_artifacts: set[str],
        *,
        name: str = "result",
        last_chunk: bool = False,
    ) -> None:
        append = artifact_id in created_artifacts
        await updater.add_artifact(
            parts=parts,
            artifact_id=artifact_id,
            name=name,
            append=append,
            last_chunk=last_chunk,
        )
        created_artifacts.add(artifact_id)

    async def _handle_deferred_event(
        self,
        event: StepEvent,
        updater: TaskUpdater,
        artifact_id: str,
        created_artifacts: set[str],
    ) -> None:
        deferred_meta = Struct()
        deferred_content = event.content
        deferred_meta.update(
            {
                "type": "deferred",
                "tool_name": event.tool_name or "",
                "tool_call_id": getattr(deferred_content, "tool_call_id", ""),
                "reason": getattr(deferred_content, "reason", None) or "",
                "args": getattr(deferred_content, "args", {}),
            }
        )
        args_text = str(getattr(deferred_content, "args", {}))
        await self._emit_artifact(
            updater,
            artifact_id,
            [Part(text=args_text, metadata=deferred_meta)],
            created_artifacts,
            last_chunk=False,
        )

    def _extract_approval_results(self, message: Any) -> Any | None:
        """Check if an incoming A2A message contains approval decisions.

        Returns framework-specific ``DeferredToolResults`` if found,
        ``None`` otherwise.
        """
        if not message or not message.parts:
            return None

        decisions: list[ApprovalDecision] = []
        for part in message.parts:
            meta = _struct_to_dict(part.metadata) if part.metadata else {}
            if meta.get("type") == "approval_result":
                for d in meta.get("decisions", []):
                    decisions.append(
                        ApprovalDecision(
                            tool_call_id=d.get("tool_call_id", ""),
                            approved=d.get("approved", False),
                            override_args=d.get("override_args"),
                            denial_reason=d.get("denial_reason"),
                        )
                    )

        if not decisions:
            return None

        return self._backend.build_deferred_results(decisions)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id or str(uuid.uuid4()),
            context_id=context.context_id or str(uuid.uuid4()),
        )
        await updater.cancel()
