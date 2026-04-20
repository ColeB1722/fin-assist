"""Unified post-response pipeline: rendering, approval, and action dispatch.

Every code path that receives an ``AgentResult`` — one-shot (``do``) or
multi-turn (``talk``) — needs the same sequence of concerns handled:

1. Auth-required detection
2. Output rendering (thinking, command/text, warnings)
3. Error handling
4. Approval widget (for agents that ``requires_approval``)

Before this module, that logic was duplicated across ``main.py``
(``_do_command``) and ``chat.py``.  ``handle_post_response`` centralises
it into a single async function that returns a typed action the caller
can branch on.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.console import Console

from fin_assist.cli.display import (
    render_agent_output,
    render_auth_required,
    render_error,
    render_info,
)
from fin_assist.cli.interaction.approve import ApprovalAction, execute_command, run_approve_widget

if TYPE_CHECKING:
    from fin_assist.agents.metadata import AgentCardMeta
    from fin_assist.cli.client import AgentResult

console = Console()


class PostResponseAction(StrEnum):
    """What happened after processing the agent's response."""

    CONTINUE = "continue"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    AUTH_REQUIRED = "auth_required"
    ERROR = "error"


@dataclass
class PostResponseResult:
    """Outcome of ``handle_post_response``.

    ``action`` tells the caller what happened; ``exit_code`` is meaningful
    for one-shot (``do``) mode where the CLI needs a process exit code.
    """

    action: PostResponseAction
    exit_code: int = 0


async def handle_post_response(
    result: AgentResult,
    card_meta: AgentCardMeta | None = None,
    *,
    show_thinking: bool = False,
    mode: str = "talk",
) -> PostResponseResult:
    """Run the full post-response pipeline and return what happened.

    Args:
        result: The ``AgentResult`` to process.
        card_meta: Agent capability metadata.  ``None`` is safe — rendering
            falls back to plain Markdown output with Panel warnings.
        show_thinking: Whether to render thinking content.
        mode: ``"do"`` or ``"talk"`` — controls rendering style and whether
            a "Cancelled" info message is printed on approval rejection.
    """
    # 1. Auth required — always takes priority
    if result.metadata.get("auth_required"):
        render_auth_required(result.output)
        return PostResponseResult(action=PostResponseAction.AUTH_REQUIRED, exit_code=1)

    # 2. Error
    if not result.success:
        render_error(result.output or "Unknown error")
        return PostResponseResult(action=PostResponseAction.ERROR, exit_code=1)

    # 3. Render output
    console.print()
    render_agent_output(result, card_meta, show_thinking=show_thinking, mode=mode)

    # 4. Approval widget — only when the agent requires it and succeeded
    if card_meta is not None and card_meta.requires_approval:
        action = await run_approve_widget(
            command=result.output,
            warnings=result.warnings,
        )
        if action == ApprovalAction.EXECUTE:
            exit_code = execute_command(result.output)
            return PostResponseResult(action=PostResponseAction.EXECUTED, exit_code=exit_code)
        else:
            if mode == "do":
                render_info("Cancelled")
            return PostResponseResult(action=PostResponseAction.CANCELLED, exit_code=0)

    return PostResponseResult(action=PostResponseAction.CONTINUE, exit_code=0)
