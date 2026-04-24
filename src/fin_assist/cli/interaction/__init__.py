"""Interaction widgets for CLI client."""

from fin_assist.cli.interaction.approve import ApprovalAction, execute_command, run_approve_widget
from fin_assist.cli.interaction.chat import run_chat_loop
from fin_assist.cli.interaction.response import (
    PostResponseAction,
    PostResponseResult,
    handle_post_response,
)
from fin_assist.cli.interaction.streaming import render_stream

__all__ = [
    "ApprovalAction",
    "PostResponseAction",
    "PostResponseResult",
    "execute_command",
    "handle_post_response",
    "render_stream",
    "run_approve_widget",
    "run_chat_loop",
]
