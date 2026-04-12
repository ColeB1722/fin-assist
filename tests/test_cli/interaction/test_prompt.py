"""Tests for cli/interaction/prompt.py — FinPrompt widget."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.document import Document


class TestSlashCompleter:
    """SlashCompleter only yields completions when input starts with /."""

    def _make_completer(self):
        from fin_assist.cli.interaction.prompt import SlashCompleter

        inner = MagicMock()
        inner.get_completions = MagicMock(return_value=[MagicMock(text="/exit")])
        return SlashCompleter(inner), inner

    def test_yields_completions_when_slash_prefix(self):
        completer, inner = self._make_completer()
        doc = Document("/ex", cursor_position=3)
        results = list(completer.get_completions(doc, MagicMock()))
        assert len(results) == 1
        inner.get_completions.assert_called_once()

    def test_yields_nothing_for_plain_text(self):
        completer, inner = self._make_completer()
        doc = Document("hello", cursor_position=5)
        results = list(completer.get_completions(doc, MagicMock()))
        assert results == []
        inner.get_completions.assert_not_called()

    def test_yields_nothing_for_empty_input(self):
        completer, inner = self._make_completer()
        doc = Document("", cursor_position=0)
        results = list(completer.get_completions(doc, MagicMock()))
        assert results == []
        inner.get_completions.assert_not_called()

    def test_yields_completions_for_bare_slash(self):
        completer, inner = self._make_completer()
        doc = Document("/", cursor_position=1)
        results = list(completer.get_completions(doc, MagicMock()))
        assert len(results) == 1
        inner.get_completions.assert_called_once()

    def test_yields_nothing_when_slash_not_at_start(self):
        completer, inner = self._make_completer()
        doc = Document("hello /ex", cursor_position=9)
        results = list(completer.get_completions(doc, MagicMock()))
        assert results == []
        inner.get_completions.assert_not_called()

    def test_handles_leading_whitespace_before_slash(self):
        completer, inner = self._make_completer()
        doc = Document("  /ex", cursor_position=5)
        results = list(completer.get_completions(doc, MagicMock()))
        assert len(results) == 1
        inner.get_completions.assert_called_once()


class TestSlashCommand:
    def test_frozen(self):
        from fin_assist.cli.interaction.prompt import SlashCommand

        cmd = SlashCommand("/exit", "End the conversation")
        with pytest.raises(AttributeError):
            cmd.name = "/changed"


class TestSlashCommandsRegistry:
    def test_slash_commands_are_defined(self):
        from fin_assist.cli.interaction.prompt import SLASH_COMMANDS

        names = [cmd.name for cmd in SLASH_COMMANDS]
        assert "/exit" in names
        assert "/help" in names
        assert "/sessions" in names

    def test_all_commands_have_descriptions(self):
        from fin_assist.cli.interaction.prompt import SLASH_COMMANDS

        for cmd in SLASH_COMMANDS:
            assert cmd.description, f"{cmd.name} is missing a description"


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
