from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.general.default_provider = "anthropic"
    config.general.default_model = "claude-sonnet-4-6"
    config.providers = {}
    return config


@pytest.fixture
def mock_credentials():
    creds = MagicMock()
    creds.get_api_key.return_value = "test-key"
    return creds


@pytest.fixture
def expected_context_types():
    from fin_assist.context.base import ContextType

    return frozenset(ContextType.__args__)


@pytest.fixture
def tracing_setup():
    """Set up an in-memory OTel TracerProvider for span assertion tests.

    Returns a dict with:
    - ``provider``: the TracerProvider
    - ``exporter``: the InMemorySpanExporter
    - ``get_spans(name=None)``: helper that returns finished spans, optionally filtered by name
    - ``clear()``: helper that clears collected spans

    Automatically restores the previous TracerProvider on teardown.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Force-set the provider even if OTel warns about overriding
    import opentelemetry.trace as _trace_mod

    _trace_mod._TRACER_PROVIDER = provider

    def get_spans(name: str | None = None):
        spans = exporter.get_finished_spans()
        if name is None:
            return spans
        return [s for s in spans if s.name == name]

    def clear():
        exporter.clear()

    yield {
        "provider": provider,
        "exporter": exporter,
        "get_spans": get_spans,
        "clear": clear,
    }

    # Reset to default on teardown
    from opentelemetry.trace import ProxyTracerProvider

    _trace_mod._TRACER_PROVIDER = ProxyTracerProvider()
