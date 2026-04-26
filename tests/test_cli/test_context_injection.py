"""Tests for _inject_context helper and CLI --file/--git-diff flags."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from fin_assist.cli.main import _inject_context
from fin_assist.context.base import ContextItem


class TestInjectContextNoFlags:
    def test_returns_prompt_unchanged_when_no_flags(self) -> None:
        assert _inject_context("hello") == "hello"

    def test_returns_prompt_unchanged_when_empty_lists(self) -> None:
        assert _inject_context("hello", files=[], git_diff=False) == "hello"


class TestInjectContextFileFlag:
    def test_prepends_file_content(self) -> None:
        mock_item = ContextItem(
            id="test.py", type="file", content="print('hi')", status="available"
        )
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = _inject_context("explain this", files=["test.py"])

        assert "[FILE: test.py]" in result
        assert "print('hi')" in result
        assert "explain this" in result

    def test_handles_missing_file(self) -> None:
        mock_item = ContextItem(
            id="missing.py",
            type="file",
            content="",
            status="not_found",
            error_reason="file does not exist",
        )
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = _inject_context("explain", files=["missing.py"])

        assert "Error:" in result
        assert "explain" in result

    def test_multiple_files(self) -> None:
        items = {
            "a.py": ContextItem(id="a.py", type="file", content="code_a", status="available"),
            "b.py": ContextItem(id="b.py", type="file", content="code_b", status="available"),
        }
        with patch("fin_assist.context.files.FileFinder") as mock_cls:
            mock_cls.return_value.get_item = lambda path: items[path]
            result = _inject_context("review", files=["a.py", "b.py"])

        assert "[FILE: a.py]" in result
        assert "[FILE: b.py]" in result
        assert "code_a" in result
        assert "code_b" in result


class TestInjectContextGitDiff:
    def test_prepends_git_diff(self) -> None:
        mock_item = ContextItem(
            id="git_diff", type="git_diff", content="diff --git a/file", status="available"
        )
        with patch("fin_assist.context.git.GitContext") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = _inject_context("review changes", git_diff=True)

        assert "[GIT DIFF]" in result
        assert "diff --git a/file" in result
        assert "review changes" in result

    def test_handles_git_error(self) -> None:
        mock_item = ContextItem(
            id="git_diff",
            type="git_diff",
            content="",
            status="error",
            error_reason="git_not_available",
        )
        with patch("fin_assist.context.git.GitContext") as mock_cls:
            mock_cls.return_value.get_item.return_value = mock_item
            result = _inject_context("review", git_diff=True)

        assert "Error:" in result

    def test_git_diff_false_does_not_inject(self) -> None:
        result = _inject_context("hello", git_diff=False)
        assert "[GIT DIFF]" not in result


class TestInjectContextCombined:
    def test_file_and_git_diff_together(self) -> None:
        file_item = ContextItem(id="f.py", type="file", content="code", status="available")
        diff_item = ContextItem(id="git_diff", type="git_diff", content="diff", status="available")
        with (
            patch("fin_assist.context.files.FileFinder") as file_cls,
            patch("fin_assist.context.git.GitContext") as git_cls,
        ):
            file_cls.return_value.get_item.return_value = file_item
            git_cls.return_value.get_item.return_value = diff_item
            result = _inject_context("explain", files=["f.py"], git_diff=True)

        assert "[FILE: f.py]" in result
        assert "[GIT DIFF]" in result
        assert "explain" in result
