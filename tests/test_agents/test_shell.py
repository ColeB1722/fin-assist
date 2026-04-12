"""Tests for ShellAgent."""

from __future__ import annotations

from fin_assist.agents.base import AgentCardMeta
from fin_assist.agents.results import CommandResult
from fin_assist.agents.shell import ShellAgent


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


class TestShellAgentBuildPydanticAgent:
    def test_returns_pydantic_agent(self, mock_config, mock_credentials) -> None:
        from pydantic_ai import Agent

        agent = ShellAgent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()

        assert isinstance(built, Agent)

    def test_no_thinking_capabilities(self, mock_config, mock_credentials) -> None:
        """ShellAgent uses the BaseAgent default — no thinking capabilities."""
        agent = ShellAgent(mock_config, mock_credentials)
        built = agent.build_pydantic_agent()

        assert not built._root_capability.capabilities
