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
~~~~~~~~~~~~~~~~~~~~~
The Executor iterates a ``StepHandle`` and dispatches based on
``StepEvent.kind``:

- ``text_delta`` / ``thinking_delta`` → streaming artifacts
- ``tool_call`` → tool call artifact
- ``tool_result`` → tool result artifact
- ``step_start`` / ``step_end`` → step boundary markers
- ``deferred`` → task pauses for human approval via ``requires_input()``

Deferred tool approval
~~~~~~~~~~~~~~~~~~~~~
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

OTel span lifecycle
~~~~~~~~~~~~~~~~~~~
All span creation and attribute setting is delegated to
``_TaskTracer`` (see ``_task_tracer.py``).  The executor never calls
OTel APIs directly — it creates a ``_TaskTracer`` per invocation and
calls its methods at the appropriate lifecycle points.
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

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.tools import ApprovalDecision, DeferredToolCall
from fin_assist.hub._task_tracer import _TaskTracer
from fin_assist.protobuf import struct_to_dict

if TYPE_CHECKING:
    from a2a.server.events import EventQueue

    from fin_assist.agents.backend import AgentBackend, RunResult
    from fin_assist.agents.step import StepEvent
    from fin_assist.hub.context_store import ContextStore

logger = logging.getLogger(__name__)


@dataclass
class _ResumeInfo:
    """Result of resume detection for a task invocation.

    ``prior_trace_ctx`` and ``prior_user_input`` are non-``None`` only
    when a pause state was found in the ``ContextStore`` — i.e. this
    invocation is a resume after a deferred-tool approval pause.
    """

    prior_trace_ctx: tuple[int, int, int] | None
    prior_user_input: str


