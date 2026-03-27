from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from fin_assist.llm.model_registry import ProviderRegistry
from fin_assist.llm.prompts import SYSTEM_INSTRUCTIONS, build_user_message

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import Agent
    from pydantic_ai.models import Model

    from fin_assist.config.schema import Config
    from fin_assist.context.base import ContextItem
    from fin_assist.credentials.store import CredentialStore

    type CommandAgent = Agent[None, CommandResult]


class CommandResult(BaseModel):
    command: str
    warnings: list[str] = []


class LLMAgent:
    def __init__(
        self,
        config: Config,
        credentials: CredentialStore,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self._registry = ProviderRegistry()
        self._agent: CommandAgent | None = None

    async def generate(
        self,
        prompt: str,
        context: Sequence[ContextItem] | None = None,
    ) -> CommandResult:
        agent = await self._get_agent()
        user_message = build_user_message(prompt, context)
        result = await agent.run(user_message)
        return result.output

    async def _get_agent(self) -> CommandAgent:
        if self._agent is None:
            self._agent = await self._build_agent()
        return self._agent

    async def _build_agent(self) -> CommandAgent:
        from pydantic_ai import Agent

        model = self._build_model()
        agent = Agent(model, output_type=CommandResult, instructions=SYSTEM_INSTRUCTIONS)
        return cast("CommandAgent", agent)

    def _build_model(self) -> Model:
        from pydantic_ai.models.fallback import FallbackModel

        default_model = self.config.general.default_model

        enabled_providers = self._get_enabled_providers()

        if len(enabled_providers) == 1:
            provider_name = enabled_providers[0]
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self.credentials.get_api_key(provider_name)
            return self._registry.create_model(provider_name, model_name, api_key=api_key)

        models = []
        for provider_name in enabled_providers:
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self.credentials.get_api_key(provider_name)
            model = self._registry.create_model(provider_name, model_name, api_key=api_key)
            models.append(model)

        return FallbackModel(*models)

    def _get_model_name(self, provider: str, default: str) -> str:
        provider_config = self.config.providers.get(provider)
        if provider_config and provider_config.default_model:
            return provider_config.default_model
        return default

    def _get_enabled_providers(self) -> list[str]:
        default_provider = self.config.general.default_provider
        enabled = [default_provider]

        for name, provider_config in self.config.providers.items():
            if name != default_provider and provider_config.enabled:
                enabled.append(name)

        return enabled
