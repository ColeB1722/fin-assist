"""Tests for BaseAgent ABC and AgentCardMeta."""

from __future__ import annotations

from abc import ABC

from fin_assist.agents.base import AgentCardMeta, AgentResult, BaseAgent
from fin_assist.context.base import ContextItem


# -- Fixtures -----------------------------------------------------------------


class DummyAgent(BaseAgent[str]):
    """Minimal concrete agent for testing ABC defaults."""

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

    def supports_context(self, context_type: str) -> bool:
        return False

    async def run(self, prompt: str, context: list[ContextItem]) -> AgentResult:
        raise NotImplementedError


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

    def test_abstract_methods(self) -> None:
        for attr in ("supports_context", "run"):
            assert getattr(BaseAgent, attr).__isabstractmethod__ is True

    def test_is_generic(self) -> None:
        assert hasattr(BaseAgent, "__class_getitem__")


class TestBaseAgentDefaults:
    def test_default_agent_card_metadata(self) -> None:
        agent = DummyAgent()
        meta = agent.agent_card_metadata
        assert isinstance(meta, AgentCardMeta)
        assert meta == AgentCardMeta()

    def test_agent_card_metadata_overridable(self) -> None:
        """agent_card_metadata should not be abstract — subclasses can override."""
        assert getattr(BaseAgent.agent_card_metadata, "__isabstractmethod__", False) is False
