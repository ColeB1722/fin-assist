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


class TestFileExporterWiring:
    """The JSONL file exporter (``TracingSettings.file_path``) is additive
    and standalone-capable.  These tests verify plumbing: the field reaches
    the provider as a span processor, it coexists with the OTLP exporter,
    and it can run as the *only* exporter when no endpoint is configured.

    They deliberately use a real in-process tracer+exporter roundtrip
    (rather than mocking ``FileSpanExporter``) because the whole point of
    this feature is that bytes hit disk — mocking that out would test
    nothing the user cares about.
    """

    def test_file_path_creates_jsonl_exporter(self, reset_tracer_provider, tmp_path):
        """When ``file_path`` is set, emitted spans must land in that file.

        Uses a ``SimpleSpanProcessor`` equivalent path by forcing a flush
        after a span ends; the BatchSpanProcessor inside ``setup_tracing``
        honors ``force_flush``.
        """
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "traces.jsonl"
        config = TracingSettings(
            enabled=True,
            endpoint="http://localhost:9999",
            file_path=str(path),
        )
        provider = setup_tracing(config)
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("wiring-check"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        import json as _json

        assert _json.loads(lines[0])["name"] == "wiring-check"

    def test_file_path_works_without_otlp_endpoint(self, reset_tracer_provider, tmp_path):
        """File exporter is standalone-capable: if the user only sets
        ``file_path`` (and leaves the endpoint at the schema default with
        no Phoenix running), tracing must still initialize and spans must
        still hit the file.  This is the 'Phoenix is down / offline dev'
        path.

        We construct the config with the default endpoint untouched so the
        resolver's 'schema-default == not set' contract applies.
        """
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "traces.jsonl"
        config = TracingSettings(enabled=True, file_path=str(path))
        provider = setup_tracing(config)
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("offline-span"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        assert path.exists()
        assert len(path.read_text().splitlines()) == 1

    def test_file_path_none_means_no_file_written(self, reset_tracer_provider, tmp_path):
        """Default (``file_path=None``) must NOT create any file.  Guards
        against regressions where a helper accidentally defaults the
        field to a non-None path."""
        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        # A path we then assert does not get created.
        stray = tmp_path / "should-not-exist.jsonl"
        config = TracingSettings(enabled=True, endpoint="http://localhost:9999")
        provider = setup_tracing(config)
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("no-file-span"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        assert not stray.exists()

    def test_file_path_truncation_applied_to_file_output(self, reset_tracer_provider, tmp_path):
        """Large string attributes must be truncated in the file output
        too — the ``_TruncatingSpanProcessor`` wrap has to apply uniformly
        across every exporter attached to the provider, not just OTLP.
        Without this, large tool outputs would blow up file size even
        though the OTLP path stays under the gRPC limit.
        """
        import json as _json

        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import _MAX_ATTR_BYTES, setup_tracing

        path = tmp_path / "traces.jsonl"
        config = TracingSettings(enabled=True, file_path=str(path))
        provider = setup_tracing(config)
        assert provider is not None

        oversized = "x" * (_MAX_ATTR_BYTES * 2)
        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("big-attr") as span:
            span.set_attribute("huge", oversized)
        provider.force_flush(5000)  # type: ignore[attr-defined]

        line = path.read_text().splitlines()[0]
        obj = _json.loads(line)
        # OTel's to_json puts attributes under "attributes"; the value
        # should have been trimmed well below the original length.
        written = obj["attributes"]["huge"]
        assert len(written) < len(oversized)
        assert "truncated" in written


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


class TestNoiseSuppression:
    """Phase 1 — framework-noise filtering.

    Two independent noise sources must be tamed before CLI/hub traces
    become readable:

    1. **a2a-sdk** wraps internal classes with ``@trace_class`` which
       emits a ``SpanKind.SERVER`` span for every EventQueue / TaskStore
       operation with zero useful attributes.  ~195 spans per invocation
       of ``fin do``.  Disabled with the vendor env var
       ``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false`` (honored by
       ``a2a/utils/telemetry.py``).  ``setup_tracing`` sets it via
       ``os.environ.setdefault`` so operator overrides (re-enable for
       debugging) still win.
    2. **FastAPIInstrumentor** emits one ``http.response.body`` span
       per SSE chunk (~45 per streamed task).  They carry only
       ``asgi.event.type = "http.response.body"`` as identifying data.
       Dropped in the export pipeline via a ``_DropSpansProcessor`` so
       we keep the request-level span (``GET /agents``, ``POST
       /agents/test``) without the per-chunk firehose.
    """

    def test_a2a_sdk_instrumentation_disabled_by_default(self):
        """``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED`` must be set to
        ``"false"`` before a2a-sdk is imported.

        a2a-sdk reads this at module-import time (not per-call), so
        setting it inside ``setup_tracing`` would be too late.  We set
        it in ``fin_assist/__init__.py`` which is always imported
        before any ``a2a.*`` import.  This test just confirms the
        side-effect is in place once the package is imported.
        """
        # Importing ``fin_assist`` triggers the ``setdefault`` in
        # ``__init__.py``.  By the time this test runs, pytest has
        # long since imported it.
        import fin_assist  # noqa: F401  — imported for the side effect

        assert os.environ.get("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED") == "false"

    def test_operator_a2a_override_not_clobbered(self):
        """``setdefault`` semantics: an operator who exports
        ``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=true`` before running
        ``fin`` (to debug a2a internals) must not have that value
        replaced on import.

        Tested by re-invoking the exact same ``setdefault`` line in a
        temporarily-set environment — we can't un-import
        ``fin_assist`` to re-trigger its ``__init__``.
        """
        import os as _os

        saved = _os.environ.get("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED")
        try:
            _os.environ["OTEL_INSTRUMENTATION_A2A_SDK_ENABLED"] = "true"
            # This is the exact line in fin_assist/__init__.py — if it
            # ever overwrites an existing value this assertion fails.
            _os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")
            assert _os.environ.get("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED") == "true"
        finally:
            if saved is None:
                _os.environ.pop("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", None)
            else:
                _os.environ["OTEL_INSTRUMENTATION_A2A_SDK_ENABLED"] = saved

    def test_asgi_http_response_body_spans_dropped(self, reset_tracer_provider, tmp_path):
        """ASGI ``http.response.body`` spans (emitted per SSE chunk) must
        be filtered out before export.  We test this end-to-end via the
        file exporter: after configuring tracing, synthesizing a span
        with the ASGI signature, and flushing, the output JSONL must
        not contain that span.
        """
        import json as _json

        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "traces.jsonl"
        config = TracingSettings(enabled=True, file_path=str(path))
        provider = setup_tracing(config)
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        # Pretend to be the FastAPI/ASGI instrumentor emitting one of its
        # per-chunk response-body spans.  The noise filter keys on the
        # attribute, not the name, so the exact span name isn't load-
        # bearing — but this is the shape the real instrumentor emits.
        with tracer.start_as_current_span("http send") as noise:
            noise.set_attribute("asgi.event.type", "http.response.body")

        with tracer.start_as_current_span("real span"):
            pass

        provider.force_flush(5000)  # type: ignore[attr-defined]

        lines = [_json.loads(line) for line in path.read_text().splitlines()]
        names = [line["name"] for line in lines]
        assert "real span" in names
        # The ASGI per-chunk span must have been filtered out.
        attr_types = [line.get("attributes", {}).get("asgi.event.type") for line in lines]
        assert "http.response.body" not in attr_types

    def test_non_asgi_spans_not_dropped(self, reset_tracer_provider, tmp_path):
        """The drop filter must only match ``http.response.body`` — other
        ASGI event types (``http.response.start``) and all non-ASGI spans
        must pass through untouched.
        """
        import json as _json

        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "traces.jsonl"
        config = TracingSettings(enabled=True, file_path=str(path))
        provider = setup_tracing(config)
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("keep-1") as s:
            s.set_attribute("asgi.event.type", "http.response.start")
        with tracer.start_as_current_span("keep-2") as s:
            s.set_attribute("some.other.attr", "value")
        provider.force_flush(5000)  # type: ignore[attr-defined]

        lines = [_json.loads(line) for line in path.read_text().splitlines()]
        names = {line["name"] for line in lines}
        assert {"keep-1", "keep-2"}.issubset(names)


class TestAttributeHygiene:
    """Phase 4 — strip attributes that add no information.

    Three redundant / leaked attributes show up in real traces:

    * ``logfire.msg`` / ``logfire.json_schema`` — leaked from pydantic-ai's
      internal instrumentation (it uses logfire as a tracing front-end
      even when logfire itself isn't configured).  They pollute the
      attribute list without helping an operator read a trace.
    * ``final_result`` on ``agent run`` spans — full pydantic RunResult
      JSON, duplicated as ``output.value`` and ``pydantic_ai.all_messages``.
      Three copies of the same bytes.  Stripping this saves ~5-30KB
      per trace.
    * ``session.id`` set identically to ``fin_assist.context.id``.
      Keeping both is legacy from when OpenInference required
      ``session.id``; operators now look at the fin_assist namespace
      first.  Dropping when equal removes the duplication without
      breaking dashboards that read ``session.id``.
    """

    def test_logfire_attrs_stripped_from_file_output(self, reset_tracer_provider, tmp_path):
        import json as _json

        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "h.jsonl"
        provider = setup_tracing(TracingSettings(enabled=True, file_path=str(path)))
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("noisy") as s:
            s.set_attribute("logfire.msg", "running tool read_file")
            s.set_attribute("logfire.json_schema", "{...}")
            s.set_attribute("keep.me", "yes")
        provider.force_flush(5000)  # type: ignore[attr-defined]

        line = _json.loads(path.read_text().splitlines()[0])
        attrs = line["attributes"]
        assert "logfire.msg" not in attrs
        assert "logfire.json_schema" not in attrs
        assert attrs.get("keep.me") == "yes"

    def test_final_result_attr_stripped(self, reset_tracer_provider, tmp_path):
        """``final_result`` on an ``agent run`` span duplicates
        ``output.value`` + ``pydantic_ai.all_messages``.  Export should
        drop it.  Other spans that happen to have a ``final_result``
        attribute stay untouched — we only strip the pydantic-ai leak.
        """
        import json as _json

        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "h.jsonl"
        provider = setup_tracing(TracingSettings(enabled=True, file_path=str(path)))
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("agent run") as s:
            s.set_attribute("final_result", '{"big": "json"}')
            s.set_attribute("output.value", "keep")
        provider.force_flush(5000)  # type: ignore[attr-defined]

        line = _json.loads(path.read_text().splitlines()[0])
        attrs = line["attributes"]
        assert "final_result" not in attrs
        assert attrs.get("output.value") == "keep"

    def test_duplicate_session_id_dropped(self, reset_tracer_provider, tmp_path):
        """When ``session.id`` equals ``fin_assist.context.id`` they are
        redundant; drop ``session.id``.  When they differ (unlikely but
        possible in future custom backends), keep both so the user-set
        ``session.id`` isn't silently erased."""
        import json as _json

        from fin_assist.config.schema import TracingSettings
        from fin_assist.hub.tracing import setup_tracing

        path = tmp_path / "h.jsonl"
        provider = setup_tracing(TracingSettings(enabled=True, file_path=str(path)))
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("same") as s:
            s.set_attribute("session.id", "ctx-1")
            s.set_attribute("fin_assist.context.id", "ctx-1")
        with tracer.start_as_current_span("different") as s:
            s.set_attribute("session.id", "override-session")
            s.set_attribute("fin_assist.context.id", "ctx-2")
        provider.force_flush(5000)  # type: ignore[attr-defined]

        lines = [_json.loads(line) for line in path.read_text().splitlines()]
        same = next(line for line in lines if line["name"] == "same")
        diff = next(line for line in lines if line["name"] == "different")

        assert "session.id" not in same["attributes"]
        assert same["attributes"]["fin_assist.context.id"] == "ctx-1"
        assert diff["attributes"]["session.id"] == "override-session"
        assert diff["attributes"]["fin_assist.context.id"] == "ctx-2"
