"""pydantic-ai → OpenInference tracing bridge.

This module is the **only** place in the codebase that imports
``openinference.instrumentation.pydantic_ai`` and ``pydantic_ai.Agent``
for the purpose of configuring instrumentation.  Everything else in the
tracing path stays on vanilla OpenTelemetry + the OpenInference semantic
conventions (attribute names only — no instrumentor imports).

Why this is a separate module from backend.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``PydanticAIBackend`` (backend.py) implements the ``AgentBackend``
protocol for per-agent concerns: message conversion, running the agent,
serializing history.  Tracing instrumentation is a *provider-level*
concern — it runs once per ``TracerProvider`` at startup, not once per
agent.  The split keeps provider-level OTel wiring separate from
per-agent request handling.

A future ``LangChainBackend`` would have its own ``langchain_tracing.py``
module following the same pattern.

What the bridge does
~~~~~~~~~~~~~~~~~~~~
- Adds ``OpenInferenceSpanProcessor`` to the provider.  This is an
  **additive** processor: at ``on_end`` it reads pydantic-ai's emitted
  ``gen_ai.*`` attributes and writes the equivalent OpenInference
  ``llm.*`` attributes in place on the span.  The original ``gen_ai.*``
  attrs are preserved so vanilla OTel consumers are unaffected.
- Calls ``Agent.instrument_all(InstrumentationSettings(include_content=True))``
  to flip pydantic-ai's global instrumentation flag.  Must run before
  any ``Agent`` instance is built that should emit spans.

Idempotency
~~~~~~~~~~~
``install_pydantic_ai_instrumentation`` can be called multiple times per
process — a module-level ``_installed`` set tracks which TracerProviders
have already been configured, and a separate flag tracks whether
``Agent.instrument_all`` has run.  Both are safe to re-enter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from weakref import WeakSet

from pydantic_ai import Agent
from pydantic_ai.models.instrumented import InstrumentationSettings

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

_installed_providers: WeakSet = WeakSet()
_agent_instrumented: bool = False


def install_pydantic_ai_instrumentation(
    provider: TracerProvider,
    *,
    include_content: bool = True,
    event_mode: Literal["attributes", "logs"] = "attributes",
) -> None:
    """Attach pydantic-ai → OpenInference tracing to *provider*.

    Idempotent: repeated calls with the same provider are no-ops.
    ``Agent.instrument_all`` is flipped once per process — subsequent
    ``include_content`` / ``event_mode`` differences after the first
    install are ignored (first call wins) because pydantic-ai does not
    support reconfiguring instrumentation on running agents.

    Args:
        provider: The fin-assist ``TracerProvider`` built by
            ``hub.tracing.setup_tracing``.  The OpenInference processor
            is added to it so ``gen_ai.*`` spans get enriched into
            ``llm.*`` attributes at ``on_end``.
        include_content: Whether pydantic-ai should include full message
            bodies in the emitted spans.  ``True`` gives OTel backends
            content to render in chat views; ``False`` for privacy-
            sensitive / shared deployments.
        event_mode: ``"attributes"`` embeds LLM messages as span
            attributes (OpenInference's preferred form for backends that
            render chat views); ``"logs"`` emits them as OTel log events
            for backends that render logs natively.
    """
    global _agent_instrumented

    if provider in _installed_providers:
        return

    from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor

    provider.add_span_processor(OpenInferenceSpanProcessor())
    _installed_providers.add(provider)

    if not _agent_instrumented:
        Agent.instrument_all(
            InstrumentationSettings(
                include_content=include_content,
                event_mode=event_mode,
                tracer_provider=provider,
            )
        )
        _agent_instrumented = True


def _reset_for_tests() -> None:
    """Clear the idempotency trackers.  Test-only; do not call from hub code."""
    global _agent_instrumented
    _installed_providers.clear()
    _agent_instrumented = False
