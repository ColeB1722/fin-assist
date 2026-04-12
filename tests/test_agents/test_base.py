"""Tests for BaseAgent, AgentCardMeta, and AgentResult."""

from __future__ import annotations

from abc import ABC
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import Agent as PydanticAgent

from fin_assist.agents.base import AgentCardMeta, AgentResult, BaseAgent
from fin_assist.context.base import ContextType


# -- Fixtures -----------------------------------------------------------------


class DummyAgent(BaseAgent[str]):
    """Minimal concrete agent for testing BaseAgent behaviour."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy agent"

    @property
    def system_prompt(self) -> str:
        return "You are a dummy."

    @property
    def output_type(self) -> type[str]:
        return str


# -- AgentResult tests --------------------------------------------------------


class TestAgentResult:
    def test_creation(self) -> None:
        result = AgentResult(success=True, output="ls -la", warnings=[], metadata={})
        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []
        assert result.metadata == {}

    def test_with_warnings(self) -> None:
        result = AgentResult(
            success=True,
            output="rm -rf /",
            warnings=["Destructive operation"],
            metadata={},
        )
        assert result.warnings == ["Destructive operation"]

    def test_with_metadata(self) -> None:
        result = AgentResult(
            success=True,
            output="echo hello",
            warnings=[],
            metadata={"provider": "anthropic", "model": "claude-sonnet-4-6"},
        )
        assert result.metadata["provider"] == "anthropic"

    def test_default_values(self) -> None:
        result = AgentResult(success=True, output="test")
        assert result.warnings == []
        assert result.metadata == {}

    def test_output_is_str(self) -> None:
        result = AgentResult(success=True, output="ls")
        assert isinstance(result.output, str)


# -- AgentCardMeta tests -----------------------------------------------------


class TestAgentCardMeta:
    def test_defaults(self) -> None:
        meta = AgentCardMeta()
        assert meta.multi_turn is True
        assert meta.supports_thinking is True
        assert meta.supports_model_selection is True
        assert meta.supported_providers is None
        assert meta.color_scheme is None
        assert meta.tags == []

    def test_equality(self) -> None:
        assert AgentCardMeta() == AgentCardMeta()
        assert AgentCardMeta(multi_turn=False) != AgentCardMeta()

    def test_one_shot_meta(self) -> None:
        meta = AgentCardMeta(multi_turn=False, supports_thinking=False)
        assert meta.multi_turn is False
        assert meta.supports_thinking is False
        assert meta.supports_model_selection is True


# -- BaseAgent ABC tests ------------------------------------------------------


class TestBaseAgentABC:
    def test_is_abc(self) -> None:
        assert issubclass(BaseAgent, ABC)

    def test_abstract_properties(self) -> None:
        for attr in ("name", "description", "system_prompt", "output_type"):
            prop = getattr(BaseAgent, attr)
            assert getattr(prop, "__isabstractmethod__", False) is True

    def test_concrete_methods(self) -> None:
        """supports_context and build_pydantic_agent have concrete defaults."""
        for attr in ("supports_context", "build_pydantic_agent"):
            method = getattr(BaseAgent, attr)
            assert getattr(method, "__isabstractmethod__", False) is False

    def test_is_generic(self) -> None:
        assert hasattr(BaseAgent, "__class_getitem__")


class TestBaseAgentDefaults:
    def test_default_agent_card_metadata(self, mock_config, mock_credentials) -> None:
        agent = DummyAgent(mock_config, mock_credentials)
        meta = agent.agent_card_metadata
        assert isinstance(meta, AgentCardMeta)
        assert meta == AgentCardMeta()

    def test_agent_card_metadata_overridable(self) -> None:
        """agent_card_metadata should not be abstract — subclasses can override."""
        assert getattr(BaseAgent.agent_card_metadata, "__isabstractmethod__", False) is False


# -- Construction tests -------------------------------------------------------


class TestBaseAgentInit:
    def test_accepts_config_and_credentials(self, mock_config, mock_credentials) -> None:
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent is not None

    def test_registry_is_lazily_initialised(self, mock_config, mock_credentials) -> None:
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent._registry is None  # not built at construction time


# -- supports_context tests ---------------------------------------------------


class TestSupportsContext:
    def test_supports_all_context_types_by_default(
        self, mock_config, mock_credentials, expected_context_types
    ) -> None:
        agent = DummyAgent(mock_config, mock_credentials)
        for ct in expected_context_types:
            assert agent.supports_context(ct) is True

    def test_rejects_unknown_context_type(self, mock_config, mock_credentials) -> None:
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent.supports_context("unknown_type") is False


# -- _get_registry tests ------------------------------------------------------


class TestGetRegistry:
    def test_returns_provider_registry_instance(self, mock_config, mock_credentials) -> None:
        from fin_assist.llm.model_registry import ProviderRegistry

        agent = DummyAgent(mock_config, mock_credentials)
        registry = agent._get_registry()
        assert isinstance(registry, ProviderRegistry)

    def test_returns_same_instance_on_repeated_calls(self, mock_config, mock_credentials) -> None:
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent._get_registry() is agent._get_registry()


# -- _get_enabled_providers tests ---------------------------------------------


class TestGetEnabledProviders:
    def test_returns_default_provider_when_no_others_configured(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent._get_enabled_providers() == ["anthropic"]

    def test_includes_enabled_additional_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = True
        mock_config.providers = {"openrouter": extra}
        agent = DummyAgent(mock_config, mock_credentials)
        providers = agent._get_enabled_providers()
        assert "anthropic" in providers
        assert "openrouter" in providers

    def test_excludes_disabled_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        extra = MagicMock()
        extra.enabled = False
        mock_config.providers = {"openrouter": extra}
        agent = DummyAgent(mock_config, mock_credentials)
        assert "openrouter" not in agent._get_enabled_providers()

    def test_default_provider_not_duplicated(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        anthropic_cfg = MagicMock()
        anthropic_cfg.enabled = True
        mock_config.providers = {"anthropic": anthropic_cfg}
        agent = DummyAgent(mock_config, mock_credentials)
        providers = agent._get_enabled_providers()
        assert providers.count("anthropic") == 1


# -- _get_model_name tests ----------------------------------------------------


class TestGetModelName:
    def test_returns_provider_specific_model_when_set(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = "claude-opus-4"
        mock_config.providers = {"anthropic": provider_cfg}
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent._get_model_name("anthropic", "default-model") == "claude-opus-4"

    def test_falls_back_to_default_model(self, mock_config, mock_credentials) -> None:
        provider_cfg = MagicMock()
        provider_cfg.default_model = None
        mock_config.providers = {"anthropic": provider_cfg}
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent._get_model_name("anthropic", "fallback-model") == "fallback-model"

    def test_falls_back_when_provider_not_in_config(self, mock_config, mock_credentials) -> None:
        mock_config.providers = {}
        agent = DummyAgent(mock_config, mock_credentials)
        assert agent._get_model_name("openai", "gpt-4o") == "gpt-4o"


# -- build_model tests --------------------------------------------------------


class TestBuildModel:
    def test_returns_single_model_for_one_provider(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        agent = DummyAgent(mock_config, mock_credentials)

        mock_model = MagicMock()
        mock_registry = MagicMock()
        mock_registry.create_model.return_value = mock_model

        with patch.object(agent, "_get_registry", return_value=mock_registry):
            model = agent.build_model()

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

        agent = DummyAgent(mock_config, mock_credentials)

        # Return real TestModel instances so FallbackModel validation passes
        mock_registry = MagicMock()
        mock_registry.create_model.return_value = TestModel()

        with patch.object(agent, "_get_registry", return_value=mock_registry):
            model = agent.build_model()

        assert isinstance(model, FallbackModel)
