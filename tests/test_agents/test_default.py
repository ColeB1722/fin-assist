from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.base import AgentResult
from fin_assist.agents.default import DefaultAgent
from fin_assist.agents.results import CommandResult
from fin_assist.context.base import ContextItem


class TestDefaultAgentInit:
    def test_requires_config_and_credentials(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert agent is not None


class TestDefaultAgentProperties:
    def test_name_is_shell(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert agent.name == "shell"

    def test_description_is_non_empty_string(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert isinstance(agent.description, str)
        assert len(agent.description) > 0

    def test_system_prompt_is_non_empty_string(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        assert isinstance(agent.system_prompt, str)
        assert len(agent.system_prompt) > 0

    def test_output_type_returns_a_type(self, mock_config, mock_credentials) -> None:
        agent = DefaultAgent(mock_config, mock_credentials)
        output_type = agent.output_type
        assert isinstance(output_type, type)
        assert output_type is not None

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


class TestDefaultAgentRun:
    @pytest.mark.asyncio
    async def test_run_returns_agent_result(self, mock_config, mock_credentials) -> None:
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="ls -la")
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(DefaultAgent, "_get_agent", return_value=mock_agent):
            agent = DefaultAgent(mock_config, mock_credentials)
            result = await agent.run("list files", [])

            assert isinstance(result, AgentResult)
            assert result.success is True
            assert result.output == "ls -la"
            assert result.warnings == []

    @pytest.mark.asyncio
    async def test_run_passes_context_to_agent(self, mock_config, mock_credentials) -> None:
        context = [ContextItem(id="1", type="file", content="test.py content", metadata={})]
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="grep test test.py")
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(DefaultAgent, "_get_agent", return_value=mock_agent):
            agent = DefaultAgent(mock_config, mock_credentials)
            await agent.run("find in file", context=context)
            mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_returns_warnings_from_result(self, mock_config, mock_credentials) -> None:
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="rm -rf /", warnings=["Destructive operation"])
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(DefaultAgent, "_get_agent", return_value=mock_agent):
            agent = DefaultAgent(mock_config, mock_credentials)
            result = await agent.run("delete everything", [])

            assert result.success is True
            assert result.output == "rm -rf /"
            assert "Destructive operation" in result.warnings


class TestDefaultAgentBuildModel:
    def test_uses_single_model_when_no_fallback(self, mock_config, mock_credentials) -> None:
        mock_model = MagicMock()

        with patch(
            "fin_assist.llm.model_registry.ProviderRegistry.create_model", return_value=mock_model
        ):
            agent = DefaultAgent(mock_config, mock_credentials)
            result = agent._build_model()
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
                result = agent._build_model()

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
