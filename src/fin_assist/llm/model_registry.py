from __future__ import annotations

from typing import TYPE_CHECKING

from fin_assist.providers import get_provider_ids

if TYPE_CHECKING:
    from pydantic_ai.models import Model


PROVIDERS: dict[str, str] = {pid: pid for pid in get_provider_ids() if pid != "ollama"}


class ProviderRegistry:
    def list_providers(self) -> list[str]:
        return list(PROVIDERS.keys())

    def get_kind(self, provider: str) -> str:
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
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        from pydantic_ai.providers.google import GoogleProvider
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        match self.get_kind(provider):
            case "anthropic":
                return AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))
            case "openai":
                return OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key))
            case "openrouter":
                return OpenRouterModel(model_name, provider=OpenRouterProvider(api_key=api_key))
            case "google":
                return GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))
            case "custom":
                return OpenAIChatModel(
                    model_name, provider=OpenAIProvider(base_url=base_url, api_key=api_key)
                )
            case _:
                raise ValueError(f"Cannot create model for provider: {provider}")
