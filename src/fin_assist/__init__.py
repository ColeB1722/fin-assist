"""Terminal inline assistant for fish shell."""

from __future__ import annotations

import os

# a2a-sdk's ``@trace_class`` decorator is applied at *module import time*
# to every internal class (EventQueue, TaskStore, request handlers).  It
# emits a ``SpanKind.SERVER`` span for every method call with zero
# useful attributes — ~70 spans per ``fin do`` invocation, polluting
# every trace.
#
# ``a2a/utils/telemetry.py`` reads ``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED``
# at module-top level, so we must set it before a2a is imported.
# ``pyproject.toml`` cannot set process-level env vars (it only
# defines build metadata), so the earliest safe anchor is this
# package ``__init__``, which runs before hub/CLI transitively
# import a2a.
#
# ``setdefault`` lets operators force-enable a2a tracing for debugging
# by exporting ``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=true`` before
# invoking ``fin`` or ``python -m fin_assist``.
os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")
