from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fin_assist.agents.base import BaseAgent

if TYPE_CHECKING:
    from pydantic_ai import Agent


class DefaultAgent(BaseAgent[str]):
    @property
    def name(self) -> str:
        return "default"

    @property
    def description(self) -> str:
        return (
            "General-purpose assistant. "
            "Helps with questions, shell commands, brainstorming, and more."
        )

    @property
    def system_prompt(self) -> str:
        from fin_assist.llm.prompts import CHAIN_OF_THOUGHT_INSTRUCTIONS

        return CHAIN_OF_THOUGHT_INSTRUCTIONS

    @property
    def output_type(self) -> type[str]:
        return str

    def build_pydantic_agent(self) -> Agent[Any, str]:
        """Build a pydantic-ai Agent with thinking capabilities when configured.

        Model is deferred — see ``BaseAgent.build_pydantic_agent`` docstring.
        """
        from pydantic_ai import Agent
        from pydantic_ai.capabilities import Thinking

        thinking_effort = self._config.general.thinking_effort
        capabilities = (
            [Thinking(effort=thinking_effort)]
            if thinking_effort and thinking_effort != "off"
            else None
        )
        return Agent(
            output_type=str,
            instructions=self.system_prompt,
            capabilities=capabilities,
        )
