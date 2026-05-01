"""OTel tracing bootstrap for the fin-assist hub.

Uses the raw OTel SDK (TracerProvider, BatchSpanProcessor, OTLP
exporters) with OpenInference semantic conventions for LLM attribute
names.  Any OTLP-compatible backend (Phoenix, Jaeger, Tempo, etc.)
can consume the exported spans.  Framework-specific instrumentation
(e.g. pydantic-ai's OpenInferenceSpanProcessor) is delegated to each
backend's ``install_tracing`` hook so the hub stays framework-neutral.

Entry point: :func:`setup_tracing`.  No-op when tracing is disabled.

Configuration precedence (highest wins):
  1. Explicit non-default ``TracingSettings`` value
  2. Standard OTel env vars (``OTEL_EXPORTER_OTLP_*``)
  3. Schema default (``http://localhost:6006/v1/traces``)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from fin_assist.tracing_shared import (
    DropSpansProcessor,
    TruncatingSpanProcessor,
    resolve_endpoint,
    resolve_headers,
    want_otlp_exporter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk.trace import SpanProcessor

    from fin_assist.config.schema import TracingSettings

logger = logging.getLogger(__name__)


def _build_sampler(ratio: float):
    """Translate ``TracingSettings.sampling_ratio`` into an OTel Sampler.

    Uses the cheap ALWAYS_ON / ALWAYS_OFF samplers for the edge cases so
    they skip the per-span ratio computation, and falls back to
    ``TraceIdRatioBased`` for fractional values.  ``TraceIdRatioBased``
    is deterministic per trace-id, so a sampled trace stays fully
    sampled across all its spans — important for debuggability.
    """
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        TraceIdRatioBased,
    )

    if ratio >= 1.0:
        return ALWAYS_ON
    if ratio <= 0.0:
        return ALWAYS_OFF
    return TraceIdRatioBased(ratio)


def setup_tracing(
    config: TracingSettings,
    backends: Sequence[object] = (),
) -> object | None:
    """Initialize the OTel TracerProvider and invoke backend tracing hooks.

    Called once at hub startup, after ``configure_logging()``.  No-op if
    tracing is disabled in config.

    Args:
        config: Resolved ``TracingSettings`` (from ``config.tracing``).
        backends: Sequence of ``AgentBackend`` instances.  For each backend
            that exposes an ``install_tracing(provider)`` method, we invoke
            it after the provider is globally installed.  Backends without
            the method are silently skipped so minimal test fakes and
            future non-LLM backends don't have to implement it.
    """
    if not config.enabled:
        logger.debug("tracing disabled")
        return None

    # Suppress a2a-sdk's per-class ``@trace_class`` instrumentation.
    # It emits a ``SpanKind.SERVER`` span for every internal EventQueue /
    # TaskStore / TaskManager method with zero useful attributes — ~195
    # spans per ``fin do`` invocation.  The env var is the vendor-
    # supported off-switch (see ``a2a/utils/telemetry.py``).  Using
    # ``setdefault`` so operators can force-enable it for debugging by
    # exporting ``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=true`` before
    # starting the hub.
    os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-untyped]
        OTLPSpanExporter as GRPCSpanExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-untyped]
        OTLPSpanExporter as HTTPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.semconv.attributes.service_attributes import SERVICE_NAME

    endpoint = resolve_endpoint(config)
    headers = resolve_headers(dict(config.headers))
    sampler = _build_sampler(config.sampling_ratio)

    resource = Resource.create(
        {
            SERVICE_NAME: config.project_name,
            # OpenInference convention for project grouping.  Stored as a
            # resource attribute so any OTel backend persists it; backends
            # that understand OpenInference use it for project-level filtering.
            "openinference.project.name": config.project_name,
        }
    )

    provider = TracerProvider(resource=resource, sampler=sampler)

    # Construct the OTLP exporter only when the user has opted into it.
    # ``want_otlp_exporter`` resolves provider / otlp_enabled
    # into a single boolean.  See that function for the full decision table.
    #
    # Processor stack (outermost → innermost):
    #   DropSpansProcessor          ← filters framework noise
    #   TruncatingSpanProcessor     ← scrubs + truncates attributes
    #   BatchSpanProcessor           ← ships to the configured exporter
    #
    # The drop processor sits outermost so filtered spans short-circuit
    # before the truncation + batch-queue cost.
    def _wrap(processor: BatchSpanProcessor) -> SpanProcessor:
        return DropSpansProcessor(TruncatingSpanProcessor(processor))

    want_otlp = want_otlp_exporter(config)
    if want_otlp:
        exporter_cls = GRPCSpanExporter if config.exporter_protocol == "grpc" else HTTPSpanExporter
        if headers:
            exporter = exporter_cls(endpoint=endpoint, headers=headers)
        else:
            exporter = exporter_cls(endpoint=endpoint)
        provider.add_span_processor(_wrap(BatchSpanProcessor(exporter)))

    # Attach the JSONL file sink as a second (or only) processor.  It
    # rides the same truncating + drop wrappers so the file output stays
    # clean and bounded even when OTLP isn't configured.
    from fin_assist.hub.file_exporter import FileSpanExporter
    from fin_assist.paths import TRACES_PATH

    file_exporter = FileSpanExporter(str(TRACES_PATH))
    provider.add_span_processor(_wrap(BatchSpanProcessor(file_exporter)))

    from opentelemetry.trace import set_tracer_provider

    set_tracer_provider(provider)

    # Give each backend a chance to attach framework-specific
    # instrumentation (e.g. OpenInferenceSpanProcessor for pydantic-ai).
    # The hook is optional — backends that don't expose it are skipped.
    #
    # ``include_content`` and ``event_mode`` are forwarded as kwargs so
    # backends can honor the operator's privacy and rendering preferences.
    # A backend is free to ignore either — they're informational hints,
    # not contracts.
    for backend in backends:
        install = getattr(backend, "install_tracing", None)
        if install is None:
            continue
        try:
            install(
                provider,
                include_content=config.include_content,
                event_mode=config.event_mode,
            )
        except TypeError:
            # Older / minimal backends may not accept the kwargs.  Fall
            # back to the minimal signature so we don't lock users out of
            # custom backends mid-refactor.
            try:
                install(provider)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "backend.install_tracing failed backend=%s",
                    type(backend).__name__,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "backend.install_tracing failed backend=%s",
                type(backend).__name__,
            )

    logger.info(
        "tracing enabled endpoint=%s protocol=%s project=%s"
        " backends=%d file=%s otlp=%s provider=%s",
        endpoint,
        config.exporter_protocol,
        config.project_name,
        sum(1 for b in backends if hasattr(b, "install_tracing")),
        str(TRACES_PATH),
        "yes" if want_otlp else "no",
        config.provider or "-",
    )
    return provider
