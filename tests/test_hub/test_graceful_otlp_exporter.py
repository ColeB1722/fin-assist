"""Tests for ``_GracefulOTLPExporter`` in ``fin_assist.tracing_shared``.

The graceful wrapper must:
1. Return FAILURE and log once on first exception from the real exporter.
2. Return FAILURE silently on subsequent failures (no repeated logs).
3. Reset the ``_failed`` flag on successful export so a Phoenix restart
   triggers a fresh one-time log if it goes down again.
4. Delegate ``shutdown()`` and ``force_flush()`` to the real exporter.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call

import pytest

from opentelemetry.sdk.trace.export import SpanExportResult

from fin_assist.tracing_shared import _GracefulOTLPExporter


def _make_spans(n: int = 1) -> list:
    return [MagicMock() for _ in range(n)]


class TestGracefulOTLPExporterFirstFailure:
    def test_returns_failure_on_exception(self):
        delegate = MagicMock()
        delegate.export.side_effect = ConnectionError("refused")
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        result = wrapper.export(_make_spans())
        assert result == SpanExportResult.FAILURE

    def test_logs_once_on_first_failure(self, caplog):
        delegate = MagicMock()
        delegate.export.side_effect = ConnectionError("refused")
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        with caplog.at_level(logging.INFO, logger="fin_assist.tracing_shared"):
            wrapper.export(_make_spans())

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "OTLP export to http://localhost:6006 failed" in record.message
        assert "/tmp/t.jsonl" in record.message

    def test_catches_any_exception_not_just_connection_error(self):
        delegate = MagicMock()
        delegate.export.side_effect = RuntimeError("unexpected")
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        result = wrapper.export(_make_spans())
        assert result == SpanExportResult.FAILURE


class TestGracefulOTLPExporterSubsequentFailures:
    def test_silent_on_repeated_failures(self, caplog):
        delegate = MagicMock()
        delegate.export.side_effect = ConnectionError("refused")
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        with caplog.at_level(logging.INFO, logger="fin_assist.tracing_shared"):
            wrapper.export(_make_spans())
            caplog.clear()
            wrapper.export(_make_spans())
            wrapper.export(_make_spans())

        assert len(caplog.records) == 0

    def test_returns_failure_on_every_failure(self):
        delegate = MagicMock()
        delegate.export.side_effect = ConnectionError("refused")
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        assert wrapper.export(_make_spans()) == SpanExportResult.FAILURE
        assert wrapper.export(_make_spans()) == SpanExportResult.FAILURE
        assert wrapper.export(_make_spans()) == SpanExportResult.FAILURE


class TestGracefulOTLPExporterRecovery:
    def test_resets_failed_flag_on_success(self):
        delegate = MagicMock()
        delegate.export.side_effect = [
            ConnectionError("refused"),
            SpanExportResult.SUCCESS,
        ]
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        wrapper.export(_make_spans())
        assert wrapper._failed is True

        wrapper.export(_make_spans())
        assert wrapper._failed is False

    def test_logs_again_after_recovery_then_failure(self, caplog):
        delegate = MagicMock()
        delegate.export.side_effect = [
            ConnectionError("refused"),
            SpanExportResult.SUCCESS,
            ConnectionError("refused again"),
        ]
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        with caplog.at_level(logging.INFO, logger="fin_assist.tracing_shared"):
            wrapper.export(_make_spans())
            wrapper.export(_make_spans())
            caplog.clear()
            wrapper.export(_make_spans())

        assert len(caplog.records) == 1
        assert "refused again" not in caplog.records[0].message
        assert "OTLP export to http://localhost:6006 failed" in caplog.records[0].message

    def test_passes_through_success_result(self):
        delegate = MagicMock()
        delegate.export.return_value = SpanExportResult.SUCCESS
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        result = wrapper.export(_make_spans())
        assert result == SpanExportResult.SUCCESS
        assert wrapper._failed is False


class TestGracefulOTLPExporterDelegation:
    def test_shutdown_delegates(self):
        delegate = MagicMock()
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        wrapper.shutdown()
        delegate.shutdown.assert_called_once()

    def test_force_flush_delegates(self):
        delegate = MagicMock()
        delegate.force_flush.return_value = True
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        result = wrapper.force_flush(5000)
        delegate.force_flush.assert_called_once_with(5000)
        assert result is True

    def test_force_flush_default_timeout(self):
        delegate = MagicMock()
        delegate.force_flush.return_value = True
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        wrapper.force_flush()
        delegate.force_flush.assert_called_once_with(30000)

    def test_export_passes_spans_to_delegate(self):
        delegate = MagicMock()
        delegate.export.return_value = SpanExportResult.SUCCESS
        wrapper = _GracefulOTLPExporter(
            delegate, endpoint="http://localhost:6006", file_sink_path="/tmp/t.jsonl"
        )

        spans = _make_spans(3)
        wrapper.export(spans)
        delegate.export.assert_called_once_with(spans)
