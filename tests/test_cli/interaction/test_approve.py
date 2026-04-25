"""Tests for cli/interaction/approve.py — approval widget for deferred tool calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fin_assist.cli.interaction.approve import (
    _build_key_bindings,
    run_approval_widget,
)


def _sample_deferred_calls() -> list[dict]:
    return [
        {
            "tool_name": "run_shell",
            "tool_call_id": "call_1",
            "args": {"command": "rm -rf /tmp/x"},
            "reason": "Shell command execution requires approval",
        }
    ]


class TestRunApprovalWidget:
    async def test_approve_returns_decisions(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(True)
            mock_cls.return_value = mock_instance

            decisions = await run_approval_widget(_sample_deferred_calls())

        assert decisions is not None
        assert len(decisions) == 1
        assert decisions[0]["tool_call_id"] == "call_1"
        assert decisions[0]["approved"] is True

    async def test_deny_returns_decisions_with_reason(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(False)
            mock_cls.return_value = mock_instance

            decisions = await run_approval_widget(_sample_deferred_calls())

        assert decisions is not None
        assert len(decisions) == 1
        assert decisions[0]["approved"] is False
        assert decisions[0]["denial_reason"] == "Denied by user"

    async def test_ctrl_c_returns_none(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_raise(KeyboardInterrupt)
            mock_cls.return_value = mock_instance

            decisions = await run_approval_widget(_sample_deferred_calls())

        assert decisions is None

    async def test_default_is_approve(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(True)
            mock_cls.return_value = mock_instance

            await run_approval_widget(_sample_deferred_calls())

            kwargs = mock_cls.call_args.kwargs
            assert kwargs["default"] is True

    async def test_denial_reason_in_decision(self):
        with patch("fin_assist.cli.interaction.approve.ChoiceInput") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.prompt_async = _async_return(False)
            mock_cls.return_value = mock_instance

            decisions = await run_approval_widget(_sample_deferred_calls())

        assert decisions is not None
        assert decisions[0]["denial_reason"] == "Denied by user"


class TestBuildKeyBindings:
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


def _async_return(value):
    async def _inner():
        return value

    return _inner


def _async_raise(exc_type):
    async def _inner():
        raise exc_type()

    return _inner
