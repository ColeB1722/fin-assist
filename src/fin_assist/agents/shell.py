from __future__ import annotations

from fin_assist.agents.base import AgentCardMeta, BaseAgent
from fin_assist.agents.results import CommandResult


class ShellAgent(BaseAgent[CommandResult]):
    """One-shot shell command generation agent.

    Accepts a natural-language prompt and returns a single ``CommandResult``
    with the best-matching shell command.  Always one-shot: no conversation
    history, no thinking effort selector.
    """

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "One-shot shell command generator. "
            "Give it a natural-language request and get back a ready-to-run command."
        )

    @property
    def system_prompt(self) -> str:
        from fin_assist.llm.prompts import SHELL_INSTRUCTIONS

        return SHELL_INSTRUCTIONS

    @property
    def output_type(self) -> type[CommandResult]:
        return CommandResult

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        return AgentCardMeta(
            multi_turn=False,
            supports_thinking=False,
            tags=["shell", "one-shot"],
            requires_approval=True,
        )
