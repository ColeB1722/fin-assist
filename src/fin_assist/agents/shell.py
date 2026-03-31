from __future__ import annotations

from typing import TYPE_CHECKING

from fin_assist.agents.base import AgentCardMeta, AgentResult
from fin_assist.agents.llm_base import LLMBaseAgent
from fin_assist.agents.results import CommandResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import Agent

    from fin_assist.context.base import ContextItem


class ShellAgent(LLMBaseAgent[CommandResult]):
    """One-shot shell command generation agent.

    Accepts a natural-language prompt and returns a single ``CommandResult``
    with the best-matching shell command.  Always one-shot: no conversation
    history, no thinking effort selector.
    """

    def __init__(self, config, credentials) -> None:
        super().__init__(config, credentials)
        # Annotated explicitly per pydantic-ai docs ("add a type hint :
        # Agent[None, <return type>] to satisfy Pyright").  Pyright accepts this
        # correctly; ty has a current inference gap and will raise
        # invalid-return-type on _build_agent, suppressed there with ty: ignore.
        self._agent: Agent[None, CommandResult] | None = None

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
            supports_regenerate=True,
        )

    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult:
        try:
            result = await self._generate(prompt, context)
            return AgentResult(
                success=True,
                output=result.command,
                warnings=list(result.warnings),
                metadata={
                    "accept_action": "insert_command",
                    "regenerate_prompt": prompt,
                    "original_output": result.command,
                },
            )
        except Exception as e:
            return AgentResult(
                success=False,
                output="",
                warnings=[str(e)],
                metadata={},
            )

    async def _generate(
        self,
        prompt: str,
        context: Sequence[ContextItem] | None = None,
    ) -> CommandResult:
        from fin_assist.llm.prompts import build_user_message

        agent = await self._get_agent()
        ctx = list(context) if context else []
        user_message = build_user_message(prompt, ctx)
        result = await agent.run(user_message)
        return result.output

    async def _get_agent(self) -> Agent[None, CommandResult]:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent[None, CommandResult]:
        from pydantic_ai import Agent

        from fin_assist.llm.prompts import SHELL_INSTRUCTIONS

        model = self._build_model()
        return Agent(  # ty: ignore[invalid-return-type]
            model,
            output_type=CommandResult,
            instructions=SHELL_INSTRUCTIONS,
        )
