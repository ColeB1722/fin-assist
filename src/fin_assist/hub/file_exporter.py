"""JSONL file sink for OpenTelemetry spans.

Issue #105 — complements the OTLP exporter by writing every span as a
line of JSON to a local file.  Motivation:

* **Agent-loop debugging.**  Coding agents (and humans) iterate on
  telemetry quality fastest when they can ``cat``, ``grep``, and ``jq``
  traces directly.  Phoenix's UI and MCP server are nice, but neither
  is as ergonomic as plain files.
* **Resilience.**  Phoenix at ``localhost:6006`` is often down or
  restarting during development; OTLP-only setups silently drop spans
  in that window.  A file sink keeps them.
* **Reproducible captures.**  ``.jsonl`` files can be committed to a
  bug report or replayed into a fresh Phoenix instance (future
  ``fin-assist trace replay`` subcommand).

Format
~~~~~~
One JSON object per line, produced by OTel's own
``ReadableSpan.to_json(indent=None)``.  That's the closest thing to a
standard JSON encoding of OTel spans — Phoenix, Tempo, and Jaeger can
all consume it via their OTLP/JSON ingestion endpoints.

Scope
~~~~~
Intentionally minimal.  No rotation, no compression, no buffering
beyond what the underlying file object does — the
``BatchSpanProcessor`` upstream already batches.  Rotation and replay
are tracked as follow-up work so this PR stays small enough to review.
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk.trace import ReadableSpan

logger = logging.getLogger(__name__)


class FileSpanExporter(SpanExporter):
    """SpanExporter that appends each span as a JSON line to ``path``.

    The file is opened in append mode at construction time and kept
    open for the exporter's lifetime to avoid per-export open/close
    overhead (the ``BatchSpanProcessor`` upstream calls ``export``
    with batches of up to ~512 spans).

    A ``Lock`` guards writes so concurrent exports (unlikely with a
    single BatchSpanProcessor, but possible if the exporter is reused
    across processors) don't interleave bytes within a line.
    """

    def __init__(self, path: str) -> None:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        # Append mode: multiple hub runs accumulate into the same file.
        # Line-buffered so a crashed process still leaves completed
        # lines readable without explicit fsync.
        self._file = resolved.open("a", encoding="utf-8", buffering=1)
        self._lock = Lock()
        self._closed = False
        self._path = resolved

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._closed:
            return SpanExportResult.FAILURE
        try:
            with self._lock:
                for span in spans:
                    # ``indent=None`` produces a single-line JSON object.
                    # Strip stray newlines defensively in case any
                    # attribute value (e.g. a tool output) contains raw
                    # ``\n`` that survived JSON escaping — it shouldn't,
                    # json.dumps always escapes, but the guarantee here
                    # matters for downstream grep/jq consumers.
                    line = span.to_json(indent=None).replace("\n", " ")
                    self._file.write(line)
                    self._file.write("\n")
            return SpanExportResult.SUCCESS
        except Exception:  # noqa: BLE001
            # Never let a file error bring down the hub.  Log and
            # report FAILURE so the BatchSpanProcessor can retry the
            # batch (per its own policy).
            logger.exception("file span export failed path=%s", self._path)
            return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        """Flush buffered writes to the OS.  Called by the
        BatchSpanProcessor on ``provider.force_flush`` and at
        shutdown; must return True on success so the processor
        doesn't log a spurious flush-failed warning."""
        if self._closed:
            return True
        try:
            with self._lock:
                self._file.flush()
        except Exception:  # noqa: BLE001
            logger.exception("file span flush failed path=%s", self._path)
            return False
        return True

    def shutdown(self) -> None:
        """Close the underlying file.  Idempotent — ``TracerProvider``
        and ``BatchSpanProcessor`` may both call this during teardown."""
        with self._lock:
            if self._closed:
                return
            try:
                self._file.flush()
                self._file.close()
            except Exception:  # noqa: BLE001
                logger.exception("file span shutdown failed path=%s", self._path)
            finally:
                self._closed = True
