"""Context providers — files, git, shell history, environment.

Both context paths are fully wired:

- **Model-driven** (tool calls): ``read_file``, ``git``, ``gh``,
  ``shell_history``, ``run_shell`` are registered in the ``ToolRegistry``
  via ``create_default_registry()`` in ``agents/tools.py``.

- **User-driven** (``@``-completion): ``@file:``, ``@git:diff``,
  ``@git:log``, ``@git:status``, ``@history:``, ``@env:`` tokens in
  FinPrompt are resolved by ``resolve_at_references()`` in
  ``cli/interaction/prompt.py``.  Works in both ``do`` and ``talk`` modes.
"""

from __future__ import annotations

from fin_assist.context.base import (
    ContextItem,
    ContextProvider,
    ContextProviderRegistry,
    ContextType,
    ItemStatus,
    create_default_context_registry,
)
from fin_assist.context.environment import Environment
from fin_assist.context.files import FileFinder
from fin_assist.context.git import GitContext
from fin_assist.context.history import ShellHistory

__all__ = [
    "ContextItem",
    "ContextProvider",
    "ContextProviderRegistry",
    "ContextType",
    "ItemStatus",
    "create_default_context_registry",
    "Environment",
    "FileFinder",
    "GitContext",
    "ShellHistory",
]
