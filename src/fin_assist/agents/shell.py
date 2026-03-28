from __future__ import annotations

from typing import TYPE_CHECKING

from fin_assist.agents.base import AgentCardMeta, AgentResult, BaseAgent
from fin_assist.agents.results import CommandResult
from fin_assist.context.base import ContextType

if TYPE_CHECKING:
    from fin_assist.config.schema import Config
    from fin_assist.context.base import ContextItem
    from fin_assist.credentials.store import CredentialStore


class ShellAgent(BaseAgent[CommandResult]):
    def __init__(self, config: Config, credentials: CredentialStore) -> None:
        self._config = config
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "One-shot shell command generator."

    @property
    def system_prompt(self) -> str:
        from fin_assist.llm.prompts import SHELL_INSTRUCTIONS

        return SHELL_INSTRUCTIONS

    @property
    def output_type(self) -> type[CommandResult]:
        return CommandResult

    def supports_context(self, context_type: str) -> bool:
        return context_type in ContextType.__args__

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        return AgentCardMeta(multi_turn=False, supports_thinking=False)

    async def run(self, prompt: str, context: list[ContextItem]) -> AgentResult:
        return AgentResult(
            success=True,
            output=prompt,
            warnings=[],
            metadata={"accept_action": "insert_command"},
        )
