from __future__ import annotations

from unittest.mock import MagicMock, patch

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


class TestProviderRegistryCreateModel:
    def test_anthropic_model(self, registry: ProviderRegistry) -> None:
        mock_model = MagicMock()
        with (
            patch(
                "pydantic_ai.models.anthropic.AnthropicModel", return_value=mock_model
            ) as MockCls,
            patch("pydantic_ai.providers.anthropic.AnthropicProvider") as MockProvider,
        ):
            result = registry.create_model("anthropic", "claude-sonnet-4-6", api_key="sk-test")
        MockCls.assert_called_once_with("claude-sonnet-4-6", provider=MockProvider.return_value)
        MockProvider.assert_called_once_with(api_key="sk-test")
        assert result is mock_model

    def test_openai_model(self, registry: ProviderRegistry) -> None:
        mock_model = MagicMock()
        with (
            patch("pydantic_ai.models.openai.OpenAIChatModel", return_value=mock_model) as MockCls,
            patch("pydantic_ai.providers.openai.OpenAIProvider") as MockProvider,
        ):
            result = registry.create_model("openai", "gpt-4o", api_key="sk-test")
        MockCls.assert_called_once_with("gpt-4o", provider=MockProvider.return_value)
        MockProvider.assert_called_once_with(api_key="sk-test")
        assert result is mock_model

    def test_openrouter_model(self, registry: ProviderRegistry) -> None:
        mock_model = MagicMock()
        with (
            patch(
                "pydantic_ai.models.openrouter.OpenRouterModel", return_value=mock_model
            ) as MockCls,
            patch("pydantic_ai.providers.openrouter.OpenRouterProvider") as MockProvider,
        ):
            result = registry.create_model("openrouter", "auto", api_key="sk-or")
        MockCls.assert_called_once_with("auto", provider=MockProvider.return_value)
        MockProvider.assert_called_once_with(api_key="sk-or")
        assert result is mock_model

    def test_google_model(self, registry: ProviderRegistry) -> None:
        mock_model = MagicMock()
        with (
            patch("pydantic_ai.models.google.GoogleModel", return_value=mock_model) as MockCls,
            patch("pydantic_ai.providers.google.GoogleProvider") as MockProvider,
        ):
            result = registry.create_model("google", "gemini-2.0-flash", api_key="aiza")
        MockCls.assert_called_once_with("gemini-2.0-flash", provider=MockProvider.return_value)
        MockProvider.assert_called_once_with(api_key="aiza")
        assert result is mock_model

    def test_custom_provider(self, registry: ProviderRegistry) -> None:
        mock_model = MagicMock()
        with (
            patch("pydantic_ai.models.openai.OpenAIChatModel", return_value=mock_model) as MockCls,
            patch("pydantic_ai.providers.openai.OpenAIProvider") as MockProvider,
        ):
            result = registry.create_model(
                "custom", "my-model", api_key="key", base_url="http://localhost:8000"
            )
        MockProvider.assert_called_once_with(base_url="http://localhost:8000", api_key="key")
        MockCls.assert_called_once_with("my-model", provider=MockProvider.return_value)
        assert result is mock_model

    def test_unknown_provider_raises(self, registry: ProviderRegistry) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            registry.create_model("nonexistent", "model")
