from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fin_assist.context.base import ContextItem

SYSTEM_INSTRUCTIONS = """\
You are a shell command assistant. Given a user's natural language \
request and context, generate a single shell command.

Rules:
1. Output ONLY the command, no explanation
2. Use fish shell syntax
3. If uncertain, prefer safer commands
4. For dangerous operations (rm, dd, mkfs), include a warning

Output format: Just the command, no preamble.\
"""


def format_context(context: Sequence[ContextItem] | None) -> str:
    if not context:
        return "No context provided."
    parts = [f"[{item.type.upper()}]\n{item.content}" for item in context]
    return "\n\n".join(parts)


def build_user_message(prompt: str, context: Sequence[ContextItem] | None) -> str:
    context_str = format_context(context)
    return f"Context:\n{context_str}\n\nUser request:\n{prompt}"
