"""Tests for cli/interaction/response.py — unified post-response pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from fin_assist.agents.metadata import AgentResult
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
    auth_required: bool = False,
) -> AgentResult:
    return AgentResult(
        success=success,
        output=output,
        context_id=context_id,
        warnings=warnings or [],
        metadata=metadata or {},
        thinking=thinking or [],
        auth_required=auth_required,
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
        expected = {"continue", "auth_required", "error"}
        actual = {a.value for a in PostResponseAction}
        assert actual == expected


# ---------------------------------------------------------------------------
# handle_post_response — auth required
# ---------------------------------------------------------------------------


class TestHandlePostResponseAuth:
    async def test_auth_required_returns_auth_action(self):
        result = _make_result(auth_required=True)
        response = await handle_post_response(result)
        assert response.action == PostResponseAction.AUTH_REQUIRED
        assert response.exit_code == 1

    async def test_auth_required_renders_auth_message(self):
        result = _make_result(output="openai", auth_required=True)
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
# handle_post_response — rendering
# ---------------------------------------------------------------------------


class TestHandlePostResponseRendering:
    async def test_no_rendering_call_for_continue(self):
        result = _make_result(output="hello world")

        response = await handle_post_response(result)

        assert response.action == PostResponseAction.CONTINUE

    async def test_no_rendering_call_with_card_meta_none(self):
        result = _make_result()

        response = await handle_post_response(result)

        assert response.action == PostResponseAction.CONTINUE
