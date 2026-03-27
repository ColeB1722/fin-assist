from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.context.base import ContextItem
from fin_assist.llm.agent import CommandResult, LLMAgent


class TestCommandResult:
    def test_command_result_defaults(self) -> None:
        result = CommandResult(command="ls -la")
        assert result.command == "ls -la"
        assert result.warnings == []

    def test_command_result_with_warnings(self) -> None:
        result = CommandResult(
            command="rm -rf /", warnings=["Warning: recursive remove on root directory"]
        )
        assert result.command == "rm -rf /"
        assert len(result.warnings) == 1

    def test_command_result_extra_fields_ignored(self) -> None:
        data = {"command": "ls", "warnings": [], "extra": "ignored"}
        result = CommandResult(**data)
        assert result.command == "ls"
        assert not hasattr(result, "extra")


class TestLLMAgentInit:
    def test_requires_config_and_credentials(self) -> None:
        mock_config = MagicMock()
        mock_credentials = MagicMock()
        agent = LLMAgent(mock_config, mock_credentials)
        assert agent is not None


class TestLLMAgentGenerate:
    @pytest.mark.asyncio
    async def test_generate_returns_command_result(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}

        mock_credentials = MagicMock()
        mock_credentials.get_api_key.return_value = "test-key"

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="ls -la")
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(LLMAgent, "_get_agent", return_value=mock_agent):
            agent = LLMAgent(mock_config, mock_credentials)
            result = await agent.generate("list files")

            assert isinstance(result, CommandResult)
            assert result.command == "ls -la"

    @pytest.mark.asyncio
    async def test_generate_passes_context_to_agent(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}

        mock_credentials = MagicMock()
        mock_credentials.get_api_key.return_value = "test-key"

        context = [ContextItem(id="1", type="file", content="test.py content", metadata={})]

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="grep test test.py")
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(LLMAgent, "_get_agent", return_value=mock_agent):
            agent = LLMAgent(mock_config, mock_credentials)
            await agent.generate("find in file", context=context)

            mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_returns_warnings_from_result(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}

        mock_credentials = MagicMock()
        mock_credentials.get_api_key.return_value = "test-key"

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="rm -rf /", warnings=["Destructive operation"])
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(LLMAgent, "_get_agent", return_value=mock_agent):
            agent = LLMAgent(mock_config, mock_credentials)
            result = await agent.generate("delete everything")

            assert "Destructive operation" in result.warnings


class TestLLMAgentBuildModel:
    def test_uses_single_model_when_no_fallback(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}

        mock_credentials = MagicMock()
        mock_credentials.get_api_key.return_value = "test-key"

        mock_model = MagicMock()

        with patch(
            "fin_assist.llm.model_registry.ProviderRegistry.create_model", return_value=mock_model
        ):
            agent = LLMAgent(mock_config, mock_credentials)
            result = agent._build_model()

            assert result is mock_model

    def test_uses_fallback_when_multiple_providers_enabled(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {"openai": MagicMock(enabled=True)}

        mock_credentials = MagicMock()
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

                agent = LLMAgent(mock_config, mock_credentials)
                result = agent._build_model()

                assert result is mock_fallback_instance
                mock_fallback_class.assert_called_once_with(mock_model1, mock_model2)

    def test_get_enabled_providers_returns_default_when_no_providers_configured(
        self,
    ) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}

        mock_credentials = MagicMock()

        agent = LLMAgent(mock_config, mock_credentials)
        enabled = agent._get_enabled_providers()

        assert enabled == ["anthropic"]

    def test_get_enabled_providers_includes_enabled_providers(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {
            "openai": MagicMock(enabled=True),
            "ollama": MagicMock(enabled=False),
        }

        mock_credentials = MagicMock()

        agent = LLMAgent(mock_config, mock_credentials)
        enabled = agent._get_enabled_providers()

        assert "anthropic" in enabled
        assert "openai" in enabled
        assert "ollama" not in enabled

    def test_get_model_name_uses_provider_specific_model(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {"anthropic": MagicMock(default_model="claude-opus-4-7")}

        mock_credentials = MagicMock()

        agent = LLMAgent(mock_config, mock_credentials)
        model_name = agent._get_model_name("anthropic", "claude-sonnet-4-6")

        assert model_name == "claude-opus-4-7"

    def test_get_model_name_falls_back_to_default(self) -> None:
        mock_config = MagicMock()
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}

        mock_credentials = MagicMock()

        agent = LLMAgent(mock_config, mock_credentials)
        model_name = agent._get_model_name("anthropic", "claude-sonnet-4-6")

        assert model_name == "claude-sonnet-4-6"
