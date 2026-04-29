"""Tests for ``fin_assist.hub.tracing_attrs``.

This module is a thin re-export of OpenInference semantic-convention
constants.  Its job is to centralize attribute names/values so the rest of
the codebase never hand-types OpenInference strings (which is the source
of several subtle Phoenix rendering bugs: ``"json"`` vs ``"application/json"``,
``"gen_ai.agent.name"`` vs ``"agent.name"``, etc.).

Tests verify:

1. The re-exports exist with the same identity as the upstream symbols
   (so any version of the OpenInference package transparently flows through).
2. The canonical string values match the OpenInference spec
   (``application/json``, not ``json``; ``openinference.span.kind``, not
   ``span.kind``).  Phoenix's LLM renderer only recognizes the canonical
   forms; divergence is a silent Phoenix-rendering bug.
"""

from __future__ import annotations


class TestSemconvConstantsReexported:
    """The module re-exports the exact upstream symbols from openinference.semconv.trace."""

    def test_span_attributes_is_upstream_class(self):
        from openinference.semconv.trace import SpanAttributes as Upstream

        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes is Upstream

    def test_span_kind_values_is_upstream_enum(self):
        from openinference.semconv.trace import OpenInferenceSpanKindValues as Upstream

        from fin_assist.hub.tracing_attrs import OpenInferenceSpanKindValues

        assert OpenInferenceSpanKindValues is Upstream

    def test_mime_type_values_is_upstream_enum(self):
        from openinference.semconv.trace import OpenInferenceMimeTypeValues as Upstream

        from fin_assist.hub.tracing_attrs import OpenInferenceMimeTypeValues

        assert OpenInferenceMimeTypeValues is Upstream


class TestCanonicalValues:
    """Lock in the canonical values Phoenix's renderer expects.

    If OpenInference ever changes these (breaking change), these tests pin
    it and we notice before Phoenix rendering silently breaks.
    """

    def test_span_kind_attribute_key(self):
        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes.OPENINFERENCE_SPAN_KIND == "openinference.span.kind"

    def test_input_value_attribute_key(self):
        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes.INPUT_VALUE == "input.value"

    def test_input_mime_type_attribute_key(self):
        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes.INPUT_MIME_TYPE == "input.mime_type"

    def test_output_value_attribute_key(self):
        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes.OUTPUT_VALUE == "output.value"

    def test_session_id_attribute_key(self):
        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes.SESSION_ID == "session.id"

    def test_tool_name_attribute_key(self):
        from fin_assist.hub.tracing_attrs import SpanAttributes

        assert SpanAttributes.TOOL_NAME == "tool.name"

    def test_mime_type_json_is_application_json(self):
        """Regression: executor previously hand-typed ``"json"``.  Phoenix's LLM
        renderer expects ``application/json`` per the OpenInference spec; a
        non-canonical value causes the span to render as plain text."""
        from fin_assist.hub.tracing_attrs import OpenInferenceMimeTypeValues

        assert OpenInferenceMimeTypeValues.JSON.value == "application/json"

    def test_span_kind_values_are_uppercase(self):
        from fin_assist.hub.tracing_attrs import OpenInferenceSpanKindValues

        assert OpenInferenceSpanKindValues.AGENT.value == "AGENT"
        assert OpenInferenceSpanKindValues.CHAIN.value == "CHAIN"
        assert OpenInferenceSpanKindValues.TOOL.value == "TOOL"
        assert OpenInferenceSpanKindValues.LLM.value == "LLM"


class TestFinAssistNamespaceConstants:
    """fin-assist adds its own platform-specific attribute namespace on top
    of OpenInference.  These live in ``tracing_attrs`` alongside the re-exports
    so there is one import surface for "attributes used by fin-assist spans".
    """

    def test_task_id_attr(self):
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.TASK_ID == "fin_assist.task.id"

    def test_context_id_attr(self):
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.CONTEXT_ID == "fin_assist.context.id"

    def test_step_number_attr(self):
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.STEP_NUMBER == "fin_assist.step.number"

    def test_tool_call_id_attr(self):
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.TOOL_CALL_ID == "fin_assist.tool.call_id"

    def test_approval_decision_attr(self):
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.APPROVAL_DECISION == "fin_assist.approval.decision"

    def test_approval_status_attr(self):
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.APPROVAL_STATUS == "fin_assist.approval.status"

    def test_link_type_attr(self):
        """Used on span Links to describe the semantic relationship
        between the linked span and this one (e.g. ``resume_from_approval``)."""
        from fin_assist.hub.tracing_attrs import FinAssistAttributes

        assert FinAssistAttributes.LINK_TYPE == "fin_assist.link.type"


class TestSpanNames:
    """Span names are also centralized so renames happen in one place."""

    def test_task_span_name(self):
        from fin_assist.hub.tracing_attrs import SpanNames

        assert SpanNames.TASK == "fin_assist.task"

    def test_step_span_name(self):
        from fin_assist.hub.tracing_attrs import SpanNames

        assert SpanNames.STEP == "fin_assist.step"

    def test_tool_execution_span_name(self):
        from fin_assist.hub.tracing_attrs import SpanNames

        assert SpanNames.TOOL_EXECUTION == "fin_assist.tool_execution"

    def test_approval_request_span_name(self):
        """Renamed from ``fin_assist.approval`` to be explicit that this is
        the *request* (issued at pause); the decision lives on a separate
        span started at resume."""
        from fin_assist.hub.tracing_attrs import SpanNames

        assert SpanNames.APPROVAL_REQUEST == "fin_assist.approval_request"

    def test_approval_decided_span_name(self):
        from fin_assist.hub.tracing_attrs import SpanNames

        assert SpanNames.APPROVAL_DECIDED == "fin_assist.approval_decided"
