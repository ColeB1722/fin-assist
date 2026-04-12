from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fin_assist.agents.default import DefaultAgent


class TestDefaultAgentInit:
    def test_requires_config_and_credentials(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert agent is not None


class TestDefaultAgentProperties:
    def test_name_is_default(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert agent.name == "default"

    def test_description_is_non_empty_string(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert isinstance(agent.description, str)
        assert len(agent.description) > 0

    def test_system_prompt_is_non_empty_string(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert isinstance(agent.system_prompt, str)
        assert len(agent.system_prompt) > 0

    def test_output_type_is_str(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert agent.output_type is str

    def test_supports_context_returns_bool(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        for context_type in ["file", "git_diff", "invalid"]:
            result = agent.supports_context(context_type)
            assert isinstance(result, bool)

    def test_supports_context_uses_context_type(
        self, expected_context_types, mock_config, mock_credentials
    ) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        for context_type in expected_context_types:
            assert agent.supports_context(context_type) is True
        assert agent.supports_context("unknown") is False


class TestDefaultAgentBuildPydanticAgent:
    def test_returns_pydantic_agent(self, mock_config, mock_credentials) -> None:
        from pydantic_ai import Agent

        agent = DefaultAgent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()

        assert isinstance(built, Agent)

    def test_with_thinking_effort(self, mock_config, mock_credentials) -> None:
        from pydantic_ai.capabilities import Thinking

        mock_config.general.thinking_effort = "high"

        agent = DefaultAgent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()

        caps = built._root_capability.capabilities
        assert len(caps) == 1
        assert isinstance(caps[0], Thinking)

    @pytest.mark.parametrize("effort", ["off", None])
    def test_thinking_off_means_no_capabilities(
        self, mock_config, mock_credentials, effort
    ) -> None:
        mock_config.general.thinking_effort = effort

        agent = DefaultAgent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()

        assert not built._root_capability.capabilities


class TestDefaultAgentBuildModel:
    def test_uses_single_model_when_no_fallback(self, mock_config, mock_credentials) -> None:
        mock_model = MagicMock()

        with patch(
            "fin_assist.llm.model_registry.ProviderRegistry.create_model", return_value=mock_model
        ):
            agent = DefaultAgent(mock_config, mock_credentials)
            result = agent.build_model()
            assert result is mock_model

    def test_uses_fallback_when_multiple_providers_enabled(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.providers = {"openai": MagicMock(enabled=True)}
        mock_credentials.get_api_key.side_effect = lambda p: {
            "anthropic": "key1",
            "openai": "key2",
        }.get(p)

        mock_model1 = MagicMock()
        mock_model2 = MagicMock()

        with patch("fin_assist.llm.model_registry.ProviderRegistry.create_model") as mock_create:
            mock_create.side_effect = [mock_model1, mock_model2]

            with patch("pydantic_ai.models.fallback.FallbackModel") as mock_fallback_class:
                mock_fallback_instance = MagicMock()
                mock_fallback_class.return_value = mock_fallback_instance

                agent = DefaultAgent(mock_config, mock_credentials)
                result = agent.build_model()

                assert result is mock_fallback_instance
                mock_fallback_class.assert_called_once_with(mock_model1, mock_model2)

    def test_get_enabled_providers_returns_default_when_no_providers_configured(
        self, mock_config, mock_credentials
    ) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        enabled = agent._get_enabled_providers()
        assert enabled == ["anthropic"]

    def test_get_enabled_providers_includes_enabled_providers(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.providers = {
            "openai": MagicMock(enabled=True),
            "ollama": MagicMock(enabled=False),
        }

        agent = DefaultAgent(mock_config, mock_credentials)
        enabled = agent._get_enabled_providers()

        assert "anthropic" in enabled
        assert "openai" in enabled
        assert "ollama" not in enabled

    def test_get_model_name_uses_provider_specific_model(
        self, mock_config, mock_credentials
    ) -> None:
        mock_config.providers = {"anthropic": MagicMock(default_model="claude-opus-4-7")}

        agent = DefaultAgent(mock_config, mock_credentials)
        model_name = agent._get_model_name("anthropic", "claude-sonnet-4-6")

        assert model_name == "claude-opus-4-7"

    def test_get_model_name_falls_back_to_default(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        model_name = agent._get_model_name("anthropic", "claude-sonnet-4-6")

        assert model_name == "claude-sonnet-4-6"
