"""Context providers — files, git, shell history, environment.

Both context paths are fully wired:

- **Model-driven** (tool calls): ``read_file``, ``git_diff``,
  ``git_log``, ``shell_history`` are registered in the ``ToolRegistry``
  via ``create_default_registry()`` in ``agents/tools.py``.

- **User-driven** (``@``-completion): ``@file:``, ``@git:diff``,
  ``@git:log``, ``@history:`` tokens in FinPrompt are resolved by
  ``resolve_at_references()`` in ``cli/interaction/prompt.py``.
  Works in both ``do`` and ``talk`` modes.

Not yet wired:
- ``Environment`` provider not exposed as a tool (intentional — sensitive).
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
