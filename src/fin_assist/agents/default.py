from __future__ import annotations

from typing import TYPE_CHECKING

from fin_assist.agents.base import AgentResult
from fin_assist.agents.llm_base import LLMBaseAgent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import Agent

    from fin_assist.context.base import ContextItem

    type GeneralAgent = Agent[None, str]


class DefaultAgent(LLMBaseAgent[str]):
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

    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult:
        try:
            response = await self.generate(prompt, context)
            return AgentResult(
                success=True,
                output=response,
                warnings=[],
                metadata={},
            )
        except Exception as e:
            return AgentResult(
                success=False,
                output="",
                warnings=[str(e)],
                metadata={},
            )

    async def generate(
        self,
        prompt: str,
        context: Sequence[ContextItem] | None = None,
    ) -> str:
        from fin_assist.llm.prompts import build_user_message

        agent = await self._get_agent()
        ctx = list(context) if context else []
        user_message = build_user_message(prompt, ctx)
        result = await agent.run(user_message)
        return result.output

    async def _get_agent(self) -> GeneralAgent:
        if self._agent is None:
            self._agent = await self._build_agent()
        assert self._agent is not None
        return self._agent

    async def _build_agent(self) -> GeneralAgent:
        from pydantic_ai import Agent
        from pydantic_ai.capabilities import Thinking

        from fin_assist.llm.prompts import CHAIN_OF_THOUGHT_INSTRUCTIONS

        model = self._build_model()
        thinking_effort = self._config.general.thinking_effort
        capabilities = (
            [Thinking(effort=thinking_effort)]
            if thinking_effort and thinking_effort != "off"
            else None
        )
        agent = Agent(
            model,
            output_type=str,
            instructions=CHAIN_OF_THOUGHT_INSTRUCTIONS,
            capabilities=capabilities,
        )
        return agent
