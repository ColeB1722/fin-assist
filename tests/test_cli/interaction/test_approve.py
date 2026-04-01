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
        assert ApprovalAction.EDIT == "edit"
        assert ApprovalAction.CANCEL == "cancel"

    def test_is_str_enum(self):
        from enum import StrEnum

        assert issubclass(ApprovalAction, StrEnum)


class TestRunApproveWidget:
    async def test_execute_returns_execute_action(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        action, edited = await run_approve_widget("ls -la", prompt=mock_fp)

        assert action == ApprovalAction.EXECUTE
        assert edited is None

    async def test_cancel_returns_cancel_action(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="cancel")

        action, edited = await run_approve_widget("ls -la", prompt=mock_fp)

        assert action == ApprovalAction.CANCEL
        assert edited is None

    async def test_regenerate_returns_edit_with_original_prompt(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="regenerate")

        action, edited = await run_approve_widget(
            "rm -rf /",
            supports_regenerate=True,
            regenerate_prompt="delete everything",
            prompt=mock_fp,
        )

        assert action == ApprovalAction.EDIT
        assert edited == "delete everything"

    async def test_regenerate_loops_when_no_prompt(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["regenerate", "execute"])

        action, edited = await run_approve_widget(
            "ls",
            supports_regenerate=True,
            regenerate_prompt=None,
            prompt=mock_fp,
        )

        assert action == ApprovalAction.EXECUTE
        assert mock_fp.ask.call_count == 2

    async def test_regenerate_not_in_options_when_disabled(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        await run_approve_widget("ls", supports_regenerate=False, prompt=mock_fp)

        call_args = mock_fp.ask.call_args[0][0]
        assert "regenerate" not in call_args
        assert "execute" in call_args
        assert "cancel" in call_args

    async def test_regenerate_in_options_when_enabled(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        await run_approve_widget("ls", supports_regenerate=True, prompt=mock_fp)

        call_args = mock_fp.ask.call_args[0][0]
        assert "regenerate" in call_args

    async def test_unknown_input_loops(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["unknown", "execute"])

        action, edited = await run_approve_widget("ls", prompt=mock_fp)

        assert action == ApprovalAction.EXECUTE
        assert mock_fp.ask.call_count == 2

    async def test_empty_input_loops(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["", "execute"])

        action, edited = await run_approve_widget("ls", prompt=mock_fp)

        assert action == ApprovalAction.EXECUTE
        assert mock_fp.ask.call_count == 2

    async def test_creates_finprompt_if_not_provided(self):
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="execute")

        with patch(
            "fin_assist.cli.interaction.approve.FinPrompt", return_value=mock_fp
        ) as mock_init:
            action, edited = await run_approve_widget("ls")
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
