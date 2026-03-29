"""Tests for ShellAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.base import AgentCardMeta, AgentResult
from fin_assist.agents.results import CommandResult
from fin_assist.agents.shell import ShellAgent
from fin_assist.context.base import ContextItem


class TestShellAgentProperties:
    def test_name(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert agent.name == "shell"

    def test_description_non_empty(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert isinstance(agent.description, str)
        assert len(agent.description) > 0

    def test_output_type_is_command_result(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert agent.output_type is CommandResult

    def test_system_prompt_is_non_empty(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert isinstance(agent.system_prompt, str)
        assert len(agent.system_prompt) > 0

    def test_supports_context_for_all_context_types(
        self, mock_config, mock_credentials, expected_context_types
    ) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        for ct in expected_context_types:
            assert agent.supports_context(ct) is True

    def test_does_not_support_unknown_context_type(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert agent.supports_context("unknown_type") is False


class TestShellAgentCardMetadata:
    def test_is_one_shot(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.multi_turn is False

    def test_no_thinking(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.supports_thinking is False

    def test_supports_model_selection(self, mock_config, mock_credentials) -> None:
        """ShellAgent should still allow provider/model choice."""
        agent = ShellAgent(mock_config, mock_credentials)
        assert agent.agent_card_metadata.supports_model_selection is True

    def test_metadata_is_agent_card_meta_instance(self, mock_config, mock_credentials) -> None:
        agent = ShellAgent(mock_config, mock_credentials)
        assert isinstance(agent.agent_card_metadata, AgentCardMeta)


class TestShellAgentRun:
    @pytest.mark.asyncio
    async def test_run_returns_successful_agent_result(self, mock_config, mock_credentials) -> None:
        mock_pydantic_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="ls -la")
        mock_pydantic_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(ShellAgent, "_get_agent", return_value=mock_pydantic_agent):
            agent = ShellAgent(mock_config, mock_credentials)
            result = await agent.run("list files", [])

        assert isinstance(result, AgentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_run_output_contains_command(self, mock_config, mock_credentials) -> None:
        mock_pydantic_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="ls -la")
        mock_pydantic_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(ShellAgent, "_get_agent", return_value=mock_pydantic_agent):
            agent = ShellAgent(mock_config, mock_credentials)
            result = await agent.run("list files", [])

        assert "ls -la" in result.output

    @pytest.mark.asyncio
    async def test_run_metadata_has_insert_command_action(
        self, mock_config, mock_credentials
    ) -> None:
        mock_pydantic_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="echo hi")
        mock_pydantic_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(ShellAgent, "_get_agent", return_value=mock_pydantic_agent):
            agent = ShellAgent(mock_config, mock_credentials)
            result = await agent.run("say hi", [])

        assert result.metadata.get("accept_action") == "insert_command"

    @pytest.mark.asyncio
    async def test_run_passes_context_to_agent(self, mock_config, mock_credentials) -> None:
        context = [ContextItem(id="1", type="file", content="README.md", metadata={})]
        mock_pydantic_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(command="cat README.md")
        mock_pydantic_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(ShellAgent, "_get_agent", return_value=mock_pydantic_agent):
            agent = ShellAgent(mock_config, mock_credentials)
            await agent.run("show the readme", context)
            mock_pydantic_agent.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_includes_warnings_from_result(self, mock_config, mock_credentials) -> None:
        mock_pydantic_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = CommandResult(
            command="rm -rf /tmp/test", warnings=["Destructive operation"]
        )
        mock_pydantic_agent.run = AsyncMock(return_value=mock_result)

        with patch.object(ShellAgent, "_get_agent", return_value=mock_pydantic_agent):
            agent = ShellAgent(mock_config, mock_credentials)
            result = await agent.run("delete the test temp dir", [])

        assert "Destructive operation" in result.warnings

    @pytest.mark.asyncio
    async def test_run_returns_failure_on_exception(self, mock_config, mock_credentials) -> None:
        with patch.object(ShellAgent, "_get_agent", side_effect=RuntimeError("model unavailable")):
            agent = ShellAgent(mock_config, mock_credentials)
            result = await agent.run("list files", [])

        assert result.success is False
        assert result.output == ""
        assert "model unavailable" in result.warnings[0]
