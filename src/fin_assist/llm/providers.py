from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai.models import Model


class ProviderKind(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    GOOGLE = "google"
    CUSTOM = "custom"


PROVIDERS: dict[str, ProviderKind] = {
    "anthropic": ProviderKind.ANTHROPIC,
    "openai": ProviderKind.OPENAI,
    "openrouter": ProviderKind.OPENROUTER,
    "google": ProviderKind.GOOGLE,
}


class ProviderRegistry:
    def list_providers(self) -> list[str]:
        return list(PROVIDERS.keys())

    def get_kind(self, provider: str) -> ProviderKind:
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        return PROVIDERS[provider]

    def create_model(
        self,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> Model:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        from pydantic_ai.providers.google import GoogleProvider
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        kind = self.get_kind(provider)

        if kind == ProviderKind.ANTHROPIC:
            return AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))

        if kind == ProviderKind.OPENAI:
            return OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key))

        if kind == ProviderKind.OPENROUTER:
            return OpenAIChatModel(model_name, provider=OpenRouterProvider(api_key=api_key))

        if kind == ProviderKind.GOOGLE:
            return GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))

        if kind == ProviderKind.CUSTOM:
            return OpenAIChatModel(
                model_name, provider=OpenAIProvider(base_url=base_url, api_key=api_key)
            )

        raise ValueError(f"Cannot create model for provider: {provider}")
