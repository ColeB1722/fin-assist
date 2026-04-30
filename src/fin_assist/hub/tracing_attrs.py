"""Central attribute names and values for fin-assist OTel spans.

Two layers:

1. **OpenInference semantic conventions** — re-exported from
   ``openinference.semconv.trace``.  Every OpenInference attribute used
   in fin-assist code should come through this module to prevent silent
   drift (e.g. wrong MIME type values that break LLM renderers).

2. **fin-assist platform attributes** — ``fin_assist.*`` namespace for
   concepts OpenInference doesn't model (task/context IDs, approval
   flow, step counters).  Collected on ``FinAssistAttributes``.

Span names are centralized on ``SpanNames`` so renames happen in one
place.

Attribute precedence in executor.py and backends:

- ``SpanAttributes.*`` / ``OpenInferenceSpanKindValues.*.value`` /
  ``OpenInferenceMimeTypeValues.*.value`` for OpenInference conventions.
- ``FinAssistAttributes.*`` for platform-specific additions.
- ``SpanNames.*`` for span names.
"""

from __future__ import annotations

from openinference.semconv.trace import (
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)

__all__ = [
    "FinAssistAttributes",
    "OpenInferenceMimeTypeValues",
    "OpenInferenceSpanKindValues",
    "SpanAttributes",
    "SpanNames",
    "TaskStateValues",
]


class FinAssistAttributes:
    """fin-assist-specific span attributes.

    These live alongside the OpenInference re-exports so there is one
    import point for "what attributes does fin-assist set on its spans."
    """

    TASK_ID = "fin_assist.task.id"
    """A2A task id (UUID).  Unique per request even for the same context."""

    CONTEXT_ID = "fin_assist.context.id"
    """A2A context id (conversation thread).  Stable across a conversation;
    doubles as the OpenInference ``session.id``."""

    STEP_NUMBER = "fin_assist.step.number"
    """0-indexed step counter inside a task."""

    TASK_RESULT_TYPE = "fin_assist.task.result_type"
    """Python type name of the task result (e.g. ``"str"`` or a pydantic
    model name for structured output)."""

    TASK_STATE = "fin_assist.task.state"
    """Terminal lifecycle state of a task, set on the ``fin_assist.task``
    span before it ends.  Distinct from A2A's ``TaskState`` (which is
    the wire protocol state) because it collapses uninteresting A2A
    states and distinguishes interesting platform sub-states that A2A
    doesn't model (e.g. ``paused_for_approval`` vs generic INPUT_REQUIRED).

    Valid values live on :class:`TaskStateValues`.

    One attribute with a small enum makes Phoenix filtering trivial:
    one equality check per state instead of a compound predicate over
    several booleans.  Replaces a short-lived
    ``fin_assist.task.paused_for_approval`` boolean that never shipped
    outside this branch."""

    CLI_INVOCATION_ID = "fin_assist.cli.invocation_id"
    """Matches the CLI-side attribute of the same name.  Stamped on the
    ``fin_assist.task`` span by the executor when OTel baggage carries
    the key (propagated over HTTP from the CLI tracer).  This is the
    join key between the CLI trace and the hub task span — they live in
    different ``trace_id``s because the HTTP boundary opens a new trace,
    but both carry the same invocation_id."""

    TOOL_NAME = "fin_assist.tool.name"
    """fin-assist's own tool-name attribute, parallel to the OpenInference
    ``tool.name``.  Both are set so queries against either work."""

    TOOL_CALL_ID = "fin_assist.tool.call_id"
    """Unique id for a single tool invocation — used as the dict key for
    ``active_tool_spans`` so parallel tool calls within one step don't
    clobber each other."""

    TOOL_ARGS = "fin_assist.tool.args"
    """JSON-encoded tool arguments."""

    APPROVAL_STATUS = "fin_assist.approval.status"
    """Status of the approval request span: ``"pending"`` at start,
    ``"paused"`` after end.  Distinct from the decision, which lives on
    the ``approval_decided`` span."""

    APPROVAL_DECISION = "fin_assist.approval.decision"
    """One of ``"approved"``, ``"denied"``, ``"overridden"``.  Set only on
    the ``approval_decided`` span (created at resume)."""

    APPROVAL_REASON = "fin_assist.approval.reason"
    """Human-readable reason — either the tool's approval policy reason
    (on the request span) or the user's denial reason (on the decided span)."""

    LINK_TYPE = "fin_assist.link.type"
    """Describes the semantic relationship of a span Link.  Known values:
    ``"resume_from_approval"`` (task span → paused approval_request span),
    ``"approval_for"`` (approval_decided → approval_request)."""


class TaskStateValues:
    """Valid values for :attr:`FinAssistAttributes.TASK_STATE`.

    Kept as string constants (rather than ``enum.Enum``) so they can be
    set directly on OTel spans without ``.value`` unwrapping at every
    call site.  Centralized here so a renamed state is a single edit
    across executor.py and its tests.
    """

    RUNNING = "running"
    """Set at the start of ``execute()``; replaced by a terminal value
    before the task span ends."""

    PAUSED_FOR_APPROVAL = "paused_for_approval"
    """The task is awaiting human approval.  Terminal from the point of
    view of the *span* — the resume opens a new trace and a new span."""

    RESUMED_FROM_APPROVAL = "resumed_from_approval"
    """Transient: set at the start of a resume, immediately before
    ``completed``/``failed`` replaces it.  Observable on the
    ``approval_decided`` span rather than the task span (task.state is
    last-write-wins)."""

    COMPLETED = "completed"
    """Normal successful completion."""

    FAILED = "failed"
    """Exception during ``execute()``; the task span was marked ERROR."""


class SpanNames:
    """Canonical span names.  Centralized so renames are a single edit."""

    TASK = "fin_assist.task"
    STEP = "fin_assist.step"
    TOOL_EXECUTION = "fin_assist.tool_execution"
    APPROVAL_REQUEST = "fin_assist.approval_request"
    """Emitted at pause time: the tool call that required approval.
    Started + ended at pause (spans cannot be reopened across processes);
    the wait-for-user duration is implicit in the time-gap between this
    span's end and the next trace's start."""
    APPROVAL_DECIDED = "fin_assist.approval_decided"
    """Emitted at resume time as the first child of the resumed task span.
    Carries the decision and a Link back to the ``approval_request`` span."""
