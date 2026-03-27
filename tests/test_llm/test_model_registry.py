from __future__ import annotations

import pytest

from fin_assist.llm.model_registry import ProviderRegistry


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry()


class TestProviderRegistryListProviders:
    def test_returns_hardcoded_providers(self, registry: ProviderRegistry) -> None:
        providers = registry.list_providers()
        assert "anthropic" in providers
        assert "openai" in providers
        assert "openrouter" in providers
        assert "google" in providers

    def test_returns_only_known_providers(self, registry: ProviderRegistry) -> None:
        providers = registry.list_providers()
        assert len(providers) == 5


class TestProviderRegistryGetProviderKind:
    def test_returns_kind_for_anthropic(self, registry: ProviderRegistry) -> None:
        assert registry.get_kind("anthropic") == "anthropic"

    def test_returns_kind_for_openai(self, registry: ProviderRegistry) -> None:
        assert registry.get_kind("openai") == "openai"

    def test_returns_kind_for_openrouter(self, registry: ProviderRegistry) -> None:
        assert registry.get_kind("openrouter") == "openrouter"

    def test_returns_kind_for_google(self, registry: ProviderRegistry) -> None:
        assert registry.get_kind("google") == "google"

    def test_raises_for_unknown_provider(self, registry: ProviderRegistry) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            registry.get_kind("unknown")

    def test_unknown_provider_error_message(self, registry: ProviderRegistry) -> None:
        with pytest.raises(ValueError, match="unknown"):
            registry.get_kind("unknown")
