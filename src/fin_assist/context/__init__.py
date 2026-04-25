"""Context providers — files, git, shell history, environment.

Status (2026-04-24): **Partially integrated.**

Model-driven path (tool calls) is wired: ``read_file``, ``git_diff``,
``git_log``, ``shell_history`` are registered in the ``ToolRegistry``
via ``create_default_registry()`` in ``agents/tools.py``.  The default
agent config includes all four tools.

User-driven path (CLI flags) is partially wired: ``--file`` and
``--git-diff`` flags on the ``do`` command inject context into the
prompt via ``_inject_context()`` in ``cli/main.py``.

Still not wired:
- ``--git-log`` CLI flag (low priority — model can call the tool).
- ``Environment`` provider not exposed as a tool (intentional — sensitive).
- ``@``-triggered completion in ``FinPrompt`` for talk mode.
- ``build_user_message``/``format_context`` helpers in ``llm/prompts.py``
  not called from the request path (CLI injection bypasses them).
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
