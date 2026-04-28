"""Named registries for output types and system prompts.

These registries allow agent configuration (TOML) to reference types and
prompts by name rather than Python class paths.  The ``Agent`` class resolves
them at construction time.
"""

from __future__ import annotations

from typing import Literal

from fin_assist.agents.results import CommandResult

OutputTypeName = Literal["text", "command"]

OUTPUT_TYPES: dict[str, type] = {
    "text": str,
    "command": CommandResult,
}

PromptName = Literal[
    "chain-of-thought", "shell", "test", "git", "git-commit", "git-pr", "git-summarize"
]

SYSTEM_PROMPTS: dict[str, str] = {}


def _init_prompts() -> None:
    from fin_assist.llm.prompts import (
        CHAIN_OF_THOUGHT_INSTRUCTIONS,
        GIT_COMMIT_INSTRUCTIONS,
        GIT_INSTRUCTIONS,
        GIT_PR_INSTRUCTIONS,
        GIT_SUMMARIZE_INSTRUCTIONS,
        SHELL_INSTRUCTIONS,
        TEST_INSTRUCTIONS,
    )

    SYSTEM_PROMPTS["chain-of-thought"] = CHAIN_OF_THOUGHT_INSTRUCTIONS
    SYSTEM_PROMPTS["shell"] = SHELL_INSTRUCTIONS
    SYSTEM_PROMPTS["test"] = TEST_INSTRUCTIONS
    SYSTEM_PROMPTS["git"] = GIT_INSTRUCTIONS
    SYSTEM_PROMPTS["git-commit"] = GIT_COMMIT_INSTRUCTIONS
    SYSTEM_PROMPTS["git-pr"] = GIT_PR_INSTRUCTIONS
    SYSTEM_PROMPTS["git-summarize"] = GIT_SUMMARIZE_INSTRUCTIONS


_init_prompts()
