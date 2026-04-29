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
# at module-top level (see vendor source, line ~110), so we have to set
# the value **before** anything imports ``a2a``.  Importing the hub or
# the CLI will pull a2a in transitively, so the earliest safe anchor is
# ``fin_assist``'s own package ``__init__``.
#
# ``setdefault`` semantics: operators can force-enable a2a tracing for
# debugging by exporting ``OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=true``
# before invoking ``fin`` or ``python -m fin_assist``.  We only set the
# default ("false") when nothing else has chosen.
os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")
