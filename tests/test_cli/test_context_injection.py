"""Tests for @-completion and resolve_at_references in cli/interaction/prompt.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from prompt_toolkit.document import Document

from fin_assist.context.base import ContextItem


class TestAtCompleter:
    """AtCompleter only yields completions when input contains @."""

    def _make_completer(self):
        from fin_assist.cli.interaction.prompt import AtCompleter

        return AtCompleter(context_settings=None)

    def test_yields_context_types_for_bare_at(self):
        from fin_assist.cli.interaction.prompt import _AT_CONTEXT_TYPES

        completer = self._make_completer()
        doc = Document("@", cursor_position=1)
        results = list(completer.get_completions(doc, MagicMock()))
        texts = [c.text for c in results]
        for name in _AT_CONTEXT_TYPES:
            assert name in texts

    def test_yields_nothing_without_at(self):
        completer = self._make_completer()
        doc = Document("hello", cursor_position=5)
        results = list(completer.get_completions(doc, MagicMock()))
        assert results == []

    def test_filters_by_prefix_after_at(self):
        completer = self._make_completer()
        doc = Document("@gi", cursor_position=3)
        results = list(completer.get_completions(doc, MagicMock()))
        texts = [c.text for c in results]
        assert "git:diff" in texts
        assert "git:log" in texts
        assert "file:" not in texts

    def test_yields_file_completions_after_file_prefix(self):
        completer = self._make_completer()
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.search_paths.return_value = ["src/main.py", "src/util.py"]
            doc = Document("@file:src/", cursor_position=10)
            results = list(completer.get_completions(doc, MagicMock()))

        texts = [c.text for c in results]
        assert "src/main.py" in texts
        assert "src/util.py" in texts

    def test_all_paths_shown_in_completion(self):
        completer = self._make_completer()
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.search_paths.return_value = ["ok.py", "bad.py"]
            doc = Document("@file:", cursor_position=6)
            results = list(completer.get_completions(doc, MagicMock()))

        texts = [c.text for c in results]
        assert "ok.py" in texts
        assert "bad.py" in texts


class TestResolveAtReferences:
    """resolve_at_references replaces @type:ref tokens with context content."""

    def test_returns_text_unchanged_when_no_at_refs(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        assert resolve_at_references("hello world") == "hello world"

    def test_unknown_at_type_left_as_is(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        result = resolve_at_references("check @unknown:thing")
        assert "@unknown:thing" in result

    def test_resolves_file_reference(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        mock_item = ContextItem(
            id="test.py", type="file", content="print('hi')", status="available"
        )
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = resolve_at_references("explain @file:test.py")

        assert "[FILE: test.py]" in result
        assert "print('hi')" in result
        assert "explain" in result

    def test_resolves_git_diff_reference(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        mock_item = ContextItem(
            id="git_diff", type="git_diff", content="diff --git a/file", status="available"
        )
        with patch("fin_assist.context.git.GitContext") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = resolve_at_references("review @git:diff")

        assert "[GIT DIFF]" in result
        assert "diff --git a/file" in result
        assert "review" in result

    def test_resolves_git_log_reference(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        mock_item = ContextItem(
            id="git_log", type="git_log", content="abc123 commit msg", status="available"
        )
        with patch("fin_assist.context.git.GitContext") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = resolve_at_references("@git:log recent changes")

        assert "[GIT LOG]" in result
        assert "abc123 commit msg" in result
        assert "recent changes" in result

    def test_resolves_history_reference(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        items = [
            ContextItem(id="0", type="history", content="git status", status="available"),
            ContextItem(id="1", type="history", content="ls -la", status="available"),
        ]
        with patch("fin_assist.context.history.ShellHistory") as mock_cls:
            mock_cls.return_value.get_all.return_value = items
            result = resolve_at_references("@history: similar to")

        assert "[SHELL HISTORY]" in result
        assert "git status" in result
        assert "ls -la" in result

    def test_resolves_history_with_query(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        items = [
            ContextItem(id="0", type="history", content="git commit", status="available"),
        ]
        with patch("fin_assist.context.history.ShellHistory") as mock_cls:
            mock_cls.return_value.search.return_value = items
            result = resolve_at_references("@history:commit what did I do")

        mock_cls.return_value.search.assert_called_once_with("commit")
        assert "[SHELL HISTORY]" in result

    def test_handles_missing_file_gracefully(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        mock_item = ContextItem(
            id="missing.py", type="file", content="", status="not_found", error_reason="not found"
        )
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = resolve_at_references("explain @file:missing.py")

        assert "[FILE: missing.py] Error:" in result

    def test_multiple_refs_resolved(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        file_item = ContextItem(id="a.py", type="file", content="code_a", status="available")
        diff_item = ContextItem(id="git_diff", type="git_diff", content="diff", status="available")
        with (
            patch("fin_assist.context.files.FileFinder") as file_cls,
            patch("fin_assist.context.git.GitContext") as git_cls,
        ):
            file_cls.return_value.get_item.return_value = file_item
            git_cls.return_value.get_item.return_value = diff_item
            result = resolve_at_references("review @file:a.py and @git:diff")

        assert "[FILE: a.py]" in result
        assert "[GIT DIFF]" in result
        assert "code_a" in result
        assert "review" in result

    def test_prompt_only_text_preserved_when_all_refs_resolved(self):
        from fin_assist.cli.interaction.prompt import resolve_at_references

        mock_item = ContextItem(id="f.py", type="file", content="code", status="available")
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = resolve_at_references("explain @file:f.py")

        assert "Context:" in result
        assert "User request:" in result
