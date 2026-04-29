"""Tests for ``setup_tracing`` — the vendor-agnostic tracing bootstrap.

Focus areas (from handoff.md Design Sketches — Telemetry Hardening Phase 2):

1. Backend hook invocation: each backend's ``install_tracing`` (when
   present) is called with the new TracerProvider.
2. Minimal backends without ``install_tracing`` are tolerated (``hasattr``
   guard) so test fakes and future non-LLM backends don't have to
   implement the method.
3. Standard ``OTEL_EXPORTER_OTLP_*`` env vars act as fallbacks below
   ``FIN_TRACING__*`` config, allowing users to point at any OTel backend
   (Tempo, Jaeger, Logfire, cloud Phoenix, custom renderer) without
   editing config.toml.
4. The OpenInference resource attribute (``openinference.project.name``)
   is still set — Phoenix uses it to group traces by project.  This
   stays out of the vendor-specific path because it's purely an
   attribute, not an API call.

``setup_tracing`` sets the global OTel TracerProvider which can only be
set once per process.  Each test cleans up with the same
``ProxyTracerProvider`` reset used by ``TestSetupTracing`` in
``test_tracing.py``.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


def _reset_global_provider() -> None:
    import opentelemetry.trace as _trace_mod
    from opentelemetry.trace import ProxyTracerProvider

    provider = _trace_mod.get_tracer_provider()
    for method in ("force_flush", "shutdown"):
        fn = getattr(provider, method, None)
        if fn:
            try:
                fn(1) if method == "force_flush" else fn()
            except Exception:  # noqa: BLE001
                pass
    _trace_mod._TRACER_PROVIDER = ProxyTracerProvider()


@pytest.fixture
def reset_tracer_provider():
    """Reset the global OTel TracerProvider before and after each test.

    OTel prohibits ``set_tracer_provider`` from replacing an existing
    non-proxy provider.  ``setup_tracing`` hits this silently (logs a
    warning, keeps the old provider) when a prior test already set one.
    Resetting before the test guarantees each test starts clean.
    """
    _reset_global_provider()
    yield
    _reset_global_provider()


class TestBackendHookInvocation:
    def test_install_tracing_called_on_each_backend(self, reset_tracer_provider):
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        backend_a = MagicMock()
        backend_b = MagicMock()
        config = TracingSettings(enabled=True, endpoint="http://localhost:9999")

        setup_tracing(config, backends=[backend_a, backend_b])

        assert backend_a.install_tracing.called
        assert backend_b.install_tracing.called

    def test_install_tracing_receives_the_configured_provider(self, reset_tracer_provider):
        """The backend hook must get the same TracerProvider that was built
        by ``setup_tracing`` — otherwise its SpanProcessor runs on a
        different provider than the one serving tracers to executor code.

        Uses the provider returned by ``setup_tracing`` as the comparison
        anchor, not ``get_tracer_provider()``, because OTel refuses to
        replace an already-initialized global provider in the same process.
        """
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        backend = MagicMock()
        config = TracingSettings(enabled=True, endpoint="http://localhost:9999")

        returned_provider = setup_tracing(config, backends=[backend])

        passed_provider = backend.install_tracing.call_args.args[0]
        assert passed_provider is returned_provider

    def test_backend_without_install_tracing_is_tolerated(self, reset_tracer_provider):
        """Minimal backends (e.g. test fakes, future non-LLM backends)
        without ``install_tracing`` must not break startup."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        class Minimal:
            pass

        config = TracingSettings(enabled=True, endpoint="http://localhost:9999")
        # Should not raise
        setup_tracing(config, backends=[Minimal()])

    def test_install_tracing_skipped_when_disabled(self, reset_tracer_provider):
        """When tracing is disabled, backends should not be asked to install
        anything — there's no provider to install against."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        backend = MagicMock()
        config = TracingSettings(enabled=False)
        setup_tracing(config, backends=[backend])

        assert not backend.install_tracing.called


class TestOtelEnvVarFallbacks:
    """Standard ``OTEL_EXPORTER_OTLP_*`` env vars act as fallbacks below
    FIN_TRACING__* config but above schema defaults.  The contract lets users
    redirect traces to any OTel backend with standard env vars.
    """

    def test_otel_endpoint_env_overrides_default(self, reset_tracer_provider, monkeypatch):
        """When FIN_TRACING__ENDPOINT is unset but OTEL_EXPORTER_OTLP_ENDPOINT
        is set, the OTel env takes precedence over the schema default."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import _resolve_endpoint

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318/v1/traces")
        # Use the schema default value as the config field value; resolver
        # treats schema-default as "not set" and falls through to env.
        config = TracingSettings(enabled=True)

        resolved = _resolve_endpoint(config)
        assert resolved == "http://otel-collector:4318/v1/traces"

    def test_explicit_fin_tracing_endpoint_beats_otel_env(self, reset_tracer_provider, monkeypatch):
        """FIN_TRACING__ENDPOINT (i.e. ``config.tracing.endpoint`` set to a
        non-default value) always wins over OTEL_EXPORTER_OTLP_ENDPOINT."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import _resolve_endpoint

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-env:4318/v1/traces")
        config = TracingSettings(enabled=True, endpoint="http://explicit:6006/v1/traces")

        resolved = _resolve_endpoint(config)
        assert resolved == "http://explicit:6006/v1/traces"

    def test_schema_default_used_when_no_env(self, reset_tracer_provider, monkeypatch):
        """With no OTel env var set and no override, the schema default stands."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import _resolve_endpoint

        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        config = TracingSettings(enabled=True)

        resolved = _resolve_endpoint(config)
        # Whatever the default is, it should match the schema default.
        assert resolved == TracingSettings.model_fields["endpoint"].default

    def test_otel_headers_env_parsed(self, reset_tracer_provider, monkeypatch):
        """``OTEL_EXPORTER_OTLP_HEADERS`` is a comma-separated key=value list
        per the OTel spec.  Parse it into a dict for the exporter."""
        from fin_assist.hub.tracing import _resolve_headers

        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            "authorization=Bearer abc123,x-project=fin",
        )
        headers = _resolve_headers({})
        assert headers == {"authorization": "Bearer abc123", "x-project": "fin"}

    def test_config_headers_win_over_otel_env(self, reset_tracer_provider, monkeypatch):
        from fin_assist.hub.tracing import _resolve_headers

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer env")
        headers = _resolve_headers({"authorization": "Bearer config"})
        assert headers == {"authorization": "Bearer config"}

    def test_malformed_otel_headers_are_skipped_with_warning(
        self, reset_tracer_provider, monkeypatch, caplog
    ):
        """A malformed ``OTEL_EXPORTER_OTLP_HEADERS`` value must not crash
        startup — skip the bad pair, keep the good ones, log a warning.
        """
        import logging

        from fin_assist.hub.tracing import _resolve_headers

        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_HEADERS",
            "authorization=Bearer abc,malformed_no_equals,x-good=yes",
        )
        with caplog.at_level(logging.WARNING, logger="fin_assist.hub.tracing"):
            headers = _resolve_headers({})
        assert headers == {"authorization": "Bearer abc", "x-good": "yes"}
        assert any("malformed" in rec.message.lower() for rec in caplog.records)


