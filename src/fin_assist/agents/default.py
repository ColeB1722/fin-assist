from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fin_assist.agents.base import AgentResult, BaseAgent
from fin_assist.agents.results import CommandResult
from fin_assist.context.base import ContextType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import Agent
    from pydantic_ai.models import Model

    from fin_assist.config.schema import Config
    from fin_assist.context.base import ContextItem
    from fin_assist.credentials.store import CredentialStore

    type ShellAgent = Agent[None, CommandResult]


SUPPORTED_CONTEXT_TYPES = frozenset(ContextType.__args__)


class DefaultAgent(BaseAgent[CommandResult]):
    def __init__(
        self,
        config: Config,
        credentials: CredentialStore,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._registry = None
        self._agent: ShellAgent | None = None

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Shell command generation agent. "
            "Converts natural language requests into fish shell commands."
        )

    @property
    def system_prompt(self) -> str:
        from fin_assist.llm.prompts import SYSTEM_INSTRUCTIONS

        return SYSTEM_INSTRUCTIONS

    @property
    def output_type(self) -> type[CommandResult]:
        return CommandResult

    def supports_context(self, context_type: str) -> bool:
        return context_type in SUPPORTED_CONTEXT_TYPES

    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult:
        command_result = await self.generate(prompt, context)
        return AgentResult(
            success=True,
            output=command_result.command,
            warnings=command_result.warnings,
            metadata={},
        )

    async def generate(
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

    async def _get_agent(self) -> ShellAgent:
        if self._agent is None:
            self._agent = await self._build_agent()
        return self._agent

    async def _build_agent(self) -> ShellAgent:
        from pydantic_ai import Agent

        from fin_assist.llm.prompts import SYSTEM_INSTRUCTIONS

        model = self._build_model()
        agent = Agent(model, output_type=CommandResult, instructions=SYSTEM_INSTRUCTIONS)
        return cast("ShellAgent", agent)

    def _get_registry(self):
        if self._registry is None:
            from fin_assist.llm.model_registry import ProviderRegistry

            self._registry = ProviderRegistry()
        return self._registry

    def _build_model(self) -> Model:
        from pydantic_ai.models.fallback import FallbackModel

        default_model = self._config.general.default_model
        enabled_providers = self._get_enabled_providers()

        if len(enabled_providers) == 1:
            provider_name = enabled_providers[0]
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self._credentials.get_api_key(provider_name)
            return self._get_registry().create_model(provider_name, model_name, api_key=api_key)

        models = []
        for provider_name in enabled_providers:
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self._credentials.get_api_key(provider_name)
            model = self._get_registry().create_model(provider_name, model_name, api_key=api_key)
            models.append(model)

        return FallbackModel(*models)

    def _get_model_name(self, provider: str, default: str) -> str:
        provider_config = self._config.providers.get(provider)
        if provider_config and provider_config.default_model:
            return provider_config.default_model
        return default

    def _get_enabled_providers(self) -> list[str]:
        default_provider = self._config.general.default_provider
        enabled = [default_provider]

        for name, provider_config in self._config.providers.items():
            if name != default_provider and provider_config.enabled:
                enabled.append(name)

        return enabled
