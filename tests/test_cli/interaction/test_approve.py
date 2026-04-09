"""Tests for cli/interaction/approve.py — approval widget and command execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.cli.interaction.approve import (
    ApprovalAction,
    execute_command,
    run_approve_widget,
)


class TestApprovalAction:
    def test_values_are_strings(self):
        assert ApprovalAction.EXECUTE == "execute"
        assert ApprovalAction.CANCEL == "cancel"

    def test_is_str_enum(self):
        from enum import StrEnum

        assert issubclass(ApprovalAction, StrEnum)


class TestRunApproveWidget:
    async def test_execute_returns_execute_action(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        action = await run_approve_widget("ls -la", prompt=mock_fp)

        assert action == ApprovalAction.EXECUTE

    async def test_cancel_returns_cancel_action(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="cancel")

        action = await run_approve_widget("ls -la", prompt=mock_fp)

        assert action == ApprovalAction.CANCEL

    async def test_unknown_input_loops(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["unknown", "execute"])

        action = await run_approve_widget("ls", prompt=mock_fp)

        assert action == ApprovalAction.EXECUTE
        assert mock_fp.ask.call_count == 2

    async def test_empty_input_loops(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["", "execute"])

        action = await run_approve_widget("ls", prompt=mock_fp)

        assert action == ApprovalAction.EXECUTE
        assert mock_fp.ask.call_count == 2

    async def test_ctrl_c_returns_cancel(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=KeyboardInterrupt)

        action = await run_approve_widget("ls", prompt=mock_fp)

        assert action == ApprovalAction.CANCEL

    async def test_ctrl_d_returns_cancel(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=EOFError)

        action = await run_approve_widget("ls", prompt=mock_fp)

        assert action == ApprovalAction.CANCEL

    async def test_prompt_text_has_no_rich_markup(self):
        """Prompt text passed to FinPrompt.ask() must not contain Rich markup tags
        because prompt_toolkit doesn't render them — they'd appear as literal text."""
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        await run_approve_widget("ls", prompt=mock_fp)

        prompt_text = mock_fp.ask.call_args[0][0]
        assert "[bold]" not in prompt_text
        assert "[/bold]" not in prompt_text

    async def test_prompt_shows_execute_and_cancel_options(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        await run_approve_widget("ls", prompt=mock_fp)

        prompt_text = mock_fp.ask.call_args[0][0]
        assert "execute" in prompt_text
        assert "cancel" in prompt_text

    async def test_creates_finprompt_if_not_provided(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        with patch(
            "fin_assist.cli.interaction.approve.FinPrompt", return_value=mock_fp
        ) as mock_init:
            action = await run_approve_widget("ls")
            mock_init.assert_called_once()

        assert action == ApprovalAction.EXECUTE


class TestExecuteCommand:
    def test_returns_exit_code_zero_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("fin_assist.cli.interaction.approve.subprocess.run", return_value=mock_result):
            code = execute_command("ls -la")

        assert code == 0

    def test_returns_nonzero_exit_code_on_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("fin_assist.cli.interaction.approve.subprocess.run", return_value=mock_result):
            code = execute_command("false")

        assert code == 1

    def test_runs_command_with_shell_true(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch(
            "fin_assist.cli.interaction.approve.subprocess.run", return_value=mock_result
        ) as mock_run:
            execute_command("echo hello")

        mock_run.assert_called_once_with("echo hello", shell=True)
