from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fin_assist.context.base import ContextItem

SHELL_INSTRUCTIONS = """\
You are a shell command assistant. Given a user's natural language \
request and context, generate a single shell command.

Rules:
1. Output ONLY the command, no explanation
2. Use fish shell syntax
3. If uncertain, prefer safer commands
4. For dangerous operations (rm, dd, mkfs), include a warning

Output format: Just the command, no preamble.\
"""

CHAIN_OF_THOUGHT_INSTRUCTIONS = """\
You are a thoughtful, general-purpose assistant. Given a user's request, \
think through the problem step-by-step before responding.

Your approach:
1. Understand what the user is asking for
2. Consider any relevant context provided
3. Reason through the solution step-by-step
4. Provide a clear, concise response

You can help with:
- Answering questions
- Generating shell commands (use fish shell syntax)
- Brainstorming and planning
- Explaining concepts
- And any other general assistance

Show your reasoning when helpful, but keep responses focused and useful.\
"""


def format_context(context: Sequence[ContextItem] | None) -> str:
    if not context:
        return "No context provided."
    parts = [f"[{item.type.upper()}]\n{item.content}" for item in context]
    return "\n\n".join(parts)


def build_user_message(prompt: str, context: Sequence[ContextItem] | None) -> str:
    context_str = format_context(context)
    return f"Context:\n{context_str}\n\nUser request:\n{prompt}"
