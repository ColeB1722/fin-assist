"""Context providers — files, git, shell history, environment.

Status (2026-04-22): **Parked, awaiting Executor rework.**

These providers are fully implemented and unit-tested in isolation, but
they are not wired into the request path. Nothing in ``src/fin_assist/``
instantiates them; only tests import them directly.

Integration is deliberately deferred until after the Executor is
refactored from one-shot to a multi-step loop (see ``handoff.md`` →
"Executor Loop Rework"). At that point, context injection for ``do``
(``--file``/``--git-diff``/``--git-log`` CLI flags) and for ``talk``
(``@``-triggered completion in ``FinPrompt``) — Steps 7 and 8 of the
config-driven-redesign plan — become the natural first consumers of
this subsystem.

**Do not delete this code.** It is reserved infrastructure, not dead
code. The classes here encode design decisions (ContextType taxonomy,
ContextItem shape, ItemStatus lifecycle) that the CLI and Executor
will consume when integration lands.

See ``handoff.md`` for the current parked-state entry and the
integration plan.
"""

from __future__ import annotations

from fin_assist.context.base import ContextItem, ContextProvider, ContextType, ItemStatus
from fin_assist.context.environment import Environment
from fin_assist.context.files import FileFinder
from fin_assist.context.git import GitContext
from fin_assist.context.history import ShellHistory

__all__ = [
    "ContextItem",
    "ContextProvider",
    "ContextType",
    "ItemStatus",
    "Environment",
    "FileFinder",
    "GitContext",
    "ShellHistory",
]