@dataclass
class _ExecutionContext:
    """Mutable business state carried between Executor helper methods for one task.

    Avoids a long parameter list on each helper.  The ``task_id`` and
    ``raw_context_id`` are captured once from the request and used for
    logging and context-store persistence throughout the task lifecycle.

    OTel span lifecycle is owned by ``tracer`` (``_TaskTracer``).
    The executor reads ``tracer.paused_approval_span_ctx`` when
    persisting the pause state but otherwise never touches span
    objects directly.
    """

    task_id: str
    raw_context_id: str | None
    updater: TaskUpdater
    artifact_id: str
    user_input: str = ""
    """Original user prompt for this task.  Persisted into the
    ContextStore at pause so the resume can hydrate ``input.value`` on
    the new task span — otherwise a resumed task's span has an empty
    ``input.value`` (the resume message only carries ``approval_result``
    metadata, not the original prompt).
    """
    created_artifacts: set[str] = field(default_factory=set)
    text_chunks: list[str] = field(default_factory=list)
    tracer: _TaskTracer = field(default_factory=_TaskTracer)


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
        model_name: str = "",
    ) -> None:
        self._backend = backend
        self._context_store = context_store
        self._agent_name = agent_name
        self._model_name = model_name

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

        user_input = self._extract_user_input(context)
        approval_decisions = self._extract_approval_decisions(context.message)
        resume_info = await self._detect_resume(ctx, approval_decisions)

        if not user_input and resume_info.prior_user_input:
            user_input = resume_info.prior_user_input
        ctx.user_input = user_input

        task_span_links: list[Any] = []
        if resume_info.prior_trace_ctx is not None:
            link = ctx.tracer.make_link(resume_info.prior_trace_ctx, "resume_from_approval")
            if link is not None:
                task_span_links.append(link)

        ctx.tracer.start_task_span(
            agent_name=self._agent_name,
            task_id=ctx.task_id,
            context_id=ctx.raw_context_id,
            user_input=user_input,
            links=task_span_links or None,
        )

        if approval_decisions and resume_info.prior_trace_ctx is not None:
            ctx.tracer.emit_approval_decided_span(approval_decisions, resume_info.prior_trace_ctx)

        try:
            message_history = await self._load_history(ctx)
            deferred_results = (
                self._backend.build_deferred_results(approval_decisions)
                if approval_decisions
                else None
            )
            if deferred_results is not None:
                logger.info("resuming from approval task_id=%s", ctx.task_id)

            handle = self._start_run(context, message_history, deferred_results)
            has_deferred = await self._consume_events(ctx, handle)
            result: RunResult = await handle.result()
        except Exception as exc:
            logger.exception("execute failed task_id=%s", ctx.task_id)
            ctx.tracer.end_task_span_failed("".join(ctx.text_chunks), exc)
            ctx.tracer.detach_task_context()
            await ctx.updater.failed()
            raise

        ctx.tracer.detach_task_context()

        if has_deferred:
            await self._pause_for_approval(ctx, result)
            return

        await self._finalize(ctx, result)

    @staticmethod
    def _extract_user_input(context: RequestContext) -> str:
        """Read the user prompt from the request context.

        Returns the empty string when the context has no message.
        """
        if context.message is None:
            return ""
        raw = context.get_user_input()
        return raw if isinstance(raw, str) else ""

    async def _detect_resume(
        self,
        ctx: _ExecutionContext,
        approval_decisions: list[ApprovalDecision],
    ) -> _ResumeInfo:
        """Check whether this invocation is a resume after a deferred-tool pause.

        Resume detection happens *before* the task span is started so the
        span can carry an OTel ``Link`` back to the paused
        ``approval_request`` span.  The link tells OTel backends that
        this trace is a continuation of a prior trace.

        Returns a ``_ResumeInfo`` with ``prior_trace_ctx`` and
        ``prior_user_input`` populated only when a pause state was found
        in the ``ContextStore``.  When no approval decisions are present
        or no pause state exists, both fields are their zero values.
        """
        if not approval_decisions or not ctx.raw_context_id:
            return _ResumeInfo(prior_trace_ctx=None, prior_user_input="")

        pause_state = await self._context_store.load_pause_state(ctx.raw_context_id)
        if pause_state is None:
            return _ResumeInfo(prior_trace_ctx=None, prior_user_input="")

        prior_trace_ctx = (
            pause_state.trace_id,
            pause_state.span_id,
            pause_state.trace_flags,
        )
        prior_user_input = pause_state.user_input or ""
        return _ResumeInfo(prior_trace_ctx=prior_trace_ctx, prior_user_input=prior_user_input)

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
        """Save history + paused approval span context, move task to
        ``requires_input``.
        """
        ctx.tracer.end_task_span_paused()

        if ctx.raw_context_id:
            await self._context_store.save(ctx.raw_context_id, result.serialized_history)
            if ctx.tracer.paused_approval_span_ctx is not None:
                await self._context_store.save_pause_state(
                    context_id=ctx.raw_context_id,
                    trace_id=ctx.tracer.paused_approval_span_ctx.trace_id,
                    span_id=ctx.tracer.paused_approval_span_ctx.span_id,
                    trace_flags=int(ctx.tracer.paused_approval_span_ctx.trace_flags),
                    user_input=ctx.user_input,
                )
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

        ctx.tracer.end_task_span_completed(result.output)

        logger.info("execute complete task_id=%s", ctx.task_id)
        await ctx.updater.complete()

    async def _dispatch_step_event(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """Route a ``StepEvent`` to the appropriate A2A artifact or state transition."""
        match event.kind:
            case "text_delta":
                ctx.text_chunks.append(event.content)
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
                ctx.tracer.start_tool_span(event)
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
                ctx.tracer.end_tool_span(event)
                result_meta = Struct()
                result_meta.update(
                    {
                        "type": "tool_result",
                        "tool_name": event.tool_name or "",
                    }
                )
                content = event.content if isinstance(event.content, str) else str(event.content)
                await self._emit_artifact(
                    ctx.updater,
                    ctx.artifact_id,
                    [Part(text=content, metadata=result_meta)],
                    ctx.created_artifacts,
                    last_chunk=False,
                )
            case "step_start":
                ctx.tracer.start_step_span(event)
            case "step_end":
                ctx.tracer.end_step_span()
            case "deferred":
                ctx.tracer.emit_approval_request_span(event)
                await self._emit_deferred_artifact(event, ctx)

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

    async def _emit_deferred_artifact(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """Emit a ``deferred`` A2A artifact for a tool approval request.

        Span lifecycle is handled by ``_TaskTracer.emit_approval_request_span``
        (called by the dispatcher before this method).  This method only
        emits the A2A artifact.
        """
        deferred = event.content
        assert isinstance(deferred, DeferredToolCall)
        deferred_meta = Struct()
        deferred_meta.update(
            {
                "type": "deferred",
                "tool_name": event.tool_name or "",
                "tool_call_id": deferred.tool_call_id,
                "reason": deferred.reason or "",
                "args": deferred.args,
            }
        )
        await self._emit_artifact(
            ctx.updater,
            ctx.artifact_id,
            [Part(text="", metadata=deferred_meta)],
            ctx.created_artifacts,
            last_chunk=False,
        )

    def _extract_approval_decisions(self, message: Any) -> list[ApprovalDecision]:
        """Pull ``ApprovalDecision`` values out of an incoming A2A message.

        Separated from ``_extract_approval_results`` so the executor can
        reason about the raw decisions (for the ``approval_decided``
        span, the Link, the decision summary attribute) without having
        to round-trip through the backend-specific
        ``DeferredToolResults`` object.  Returns an empty list when no
        ``approval_result`` metadata part is present, which is the
        signal to ``execute()`` that this is a fresh (non-resume) run.
        """
        if not message or not message.parts:
            return []

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
        return decisions

    def _extract_approval_results(self, message: Any) -> Any | None:
        """Check if an incoming A2A message contains approval decisions.

        Returns backend-specific ``DeferredToolResults`` if found,
        ``None`` otherwise.  Retained for callers that want the
        ready-to-send deferred results; prefer
        ``_extract_approval_decisions`` when you need the raw list.
        """
        decisions = self._extract_approval_decisions(message)
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
