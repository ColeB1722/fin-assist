"""Tests for LLMBaseAgent — shared model-building utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fin_assist.agents.base import AgentResult
from fin_assist.agents.llm_base import LLMBaseAgent
from fin_assist.agents.results import CommandResult
from fin_assist.context.base import ContextItem, ContextType


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------


class _ConcreteAgent(LLMBaseAgent[str]):
    @property
    def name(self) -> str:
        return "concrete"

    @property
    def description(self) -> str:
        return "A concrete test agent"

    @property
    def system_prompt(self) -> str:
        return "You are a test agent."

    @property
    def output_type(self) -> type[str]:
        return str

    async def run(self, prompt: str, context: list[ContextItem]) -> AgentResult:
        return AgentResult(success=True, output="ok")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestLLMBaseAgentInit:
    def test_accepts_config_and_credentials(self, mock_config, mock_credentials) -> None:
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent is not None

    def test_registry_is_lazily_initialised(self, mock_config, mock_credentials) -> None:
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent._registry is None  # not built at construction time


# ---------------------------------------------------------------------------
# supports_context default
# ---------------------------------------------------------------------------


class TestLLMBaseAgentSupportsContext:
    def test_supports_all_context_types_by_default(
        self, mock_config, mock_credentials, expected_context_types
    ) -> None:
        agent = _ConcreteAgent(mock_config, mock_credentials)
        for ct in expected_context_types:
            assert agent.supports_context(ct) is True

    def test_rejects_unknown_context_type(self, mock_config, mock_credentials) -> None:
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent.supports_context("unknown_type") is False


# ---------------------------------------------------------------------------
# _get_registry
# ---------------------------------------------------------------------------


class TestGetRegistry:
    def test_returns_provider_registry_instance(self, mock_config, mock_credentials) -> None:
        from fin_assist.llm.model_registry import ProviderRegistry

        agent = _ConcreteAgent(mock_config, mock_credentials)
        registry = agent._get_registry()
        assert isinstance(registry, ProviderRegistry)

    def test_returns_same_instance_on_repeated_calls(self, mock_config, mock_credentials) -> None:
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent._get_registry() is agent._get_registry()


# ---------------------------------------------------------------------------
# _get_enabled_providers
# ---------------------------------------------------------------------------


class TestGetEnabledProviders:
    def test_returns_default_provider_when_no_others_configured(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent._get_enabled_providers() == ["anthropic"]

    def test_includes_enabled_additional_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        providers = agent._get_enabled_providers()
        assert "anthropic" in providers
        assert "openrouter" in providers

    def test_excludes_disabled_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = False
        mock_config.providers = {"openrouter": extra}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert "openrouter" not in agent._get_enabled_providers()

    def test_default_provider_not_duplicated(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        anthropic_cfg = MagicMock()
        anthropic_cfg.enabled = True
        mock_config.providers = {"anthropic": anthropic_cfg}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        providers = agent._get_enabled_providers()
        assert providers.count("anthropic") == 1


# ---------------------------------------------------------------------------
# _get_model_name
# ---------------------------------------------------------------------------


class TestGetModelName:
    def test_returns_provider_specific_model_when_set(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = "claude-opus-4"
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent._get_model_name("anthropic", "default-model") == "claude-opus-4"

    def test_falls_back_to_default_model(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = None
        mock_config.providers = {"anthropic": provider_cfg}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent._get_model_name("anthropic", "fallback-model") == "fallback-model"

    def test_falls_back_when_provider_not_in_config(self, mock_config, mock_credentials) -> None:
        mock_config.providers = {}
        agent = _ConcreteAgent(mock_config, mock_credentials)
        assert agent._get_model_name("openai", "gpt-4o") == "gpt-4o"


# ---------------------------------------------------------------------------
# _build_model
# ---------------------------------------------------------------------------


class TestBuildModel:
    def test_returns_single_model_for_one_provider(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        agent = _ConcreteAgent(mock_config, mock_credentials)

        mock_model = MagicMock()
        mock_registry = MagicMock()
        mock_registry.create_model.return_value = mock_model

        with patch.object(agent, "_get_registry", return_value=mock_registry):
            model = agent._build_model()

        assert model is mock_model
        mock_registry.create_model.assert_called_once_with(
            "anthropic", "claude-sonnet-4-6", api_key="test-key"
        )

    def test_returns_fallback_model_for_multiple_providers(
        self, mock_config, mock_credentials
    ) -> None:
        from pydantic_ai.models.fallback import FallbackModel
        from pydantic_ai.models.test import TestModel

        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        extra = MagicMock()
        extra.enabled = True
        extra.default_model = None
        mock_config.providers = {"openrouter": extra}

        agent = _ConcreteAgent(mock_config, mock_credentials)

        # Return real TestModel instances so FallbackModel validation passes
        mock_registry = MagicMock()
        mock_registry.create_model.return_value = TestModel()

        with patch.object(agent, "_get_registry", return_value=mock_registry):
            model = agent._build_model()

        assert isinstance(model, FallbackModel)
