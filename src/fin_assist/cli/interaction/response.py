"""Unified post-response pipeline: auth, error handling, and approval.

Every code path that receives an ``AgentResult`` — one-shot (``do``) or
multi-turn (``talk``) — needs the same sequence of concerns handled:

1. Auth-required detection
2. Error handling
3. Approval widget (for agents that ``requires_approval``)

Output rendering (thinking, command/text, warnings) is handled by
``render_stream`` during streaming; ``handle_post_response`` is responsible
only for auth/error/approval — concerns that cannot be rendered progressively.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.console import Console

from fin_assist.cli.display import (
    render_auth_required,
    render_error,
    render_info,
)
from fin_assist.cli.interaction.approve import ApprovalAction, execute_command, run_approve_widget

if TYPE_CHECKING:
    from fin_assist.agents.metadata import AgentCardMeta, AgentResult

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
    mode: str = "talk",
) -> PostResponseResult:
    """Run the post-response pipeline and return what happened.

    Args:
        result: The ``AgentResult`` to process.
        card_meta: Agent capability metadata.  ``None`` is safe — approval
            widget is skipped.
        mode: ``"do"`` or ``"talk"`` — controls whether a "Cancelled" info
            message is printed on approval rejection.
    """
    if result.auth_required:
        render_auth_required(result.output)
        return PostResponseResult(action=PostResponseAction.AUTH_REQUIRED, exit_code=1)

    if not result.success:
        render_error(result.output or "Unknown error")
        return PostResponseResult(action=PostResponseAction.ERROR, exit_code=1)

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
