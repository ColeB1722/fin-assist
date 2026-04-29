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
- ``step_start`` / ``step_end`` → step boundary markers, create/end OTel step spans
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

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from google.protobuf.struct_pb2 import Struct
from opentelemetry import trace as trace_api
from opentelemetry.trace import StatusCode
from opentelemetry.trace.status import Status

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.tools import ApprovalDecision
from fin_assist.protobuf import struct_to_dict

if TYPE_CHECKING:
    from a2a.server.events import EventQueue

    from fin_assist.agents.backend import AgentBackend, RunResult
    from fin_assist.agents.step import StepEvent
    from fin_assist.hub.context_store import ContextStore

logger = logging.getLogger(__name__)


def _get_tracer() -> Any:
    """Return the fin-assist OTel tracer (no-op if tracing is not set up)."""
    from opentelemetry.trace import get_tracer

    return get_tracer("fin_assist")


@dataclass
class _ExecutionContext:
    """Mutable state carried between Executor helper methods for one task.

    Avoids a long parameter list on each helper.  The ``task_id`` and
    ``raw_context_id`` are captured once from the request and used for
    logging and context-store persistence throughout the task lifecycle.

    OTel span fields (``task_span``, ``current_step_span``,
    ``current_tool_span``) track the live span hierarchy so that child
    spans are correctly parented and ended at the right time.
    """

    task_id: str
    raw_context_id: str | None
    updater: TaskUpdater
    artifact_id: str
    created_artifacts: set[str] = field(default_factory=set)
    task_span: Any = None
    current_step_span: Any = None
    current_tool_span: Any = None


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
        agent_name: str = "",
    ) -> None:
        self._backend = backend
        self._context_store = context_store
        self._agent_name = agent_name
        self._tracer = _get_tracer()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Run one task through its lifecycle.

        Sequence:

        1. ``_setup_task`` — create updater, enqueue initial task, start work.
           Short-circuits to ``requires_auth`` if credentials missing.
        2. ``_load_history`` — read prior conversation bytes from the
           ``ContextStore`` and deserialize via the backend.
        3. ``_extract_approval_results`` — detect a resume-after-approval
           request so we can pass deferred results back to the backend.
        4. ``_start_run`` → ``_consume_events`` → ``handle.result()`` —
           drive the ``StepHandle`` event loop, dispatch each ``StepEvent``,
           and surface pause-for-approval via a sentinel flag.  Failures
           here set the task to ``failed``.
        5. Either ``_pause_for_approval`` (if any ``deferred`` event was
           seen) or ``_finalize`` (emit last-chunk artifact, save history,
           attach structured output, complete).
        """
        ctx = await self._setup_task(context, event_queue)
        if ctx is None:
            return

        task_span = self._tracer.start_span(
            "fin_assist.task",
            attributes={
                "gen_ai.agent.name": self._agent_name,
                "fin_assist.task.id": ctx.task_id,
                "fin_assist.context.id": ctx.raw_context_id or "",
            },
        )
        ctx.task_span = task_span

        try:
            message_history = await self._load_history(ctx)
            deferred_results = self._extract_approval_results(context.message)
            if deferred_results is not None:
                logger.info("resuming from approval task_id=%s", ctx.task_id)

            handle = self._start_run(context, message_history, deferred_results)
            has_deferred = await self._consume_events(ctx, handle)
            result: RunResult = await handle.result()
        except Exception:
            logger.exception("execute failed task_id=%s", ctx.task_id)
            task_span.set_status(Status(StatusCode.ERROR, "execute failed"))
            task_span.end()
            await ctx.updater.failed()
            raise

        if has_deferred:
            await self._pause_for_approval(ctx, result)
            return

        await self._finalize(ctx, result)

    async def _setup_task(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> _ExecutionContext | None:
        """Create the updater, enqueue the initial task, and start work.

        Returns ``None`` if credentials are missing (task is moved to
        ``requires_auth`` and no further work is done).
        """
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())
        logger.info("execute start task_id=%s context_id=%s", task_id, context_id)

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

        missing = self._backend.check_credentials()
        if missing:
            logger.warning("auth required task_id=%s missing=%s", task_id, missing)
            exc = MissingCredentialsError(providers=missing)
            auth_msg = updater.new_agent_message(parts=[Part(text=str(exc))])
            await updater.requires_auth(message=auth_msg)
            return None

        return _ExecutionContext(
            task_id=task_id,
            raw_context_id=context.context_id,
            updater=updater,
            artifact_id=str(uuid.uuid4()),
        )

    async def _load_history(self, ctx: _ExecutionContext) -> list[Any]:
        """Load and deserialize prior conversation history, if any."""
        serialized: bytes | None = (
            await self._context_store.load(ctx.raw_context_id) if ctx.raw_context_id else None
        )
        message_history: list[Any] = (
            self._backend.deserialize_history(serialized) if serialized else []
        )
        logger.debug(
            "history loaded task_id=%s resumed=%s message_count=%d",
            ctx.task_id,
            serialized is not None,
            len(message_history),
        )
        return message_history

    def _start_run(
        self,
        context: RequestContext,
        message_history: list[Any],
        deferred_results: Any | None,
    ) -> Any:
        """Return a ``StepHandle`` for either a fresh run or a resume."""
        if deferred_results is not None and message_history:
            return self._backend.run_steps(
                messages=message_history,
                deferred_tool_results=deferred_results,
            )
        if context.message:
            message_history.extend(self._backend.convert_history([context.message]))
        return self._backend.run_steps(messages=message_history)

    async def _consume_events(self, ctx: _ExecutionContext, handle: Any) -> bool:
        """Iterate the handle's events and dispatch each one.

        Returns ``True`` if any ``deferred`` event was seen (task needs
        to pause for approval).
        """
        has_deferred = False
        async for event in handle:
            if event.kind == "deferred":
                has_deferred = True
            await self._dispatch_step_event(event, ctx)
        return has_deferred

    async def _pause_for_approval(
        self,
        ctx: _ExecutionContext,
        result: RunResult,
    ) -> None:
        """Save history and move the task to ``requires_input``."""
        if ctx.task_span is not None:
            ctx.task_span.set_attribute("fin_assist.task.paused_for_approval", True)
            ctx.task_span.end()

        if ctx.raw_context_id:
            await self._context_store.save(ctx.raw_context_id, result.serialized_history)
        logger.info("paused for approval task_id=%s", ctx.task_id)
        deferred_msg = ctx.updater.new_agent_message(parts=[Part(text="Waiting for approval")])
        await ctx.updater.requires_input(message=deferred_msg)

    async def _finalize(self, ctx: _ExecutionContext, result: RunResult) -> None:
        """Emit the closing last-chunk artifact, save history, and complete.

        For non-string (structured) output, also emits a separate
        artifact carrying the serialized result via
        ``backend.convert_result_to_part``.
        """
        append = ctx.artifact_id in ctx.created_artifacts
        await ctx.updater.add_artifact(
            parts=[Part(text="")],
            artifact_id=ctx.artifact_id,
            name="result",
            append=append,
            last_chunk=True,
        )
        ctx.created_artifacts.add(ctx.artifact_id)

        if ctx.raw_context_id:
            await self._context_store.save(ctx.raw_context_id, result.serialized_history)

        if not isinstance(result.output, str):
            part = self._backend.convert_result_to_part(result.output)
            await self._emit_artifact(
                ctx.updater,
                str(uuid.uuid4()),
                [part],
                ctx.created_artifacts,
            )

        if ctx.task_span is not None:
            ctx.task_span.set_attribute("fin_assist.task.result_type", type(result.output).__name__)
            ctx.task_span.end()

        logger.info("execute complete task_id=%s", ctx.task_id)
        await ctx.updater.complete()

    async def _dispatch_step_event(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """Route a ``StepEvent`` to the appropriate A2A artifact or state transition."""
        match event.kind:
            case "text_delta":
                await self._emit_artifact(
                    ctx.updater,
                    ctx.artifact_id,
                    [Part(text=event.content)],
                    ctx.created_artifacts,
                    last_chunk=False,
                )
            case "thinking_delta":
                meta = Struct()
                meta.update({"type": "thinking"})
                await self._emit_artifact(
                    ctx.updater,
                    ctx.artifact_id,
                    [Part(text=event.content, metadata=meta)],
                    ctx.created_artifacts,
                    last_chunk=False,
                )
            case "tool_call":
                self._start_tool_span(event, ctx)
                tool_meta = Struct()
                tool_meta.update(
                    {
                        "type": "tool_call",
                        "tool_name": event.tool_name or "",
                        **event.metadata,
                    }
                )
                await self._emit_artifact(
                    ctx.updater,
                    ctx.artifact_id,
                    [Part(text="", metadata=tool_meta)],
                    ctx.created_artifacts,
                    last_chunk=False,
                )
            case "tool_result":
                self._end_tool_span(event, ctx)
                result_meta = Struct()
                result_meta.update(
                    {
                        "type": "tool_result",
                        "tool_name": event.tool_name or "",
                    }
                )
                # Backends are required to emit ``content`` as ``str`` for
                # ``tool_result`` events — see StepEvent docstring and
                # PydanticAIBackend._extract_tool_result_text.
                content = event.content if isinstance(event.content, str) else str(event.content)
                await self._emit_artifact(
                    ctx.updater,
                    ctx.artifact_id,
                    [Part(text=content, metadata=result_meta)],
                    ctx.created_artifacts,
                    last_chunk=False,
                )
            case "step_start":
                self._start_step_span(event, ctx)
            case "step_end":
                self._end_step_span(ctx)
            case "deferred":
                await self._handle_deferred_event(event, ctx)

    def _start_step_span(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """Start a fin_assist.step span as a child of the task span."""
        parent_context = trace_api.set_span_in_context(ctx.task_span) if ctx.task_span else None
        ctx.current_step_span = self._tracer.start_span(
            "fin_assist.step",
            context=parent_context,
            attributes={
                "fin_assist.step.number": event.step,
            },
        )

    def _end_step_span(self, ctx: _ExecutionContext) -> None:
        """End the current step span."""
        if ctx.current_step_span is not None:
            ctx.current_step_span.end()
        ctx.current_step_span = None

    def _start_tool_span(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """Start a fin_assist.tool_execution span as a child of the current step span."""
        parent = ctx.current_step_span or ctx.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        ctx.current_tool_span = self._tracer.start_span(
            "fin_assist.tool_execution",
            context=parent_context,
            attributes={
                "fin_assist.tool.name": event.tool_name or "",
                "fin_assist.tool.args": str(event.metadata.get("args", "")),
            },
        )

    def _end_tool_span(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """End the current tool execution span, recording result attributes."""
        if ctx.current_tool_span is not None:
            ctx.current_tool_span.end()
        ctx.current_tool_span = None

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

    async def _handle_deferred_event(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        parent = ctx.current_step_span or ctx.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        approval_span = self._tracer.start_span(
            "fin_assist.approval",
            context=parent_context,
            attributes={
                "fin_assist.tool.name": event.tool_name or "",
                "fin_assist.approval.decision": "pending",
            },
        )
        approval_span.end()

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
        await self._emit_artifact(
            ctx.updater,
            ctx.artifact_id,
            [Part(text="", metadata=deferred_meta)],
            ctx.created_artifacts,
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
            meta = struct_to_dict(part.metadata) if part.metadata else {}
            if meta.get("type") == "approval_result":
                for d in meta.get("decisions", []):
                    tool_call_id = d.get("tool_call_id", "")
                    if not tool_call_id:
                        logger.warning("Approval decision missing tool_call_id, skipping")
                        continue
                    decisions.append(
                        ApprovalDecision(
                            tool_call_id=tool_call_id,
                            approved=d.get("approved", False),
                            override_args=d.get("override_args"),
                            denial_reason=d.get("denial_reason"),
                        )
                    )

        if not decisions:
            return None

        return self._backend.build_deferred_results(decisions)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        logger.info("cancel task_id=%s", task_id)
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context.context_id or str(uuid.uuid4()),
        )
        await updater.cancel()
