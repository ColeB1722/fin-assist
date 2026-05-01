"""Tests for ``fin_assist.cli.tracing`` — the client-side tracer.

Issue #104: one ``fin`` invocation must produce one root trace whose
children include every HTTP call the CLI makes (``GET /health``,
``GET /agents``, ``POST /agents/.../send-message``) and — via W3C
traceparent propagation — the hub-side ``fin_assist.task`` span.

These tests pin the contract:

1. ``setup_cli_tracing`` is a no-op when tracing is disabled.
2. When enabled, it installs a TracerProvider that writes to
   ``paths.TRACES_PATH`` and enables ``HTTPXClientInstrumentor``
   so outgoing httpx requests carry a ``traceparent`` header.
3. ``cli_root_span(command, agent, ...)`` opens the root
   ``cli.<command>`` span with an ``fin_assist.cli.invocation_id``
   baggage entry that subsequent HTTP calls will propagate to the hub.
4. ``approval_wait_span()`` wraps the y/N prompt in a child so the
   hub's trace-duration dashboards can subtract human think-time.
5. The invocation_id attribute shape is stable (``fin_assist.cli.*``)
   so both OTLP queries and tests key on the same names.

The tests intentionally do NOT assert on traceparent header bytes —
that's the ``HTTPXClientInstrumentor``'s contract, not ours.  We only
assert that the instrumentor has been installed.
"""

from __future__ import annotations

import pytest


def _reset_global_provider() -> None:
    """Tear down the global OTel provider completely.

    Subtleties:

    * Setting ``_TRACER_PROVIDER`` to a fresh ``ProxyTracerProvider()``
      (the pattern used elsewhere in the suite) would work for tests
      that never call ``get_tracer_provider().get_tracer(...)``.
      Here we do — inside ``cli_root_span`` — and
      ``ProxyTracerProvider.get_tracer`` checks
      ``if _TRACER_PROVIDER:`` and delegates to it, so a proxy-as-
      global would recurse forever.  ``None`` is the actual
      uninitialized state.
    * ``_TRACER_PROVIDER_SET_ONCE`` is OTel's ``Once`` guard against
      repeat installs.  After one real ``set_tracer_provider``, any
      subsequent call is refused with a warning.  Flipping ``_done``
      back to ``False`` lets the next test install a fresh provider.
    """
    import opentelemetry.trace as _trace_mod

    from fin_assist.cli.tracing import _reset_for_tests

    provider = _trace_mod.get_tracer_provider()
    for method in ("force_flush", "shutdown"):
        fn = getattr(provider, method, None)
        if fn:
            try:
                fn(1) if method == "force_flush" else fn()
            except Exception:  # noqa: BLE001
                pass
    _trace_mod._TRACER_PROVIDER = None
    _trace_mod._TRACER_PROVIDER_SET_ONCE._done = False
    _reset_for_tests()


@pytest.fixture
def reset_tracer_provider():
    _reset_global_provider()
    yield
    _reset_global_provider()