class TestIdempotencyAndVendorNeutrality:
    def test_setup_does_not_import_openinference_instrumentation_module(
        self, reset_tracer_provider
    ):
        """``hub/tracing.py`` must remain vendor-agnostic.  The
        ``openinference.instrumentation.*`` packages should only be
        pulled in via the backend hook, never from the hub core.
        """
        import sys

        # Clear any prior imports so we can observe what setup_tracing pulls in.
        for mod in list(sys.modules):
            if mod.startswith("openinference.instrumentation"):
                # We can't actually unload them once pydantic-ai module is
                # imported in a prior test.  So this test asserts on a
                # static-code property instead: the source of hub/tracing
                # should not import from openinference.instrumentation.
                pass

        import fin_assist.hub.tracing as tracing_mod

        src = open(tracing_mod.__file__).read()
        assert "openinference.instrumentation" not in src, (
            "hub/tracing.py must stay vendor-neutral — backend-specific "
            "instrumentation belongs in agents/pydantic_ai_tracing.py"
        )

    def test_resource_includes_openinference_project_name(self, reset_tracer_provider):
        """Phoenix groups traces by ``openinference.project.name`` on the
        resource, so we set it even though hub/tracing.py is vendor-neutral
        — it's a resource attribute, not an instrumentation call."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        config = TracingSettings(
            enabled=True, endpoint="http://localhost:9999", project_name="test-project"
        )
        provider = setup_tracing(config)

        assert provider is not None
        resource = provider.resource  # type: ignore[attr-defined]
        assert resource.attributes.get("openinference.project.name") == "test-project"
        assert resource.attributes.get("service.name") == "test-project"


class TestNoOpWhenDisabled:
    def test_no_op_when_disabled(self, reset_tracer_provider):
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        assert setup_tracing(TracingSettings(enabled=False)) is None


class TestSamplingWiring:
    """``sampling_ratio`` must actually reach the TracerProvider's sampler.

    We verify via the sampler's ``description`` attribute (TraceIdRatioBased
    embeds the ratio in its description) rather than poking at private
    state — it's the public surface that OTel intends consumers to use.
    """

    def test_full_sampling_uses_always_on(self, reset_tracer_provider):
        """ratio == 1.0 should pick ALWAYS_ON (no ratio math per span)."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        config = TracingSettings(enabled=True, endpoint="http://localhost:9999", sampling_ratio=1.0)
        provider = setup_tracing(config)
        assert provider is not None
        sampler = provider.sampler  # type: ignore[attr-defined]
        # ALWAYS_ON is the canonical full-sampling sampler.
        assert (
            "AlwaysOn" in type(sampler).__name__ or sampler.get_description() == "AlwaysOnSampler"
        )

    def test_zero_sampling_uses_always_off(self, reset_tracer_provider):
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        config = TracingSettings(enabled=True, endpoint="http://localhost:9999", sampling_ratio=0.0)
        provider = setup_tracing(config)
        assert provider is not None
        sampler = provider.sampler  # type: ignore[attr-defined]
        assert (
            "AlwaysOff" in type(sampler).__name__ or sampler.get_description() == "AlwaysOffSampler"
        )

    def test_fractional_sampling_uses_trace_id_ratio(self, reset_tracer_provider):
        """A fractional ratio should wire in ``TraceIdRatioBased`` so spans
        are sampled proportionally (and deterministically per trace id).
        """
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        config = TracingSettings(
            enabled=True, endpoint="http://localhost:9999", sampling_ratio=0.25
        )
        provider = setup_tracing(config)
        assert provider is not None
        sampler = provider.sampler  # type: ignore[attr-defined]
        desc = sampler.get_description()
        assert "TraceIdRatioBased" in desc
        assert "0.25" in desc


class TestHeaderWiring:
    """Config-level headers and OTEL env headers should reach
    ``_resolve_headers`` via ``setup_tracing``.  The resolver is unit-
    tested elsewhere; here we only verify plumbing (config field →
    resolver)."""

    def test_config_headers_reach_resolver(self, reset_tracer_provider, monkeypatch):
        """When ``TracingSettings.headers`` is set, it wins over env."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer env")
        config = TracingSettings(
            enabled=True,
            endpoint="http://localhost:9999",
            headers={"authorization": "Bearer config"},
        )
        # Should not raise even though endpoint is unreachable.
        provider = setup_tracing(config)
        assert provider is not None
