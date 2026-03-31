"""Tests for cli/interaction/approve.py — approval widget and command execution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
    def test_execute_returns_execute_action(self):
        with patch("fin_assist.cli.interaction.approve.Prompt.ask", return_value="execute"):
            action, edited = run_approve_widget("ls -la")

        assert action == ApprovalAction.EXECUTE
        assert edited is None

    def test_cancel_returns_cancel_action(self):
        with patch("fin_assist.cli.interaction.approve.Prompt.ask", return_value="cancel"):
            action, edited = run_approve_widget("ls -la")

        assert action == ApprovalAction.CANCEL
        assert edited is None

    def test_regenerate_returns_edit_with_original_prompt(self):
        with patch("fin_assist.cli.interaction.approve.Prompt.ask", return_value="regenerate"):
            action, edited = run_approve_widget(
                "rm -rf /",
                supports_regenerate=True,
                regenerate_prompt="delete everything",
            )

        assert action == ApprovalAction.EDIT
        assert edited == "delete everything"

    def test_regenerate_loops_when_no_prompt(self):
        """If regenerate has no prompt, it should loop — so provide execute on second call."""
        call_count = 0

        def mock_ask(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "regenerate"
            return "execute"

        with patch("fin_assist.cli.interaction.approve.Prompt.ask", side_effect=mock_ask):
            action, edited = run_approve_widget(
                "ls",
                supports_regenerate=True,
                regenerate_prompt=None,  # no prompt → loops
            )

        assert action == ApprovalAction.EXECUTE
        assert call_count == 2

    def test_regenerate_not_in_options_when_disabled(self):
        """With supports_regenerate=False, only execute/cancel are choices."""
        captured_choices = []

        def mock_ask(*args, **kwargs):
            captured_choices.extend(kwargs.get("choices", []))
            return "execute"

        with patch("fin_assist.cli.interaction.approve.Prompt.ask", side_effect=mock_ask):
            run_approve_widget("ls", supports_regenerate=False)

        assert "regenerate" not in captured_choices
        assert "execute" in captured_choices
        assert "cancel" in captured_choices

    def test_regenerate_in_options_when_enabled(self):
        captured_choices = []

        def mock_ask(*args, **kwargs):
            captured_choices.extend(kwargs.get("choices", []))
            return "execute"

        with patch("fin_assist.cli.interaction.approve.Prompt.ask", side_effect=mock_ask):
            run_approve_widget("ls", supports_regenerate=True)

        assert "regenerate" in captured_choices


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
