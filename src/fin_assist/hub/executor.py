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

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from google.protobuf.struct_pb2 import Struct
from opentelemetry import trace as trace_api
from opentelemetry.context import attach, detach
from opentelemetry.trace import StatusCode
from opentelemetry.trace.status import Status

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.tools import ApprovalDecision
from fin_assist.hub.tracing_attrs import (
    FinAssistAttributes,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
    SpanNames,
)
from fin_assist.protobuf import struct_to_dict

if TYPE_CHECKING:
    from a2a.server.events import EventQueue
    from opentelemetry.trace import Span, Tracer

    from fin_assist.agents.backend import AgentBackend, RunResult
    from fin_assist.agents.step import StepEvent
    from fin_assist.hub.context_store import ContextStore

logger = logging.getLogger(__name__)


def _aggregate_decisions(
    decisions: list[ApprovalDecision],
) -> tuple[str, str | None]:
    """Collapse multiple ``ApprovalDecision`` values into one span-level verdict.

    Rule:

    - Any denial → ``("denied", first_denial_reason)``.  Denial beats
      approval because the user's safety concern on any one tool should
      show up at a glance.
    - Any ``override_args`` → ``("overridden", None)``.  Distinguished
      from plain approval so reviewers see that the user tweaked
      arguments, not just rubber-stamped.
    - Otherwise → ``("approved", None)``.

    Returning a tuple keeps the reason plumbing localized — callers
    set both attributes from one call site.
    """
    denial = next((d for d in decisions if not d.approved), None)
    if denial is not None:
        return ("denied", denial.denial_reason)
    if any(d.override_args for d in decisions):
        return ("overridden", None)
    return ("approved", None)


def _get_tracer() -> Tracer:
    """Return the fin-assist OTel tracer (no-op if tracing is not set up)."""
    from opentelemetry.trace import get_tracer, get_tracer_provider

    provider = get_tracer_provider()
    from opentelemetry.trace import ProxyTracerProvider

    if isinstance(provider, ProxyTracerProvider):
        return provider.get_tracer("fin_assist")
    return get_tracer("fin_assist")


