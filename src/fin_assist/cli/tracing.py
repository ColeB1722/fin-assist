"""CLI-side OpenTelemetry tracer — one root span per ``fin`` invocation.

Each ``fin`` command produces a ``cli.<command>`` root span that covers
the full CLI wall-clock time, including all HTTP round-trips to the hub.
This module:

* Opens the root span via :func:`cli_root_span`.
* Installs ``HTTPXClientInstrumentor`` so every outgoing httpx request
  auto-injects W3C ``traceparent`` and ``baggage`` headers.
* Stamps a unique ``fin_assist.cli.invocation_id`` onto the root span
  **and** OTel Baggage, so the hub can attach it to its own
  ``fin_assist.task`` span.
* Provides :func:`approval_wait_span` so dashboards can subtract
  human-think-time from total CLI wall-clock.

Why a separate CLI tracer (not just the hub's)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The CLI and hub are separate processes — the hub is a long-lived server,
the CLI is a short-lived client.  They cannot share a TracerProvider.
Each process emits its own trace with its own ``trace_id``.  The
``traceparent`` header propagates the *span context* (not the trace) so
the hub's spans are children of the CLI's HTTP-client span within the
hub's own trace.

This produces two spans that cover the same logical operation (the CLI
root and the hub's ``fin_assist.task`` span) but from different
perspectives:

* The CLI root span measures wall-clock time from the user's terminal,
  including network latency and human think-time during approval prompts.
* The hub task span measures server-side processing time only.

This is the standard pattern for distributed tracing across service
boundaries — it's how every HTTP microservice instrumented with OTel
works.  The ``invocation_id`` join key lets OTel backends correlate the
two traces into a single logical operation view.

The alternative — having the CLI create one trace and having the hub
continue it — would require the CLI to pass its full TracerProvider
configuration to the hub, which is impractical across process boundaries
and would collapse the useful distinction between client and server spans.
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fin_assist.config.schema import TracingSettings

logger = logging.getLogger(__name__)

# Attribute + baggage key used to join a CLI trace to the hub task span.
# Exported here so the hub executor can import and read the same name
# instead of string-duplicating it.
INVOCATION_ID_KEY = "fin_assist.cli.invocation_id"
COMMAND_KEY = "fin_assist.cli.command"
AGENT_KEY = "fin_assist.cli.agent"

# Module-level guard so repeated ``setup_cli_tracing`` calls (e.g. in
# tests or multi-command invocations) don't try to install a second
# provider.  OTel itself warns and ignores a second set_tracer_provider,
# but swallowing here keeps the logs clean and short-circuits the
# HTTPXClientInstrumentor double-instrumentation path too.
_installed: bool = False


def setup_cli_tracing(config: TracingSettings) -> object | None:
    """Install a TracerProvider for the CLI process.

    No-op if ``config.enabled`` is ``False`` — the CLI must stay snappy
    when tracing is off.

    Returns the provider so tests can ``force_flush`` on it; production
    callers can ignore the return value.

    Idempotency
    -----------
    Safe to call multiple times per process (e.g. in tests).  The first
    call wins; subsequent calls return the existing provider.
    """
    global _installed

    if not config.enabled:
        return None

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.semconv.attributes.service_attributes import SERVICE_NAME
    from opentelemetry.trace import get_tracer_provider, set_tracer_provider

    if _installed:
        return get_tracer_provider()

    # The CLI doesn't need the full sampler/endpoint/headers machinery
    # from ``hub/tracing.py`` — it only writes to the file sink
    # (operators use a single ``traces.jsonl`` for both processes) and
    # to OTLP *only if* the operator explicitly configured it.  A CLI
    # that tries to POST to a dead Phoenix on every ``fin`` invocation
    # would be unusable.
    resource = Resource.create(
        {
            SERVICE_NAME: f"{config.project_name}-cli",
            # The hub and CLI both set ``openinference.project.name``
            # so Phoenix groups their traces in one project.  Same
            # string so linked traces show up together in the UI.
            "openinference.project.name": config.project_name,
        }
    )
    provider = TracerProvider(resource=resource)

    # Share the wrappers with the hub so the CLI gets the same noise-
    # filtering + truncation story.  Importing lazily keeps the
    # module's cold-start cost near zero when tracing is disabled.
    from fin_assist.hub.tracing import (
        _DropSpansProcessor,
        _TruncatingSpanProcessor,
        _want_otlp_exporter,
    )

    def _wrap(inner: BatchSpanProcessor):
        return _DropSpansProcessor(_TruncatingSpanProcessor(inner))

    from fin_assist.hub.file_exporter import FileSpanExporter
    from fin_assist.paths import TRACES_PATH

    provider.add_span_processor(_wrap(BatchSpanProcessor(FileSpanExporter(str(TRACES_PATH)))))

    # Only construct the OTLP exporter when the operator has opted in
    # via provider preset or otlp_enabled.  ``_want_otlp_exporter``
    # consolidates the provider / otlp_enabled decision so the CLI
    # stays in sync with the hub.
    if _want_otlp_exporter(config):
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-untyped]
            OTLPSpanExporter as GRPCSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-untyped]
            OTLPSpanExporter as HTTPSpanExporter,
        )

        exporter_cls = GRPCSpanExporter if config.exporter_protocol == "grpc" else HTTPSpanExporter
        endpoint = _resolve_endpoint(config)
        headers = _resolve_headers(dict(config.headers))
        exporter = (
            exporter_cls(endpoint=endpoint, headers=headers)
            if headers
            else exporter_cls(endpoint=endpoint)
        )
        provider.add_span_processor(_wrap(BatchSpanProcessor(exporter)))

    set_tracer_provider(provider)

    # Auto-inject ``traceparent`` + ``baggage`` on every outgoing httpx
    # request from this process.  The instrumentor patches the global
    # ``AsyncClient`` transport class, so any httpx.AsyncClient created
    # *after* this call is auto-traced — including the lazily-created
    # ``HubClient._http``.
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        logger.exception("failed to instrument httpx")

    _installed = True
    return provider


def _resolve_endpoint(config: TracingSettings) -> str:
    from fin_assist.config.schema import TracingSettings as _TS

    default = _TS.model_fields["endpoint"].default
    if config.endpoint != default:
        return config.endpoint
    env = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    return env or config.endpoint


def _resolve_headers(cfg_headers: dict[str, str]) -> dict[str, str]:
    if cfg_headers:
        return cfg_headers
    env = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")
    if not env:
        return {}
    parsed: dict[str, str] = {}
    for pair in env.split(","):
        if "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        parsed[k.strip()] = v.strip()
    return parsed


@contextlib.contextmanager
def cli_root_span(
    command: str,
    *,
    agent: str = "",
    extra_attributes: dict[str, str] | None = None,
) -> Iterator[None]:
    """Open the ``cli.<command>`` root span for one ``fin`` invocation.

    Also sets the baggage entry ``fin_assist.cli.invocation_id`` so
    outgoing HTTP requests propagate it to the hub.  The span carries
    the same id as an attribute so Phoenix queries filtering on
    ``fin_assist.cli.invocation_id`` match both the CLI root and the
    hub task span.

    If tracing is disabled / not set up, this is a no-op context
    manager — callers can wrap every command in it unconditionally.

    Args:
        command: One of ``do``, ``talk``, ``serve``, ``status``,
            ``agents``, ``list``, ``start``, ``stop``.  Used as the
            span name suffix.
        agent: The agent name the command targets, if any.  Empty
            string for commands that don't target a specific agent.
        extra_attributes: Optional additional string attributes to
            stamp on the root (e.g. ``{"fin_assist.cli.workflow":
            "commit"}``).
    """
    import opentelemetry.trace as trace_api
    from opentelemetry import baggage, context
    from opentelemetry.trace import ProxyTracerProvider

    provider = trace_api.get_tracer_provider()
    if isinstance(provider, ProxyTracerProvider):
        # Tracing not set up — no-op so callers don't have to branch.
        yield
        return

    tracer = provider.get_tracer("fin_assist.cli")
    invocation_id = uuid.uuid4().hex

    attributes: dict[str, str] = {
        COMMAND_KEY: command,
        AGENT_KEY: agent,
        INVOCATION_ID_KEY: invocation_id,
    }
    if extra_attributes:
        attributes.update(extra_attributes)

    # Attach the invocation_id to OTel Baggage so every outgoing httpx
    # request (instrumented by ``HTTPXClientInstrumentor``) carries it
    # in a W3C ``baggage`` header.  The hub executor reads it in
    # ``_setup_task`` and stamps it on the ``fin_assist.task`` span.
    baggage_ctx = baggage.set_baggage(INVOCATION_ID_KEY, invocation_id)
    token = context.attach(baggage_ctx)
    try:
        with tracer.start_as_current_span(f"cli.{command}", attributes=attributes):
            yield
    finally:
        context.detach(token)


@contextlib.contextmanager
def approval_wait_span() -> Iterator[None]:
    """Wrap the y/N approval prompt so dashboards can subtract
    human-think-time from the CLI root-span duration.

    Parented on the current ``cli.<command>`` span if one is open,
    otherwise a no-op.  The name is fixed (``cli.approval_wait``) so
    Phoenix dashboards and queries can group on it without the CLI
    having to pass a name parameter from the call site.
    """
    import opentelemetry.trace as trace_api
    from opentelemetry.trace import ProxyTracerProvider

    provider = trace_api.get_tracer_provider()
    if isinstance(provider, ProxyTracerProvider):
        yield
        return

    tracer = provider.get_tracer("fin_assist.cli")
    with tracer.start_as_current_span("cli.approval_wait"):
        yield


def _reset_for_tests() -> None:
    """Test hook to allow re-running ``setup_cli_tracing`` in the same
    process.  Not part of the public API."""
    global _installed
    _installed = False
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        if HTTPXClientInstrumentor().is_instrumented_by_opentelemetry:
            HTTPXClientInstrumentor().uninstrument()
    except Exception:  # noqa: BLE001
        pass
