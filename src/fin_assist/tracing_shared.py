"""Shared OpenTelemetry utilities for CLI and hub.

This module contains span processors, the graceful OTLP exporter wrapper,
and config resolution helpers used by both the CLI and hub processes.
Extracted from ``hub/tracing.py`` so the CLI can import from a public API
without depending on private hub internals.

The constants (``MAX_ATTR_BYTES``, ``NOISE_ATTRS``, etc.) are documented as
the "spec" for non-Python clients (e.g. a future Rust TUI) that need to
implement compatible span processing logic.

Span Processor Stack
~~~~~~~~~~~~~~~~~~~~~
Two SpanProcessor wrappers sit between the export pipeline and the real
exporters:

* **Noise filtering** — drops framework-internal spans (e.g. ASGI
  per-chunk response spans) that have no diagnostic value.
* **Attribute hygiene** — scrubs noise attributes leaked by upstream
  instrumentors (e.g. ``logfire.*`` from pydantic-ai) and truncates
  oversized string attributes to stay under gRPC's 4MB message limit.

Both CLI and hub use the same processor stack so traces from both processes
have consistent attribute hygiene.

Graceful OTLP Exporter
~~~~~~~~~~~~~~~~~~~~~~
``_GracefulOTLPExporter`` wraps the real OTLP exporter and catches all
exceptions from ``export()``, returning ``SpanExportResult.FAILURE``
instead of letting them propagate to the SDK's ``BatchSpanProcessor``.
The SDK's exception handler produces multi-line tracebacks on every batch
flush when Phoenix isn't running; the wrapper suppresses that noise while
still allowing the file sink (``FileSpanExporter``) to work normally.

A one-time INFO log on first failure tells the operator the endpoint is
unreachable and where spans continue to be written (the JSONL file sink).
Subsequent failures are silent.  The ``_failed`` flag resets on successful
export so mid-session Phoenix restarts are handled gracefully.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

if TYPE_CHECKING:
    from fin_assist.config.schema import TracingSettings

logger = logging.getLogger(__name__)


MAX_ATTR_BYTES = 50_000
"""Maximum size for string span attributes (in bytes).

Attributes larger than this are truncated before export to avoid exceeding
gRPC's 4MB message limit.  This is the spec for non-Python clients that
need to implement compatible truncation logic.
"""

NOISE_ATTRS: dict[str, frozenset[str]] = {
    "asgi.event.type": frozenset({"http.response.body"}),
}
"""Attribute values whose spans are unconditionally dropped before export.

Keyed by attribute name → set of values that mark the span as noise.

Why key on attributes, not span names: ASGI / FastAPI instrumentation names
its per-chunk response spans ``"http send"`` (older versions) or ``"{route}
http send"`` (newer), and the string isn't stable across the instrumentor's
own refactors.  ``asgi.event.type = "http.response.body"`` *is* stable —
it's the ASGI-spec event name and shows up verbatim in the instrumentor
source.  Keying on it survives instrumentor upgrades.

This is the spec for non-Python clients that need to implement compatible
noise filtering logic.
"""

SCRUB_ATTR_PREFIXES = ("logfire.",)
"""Attribute prefixes to scrub from every span before export.

These are noise leaked by upstream instrumentors — they carry no diagnostic
value for downstream consumers and bloat span size.

* ``logfire.*`` — pydantic-ai's internal tracing front-end emits these as
  rendered log messages + JSON schemas, both already available in dedicated
  OpenInference fields.
"""

SCRUB_ATTR_NAMES = frozenset({"final_result"})
"""Attribute names to scrub from every span before export.

* ``final_result`` — pydantic-ai dumps the full ``RunResult`` on the
  ``agent run`` span.  Redundantly available as ``output.value``
  (OpenInference) and ``pydantic_ai.all_messages``.
