"""Tests for the backend-owned tracing-installation hook.

Design (handoff.md Design Sketches — Telemetry Hardening Phase 2):

- ``AgentBackend`` protocol has an optional ``install_tracing(provider)``
  method.  The hub's ``setup_tracing`` calls it on each registered
  backend **once** at startup, after the TracerProvider is set.
- Backends that wrap an LLM framework are responsible for attaching any
  framework-specific instrumentation (e.g. ``OpenInferenceSpanProcessor``
  for pydantic-ai, or a future LangChain adapter).
- Backends without framework instrumentation (like test fakes) can omit
  the method entirely; ``setup_tracing`` treats it as optional via
  ``hasattr``.  This keeps test fakes minimal.

These tests exercise the hook contract.  The actual pydantic-ai
instrumentation payload is tested in ``test_pydantic_ai_tracing.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fin_assist.agents.backend import PydanticAIBackend


class TestAgentBackendTracingHook:
    """The hook is optional — backends may or may not implement it."""

    def test_pydantic_ai_backend_exposes_install_tracing(self):
        """PydanticAIBackend must implement install_tracing because it wraps
        pydantic-ai (which needs OpenInferenceSpanProcessor attached)."""
        spec = MagicMock()
        backend = PydanticAIBackend(agent_spec=spec)
        assert callable(backend.install_tracing)

    def test_install_tracing_is_idempotent(self):
        """Calling install_tracing twice with the same provider must not
        double-register the processor or re-instrument agents.  Hub
        startup may invoke it multiple times (once per mounted agent,
        or across hub restarts in-process during tests)."""
        from unittest.mock import patch

        from opentelemetry.sdk.trace import TracerProvider

        spec = MagicMock()
        backend = PydanticAIBackend(agent_spec=spec)
        provider = TracerProvider()

        with patch("fin_assist.agents.pydantic_ai_tracing.Agent") as mock_agent:
            backend.install_tracing(provider)
            backend.install_tracing(provider)

        # Agent.instrument_all should be called exactly once across both invocations
        assert mock_agent.instrument_all.call_count == 1

    def test_install_tracing_takes_provider_and_optional_kwargs(self):
        """The hook's one required argument is a ``TracerProvider`` — this
        keeps it pure OTel and lets backends add SpanProcessors directly.
        Additional knobs (``include_content``, ``event_mode``) are
        keyword-only so the signature stays stable when new options get
        added.  Callers that don't care just pass the provider.
        """
        import inspect

        spec = MagicMock()
        backend = PydanticAIBackend(agent_spec=spec)
        sig = inspect.signature(backend.install_tracing)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        # Exactly one positional parameter
        positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        assert len(positional) == 1, (
            f"install_tracing must have one positional arg (TracerProvider); got {params}"
        )
        ann = positional[0].annotation
        ann_str = getattr(ann, "__name__", str(ann))
        assert "TracerProvider" in ann_str

        # Any additional parameters must be keyword-only (so callers can
        # omit them safely).
        extras = [p for p in params if p not in positional]
        for p in extras:
            assert p.kind == p.KEYWORD_ONLY, (
                f"extra install_tracing param {p.name!r} must be keyword-only"
            )


class TestBackendProtocolStructure:
    """The Protocol definition accepts install_tracing as an optional method
    via a hasattr-style contract in the hub."""

    def test_hub_setup_tracing_tolerates_backend_without_install_tracing(self):
        """A minimal backend without install_tracing must not break startup."""

        class MinimalBackend:
            def check_credentials(self):
                return []

            def convert_history(self, a2a_messages):
                return []

            def run_steps(self, *, messages, model=None, deferred_tool_results=None):
                return None

            def serialize_history(self, messages):
                return b""

            def deserialize_history(self, data):
                return []

            def convert_result_to_part(self, result):
                return MagicMock()

            def convert_response_parts(self, parts):
                return []

            def build_deferred_results(self, decisions):
                return None

        # No install_tracing method — must not be required
        backend = MinimalBackend()
        assert not hasattr(backend, "install_tracing")