class TestSetupCLITracing:
    def test_no_op_when_disabled(self, reset_tracer_provider):
        """Disabled config must not construct a provider, touch env
        vars, or install any instrumentor."""
        from fin_assist.cli.tracing import setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        assert setup_cli_tracing(TracingSettings(enabled=False)) is None

    def test_writes_spans_to_jsonl_file(self, reset_tracer_provider, tmp_path):
        """When tracing is enabled, spans emitted via a returned tracer
        must land in the JSONL file."""
        import json as _json
        from unittest.mock import patch

        from fin_assist.cli.tracing import setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "cli.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            provider = setup_cli_tracing(config)
        assert provider is not None

        tracer = provider.get_tracer("test")  # type: ignore[attr-defined]
        with tracer.start_as_current_span("cli-test-span"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        assert path.exists()
        lines = path.read_text().splitlines()
        assert any(_json.loads(line)["name"] == "cli-test-span" for line in lines)

    def test_httpx_instrumented(self, reset_tracer_provider, tmp_path):
        """``setup_cli_tracing`` must call ``HTTPXClientInstrumentor``
        so outgoing hub HTTP calls carry W3C ``traceparent``."""
        from unittest.mock import patch

        from fin_assist.cli.tracing import setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "x.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            setup_cli_tracing(config)

        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        assert HTTPXClientInstrumentor().is_instrumented_by_opentelemetry


class TestCLIRootSpan:
    """``cli_root_span`` opens the single per-invocation root span and
    seeds the baggage that ties hub spans back to this CLI run.
    """

    def test_emits_cli_command_span(self, reset_tracer_provider, tmp_path):
        """The span name must be ``cli.<command>``."""
        import json as _json
        from unittest.mock import patch

        from fin_assist.cli.tracing import cli_root_span, setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "c.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            provider = setup_cli_tracing(config)
        assert provider is not None

        with cli_root_span("do", agent="test"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        names = [_json.loads(line)["name"] for line in path.read_text().splitlines()]
        assert "cli.do" in names

    def test_span_has_invocation_id_attribute(self, reset_tracer_provider, tmp_path):
        """The span must carry ``fin_assist.cli.invocation_id``.  This
        is the join key between the CLI trace and the hub task span."""
        import json as _json
        from unittest.mock import patch

        from fin_assist.cli.tracing import cli_root_span, setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "c.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            provider = setup_cli_tracing(config)
        assert provider is not None

        with cli_root_span("do", agent="test"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        span = next(
            _json.loads(line)
            for line in path.read_text().splitlines()
            if _json.loads(line)["name"] == "cli.do"
        )
        attrs = span["attributes"]
        assert "fin_assist.cli.invocation_id" in attrs
        assert attrs["fin_assist.cli.command"] == "do"
        assert attrs["fin_assist.cli.agent"] == "test"

    def test_invocation_id_is_unique_per_call(self, reset_tracer_provider, tmp_path):
        """Two CLI invocations must produce distinct invocation_ids."""
        import json as _json
        from unittest.mock import patch

        from fin_assist.cli.tracing import cli_root_span, setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "c.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            provider = setup_cli_tracing(config)
        assert provider is not None

        with cli_root_span("do", agent="a"):
            pass
        with cli_root_span("do", agent="b"):
            pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        spans = [_json.loads(line) for line in path.read_text().splitlines()]
        ids = {
            s["attributes"]["fin_assist.cli.invocation_id"] for s in spans if s["name"] == "cli.do"
        }
        assert len(ids) == 2

    def test_invocation_id_set_in_baggage(self, reset_tracer_provider, tmp_path):
        """Inside the ``cli_root_span`` context, the baggage must carry
        ``fin_assist.cli.invocation_id`` so ``HTTPXClientInstrumentor``
        propagates it via ``baggage`` header on outgoing requests."""
        from unittest.mock import patch

        from opentelemetry import baggage

        from fin_assist.cli.tracing import cli_root_span, setup_cli_tracing
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "b.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            setup_cli_tracing(config)

        with cli_root_span("do", agent="test"):
            value = baggage.get_baggage("fin_assist.cli.invocation_id")
            assert value is not None
            assert isinstance(value, str)
            assert len(value) > 0

    def test_disabled_tracing_yields_no_op(self, reset_tracer_provider):
        """With tracing disabled, ``cli_root_span`` must still be a
        usable context manager (no crash) but produces no real span."""
        from fin_assist.cli.tracing import cli_root_span

        with cli_root_span("do", agent="test"):
            pass


class TestApprovalWaitSpan:
    """``approval_wait_span`` wraps the y/N prompt.  Dashboards subtract
    its duration from the CLI root-span duration to get "actual agent
    time" vs "human think time".
    """

    def test_emits_cli_approval_wait_span(self, reset_tracer_provider, tmp_path):
        import json as _json
        from unittest.mock import patch

        from fin_assist.cli.tracing import (
            approval_wait_span,
            cli_root_span,
            setup_cli_tracing,
        )
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "a.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            provider = setup_cli_tracing(config)
        assert provider is not None

        with cli_root_span("do", agent="test"):
            with approval_wait_span():
                pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        names = [_json.loads(line)["name"] for line in path.read_text().splitlines()]
        assert "cli.approval_wait" in names

    def test_approval_wait_is_child_of_root(self, reset_tracer_provider, tmp_path):
        """The wait span must be parented on the CLI root so backends
        render them nested, not as siblings."""
        import json as _json
        from unittest.mock import patch

        from fin_assist.cli.tracing import (
            approval_wait_span,
            cli_root_span,
            setup_cli_tracing,
        )
        from fin_assist.config.schema import TracingSettings

        path = tmp_path / "a.jsonl"
        config = TracingSettings(enabled=True, provider="none")
        with patch("fin_assist.paths.TRACES_PATH", path):
            provider = setup_cli_tracing(config)
        assert provider is not None

        with cli_root_span("do", agent="test"):
            with approval_wait_span():
                pass
        provider.force_flush(5000)  # type: ignore[attr-defined]

        spans = {
            _json.loads(line)["name"]: _json.loads(line) for line in path.read_text().splitlines()
        }
        root = spans["cli.do"]
        wait = spans["cli.approval_wait"]
        root_span_id = root["context"]["span_id"]
        assert wait["parent_id"] == root_span_id
