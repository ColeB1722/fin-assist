"""Per-task OTel span lifecycle — extracted from Executor.

``_TaskTracer`` owns all span creation, attribute setting, and context
token management for one task invocation.  The executor creates a
``_TaskTracer`` at the start of ``execute()`` and delegates all OTel
calls through it.  Business logic (A2A artifact emission, task state
transitions, history persistence) stays in the executor.

Span hierarchy managed by this class:

- ``task_span`` — one root ``fin_assist.task`` span per invocation.
- ``current_step_span`` — the currently-open ``fin_assist.step``
  span, or ``None`` between step boundaries.
- ``active_tool_spans`` — dict keyed by ``tool_call_id``.  Parallel
  tool calls within a single step each get their own entry so
  ``end_tool_span`` can close the correct one when the matching
  ``tool_result`` arrives.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace as trace_api
from opentelemetry.context import attach, detach
from opentelemetry.trace import StatusCode
from opentelemetry.trace.status import Status

from fin_assist.agents.tools import DeferredToolCall
from fin_assist.hub.tracing_attrs import (
    FinAssistAttributes,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
    SpanNames,
    TaskStateValues,
)

if TYPE_CHECKING:
    from opentelemetry.trace import Span, Tracer

    from fin_assist.agents.step import StepEvent
    from fin_assist.agents.tools import ApprovalDecision

logger = logging.getLogger(__name__)


def _get_tracer() -> Tracer:
    """Return the fin-assist OTel tracer (no-op if tracing is not set up)."""
    from opentelemetry.trace import get_tracer, get_tracer_provider

    provider = get_tracer_provider()
    from opentelemetry.trace import ProxyTracerProvider

    if isinstance(provider, ProxyTracerProvider):
        return provider.get_tracer("fin_assist")
    return get_tracer("fin_assist")


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
    - otherwise → ``("approved", None)``.
    """
    denial = next((d for d in decisions if not d.approved), None)
    if denial is not None:
        return ("denied", denial.denial_reason)
    if any(d.override_args for d in decisions):
        return ("overridden", None)
    return ("approved", None)


