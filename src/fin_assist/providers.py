from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderMeta:
    display: str
    requires_api_key: bool


PROVIDER_META: dict[str, ProviderMeta] = {
    "anthropic": ProviderMeta(display="Anthropic", requires_api_key=True),
    "openai": ProviderMeta(display="OpenAI", requires_api_key=True),
    "openrouter": ProviderMeta(display="OpenRouter", requires_api_key=True),
    "google": ProviderMeta(display="Google", requires_api_key=True),
    "ollama": ProviderMeta(display="Ollama (local)", requires_api_key=False),
    "custom": ProviderMeta(display="Custom / Self-hosted", requires_api_key=False),
}


def get_provider_ids() -> list[str]:
    return list(PROVIDER_META.keys())


def get_providers_requiring_api_key() -> set[str]:
    return {pid for pid, meta in PROVIDER_META.items() if meta.requires_api_key}
