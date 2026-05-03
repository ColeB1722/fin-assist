from __future__ import annotations

from fin_assist.llm import SHELL_INSTRUCTIONS


class TestShellInstructions:
    def test_shell_instructions_exists(self) -> None:
        assert SHELL_INSTRUCTIONS is not None
        assert "shell command assistant" in SHELL_INSTRUCTIONS

    def test_shell_instructions_contains_rules(self) -> None:
        assert "Output ONLY the command" in SHELL_INSTRUCTIONS
        assert "fish shell syntax" in SHELL_INSTRUCTIONS

    def test_shell_instructions_no_template_placeholders(self) -> None:
        assert "{context}" not in SHELL_INSTRUCTIONS
        assert "{prompt}" not in SHELL_INSTRUCTIONS
