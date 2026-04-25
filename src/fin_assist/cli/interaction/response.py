"""Unified post-response pipeline: auth and error handling.

Every code path that receives an ``AgentResult`` — one-shot (``do``) or
multi-turn (``talk``) — needs the same sequence of concerns handled:

1. Auth-required detection
2. Error handling

Approval is now handled in-flight via the deferred tool flow (Phase C),
not post-response.  ``render_stream`` and the chat loop handle the
``input_required`` event by showing the approval widget and resuming.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.console import Console

from fin_assist.cli.display import (
    render_auth_required,
    render_error,
)

if TYPE_CHECKING:
    from fin_assist.agents.metadata import AgentCardMeta, AgentResult

console = Console()


class PostResponseAction(StrEnum):
    """What happened after processing the agent's response."""

    CONTINUE = "continue"
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
) -> PostResponseResult:
    """Run the post-response pipeline and return what happened.

    Args:
        result: The ``AgentResult`` to process.
        card_meta: Agent capability metadata.  ``None`` is safe.
    """
    if result.auth_required:
        render_auth_required(result.output)
        return PostResponseResult(action=PostResponseAction.AUTH_REQUIRED, exit_code=1)

    if not result.success:
        render_error(result.output or "Unknown error")
        return PostResponseResult(action=PostResponseAction.ERROR, exit_code=1)

    return PostResponseResult(action=PostResponseAction.CONTINUE, exit_code=0)