class _TaskTracer:
    """Owns all OTel span lifecycle for one task invocation.

    Created by the executor at the start of ``execute()`` and stored on
    ``_ExecutionContext.tracer``.  All span creation, attribute setting,
    and context token management goes through this class.  The executor
    never touches OTel APIs directly.
    """

    def __init__(self) -> None:
        self.task_span: Span | None = None
        self.current_step_span: Span | None = None
        self.active_tool_spans: dict[str, Span] = {}
        self.paused_approval_span_ctx: Any = None
        self._task_context_token: Any = None
        self._step_context_token: Any = None
        self._tracer: Tracer | None = None
        self._task_id: str = ""

    @property
    def _active_tracer(self) -> Tracer:
        if self._tracer is None:
            self._tracer = _get_tracer()
        return self._tracer

    def read_invocation_id_from_baggage(self) -> str:
        """Read ``fin_assist.cli.invocation_id`` from current OTel baggage.

        Returns the empty string if baggage is missing or the value
        isn't a string — callers treat ``""`` as "no CLI trace" and skip
        setting the attribute.
        """
        from opentelemetry import baggage

        value = baggage.get_baggage(FinAssistAttributes.CLI_INVOCATION_ID)
        return value if isinstance(value, str) else ""

    def start_task_span(
        self,
        *,
        agent_name: str,
        task_id: str,
        context_id: str | None,
        user_input: str,
        links: list[Any] | None = None,
    ) -> None:
        """Create and activate the root ``fin_assist.task`` span."""
        attributes: dict[str, Any] = {
            SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.AGENT.value,
            FinAssistAttributes.GEN_AI_AGENT_NAME: agent_name,
            FinAssistAttributes.TASK_ID: task_id,
            FinAssistAttributes.CONTEXT_ID: context_id or "",
            SpanAttributes.SESSION_ID: context_id or "",
            SpanAttributes.INPUT_VALUE: user_input,
            FinAssistAttributes.TASK_STATE: TaskStateValues.RUNNING,
        }

        invocation_id = self.read_invocation_id_from_baggage()
        if invocation_id:
            attributes[FinAssistAttributes.CLI_INVOCATION_ID] = invocation_id

        self.task_span = self._active_tracer.start_span(
            SpanNames.TASK,
            attributes=attributes,
            links=links,
        )
        self._task_context_token = attach(trace_api.set_span_in_context(self.task_span))
        self._task_id = task_id
        logger.info("task_span started agent=%s task_id=%s", agent_name, task_id)

    def end_task_span_completed(self, result: Any) -> None:
        """Set output attributes and end the task span on success."""
        if self.task_span is None:
            return
        self.task_span.set_attribute(FinAssistAttributes.TASK_RESULT_TYPE, type(result).__name__)
        self.task_span.set_attribute(FinAssistAttributes.TASK_STATE, TaskStateValues.COMPLETED)
        if isinstance(result, str):
            self.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, result)
        else:
            try:
                self.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, json.dumps(result))
                self.task_span.set_attribute(
                    SpanAttributes.OUTPUT_MIME_TYPE,
                    OpenInferenceMimeTypeValues.JSON.value,
                )
            except (TypeError, ValueError):
                self.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, str(result))
        self.task_span.end()
        logger.info("task_span completed task_id=%s", self._task_id)

    def end_task_span_paused(self) -> None:
        """Set paused state and end the task span before approval pause."""
        if self.task_span is None:
            return
        self.task_span.set_attribute(
            FinAssistAttributes.TASK_STATE, TaskStateValues.PAUSED_FOR_APPROVAL
        )
        self.task_span.end()
        logger.info("task_span paused task_id=%s", self._task_id)

    def end_task_span_failed(self, partial_output: str, exc: Exception) -> None:
        """Set error attributes and end the task span on failure."""
        if self.task_span is None:
            return
        if partial_output:
            self.task_span.set_attribute(SpanAttributes.OUTPUT_VALUE, partial_output)
        self.task_span.set_attribute(FinAssistAttributes.TASK_STATE, TaskStateValues.FAILED)
        self.task_span.record_exception(exc)
        self.task_span.set_status(Status(StatusCode.ERROR, "execute failed"))
        self.task_span.end()
        logger.info("task_span failed task_id=%s exc=%s", self._task_id, type(exc).__name__)

    def detach_task_context(self) -> None:
        """Detach the task span's OTel context token."""
        if self._task_context_token is not None:
            detach(self._task_context_token)
            self._task_context_token = None

    def start_step_span(self, event: StepEvent) -> None:
        """Start a ``fin_assist.step`` span as a child of the task span."""
        parent = self.current_step_span or self.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        self.current_step_span = self._active_tracer.start_span(
            SpanNames.STEP,
            context=parent_context,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.CHAIN.value,
                FinAssistAttributes.STEP_NUMBER: event.step,
            },
        )
        self._step_context_token = attach(trace_api.set_span_in_context(self.current_step_span))

    def end_step_span(self) -> None:
        """End the current step span and restore the task span as active context."""
        if self._step_context_token is not None:
            detach(self._step_context_token)
            self._step_context_token = None

        if self.current_step_span is not None:
            self.current_step_span.end()
        self.current_step_span = None

    def start_tool_span(self, event: StepEvent) -> None:
        """Start a ``fin_assist.tool_execution`` span as a child of the current step span.

        Spans are stored in ``active_tool_spans`` keyed by
        ``tool_call_id``.  Multiple parallel tool calls within a single
        step each get their own entry so ``end_tool_span`` can close the
        correct one when the matching ``tool_result`` arrives.
        """
        parent = self.current_step_span or self.task_span
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
        self.active_tool_spans[tool_call_id] = span

    def end_tool_span(self, event: StepEvent) -> None:
        """End the tool-execution span matching this ``tool_result`` event.

        Looks up the span by ``tool_call_id`` so parallel tool calls don't
        clobber each other.  Falls back to ending a single lone span if
        the id is missing (older backends / synthetic test events).
        """
        tool_call_id = str(event.metadata.get("tool_call_id") or "")
        span = self.active_tool_spans.pop(tool_call_id, None)
        if span is None and tool_call_id == "" and len(self.active_tool_spans) == 1:
            lone_key = next(iter(self.active_tool_spans))
            span = self.active_tool_spans.pop(lone_key)
        if span is None:
            return
        content = event.content if isinstance(event.content, str) else str(event.content)
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, content)
        span.end()

    def make_link(
        self,
        trace_ctx: tuple[int, int, int],
        link_type: str,
    ) -> Any:
        """Build an OTel ``Link`` from a persisted ``(trace, span, flags)``.

        Returns ``None`` if the IDs look invalid (zero), so callers don't
        attach broken links.
        """
        from opentelemetry.trace import Link, SpanContext, TraceFlags

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

    def emit_approval_decided_span(
        self,
        decisions: list[ApprovalDecision],
        prior_trace_ctx: tuple[int, int, int],
    ) -> None:
        """Emit the ``approval_decided`` span as the first child of the
        resumed task span.

        Carries the aggregate decision (``approved``/``denied``/
        ``overridden``) as an attribute and a ``Link`` back to the
        paused ``approval_request`` span (tagged ``approval_for``) so
        OTel backends can render the full decision trail.
        """
        aggregate_decision, reason = _aggregate_decisions(decisions)
        link = self.make_link(prior_trace_ctx, "approval_for")
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

    def emit_approval_request_span(self, event: StepEvent) -> None:
        """Emit an ``approval_request`` span and capture its SpanContext.

        The span is started **and** ended in this method — OTel spans
        cannot be reopened across processes, so the actual
        wait-for-user is represented implicitly by the time-gap between
        this span's end and the ``approval_decided`` span that opens
        when the task resumes.

        After this call, ``paused_approval_span_ctx`` holds the
        ``SpanContext`` for the executor to persist via the
        ``ContextStore`` so the resume can Link back.
        """
        parent = self.current_step_span or self.task_span
        parent_context = trace_api.set_span_in_context(parent) if parent else None
        deferred = event.content
        if not isinstance(deferred, DeferredToolCall):
            raise TypeError(f"Expected DeferredToolCall, got {type(deferred).__name__}")
        args_str = (
            json.dumps(deferred.args) if isinstance(deferred.args, dict) else str(deferred.args)
        )

        approval_span = self._active_tracer.start_span(
            SpanNames.APPROVAL_REQUEST,
            context=parent_context,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.TOOL.value,
                SpanAttributes.TOOL_NAME: event.tool_name or "",
                FinAssistAttributes.TOOL_NAME: event.tool_name or "",
                FinAssistAttributes.TOOL_CALL_ID: deferred.tool_call_id,
                FinAssistAttributes.APPROVAL_STATUS: "paused",
                FinAssistAttributes.APPROVAL_REASON: deferred.reason or "",
                SpanAttributes.INPUT_VALUE: args_str,
                SpanAttributes.INPUT_MIME_TYPE: OpenInferenceMimeTypeValues.JSON.value,
            },
        )
        self.paused_approval_span_ctx = approval_span.get_span_context()
        approval_span.end()
