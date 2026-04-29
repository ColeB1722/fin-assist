"""OpenTelemetry tracing initialization for the fin-assist hub.

Call ``setup_tracing()`` once at hub startup, after ``configure_logging()``.
No-op when tracing is disabled (the default).

Uses raw OTel SDK (TracerProvider + OTLPSpanExporter) instead of
``phoenix.otel.register()`` for portability — works with any OTel
backend (Phoenix, Jaeger, Tempo, etc.).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fin_assist.config.schema import TracingSettings

logger = logging.getLogger(__name__)


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
        }
    )

    exporter_cls = GRPCSpanExporter if config.exporter_protocol == "grpc" else HTTPSpanExporter
    exporter = exporter_cls(endpoint=config.endpoint)

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

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
    # The OTLP endpoint is typically 4317 (gRPC) or 4318 (HTTP).
    # Derive the health check URL from the OTLP endpoint.
    try:
        if config.exporter_protocol == "grpc" and ":4317" in base:
            health_url = base.replace(":4317", ":6006") + "/healthz"
        elif config.exporter_protocol == "http" and ":4318" in base:
            health_url = base.replace(":4318", ":6006") + "/healthz"
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
