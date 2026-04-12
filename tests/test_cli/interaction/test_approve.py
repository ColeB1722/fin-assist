"""Tests for cli/interaction/approve.py — approval widget and command execution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fin_assist.cli.interaction.approve import (
    ApprovalAction,
    _build_key_bindings,
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
    """Tests for the choice()-based approval widget."""

    async def test_execute_returns_execute_action(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(ApprovalAction.EXECUTE)
            mock_cls.return_value = mock_instance

            action = await run_approve_widget("ls -la")

        assert action == ApprovalAction.EXECUTE

    async def test_cancel_returns_cancel_action(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(ApprovalAction.CANCEL)
            mock_cls.return_value = mock_instance

            action = await run_approve_widget("ls -la")

        assert action == ApprovalAction.CANCEL

    async def test_ctrl_c_returns_cancel(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_raise(KeyboardInterrupt)
            mock_cls.return_value = mock_instance

            action = await run_approve_widget("ls")

        assert action == ApprovalAction.CANCEL

    async def test_choice_input_created_with_both_options(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(ApprovalAction.EXECUTE)
            mock_cls.return_value = mock_instance

            await run_approve_widget("ls")

            kwargs = mock_cls.call_args.kwargs
            values = [v for v, _label in kwargs["options"]]
            assert ApprovalAction.EXECUTE in values
            assert ApprovalAction.CANCEL in values

    async def test_default_is_execute(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(ApprovalAction.EXECUTE)
            mock_cls.return_value = mock_instance

            await run_approve_widget("ls")

            kwargs = mock_cls.call_args.kwargs
            assert kwargs["default"] == ApprovalAction.EXECUTE

    async def test_no_prompt_parameter(self):
        """run_approve_widget no longer accepts a prompt parameter."""
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            await run_approve_widget("ls", prompt=MagicMock())  # type: ignore[call-arg]


class TestBuildKeyBindings:
    """Tests for the extra key bindings (Escape, Ctrl+D)."""

    def test_returns_key_bindings(self):
        from prompt_toolkit.key_binding import KeyBindings

        kb = _build_key_bindings()
        assert isinstance(kb, KeyBindings)

    def test_has_escape_binding(self):
        kb = _build_key_bindings()
        keys = [b.keys for b in kb.bindings]
        assert ("escape",) in keys

    def test_has_ctrl_d_binding(self):
        kb = _build_key_bindings()
        keys = [b.keys for b in kb.bindings]
        assert ("c-d",) in keys


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


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _async_return(value):
    """Create an async callable that returns a value."""

    async def _inner():
        return value

    return _inner


def _async_raise(exc_type):
    """Create an async callable that raises an exception."""

    async def _inner():
        raise exc_type()

    return _inner
