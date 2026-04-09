"""Tests for cli/interaction/prompt.py — FinPrompt widget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFinPromptSlashCommands:
    def test_slash_commands_are_defined(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        assert hasattr(FinPrompt, "SLASH_COMMANDS")
        assert "/exit" in FinPrompt.SLASH_COMMANDS
        assert "/quit" in FinPrompt.SLASH_COMMANDS
        assert "/q" in FinPrompt.SLASH_COMMANDS
        assert "/switch" in FinPrompt.SLASH_COMMANDS
        assert "/help" in FinPrompt.SLASH_COMMANDS


class TestFinPromptAsk:
    async def test_ask_returns_user_input(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="hello world")

        with patch("fin_assist.cli.interaction.prompt.PromptSession", return_value=mock_session):
            result = await fp.ask("> ")

        assert result == "hello world"
        mock_session.prompt_async.assert_called_once_with("> ")

    async def test_ask_propagates_keyboard_interrupt(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(side_effect=KeyboardInterrupt)

        with patch("fin_assist.cli.interaction.prompt.PromptSession", return_value=mock_session):
            with pytest.raises(KeyboardInterrupt):
                await fp.ask("> ")

    async def test_ask_propagates_eof_error(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(side_effect=EOFError)

        with patch("fin_assist.cli.interaction.prompt.PromptSession", return_value=mock_session):
            with pytest.raises(EOFError):
                await fp.ask("> ")


class TestFinPromptHistory:
    def test_history_path_is_configurable(self, tmp_path):
        from fin_assist.cli.interaction.prompt import FinPrompt

        custom_path = tmp_path / "custom_history"
        fp = FinPrompt(history_path=custom_path)

        assert fp.history_path == custom_path

    def test_default_history_path_uses_fin_share(self):
        from fin_assist.cli.interaction.prompt import FinPrompt, HISTORY_PATH

        fp = FinPrompt()
        assert fp.history_path == HISTORY_PATH


class TestFinPromptAgents:
    def test_agents_are_configurable(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt(agents=["shell", "default"])
        assert fp.agents == ["shell", "default"]

    def test_agents_default_to_empty_list(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        assert fp.agents == []
