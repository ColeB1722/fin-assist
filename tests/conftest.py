from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fin_assist.agents.base import AgentResult, BaseAgent
from fin_assist.agents.results import CommandResult
from fin_assist.context.base import ContextItem


class ConcreteAgent(BaseAgent[CommandResult]):
    @property
    def name(self) -> str:
        return "test_agent"

    @property
    def description(self) -> str:
        return "A test agent"

    @property
    def system_prompt(self) -> str:
        return "Test prompt"

    @property
    def output_type(self) -> type[CommandResult]:
        return CommandResult

    def supports_context(self, context_type: str) -> bool:
        return True

    async def run(self, prompt: str, context: list[ContextItem]) -> AgentResult:
        return AgentResult(success=True, output="test", warnings=[], metadata={})


class AnotherAgent(BaseAgent[CommandResult]):
    @property
    def name(self) -> str:
        return "another_agent"

    @property
    def description(self) -> str:
        return "Another test agent"

    @property
    def system_prompt(self) -> str:
        return "Another prompt"

    @property
    def output_type(self) -> type[CommandResult]:
        return CommandResult

    def supports_context(self, context_type: str) -> bool:
        return False

    async def run(self, prompt: str, context: list[ContextItem]) -> AgentResult:
        return AgentResult(success=True, output="another", warnings=[], metadata={})


@pytest.fixture
def clean_registry():
    from fin_assist.agents.registry import AgentRegistry

    AgentRegistry._agents.clear()
    yield
    AgentRegistry._agents.clear()


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.general.default_provider = "anthropic"
    config.general.default_model = "claude-sonnet-4-6"
    config.providers = {}
    return config


@pytest.fixture
def mock_credentials():
    creds = MagicMock()
    creds.get_api_key.return_value = "test-key"
    return creds


@pytest.fixture
def expected_context_types():
    from fin_assist.context.base import ContextType

    return frozenset(ContextType.__args__)
