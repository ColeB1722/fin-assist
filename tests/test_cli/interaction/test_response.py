"""Tests for cli/interaction/response.py — unified post-response pipeline."""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from fin_assist.agents.metadata import AgentCardMeta
from fin_assist.cli.client import AgentResult
from fin_assist.cli.interaction.response import (
    PostResponseAction,
    PostResponseResult,
    handle_post_response,
)


def _make_result(
    output: str = "response",
    success: bool = True,
    context_id: str | None = "ctx-1",
    warnings: list[str] | None = None,
    metadata: dict | None = None,
    thinking: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        success=success,
        output=output,
        context_id=context_id,
        warnings=warnings or [],
        metadata=metadata or {},
        thinking=thinking or [],
    )


# ---------------------------------------------------------------------------
# PostResponseResult dataclass
# ---------------------------------------------------------------------------


class TestPostResponseResult:
    def test_default_exit_code_is_zero(self):
        r = PostResponseResult(action=PostResponseAction.CONTINUE)
        assert r.exit_code == 0

    def test_custom_exit_code(self):
        r = PostResponseResult(action=PostResponseAction.ERROR, exit_code=1)
        assert r.exit_code == 1


# ---------------------------------------------------------------------------
# PostResponseAction enum
# ---------------------------------------------------------------------------


class TestPostResponseAction:
    def test_all_values_present(self):
        expected = {"continue", "executed", "cancelled", "auth_required", "error"}
        actual = {a.value for a in PostResponseAction}
        assert actual == expected


# ---------------------------------------------------------------------------
# handle_post_response — auth required
# ---------------------------------------------------------------------------


class TestHandlePostResponseAuth:
    async def test_auth_required_returns_auth_action(self):
        result = _make_result(metadata={"auth_required": True})
        response = await handle_post_response(result)
        assert response.action == PostResponseAction.AUTH_REQUIRED
        assert response.exit_code == 1

    async def test_auth_required_renders_auth_message(self):
        result = _make_result(output="openai", metadata={"auth_required": True})
        with patch("fin_assist.cli.interaction.response.render_auth_required") as mock_render:
            await handle_post_response(result)
        mock_render.assert_called_once_with("openai")


# ---------------------------------------------------------------------------
# handle_post_response — error
# ---------------------------------------------------------------------------


class TestHandlePostResponseError:
    async def test_error_returns_error_action(self):
        result = _make_result(success=False, output="something broke")
        response = await handle_post_response(result)
        assert response.action == PostResponseAction.ERROR
        assert response.exit_code == 1


# ---------------------------------------------------------------------------
# handle_post_response — approval path
# ---------------------------------------------------------------------------


class TestHandlePostResponseApproval:
    async def test_approval_execute_returns_executed(self):
        from fin_assist.cli.interaction.approve import ApprovalAction

        result = _make_result(output="rm -rf /tmp/x")
        card_meta = AgentCardMeta(requires_approval=True)

        with (
            patch(
                "fin_assist.cli.interaction.response.run_approve_widget",
                new_callable=AsyncMock,
                return_value=ApprovalAction.EXECUTE,
            ),
            patch(
                "fin_assist.cli.interaction.response.execute_command",
                return_value=0,
            ) as mock_exec,
        ):
            response = await handle_post_response(result, card_meta, mode="do")

        assert response.action == PostResponseAction.EXECUTED
        assert response.exit_code == 0
        mock_exec.assert_called_once_with("rm -rf /tmp/x")

    async def test_approval_execute_propagates_exit_code(self):
        from fin_assist.cli.interaction.approve import ApprovalAction

        result = _make_result(output="false")
        card_meta = AgentCardMeta(requires_approval=True)

        with (
            patch(
                "fin_assist.cli.interaction.response.run_approve_widget",
                new_callable=AsyncMock,
                return_value=ApprovalAction.EXECUTE,
            ),
            patch(
                "fin_assist.cli.interaction.response.execute_command",
                return_value=1,
            ),
        ):
            response = await handle_post_response(result, card_meta)

        assert response.action == PostResponseAction.EXECUTED
        assert response.exit_code == 1

    async def test_approval_cancel_returns_cancelled(self):
        from fin_assist.cli.interaction.approve import ApprovalAction

        result = _make_result(output="rm -rf /")
        card_meta = AgentCardMeta(requires_approval=True)

        with patch(
            "fin_assist.cli.interaction.response.run_approve_widget",
            new_callable=AsyncMock,
            return_value=ApprovalAction.CANCEL,
        ):
            response = await handle_post_response(result, card_meta, mode="talk")

        assert response.action == PostResponseAction.CANCELLED
        assert response.exit_code == 0

    async def test_approval_cancel_in_do_mode_renders_cancelled(self):
        from fin_assist.cli.interaction.approve import ApprovalAction

        result = _make_result(output="rm -rf /")
        card_meta = AgentCardMeta(requires_approval=True)

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch(
                "fin_assist.cli.interaction.response.run_approve_widget",
                new_callable=AsyncMock,
                return_value=ApprovalAction.CANCEL,
            ),
            patch("fin_assist.cli.display.console", test_console),
        ):
            response = await handle_post_response(result, card_meta, mode="do")

        assert "Cancelled" in buf.getvalue()
        assert response.action == PostResponseAction.CANCELLED

    async def test_no_approval_when_not_required(self):
        result = _make_result()
        card_meta = AgentCardMeta(requires_approval=False)

        with patch(
            "fin_assist.cli.interaction.response.run_approve_widget",
        ) as mock_widget:
            response = await handle_post_response(result, card_meta)

        mock_widget.assert_not_called()
        assert response.action == PostResponseAction.CONTINUE

    async def test_no_approval_when_card_meta_is_none(self):
        result = _make_result()

        with patch(
            "fin_assist.cli.interaction.response.run_approve_widget",
        ) as mock_widget:
            response = await handle_post_response(result, None)

        mock_widget.assert_not_called()
        assert response.action == PostResponseAction.CONTINUE

    async def test_no_approval_on_failed_result(self):
        result = _make_result(success=False, output="error")
        card_meta = AgentCardMeta(requires_approval=True)

        with patch(
            "fin_assist.cli.interaction.response.run_approve_widget",
        ) as mock_widget:
            response = await handle_post_response(result, card_meta)

        mock_widget.assert_not_called()
        assert response.action == PostResponseAction.ERROR


# ---------------------------------------------------------------------------
# handle_post_response — rendering
# ---------------------------------------------------------------------------


class TestHandlePostResponseRendering:
    async def test_renders_output_via_render_agent_output(self):
        result = _make_result(output="hello world")
        card_meta = AgentCardMeta()

        with patch("fin_assist.cli.interaction.response.render_agent_output") as mock_render:
            await handle_post_response(result, card_meta, mode="talk")

        mock_render.assert_called_once_with(result, card_meta, show_thinking=False, mode="talk")

    async def test_passes_show_thinking_flag(self):
        result = _make_result(thinking=["hmm"])
        card_meta = AgentCardMeta()

        with patch("fin_assist.cli.interaction.response.render_agent_output") as mock_render:
            await handle_post_response(result, card_meta, show_thinking=True, mode="do")

        mock_render.assert_called_once_with(result, card_meta, show_thinking=True, mode="do")

    async def test_renders_with_card_meta_none(self):
        result = _make_result()

        with patch("fin_assist.cli.interaction.response.render_agent_output") as mock_render:
            await handle_post_response(result, None, mode="talk")

        mock_render.assert_called_once_with(result, None, show_thinking=False, mode="talk")
