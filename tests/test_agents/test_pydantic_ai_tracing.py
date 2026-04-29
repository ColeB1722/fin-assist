"""Tests for ``fin_assist.agents.pydantic_ai_tracing``.

This module is the backend-specific tracing bridge: it attaches the
``OpenInferenceSpanProcessor`` (from ``openinference-instrumentation-pydantic-ai``)
to a TracerProvider and configures ``Agent.instrument_all`` so pydantic-ai
emits GenAI semconv spans which are then translated to OpenInference
attributes in-place at ``on_end``.

Why this matters: pydantic-ai emits ``gen_ai.*`` attributes by default.
Phoenix's LLM renderer only activates on OpenInference attributes
(``openinference.span.kind=LLM``, ``llm.input_messages.0.message.role``, ...).
Without this bridge, the user sees "kind: unknown" and a raw-JSON message
blob in Phoenix instead of the native chat viewer.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider


@pytest.fixture(autouse=True)
def _reset_bridge_state():
    """Clear the module-level idempotency trackers between tests.

    Without this, the ``_agent_instrumented`` flag persists across tests
    and the second test in a class sees ``Agent.instrument_all`` as
    already-called.
    """
    from fin_assist.agents.pydantic_ai_tracing import _reset_for_tests

    _reset_for_tests()
    yield
    _reset_for_tests()


class TestInstallPydanticAIInstrumentation:
    def test_adds_openinference_span_processor(self):
        """The OpenInferenceSpanProcessor must be registered on the provider
        so it runs at span ``on_end`` to enrich gen_ai.* attributes into
        OpenInference llm.* attributes."""
        from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor

        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent"):
            install_pydantic_ai_instrumentation(provider)

        # Reach into the provider's processor chain (public-ish attribute).
        # We don't care about ordering, only presence.
        active_processor = provider._active_span_processor
        processors = list(getattr(active_processor, "_span_processors", ()))
        assert any(isinstance(p, OpenInferenceSpanProcessor) for p in processors), (
            "OpenInferenceSpanProcessor must be attached to the TracerProvider"
        )

    def test_calls_agent_instrument_all(self):
        """pydantic-ai emits framework spans only after ``Agent.instrument_all``
        is called.  Must happen during install_tracing."""
        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            install_pydantic_ai_instrumentation(provider)

        assert mock_agent.instrument_all.called

    def test_instrument_all_receives_explicit_settings(self):
        """Pass an explicit ``InstrumentationSettings`` rather than relying on
        library defaults, so our instrumentation behavior is visible in code
        and doesn't drift with pydantic-ai version bumps."""
        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            install_pydantic_ai_instrumentation(provider)

        call_args = mock_agent.instrument_all.call_args
        # First positional arg (or 'settings' kwarg) should be an InstrumentationSettings
        from pydantic_ai.models.instrumented import InstrumentationSettings

        settings = call_args.args[0] if call_args.args else call_args.kwargs.get("instrument")
        assert isinstance(settings, InstrumentationSettings), (
            f"expected InstrumentationSettings, got {type(settings)}"
        )

    def test_instrumentation_settings_include_content(self):
        """Content inclusion is what makes Phoenix's message viewer
        non-empty.  Explicitly on by default."""
        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            install_pydantic_ai_instrumentation(provider)

        call_args = mock_agent.instrument_all.call_args
        settings = call_args.args[0] if call_args.args else call_args.kwargs.get("instrument")
        assert settings.include_content is True

    def test_include_content_false_propagates(self):
        """For privacy-/cost-sensitive deployments the caller can pass
        ``include_content=False`` and the bridge must honor it so
        pydantic-ai emits only metadata (roles, counts) — not message
        bodies."""
        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            install_pydantic_ai_instrumentation(provider, include_content=False)

        call_args = mock_agent.instrument_all.call_args
        settings = call_args.args[0] if call_args.args else call_args.kwargs.get("instrument")
        assert settings.include_content is False

    def test_event_mode_propagates(self):
        """``event_mode='logs'`` hands LLM messages to the OTel log pipeline
        instead of embedding them on the span — useful for backends that
        render log events natively."""
        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            install_pydantic_ai_instrumentation(provider, event_mode="logs")

        call_args = mock_agent.instrument_all.call_args
        settings = call_args.args[0] if call_args.args else call_args.kwargs.get("instrument")
        assert settings.event_mode == "logs"

    def test_idempotent_on_repeated_calls(self):
        """Calling twice with the same provider must not double-register
        the processor (each SpanProcessor should appear at most once)."""
        from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor

        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent"):
            install_pydantic_ai_instrumentation(provider)
            install_pydantic_ai_instrumentation(provider)

        active_processor = provider._active_span_processor
        processors = list(getattr(active_processor, "_span_processors", ()))
        oi_count = sum(1 for p in processors if isinstance(p, OpenInferenceSpanProcessor))
        assert oi_count == 1

    def test_agent_instrument_all_called_once_across_repeated_installs(self):
        """Same idempotency check for the global ``Agent.instrument_all``
        flag — calling it twice is harmless but indicates we're not
        tracking the flip."""
        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        provider = TracerProvider()
        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            install_pydantic_ai_instrumentation(provider)
            install_pydantic_ai_instrumentation(provider)

        assert mock_agent.instrument_all.call_count == 1


class TestEnrichmentEndToEnd:
    """A pydantic-ai-produced span with ``gen_ai.*`` attributes gets
    enriched with OpenInference ``llm.*`` attributes after the processor
    runs.  This is the core Phoenix-rendering fix.
    """

    def test_gen_ai_span_gets_openinference_attributes(self):
        """Simulate a pydantic-ai-style chat span and verify that after the
        OpenInferenceSpanProcessor runs on ``on_end``, OpenInference
        attributes appear on the span.

        This exercises the real processor (no mocks on openinference itself)
        so a breaking change in the upstream bridge surfaces immediately.
        """
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        from fin_assist.agents.pydantic_ai_tracing import install_pydantic_ai_instrumentation

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with patch("fin_assist.agents.pydantic_ai_tracing.Agent"):
            install_pydantic_ai_instrumentation(provider)

        tracer = provider.get_tracer("test")
        # Mimic pydantic-ai's chat span attributes.  ``gen_ai.operation.name``
        # is what drives the span-kind translation in the bridge — without it,
        # the processor enriches the message structure but leaves the span kind
        # unset.  pydantic-ai's real chat spans always carry this attribute.
        with tracer.start_as_current_span("chat gpt-4") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", "openai")
            span.set_attribute("gen_ai.request.model", "gpt-4")
            span.set_attribute(
                "gen_ai.input.messages",
                '[{"role":"user","parts":[{"type":"text","content":"hi"}]}]',
            )
            span.set_attribute(
                "gen_ai.output.messages",
                '[{"role":"assistant","parts":[{"type":"text","content":"hello!"}]}]',
            )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})

        # Strongest signal that the bridge ran: openinference.span.kind is LLM
        assert attrs.get("openinference.span.kind") == "LLM", (
            f"OpenInferenceSpanProcessor failed to tag LLM kind; attrs = {attrs}"
        )
        # And the flattened message shape Phoenix's renderer expects
        assert attrs.get("llm.input_messages.0.message.role") == "user"
        assert attrs.get("llm.output_messages.0.message.role") == "assistant"
        assert attrs.get("llm.model_name") == "gpt-4"
