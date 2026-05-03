"""Tests for cli/interaction/prompt.py — FinPrompt widget."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.document import Document


class TestSlashCompleter:
    """SlashCompleter fuzzy-matches slash commands when input starts with /."""

    def _make_completer(self, agents: list[str] | None = None):
        from fin_assist.cli.interaction.prompt import SLASH_COMMANDS, SlashCompleter

        return SlashCompleter(SLASH_COMMANDS, agents or [])

    def test_yields_exit_for_exact_prefix(self):
        completer = self._make_completer()
        doc = Document("/ex", cursor_position=3)
        results = list(completer.get_completions(doc, MagicMock()))
        texts = [c.text for c in results]
        # /exit should be ranked first; others may or may not appear under cutoff.
        assert texts[0] == "/exit"

    def test_yields_nothing_for_plain_text(self):
        completer = self._make_completer()
        doc = Document("hello", cursor_position=5)
        assert list(completer.get_completions(doc, MagicMock())) == []

    def test_yields_nothing_for_empty_input(self):
        completer = self._make_completer()
        doc = Document("", cursor_position=0)
        assert list(completer.get_completions(doc, MagicMock())) == []

    def test_yields_all_commands_for_bare_slash(self):
        completer = self._make_completer()
        doc = Document("/", cursor_position=1)
        texts = [c.text for c in completer.get_completions(doc, MagicMock())]
        assert "/exit" in texts
        assert "/help" in texts
        assert "/sessions" in texts

    def test_yields_nothing_when_slash_not_at_start(self):
        completer = self._make_completer()
        doc = Document("hello /ex", cursor_position=9)
        assert list(completer.get_completions(doc, MagicMock())) == []

    def test_handles_leading_whitespace_before_slash(self):
        completer = self._make_completer()
        doc = Document("  /ex", cursor_position=5)
        texts = [c.text for c in completer.get_completions(doc, MagicMock())]
        assert "/exit" in texts

    def test_fuzzy_matches_typos(self):
        """rapidfuzz should still rank /help first for /hlp."""
        completer = self._make_completer()
        doc = Document("/hlp", cursor_position=4)
        texts = [c.text for c in completer.get_completions(doc, MagicMock())]
        assert texts[0] == "/help"

    def test_includes_agent_names(self):
        completer = self._make_completer(agents=["shell", "coder"])
        doc = Document("/sh", cursor_position=3)
        texts = [c.text for c in completer.get_completions(doc, MagicMock())]
        assert "shell" in texts


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
        mock_session.prompt_async.assert_called_once_with("> ", default="")

    async def test_ask_passes_default_to_prompt_async(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="edited prompt")

        with patch("fin_assist.cli.interaction.prompt.PromptSession", return_value=mock_session):
            result = await fp.ask("> ", default="original prompt")

        assert result == "edited prompt"
        mock_session.prompt_async.assert_called_once_with("> ", default="original prompt")

    async def test_ask_default_none_passes_empty_string(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="typed input")

        with patch("fin_assist.cli.interaction.prompt.PromptSession", return_value=mock_session):
            result = await fp.ask("> ", default=None)

        assert result == "typed input"
        mock_session.prompt_async.assert_called_once_with("> ", default="")

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

    def test_context_settings_stored(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt(context_settings=MagicMock())
        assert fp.context_settings is not None


class TestSkillCompleter:
    def _make_completer(self, skills: list[tuple[str, str]] | None = None):
        from fin_assist.cli.interaction.prompt import SkillCompleter

        return SkillCompleter(skills or [("commit", "Generate a commit"), ("pr", "Create a PR")])

    def test_yields_nothing_without_skill_prefix(self):
        completer = self._make_completer()
        doc = Document("hello", cursor_position=5)
        assert list(completer.get_completions(doc, MagicMock())) == []

    def test_yields_matching_skill_for_prefix(self):
        completer = self._make_completer()
        doc = Document("/skill:com", cursor_position=10)
        results = list(completer.get_completions(doc, MagicMock()))
        texts = [c.text for c in results]
        assert "commit" in texts

    def test_yields_all_skills_for_empty_prefix(self):
        completer = self._make_completer()
        doc = Document("/skill:", cursor_position=7)
        texts = [c.text for c in completer.get_completions(doc, MagicMock())]
        assert "commit" in texts
        assert "pr" in texts

    def test_fuzzy_matches_partial_name(self):
        completer = self._make_completer(
            [("commit", "Commit changes"), ("summarize", "Summarize text")]
        )
        doc = Document("/skill:sum", cursor_position=10)
        texts = [c.text for c in completer.get_completions(doc, MagicMock())]
        assert texts[0] == "summarize"

    def test_yields_nothing_for_no_skills(self):
        from fin_assist.cli.interaction.prompt import SkillCompleter

        completer = SkillCompleter([])
        doc = Document("/skill:com", cursor_position=10)
        assert list(completer.get_completions(doc, MagicMock())) == []

    def test_skill_description_as_display_meta(self):
        completer = self._make_completer([("commit", "Generate a conventional commit")])
        doc = Document("/skill:commit", cursor_position=13)
        results = list(completer.get_completions(doc, MagicMock()))
        assert len(results) > 0
        meta_text = str(results[0].display_meta)
        assert "Generate a conventional commit" in meta_text


class TestFinPromptSkills:
    def test_skills_default_to_empty_list(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        fp = FinPrompt()
        assert fp._skills == []

    def test_skills_are_stored(self):
        from fin_assist.cli.interaction.prompt import FinPrompt

        skills = [("commit", "Generate a commit"), ("pr", "Create a PR")]
        fp = FinPrompt(skills=skills)
        assert fp._skills == skills