"""


def _scrub_span_attributes(span) -> None:
    """Delete attribute keys that leak from upstream instrumentors.

    Applied at ``on_end`` before export.  Mutates ``span._attributes``
    directly because ``set_attribute`` no-ops after ``end()`` and the
    read-only snapshot passed to multi-processor setups doesn't expose a
    public write API.

    Also drops ``session.id`` when it equals ``fin_assist.context.id``:
    both are set to the same value by the executor, so carrying both is
    redundant.  Kept when the values differ (a future backend may set
    ``session.id`` to a different value, e.g. a tenant identifier).
    """
    attributes = getattr(span, "_attributes", None)
    if attributes is None:
        attributes = span.attributes
    if not attributes:
        return

    for key in list(attributes.keys()):
        if key in SCRUB_ATTR_NAMES or any(key.startswith(p) for p in SCRUB_ATTR_PREFIXES):
            try:
                del attributes[key]
            except (TypeError, KeyError, AttributeError):
                logger.debug("could not scrub attribute key=%s", key)

    session_id = attributes.get("session.id")
    context_id = attributes.get("fin_assist.context.id")
    if session_id is not None and session_id == context_id:
        try:
            del attributes["session.id"]
        except (TypeError, KeyError, AttributeError):
            logger.debug("could not dedupe session.id")


def _truncate_span_attributes(span) -> None:
    """Truncate string attributes that exceed the export size limit.

    LLM instrumentation can embed full message history as JSON in span
    attributes (e.g. ``gen_ai.input.messages``), and tool results can be
    very large, producing attributes that exceed gRPC's 4MB message limit.

    Replaces any string attribute longer than ``MAX_ATTR_BYTES`` (50KB)
    with a truncated marker.  Like ``_scrub_span_attributes``, this
    mutates ``span._attributes`` directly because the public API is
    read-only after ``end()``.
    """
    attributes = getattr(span, "_attributes", None)
    if attributes is None:
        attributes = span.attributes
    if not attributes:
        return
    for key, value in list(attributes.items()):
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) > MAX_ATTR_BYTES:
                half_budget = MAX_ATTR_BYTES // 2
                truncated_prefix = encoded[:half_budget].decode("utf-8", errors="ignore")
                truncated = truncated_prefix + f"\n... [truncated, {len(encoded)} bytes total]"
                try:
                    attributes[key] = truncated
                except (TypeError, AttributeError):
                    logger.debug("could not rewrite oversized attribute key=%s", key)


class TruncatingSpanProcessor(SpanProcessor):
    """SpanProcessor that scrubs noise attributes and truncates large
    string attributes before export.

    Processing order at ``on_end``:
      1. Scrub noise attributes (leaked instrumentor keys, redundant
         ``session.id``).
      2. Truncate oversized string attributes.
      3. Forward to the downstream delegate (the batch exporter).

    Scrubbing before truncation avoids wasting work on attributes that
    are about to be deleted.
    """

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span, parent_context=None):
        self._delegate.on_start(span, parent_context)

    def on_end(self, span):
        _scrub_span_attributes(span)
        _truncate_span_attributes(span)
        self._delegate.on_end(span)

    def shutdown(self):
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


class DropSpansProcessor(SpanProcessor):
    """SpanProcessor that drops framework-noise spans before export.

    Sits at the head of the export chain.  For each finishing span we
    peek at its attributes; if any ``(name, value)`` pair matches
    ``NOISE_ATTRS`` we simply do not forward the span to the
    downstream delegate, dropping it from every configured exporter
    (OTLP, file, both) in one shot.

    We can't prevent the span from being *created* — the instrumentor
    that emits it doesn't check with us first — but suppressing at
    export-time costs microseconds per span and gives us a single
    choke point for future noise sources.
    """

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span, parent_context=None):
        self._delegate.on_start(span, parent_context)

    def on_end(self, span):
        attrs = getattr(span, "attributes", None) or {}
        for attr_name, bad_values in NOISE_ATTRS.items():
            if attrs.get(attr_name) in bad_values:
                return
        self._delegate.on_end(span)

    def shutdown(self):
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


class _GracefulOTLPExporter(SpanExporter):
    """SpanExporter wrapper that catches OTLP connection errors gracefully.

    When Phoenix (or any OTLP backend) is unreachable, the real
    ``OTLPSpanExporter`` raises ``ConnectionError`` on every batch flush.
    The SDK's ``BatchSpanProcessor._export()`` catches this via
    ``except Exception`` and logs it via ``logger.exception()``, producing
    multi-line tracebacks that spam the terminal.

    This wrapper intercepts exceptions *before* they reach the SDK:

    .. code-block:: text

       Before:  SDK._export() → OTLPSpanExporter.export() → ConnectionError
                → SDK catches → logger.exception() → TRACEBACK SPAM

       After:   SDK._export() → _GracefulOTLPExporter.export()
                → OTLPSpanExporter.export() → ConnectionError
                → wrapper catches → returns FAILURE silently → NO TRACEBACK

    Behaviour:

    * First failure: one-time ``logger.info`` naming the endpoint and the
      file-sink path so the operator knows spans are still being captured.
    * Subsequent failures: silent (``SpanExportResult.FAILURE`` returned).
    * Successful export resets ``_failed`` so a mid-session Phoenix restart
      triggers a fresh one-time log if it goes down again.
    * ``shutdown()`` and ``force_flush()`` delegate to the real exporter.
    """

    def __init__(self, delegate: SpanExporter, *, endpoint: str, file_sink_path: str) -> None:
        self._delegate = delegate
        self._endpoint = endpoint
        self._file_sink_path = file_sink_path
        self._failed = False

    def export(self, spans) -> SpanExportResult:
        try:
            result = self._delegate.export(spans)
            if self._failed:
                self._failed = False
            return result
        except Exception:
            if not self._failed:
                logger.info(
                    "OTLP export to %s failed — spans continue to file sink at %s",
                    self._endpoint,
                    self._file_sink_path,
                )
                self._failed = True
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


def resolve_endpoint(config: TracingSettings) -> str:
    """Resolve the effective OTLP endpoint: explicit config > env > default.

    When the config endpoint equals the schema default we treat it as
    unset and fall back to ``OTEL_EXPORTER_OTLP_ENDPOINT`` (standard
    OTel env var).

    Args:
        config: Resolved ``TracingSettings`` (from ``config.tracing``).

    Returns:
        The endpoint URL to use for the OTLP exporter.
    """
    from fin_assist.config.schema import TracingSettings

    default = TracingSettings.model_fields["endpoint"].default
    if config.endpoint != default:
        return config.endpoint

    env_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if env_endpoint:
        return env_endpoint

    return config.endpoint


def want_otlp_exporter(config: TracingSettings) -> bool:
    """Whether to construct the OTLP exporter.

    Resolution order (first match wins):

    1. ``provider="none"`` → always False (file-only mode).
    2. ``otlp_enabled=False`` → always False (explicit opt-out).
    3. ``provider`` is any non-None value (e.g. ``"phoenix"``) → True.
    4. ``provider=None`` (manual mode) → ``otlp_enabled`` (default True).

    Args:
        config: Resolved ``TracingSettings`` (from ``config.tracing``).

    Returns:
        True if an OTLP exporter should be constructed.
    """
    if config.provider == "none":
        return False
    if not config.otlp_enabled:
        return False
    if config.provider is not None:
        return True
    return config.otlp_enabled


def resolve_headers(config_headers: dict[str, str]) -> dict[str, str]:
    """Resolve OTLP exporter headers: explicit config > OTEL env > empty.

    Parses ``OTEL_EXPORTER_OTLP_HEADERS`` per the OTel spec (comma-
    separated ``key=value`` pairs).  Config-level headers always win
    (per-key).  Malformed env pairs are skipped with a warning so a
    typo doesn't bring down the hub.

    Args:
        config_headers: Headers from ``TracingSettings.headers``.

    Returns:
        Resolved headers dict for the OTLP exporter.
    """
    if config_headers:
        return dict(config_headers)

    env = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")
    if not env:
        return {}

    parsed: dict[str, str] = {}
    for pair in env.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            logger.warning("malformed OTEL_EXPORTER_OTLP_HEADERS pair (no '='): %r", pair)
            continue
        key, _, value = pair.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed
