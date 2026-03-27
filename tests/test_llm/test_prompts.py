from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fin_assist.context.base import ContextItem
from fin_assist.llm.prompts import SYSTEM_INSTRUCTIONS, build_user_message


class TestBuildUserMessage:
    def test_build_with_no_context(self) -> None:
        result = build_user_message("list files", context=None)
        assert "list files" in result
        assert "No context provided" in result
        assert "User request:" in result

    def test_build_with_empty_context(self) -> None:
        result = build_user_message("list files", context=[])
        assert "list files" in result
        assert "No context provided" in result

    def test_build_with_context(self) -> None:
        context_item = MagicMock(spec=ContextItem)
        context_item.content = "file1.py\nfile2.py"
        context_item.type = "file"

        result = build_user_message("search for function", context=[context_item])
        assert "search for function" in result
        assert "file1.py" in result
        assert "file2.py" in result
        assert "[FILE]" in result

    def test_context_items_joined(self) -> None:
        item1 = MagicMock(spec=ContextItem)
        item1.content = "content1"
        item1.type = "file"
        item2 = MagicMock(spec=ContextItem)
        item2.content = "content2"
        item2.type = "git_diff"

        result = build_user_message("do something", context=[item1, item2])
        assert "content1" in result
        assert "content2" in result
        assert "[FILE]" in result
        assert "[GIT_DIFF]" in result


class TestSystemInstructions:
    def test_system_instructions_exists(self) -> None:
        assert SYSTEM_INSTRUCTIONS is not None
        assert "shell command assistant" in SYSTEM_INSTRUCTIONS

    def test_system_instructions_contains_rules(self) -> None:
        assert "Output ONLY the command" in SYSTEM_INSTRUCTIONS
        assert "fish shell syntax" in SYSTEM_INSTRUCTIONS

    def test_system_instructions_no_template_placeholders(self) -> None:
        assert "{context}" not in SYSTEM_INSTRUCTIONS
        assert "{prompt}" not in SYSTEM_INSTRUCTIONS
