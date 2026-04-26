"""Tests for output type and system prompt registries."""

from __future__ import annotations

from fin_assist.agents.registry import OUTPUT_TYPES, SYSTEM_PROMPTS
from fin_assist.agents.results import CommandResult


class TestOutputTypes:
    def test_text_maps_to_str(self) -> None:
        assert OUTPUT_TYPES["text"] is str

    def test_command_maps_to_command_result(self) -> None:
        assert OUTPUT_TYPES["command"] is CommandResult

    def test_has_expected_keys(self) -> None:
        assert set(OUTPUT_TYPES.keys()) == {"text", "command"}


class TestSystemPrompts:
    def test_chain_of_thought_exists(self) -> None:
        assert "chain-of-thought" in SYSTEM_PROMPTS

    def test_shell_exists(self) -> None:
        assert "shell" in SYSTEM_PROMPTS

    def test_test_exists(self) -> None:
        assert "test" in SYSTEM_PROMPTS

    def test_chain_of_thought_is_non_empty(self) -> None:
        assert len(SYSTEM_PROMPTS["chain-of-thought"]) > 0

    def test_shell_is_non_empty(self) -> None:
        assert len(SYSTEM_PROMPTS["shell"]) > 0

    def test_test_is_non_empty(self) -> None:
        assert len(SYSTEM_PROMPTS["test"]) > 0

    def test_has_expected_keys(self) -> None:
        assert set(SYSTEM_PROMPTS.keys()) == {"chain-of-thought", "shell", "test"}
