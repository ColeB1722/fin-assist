"""OpenTelemetry tracing bootstrap for the fin-assist hub.

Vendor-agnostic by design.  The module knows nothing about Phoenix,
Logfire, Tempo, Jaeger, or any specific OTel backend — it only knows
how to build an OTLP exporter, a TracerProvider, and invoke each
registered backend's ``install_tracing`` hook (which is where backend-
specific instrumentation like the OpenInference bridge lives).

Entry point: ``setup_tracing(config, backends=...)``.  Called once at
hub startup from ``cli/main.py:_serve_command``.  No-op when tracing is
disabled.

Configuration precedence (highest wins)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Explicit non-default value in ``TracingSettings`` (``FIN_TRACING__*``
   env or config.toml).
2. Standard OTel env vars: ``OTEL_EXPORTER_OTLP_ENDPOINT``,
   ``OTEL_EXPORTER_OTLP_HEADERS``, ``OTEL_EXPORTER_OTLP_PROTOCOL``.
3. Schema default (``http://localhost:6006/v1/traces`` — Phoenix's
   default OTLP/HTTP port, but nothing else in the code assumes Phoenix).

Why we don't use ``phoenix.otel.register()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
That helper couples the process to Phoenix's API.  Raw OTel SDK is a
dozen extra lines and works with any OTLP-compatible backend.  Users
who want to point at Tempo, Jaeger, Logfire, or their own renderer do
so via env vars without editing code.

Attribute-size truncation
~~~~~~~~~~~~~~~~~~~~~~~~~
LLM instrumentation produces spans whose attribute strings
(``gen_ai.input.messages`` / ``gen_ai.output.messages``) can exceed
gRPC's default 4MB message limit when tool outputs are large.  The
``_TruncatingSpanProcessor`` wraps the export pipeline and trims any
string attribute longer than ``_MAX_ATTR_BYTES`` before export.  This
keeps the gRPC path usable and the UI snappy without changing span
semantics.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import SpanProcessor

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fin_assist.config.schema import TracingSettings

logger = logging.getLogger(__name__)

_MAX_ATTR_BYTES = 50_000


def _truncate_span_attributes(span) -> None:
    """Truncate string attributes that exceed the export size limit.

    LLM instrumentation (pydantic-ai) embeds full message history as JSON
    in ``gen_ai.input.messages`` and ``gen_ai.output.messages``.  Tool
    results can be very large (e.g. ``find . -type f`` returning 70K+ lines),
    producing span attributes that exceed gRPC's 4MB message limit.

    Truncates any string attribute longer than ``_MAX_ATTR_BYTES`` (50KB),
    replacing it with a truncated marker.  Applied at ``on_end`` before
    export.

    Implementation note — why we mutate ``_attributes`` directly
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``span.set_attribute`` no-ops after ``end()`` (OTel logs a warning
    and drops the write) and isn't defined at all on the read-only
    snapshots OTel passes to multi-processor setups.  The underlying
    ``_attributes`` is a plain mapping that both ``_Span`` and
    ``ReadableSpan`` expose, and mutating it here is the only way to
    rewrite a value at ``on_end`` time without re-implementing the
    attribute pipeline.  This is a grey-area API but OTel's own
    ``BatchSpanProcessor`` relies on the same invariant (the span being
    read-only after end), so we're safe as long as we only mutate
    values, never keys.
    """
    attributes = getattr(span, "_attributes", None) or span.attributes
    if not attributes:
        return
    for key, value in list(attributes.items()):
        if isinstance(value, str) and len(value.encode("utf-8")) > _MAX_ATTR_BYTES:
            truncated = (
                value[: _MAX_ATTR_BYTES // 2] + f"\n... [truncated, {len(value)} chars total]"
            )
            try:
                attributes[key] = truncated
            except (TypeError, AttributeError):
                # ``attributes`` proxy is read-only (rare — some
                # BoundedAttributes configurations).  Best-effort: drop
                # the oversized attribute so the export doesn't blow
                # past the size limit.
                logger.debug("could not rewrite oversized attribute key=%s", key)


class _TruncatingSpanProcessor(SpanProcessor):
    """SpanProcessor that truncates large string attributes before export."""

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span, parent_context=None):
        self._delegate.on_start(span, parent_context)

    def on_end(self, span):
        _truncate_span_attributes(span)
        self._delegate.on_end(span)

    def shutdown(self):
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


def _default_endpoint() -> str:
    """The schema default for ``TracingSettings.endpoint``.

    Kept as a helper so ``_resolve_endpoint`` can distinguish "user left
    the schema default" from "user explicitly set this value to the
    default."  Pydantic doesn't preserve that distinction, but in
    practice the default is only ever set by schema-default, so
    equality-with-default is a safe proxy.
    """
    from fin_assist.config.schema import TracingSettings

    return TracingSettings.model_fields["endpoint"].default


def _resolve_endpoint(config: TracingSettings) -> str:
    """Resolve the effective OTLP endpoint: explicit config > env > default.

    ``TracingSettings.endpoint`` defaults to Phoenix's local HTTP port.
    When it equals the default we treat it as unset and fall back to
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` (standard OTel env var).
    """
    if config.endpoint != _default_endpoint():
        return config.endpoint

    env_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if env_endpoint:
        return env_endpoint

    return config.endpoint


def _otlp_explicitly_configured(config: TracingSettings) -> bool:
    """Whether the user actually asked for OTLP export.

    Used to decide if the OTLP exporter should be constructed at all
    when ``file_path`` is set.  The rule is: treat the schema default
    as 'not set' — only build the OTLP exporter when the user has
    either overridden the endpoint in ``TracingSettings`` or set
    ``OTEL_EXPORTER_OTLP_ENDPOINT``.

    This matters because when only ``file_path`` is configured and
    Phoenix isn't running at the default port, we don't want to
    silently try to POST to a dead socket on every batch flush —
    file-only users shouldn't pay that cost.
    """
    if config.endpoint != _default_endpoint():
        return True
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


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


def _resolve_headers(config_headers: dict[str, str]) -> dict[str, str]:
    """Resolve OTLP exporter headers: explicit config > OTEL env > empty.

    Parses ``OTEL_EXPORTER_OTLP_HEADERS`` per the OTel spec (comma-
    separated ``key=value`` pairs).  Config-level headers always win
    (per-key).  Malformed env pairs are skipped with a warning so a
    typo doesn't bring down the hub.
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

    endpoint = _resolve_endpoint(config)
    headers = _resolve_headers(dict(config.headers))
    sampler = _build_sampler(config.sampling_ratio)

    resource = Resource.create(
        {
            SERVICE_NAME: config.project_name,
            # Phoenix-only attribute, but it's a resource attribute, not an
            # API call — keeping it here does not couple us to Phoenix.
            "openinference.project.name": config.project_name,
        }
    )

    provider = TracerProvider(resource=resource, sampler=sampler)

    # Construct the OTLP exporter only when the user has opted into it.
    # When ``file_path`` is the sole configured sink, skip OTLP entirely
    # so we don't ship spans at a dead localhost:6006 on every batch.
    # Backward compat: if ``file_path`` is unset (the existing shape),
    # we always build the OTLP exporter — even at the default endpoint —
    # to match prior behavior.
    want_otlp = config.file_path is None or _otlp_explicitly_configured(config)
    if want_otlp:
        exporter_cls = GRPCSpanExporter if config.exporter_protocol == "grpc" else HTTPSpanExporter
        if headers:
            exporter = exporter_cls(endpoint=endpoint, headers=headers)
        else:
            exporter = exporter_cls(endpoint=endpoint)
        provider.add_span_processor(_TruncatingSpanProcessor(BatchSpanProcessor(exporter)))

    # Attach the JSONL file sink as a second (or only) processor.  It
    # rides the same truncating wrapper so large tool outputs don't
    # balloon the file either.
    if config.file_path:
        from fin_assist.hub.file_exporter import FileSpanExporter

        file_exporter = FileSpanExporter(config.file_path)
        provider.add_span_processor(_TruncatingSpanProcessor(BatchSpanProcessor(file_exporter)))

    from opentelemetry.trace import set_tracer_provider

    set_tracer_provider(provider)

    # Give each backend a chance to attach framework-specific
    # instrumentation (e.g. OpenInferenceSpanProcessor for pydantic-ai).
    # The hook is optional — skip backends that don't expose it.
    #
    # Forward the content/event-mode knobs through as kwargs so backends
    # can honor the operator's privacy and rendering preferences.  A
    # backend is free to ignore either (it's informational — the hub
    # makes no assumptions about what each framework supports).
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
        "tracing enabled endpoint=%s protocol=%s project=%s backends=%d file=%s otlp=%s",
        endpoint,
        config.exporter_protocol,
        config.project_name,
        sum(1 for b in backends if hasattr(b, "install_tracing")),
        config.file_path or "-",
        "yes" if want_otlp else "no",
    )
    return provider