@dataclass
class _ExecutionContext:
    """Mutable state carried between Executor helper methods for one task.

    Avoids a long parameter list on each helper.  The ``task_id`` and
    ``raw_context_id`` are captured once from the request and used for
    logging and context-store persistence throughout the task lifecycle.

    OTel span tracking:

    - ``task_span`` — the one root ``fin_assist.task`` span for this run.
    - ``current_step_span`` — the currently-open ``fin_assist.step`` span,
      or ``None`` between ``step_start`` / ``step_end`` boundaries.
    - ``active_tool_spans`` — dict keyed by ``tool_call_id``.  pydantic-ai
      can emit multiple ``tool_call`` events within a single step (parallel
      tool calls) whose results arrive interleaved; keying by
      ``tool_call_id`` keeps each ``tool_call`` → ``tool_result`` pair
      correctly paired instead of letting a later call clobber the span
      of an earlier one.  Tool events without a ``tool_call_id`` (older
      backends, synthetic test events) fall back to the ``""`` key.
    """

    task_id: str
    raw_context_id: str | None
    updater: TaskUpdater
    artifact_id: str
    created_artifacts: set[str] = field(default_factory=set)
    text_chunks: list[str] = field(default_factory=list)
    task_span: Span | None = None
    current_step_span: Span | None = None
    active_tool_spans: dict[str, Span] = field(default_factory=dict)
    paused_approval_span_ctx: Any = field(default=None, repr=False)
    """SpanContext of the most recent ``approval_request`` span in this run.

    Captured in ``_handle_deferred_event`` right after the request span
    ends, consumed in ``_pause_for_approval`` to persist via the
    ContextStore so the next process can Link back to it on resume.
    ``Any`` here avoids a top-level import of ``SpanContext`` (TYPE_CHECKING
    can't help because the field is real data, not just a type hint).
    """
    _task_context_token: Any = field(default=None, repr=False)
    _step_context_token: Any = field(default=None, repr=False)


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
        self._tracer: Tracer | None = None

    @property
    def _active_tracer(self) -> Tracer:
        if self._tracer is None:
            self._tracer = _get_tracer()
        return self._tracer

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

        user_input = ""
        if context.message and hasattr(context.message, "parts"):
            user_input = getattr(context.message, "get_user_input", lambda: "")() or ""

        # Resume detection needs to happen *before* the task span is
        # started so the task span can carry a Link back to the paused
        # approval_request span.  The Link signals to Phoenix that this
        # trace is a continuation of a prior trace — the operator sees
        # a "linked" affordance and can click through.
        approval_decisions = self._extract_approval_decisions(context.message)
        prior_trace_ctx = None
        if approval_decisions and ctx.raw_context_id:
            prior_trace_ctx = await self._context_store.load_trace_context(ctx.raw_context_id)

        task_span_links = []
        if prior_trace_ctx is not None:
            link = self._make_link(prior_trace_ctx, "resume_from_approval")
            if link is not None:
                task_span_links.append(link)

        task_span = self._active_tracer.start_span(
            SpanNames.TASK,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: (OpenInferenceSpanKindValues.AGENT.value),
                "gen_ai.agent.name": self._agent_name,
                FinAssistAttributes.TASK_ID: ctx.task_id,
                FinAssistAttributes.CONTEXT_ID: ctx.raw_context_id or "",
                SpanAttributes.SESSION_ID: ctx.raw_context_id or "",
                SpanAttributes.INPUT_VALUE: user_input,
            },
            links=task_span_links or None,
        )
        ctx.task_span = task_span

        ctx._task_context_token = attach(trace_api.set_span_in_context(task_span))

        # As the first child of the resumed task, emit the
        # ``approval_decided`` span so the decision and its Link back to
        # the paused ``approval_request`` are visible before any new
        # model turn starts.
        if approval_decisions and prior_trace_ctx is not None:
            self._emit_approval_decided_span(approval_decisions, prior_trace_ctx)

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
            if ctx.task_span is not None:
                partial = "".join(ctx.text_chunks)
                if partial:
                    ctx.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, partial)
                ctx.task_span.record_exception(exc)
                ctx.task_span.set_status(Status(StatusCode.ERROR, "execute failed"))
                ctx.task_span.end()
            self._detach_task_context(ctx)
            await ctx.updater.failed()
            raise

        self._detach_task_context(ctx)

        if has_deferred:
            await self._pause_for_approval(ctx, result)
            return

        await self._finalize(ctx, result)

    def _detach_task_context(self, ctx: _ExecutionContext) -> None:
        if ctx._task_context_token is not None:
            detach(ctx._task_context_token)
            ctx._task_context_token = None

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

        Trace-context persistence is what makes pause → resume one
        browsable flow in Phoenix.  Without it, the resume's new trace
        has no Link back to the paused ``approval_request`` span and the
        user sees two disconnected traces.
        """
        if ctx.task_span is not None:
            ctx.task_span.set_attribute(FinAssistAttributes.TASK_PAUSED_FOR_APPROVAL, True)
            ctx.task_span.end()

        if ctx.raw_context_id:
            await self._context_store.save(ctx.raw_context_id, result.serialized_history)
            if ctx.paused_approval_span_ctx is not None:
                await self._context_store.save_trace_context(
                    ctx.raw_context_id,
                    ctx.paused_approval_span_ctx.trace_id,
                    ctx.paused_approval_span_ctx.span_id,
                    int(ctx.paused_approval_span_ctx.trace_flags),
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

        if ctx.task_span is not None:
            ctx.task_span.set_attribute(
                FinAssistAttributes.TASK_RESULT_TYPE, type(result.output).__name__
            )
            if isinstance(result.output, str):
                ctx.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, result.output)
            else:
                try:
                    ctx.task_span.set_attribute(
                        SpanAttributes.OUTPUT_VALUE, json.dumps(result.output)
                    )
                    ctx.task_span.set_attribute(
                        SpanAttributes.OUTPUT_MIME_TYPE,
                        OpenInferenceMimeTypeValues.JSON.value,
                    )
                except (TypeError, ValueError):
                    ctx.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, str(result.output))
            ctx.task_span.end()

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
        """Start a ``fin_assist.step`` span as a child of the task span."""
        parent = ctx.current_step_span or ctx.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        ctx.current_step_span = self._active_tracer.start_span(
            SpanNames.STEP,
            context=parent_context,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: (OpenInferenceSpanKindValues.CHAIN.value),
                FinAssistAttributes.STEP_NUMBER: event.step,
            },
        )
        ctx._step_context_token = attach(trace_api.set_span_in_context(ctx.current_step_span))

    def _end_step_span(self, ctx: _ExecutionContext) -> None:
        """End the current step span and restore the task span as active context."""
        if ctx._step_context_token is not None:
            detach(ctx._step_context_token)
            ctx._step_context_token = None

        if ctx.current_step_span is not None:
            ctx.current_step_span.end()
        ctx.current_step_span = None

    def _start_tool_span(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """Start a ``fin_assist.tool_execution`` span as a child of the current step span.

        Spans are stored in ``ctx.active_tool_spans`` keyed by
        ``tool_call_id``.  Multiple parallel tool calls within a single
        step each get their own entry so ``_end_tool_span`` can close the
        correct one when the matching ``tool_result`` arrives.
        """
        parent = ctx.current_step_span or ctx.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        args = event.metadata.get("args", {})
        args_str = json.dumps(args) if isinstance(args, dict) else str(args)
        tool_call_id = str(event.metadata.get("tool_call_id") or "")
        span = self._active_tracer.start_span(
            SpanNames.TOOL_EXECUTION,
            context=parent_context,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.TOOL.value,
                SpanAttributes.TOOL_NAME: event.tool_name or "",
                FinAssistAttributes.TOOL_NAME: event.tool_name or "",
                FinAssistAttributes.TOOL_ARGS: args_str,
                FinAssistAttributes.TOOL_CALL_ID: tool_call_id,
                SpanAttributes.INPUT_VALUE: args_str,
                SpanAttributes.INPUT_MIME_TYPE: OpenInferenceMimeTypeValues.JSON.value,
            },
        )
        ctx.active_tool_spans[tool_call_id] = span

    def _end_tool_span(self, event: StepEvent, ctx: _ExecutionContext) -> None:
        """End the tool-execution span matching this ``tool_result`` event.

        Looks up the span by ``tool_call_id`` so parallel tool calls don't
        clobber each other.  Falls back to ending a single lone span if
        the id is missing (older backends / synthetic test events).
        """
        tool_call_id = str(event.metadata.get("tool_call_id") or "")
        span = ctx.active_tool_spans.pop(tool_call_id, None)
        if span is None and tool_call_id == "" and len(ctx.active_tool_spans) == 1:
            # Test-fixture compatibility: events without tool_call_id can
            # still close the single open span unambiguously.
            lone_key = next(iter(ctx.active_tool_spans))
            span = ctx.active_tool_spans.pop(lone_key)
        if span is None:
            return
        content = event.content if isinstance(event.content, str) else str(event.content)
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, content)
        span.end()

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
        """Emit an ``approval_request`` span and a ``deferred`` A2A artifact.

        The approval-request span is started **and** ended in this
        method — OTel spans cannot be reopened across processes, so the
        actual wait-for-user is represented implicitly by the time-gap
        between this span's end and the ``approval_decided`` span that
        opens when the task resumes (see architecture.md → HITL tracing).

        The span carries ``approval.status = "paused"`` so Phoenix/other
        UIs can filter pending approvals without needing to know about
        the downstream decision.
        """
        parent = ctx.current_step_span or ctx.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        deferred_content = event.content
        args = getattr(deferred_content, "args", {})
        args_str = json.dumps(args) if isinstance(args, dict) else str(args)
        tool_call_id = getattr(deferred_content, "tool_call_id", "") or ""
        reason = getattr(deferred_content, "reason", None) or ""

        approval_span = self._active_tracer.start_span(
            SpanNames.APPROVAL_REQUEST,
            context=parent_context,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.TOOL.value,
                SpanAttributes.TOOL_NAME: event.tool_name or "",
                FinAssistAttributes.TOOL_NAME: event.tool_name or "",
                FinAssistAttributes.TOOL_CALL_ID: tool_call_id,
                FinAssistAttributes.APPROVAL_STATUS: "paused",
                FinAssistAttributes.APPROVAL_REASON: reason,
                SpanAttributes.INPUT_VALUE: args_str,
                SpanAttributes.INPUT_MIME_TYPE: OpenInferenceMimeTypeValues.JSON.value,
            },
        )
        # Capture the SpanContext **before** ending — SpanContext is
        # immutable and safe to stash; we'll persist it in
        # ``_pause_for_approval`` so the resume task in a potentially
        # different process can Link back here.
        ctx.paused_approval_span_ctx = approval_span.get_span_context()
        approval_span.end()

        deferred_meta = Struct()
        deferred_meta.update(
            {
                "type": "deferred",
                "tool_name": event.tool_name or "",
                "tool_call_id": tool_call_id,
                "reason": reason,
                "args": args,
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
        to round-trip through the framework-specific
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

        Returns framework-specific ``DeferredToolResults`` if found,
        ``None`` otherwise.  Retained for callers that want the
        ready-to-send deferred results; prefer
        ``_extract_approval_decisions`` when you need the raw list.
        """
        decisions = self._extract_approval_decisions(message)
        if not decisions:
            return None
        return self._backend.build_deferred_results(decisions)

    def _make_link(
        self,
        trace_ctx: tuple[int, int, int],
        link_type: str,
    ) -> Any:
        """Build an OTel ``Link`` from a persisted ``(trace, span, flags)``.

        The flags live in ``TraceFlags`` (1-bit sampled flag today).  We
        mark the context as remote because the paused span was exported
        from a potentially different process.  Returns ``None`` if the
        IDs look invalid (zero), so callers don't attach broken links.
        """
        from opentelemetry.trace import (
            Link,
            SpanContext,
            TraceFlags,
        )

        trace_id, span_id, flags = trace_ctx
        if trace_id == 0 or span_id == 0:
            return None
        span_ctx = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            trace_flags=TraceFlags(flags),
        )
        return Link(span_ctx, attributes={FinAssistAttributes.LINK_TYPE: link_type})

    def _emit_approval_decided_span(
        self,
        decisions: list[ApprovalDecision],
        prior_trace_ctx: tuple[int, int, int],
    ) -> None:
        """Emit the ``approval_decided`` span as the first child of the
        resumed task span.

        Carries the aggregate decision (``approved``/``denied``/
        ``overridden``) as an attribute and a ``Link`` back to the
        paused ``approval_request`` span (tagged ``approval_for``) so
        Phoenix can render the full decision trail.

        With multiple decisions in one resume message, the aggregate
        rule is: if **any** decision is a denial, the span's decision
        is ``denied``; if any include ``override_args``, it's
        ``overridden``; otherwise ``approved``.  The first denial's
        ``denial_reason`` is preserved as ``approval.reason`` so the
        operator sees *why* the flow stopped.
        """
        aggregate_decision, reason = _aggregate_decisions(decisions)
        link = self._make_link(prior_trace_ctx, "approval_for")
        links = [link] if link is not None else None

        attributes: dict[str, Any] = {
            SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.TOOL.value,
            FinAssistAttributes.APPROVAL_DECISION: aggregate_decision,
        }
        if reason:
            attributes[FinAssistAttributes.APPROVAL_REASON] = reason

        decided_span = self._active_tracer.start_span(
            SpanNames.APPROVAL_DECIDED,
            attributes=attributes,
            links=links,
        )
        decided_span.end()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        logger.info("cancel task_id=%s", task_id)
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context.context_id or str(uuid.uuid4()),
        )
        await updater.cancel()
