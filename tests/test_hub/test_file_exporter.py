"""Tests for ``FileSpanExporter`` — the JSONL file sink for OTel spans.

Why this exists (issue #105)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OTLP collectors (Phoenix, Tempo, Jaeger) are great for browsing traces
but terrible for the "grep/jq/cat inside an agent loop" workflow we use
to iterate on telemetry quality.  The JSONL exporter writes every span
as a line of OTel-produced JSON to a local file, so coding agents (and
humans) can inspect traces with standard text tools, and so traces
survive when the remote collector is offline or flaky.

Contract
~~~~~~~~
1. One span per line — readable with ``jq -c``, ``rg``, etc.
2. Each line is independently valid JSON (OTel's ``ReadableSpan.to_json``
   output with newlines stripped).
3. Parent directory is auto-created so ``FIN_TRACING__FILE_PATH=./a/b/c.jsonl``
   works on first run without user setup.
4. Append semantics — multiple hub runs accumulate into the same file.
   Rotation is deferred (issue #106 / a future follow-up); a simple
   ``rm`` between runs is the current escape hatch.
5. ``shutdown()`` / ``force_flush()`` actually flush buffered bytes to
   disk so a crashing hub leaves the latest spans readable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestFileSpanExporterBasics:
    def test_export_writes_one_line_per_span(self, tmp_path: Path) -> None:
        """Every exported span produces exactly one newline-terminated line.

        Uses real ``ReadableSpan`` objects via an in-process TracerProvider
        rather than mocks so we're testing against OTel's actual ``to_json``
        output shape (which is what downstream grep/jq consumers will see).
        """
        from fin_assist.hub.file_exporter import FileSpanExporter

        path = tmp_path / "traces.jsonl"
        exporter = FileSpanExporter(str(path))

        spans = _make_spans(count=3)
        result = exporter.export(spans)

        from opentelemetry.sdk.trace.export import SpanExportResult

        assert result == SpanExportResult.SUCCESS
        exporter.shutdown()

        lines = path.read_text().splitlines()
        assert len(lines) == 3
        # Each line must parse as JSON independently.
        for line in lines:
            json.loads(line)

    def test_export_appends_across_calls(self, tmp_path: Path) -> None:
        """Two ``export()`` calls on the same exporter accumulate lines.

        Protects against the 'each export truncates the file' regression —
        a subtle bug when someone reaches for ``open(path, "w")`` instead
        of append mode.
        """
        from fin_assist.hub.file_exporter import FileSpanExporter

        path = tmp_path / "traces.jsonl"
        exporter = FileSpanExporter(str(path))

        exporter.export(_make_spans(count=2))
        exporter.export(_make_spans(count=3))
        exporter.shutdown()

        assert len(path.read_text().splitlines()) == 5

    def test_parent_directory_is_created(self, tmp_path: Path) -> None:
        """The exporter creates missing parent dirs so users can point
        ``FIN_TRACING__FILE_PATH`` at a nested path without pre-creating it.
        """
        from fin_assist.hub.file_exporter import FileSpanExporter

        path = tmp_path / "nested" / "deeper" / "traces.jsonl"
        exporter = FileSpanExporter(str(path))
        exporter.export(_make_spans(count=1))
        exporter.shutdown()

        assert path.exists()
        assert len(path.read_text().splitlines()) == 1

    def test_force_flush_returns_true(self, tmp_path: Path) -> None:
        """``force_flush`` is called by the BatchSpanProcessor on shutdown
        and during test teardown; it must return True on success so the
        processor doesn't log spurious flush-failed warnings."""
        from fin_assist.hub.file_exporter import FileSpanExporter

        exporter = FileSpanExporter(str(tmp_path / "traces.jsonl"))
        try:
            assert exporter.force_flush() is True
        finally:
            exporter.shutdown()

    def test_shutdown_is_idempotent(self, tmp_path: Path) -> None:
        """Double-shutdown must not raise — BatchSpanProcessor and
        TracerProvider both call ``shutdown`` in some teardown paths.
        """
        from fin_assist.hub.file_exporter import FileSpanExporter

        exporter = FileSpanExporter(str(tmp_path / "traces.jsonl"))
        exporter.shutdown()
        exporter.shutdown()  # Must not raise.

    def test_lines_contain_expected_span_fields(self, tmp_path: Path) -> None:
        """Sanity check on the JSON shape: every line should carry at least
        ``name``, ``context``/``trace_id``, and ``start_time`` — the fields
        an operator or replay tool will actually key on.  The exact schema
        is OTel's, we're just guarding that we didn't accidentally
        double-encode or wrap the payload.
        """
        from fin_assist.hub.file_exporter import FileSpanExporter

        path = tmp_path / "traces.jsonl"
        exporter = FileSpanExporter(str(path))
        exporter.export(_make_spans(count=1, name="my-operation"))
        exporter.shutdown()

        line = path.read_text().splitlines()[0]
        obj = json.loads(line)
        assert obj["name"] == "my-operation"
        # OTel's to_json nests identifiers under "context" in Python SDK.
        assert "context" in obj
        assert "trace_id" in obj["context"]


def _make_spans(count: int, name: str = "test-span"):
    """Build ``count`` real ``ReadableSpan`` objects via an isolated
    TracerProvider.  We go through the real API rather than mocking so
    ``span.to_json()`` produces the exact shape downstream tools see.

    The provider is local to this helper — it never touches the global
    one — so these tests don't interact with ``setup_tracing`` state.
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    tracer = provider.get_tracer("test")

    spans = []
    for i in range(count):
        with tracer.start_as_current_span(f"{name}" if count == 1 else f"{name}-{i}") as span:
            span.set_attribute("index", i)
            spans.append(span)
    # At this point the spans are ended; they satisfy the ReadableSpan
    # interface the exporter uses.
    return spans


@pytest.fixture(autouse=True)
def _isolate_global_tracer_provider():
    """Prevent local ``TracerProvider`` objects from leaking into the
    global state used by ``test_tracing_setup.py``.  OTel's global
    provider is module-level; resetting the proxy here keeps test
    ordering from mattering."""
    import opentelemetry.trace as _trace_mod
    from opentelemetry.trace import ProxyTracerProvider

    yield
    _trace_mod._TRACER_PROVIDER = ProxyTracerProvider()
