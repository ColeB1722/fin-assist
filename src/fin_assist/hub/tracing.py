"""OpenTelemetry tracing initialization for the fin-assist hub.

Call ``setup_tracing()`` once at hub startup, after ``configure_logging()``.
No-op when tracing is disabled (the default).

Uses raw OTel SDK (TracerProvider + OTLPSpanExporter) instead of
``phoenix.otel.register()`` for portability — works with any OTel
backend (Phoenix, Jaeger, Tempo, etc.).

Default protocol is HTTP/protobuf (port 4318) rather than gRPC (port 4317)
because gRPC has a default 4MB message size limit.  LLM instrumentation
can produce large spans (e.g. ``gen_ai.input.messages`` with tool results),
which exceed the gRPC limit and cause ``RESOURCE_EXHAUSTED`` errors.
HTTP/protobuf has no such limit.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import SpanProcessor

if TYPE_CHECKING:
    from fin_assist.config.schema import TracingSettings

logger = logging.getLogger(__name__)

_MAX_ATTR_BYTES = 50_000


def _truncate_span_attributes(span) -> None:
    """Truncate string attributes that exceed the export size limit.

    LLM instrumentation (pydantic-ai) embeds full message history as JSON
    in ``gen_ai.input.messages`` and ``gen_ai.output.messages``.  Tool
    results can be very large (e.g. ``find . -type f`` returning 70K+ lines),
    producing span attributes that exceed gRPC's 4MB message limit.

    This function truncates any string attribute longer than
    ``_MAX_ATTR_BYTES`` (50KB), replacing it with a truncated marker.
    """
    if not span.attributes:
        return
    for key, value in list(span.attributes.items()):
        if isinstance(value, str) and len(value.encode("utf-8")) > _MAX_ATTR_BYTES:
            truncated = (
                value[: _MAX_ATTR_BYTES // 2] + f"\n... [truncated, {len(value)} chars total]"
            )
            span.set_attribute(key, truncated)


class _TruncatingSpanProcessor(SpanProcessor):
    """SpanProcessor that truncates large attributes before export."""

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span, parent_context=None):
        self._delegate.on_start(span, parent_context)

    def on_end(self, span):
        _truncate_span_attributes(span)
        self._delegate.on_end(span)

    def shutdown(self):
        self._delegate.shutdown()

    def force_flush(self, timeout_millis=None):
        return self._delegate.force_flush(timeout_millis)


def setup_tracing(config: TracingSettings) -> None:
    """Initialize OTel TracerProvider with OTLP exporter.

    Called once at hub startup, after ``configure_logging()``.
    No-op if tracing is disabled.
    """
    if not config.enabled:
        logger.debug("tracing disabled")
        return

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-untyped]
        OTLPSpanExporter as GRPCSpanExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-untyped]
        OTLPSpanExporter as HTTPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.semconv.resource import ResourceAttributes

    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: config.project_name,
            "openinference.project.name": config.project_name,
        }
    )

    exporter_cls = GRPCSpanExporter if config.exporter_protocol == "grpc" else HTTPSpanExporter
    exporter = exporter_cls(endpoint=config.endpoint)

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(_TruncatingSpanProcessor(BatchSpanProcessor(exporter)))

    from opentelemetry.trace import set_tracer_provider

    set_tracer_provider(provider)

    _probe_phoenix(config)

    logger.info(
        "tracing enabled endpoint=%s protocol=%s project=%s",
        config.endpoint,
        config.exporter_protocol,
        config.project_name,
    )


def _probe_phoenix(config: TracingSettings) -> None:
    """One-time startup probe: check if the OTLP backend is reachable.

    Logs the result but does not block or raise — BatchSpanProcessor
    handles unreachable endpoints gracefully by silently dropping spans.
    """
    import httpx

    base = config.endpoint.rstrip("/")
    # Phoenix exposes /healthz on its HTTP port (default 6006).
    # Derive the health check URL from the OTLP endpoint.
    try:
        if ":4317" in base and config.exporter_protocol == "grpc":
            health_url = base.replace(":4317", ":6006") + "/healthz"
        elif ":6006" in base:
            health_url = base.split(":6006")[0] + ":6006/healthz"
        else:
            health_url = None

        if health_url:
            resp = httpx.get(health_url, timeout=2)
            if resp.status_code == 200:
                logger.info("phoenix health check: reachable at %s", health_url)
            else:
                logger.warning(
                    "phoenix health check: unexpected status %d at %s",
                    resp.status_code,
                    health_url,
                )
        else:
            logger.debug("skipping phoenix health check (non-default endpoint)")
    except Exception:
        logger.warning(
            "phoenix health check: unreachable — traces will be dropped until backend is available",
            exc_info=True,
        )
