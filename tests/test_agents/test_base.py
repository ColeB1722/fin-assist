from __future__ import annotations

from abc import ABC

import pytest

from fin_assist.agents.base import AgentResult, BaseAgent


class TestAgentResult:
    def test_agent_result_creation(self) -> None:
        result = AgentResult(success=True, output="ls -la", warnings=[], metadata={})
        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []
        assert result.metadata == {}

    def test_agent_result_with_warnings(self) -> None:
        result = AgentResult(
            success=True,
            output="rm -rf /",
            warnings=["Destructive operation"],
            metadata={},
        )
        assert result.success is True
        assert result.output == "rm -rf /"
        assert result.warnings == ["Destructive operation"]

    def test_agent_result_with_metadata(self) -> None:
        result = AgentResult(
            success=True,
            output="echo hello",
            warnings=[],
            metadata={"provider": "anthropic", "model": "claude-sonnet-4-6"},
        )
        assert result.metadata["provider"] == "anthropic"
        assert result.metadata["model"] == "claude-sonnet-4-6"

    def test_agent_result_default_values(self) -> None:
        result = AgentResult(success=True, output="test")
        assert result.warnings == []
        assert result.metadata == {}

    def test_agent_result_output_is_str(self) -> None:
        result = AgentResult(success=True, output="ls")
        assert isinstance(result.output, str)


class TestBaseAgentABC:
    def test_base_agent_is_abc(self) -> None:
        assert issubclass(BaseAgent, ABC)

    def test_base_agent_has_required_properties(self) -> None:
        assert hasattr(BaseAgent, "name")
        assert hasattr(BaseAgent, "description")
        assert hasattr(BaseAgent, "system_prompt")
        assert hasattr(BaseAgent, "output_type")

    def test_base_agent_has_required_methods(self) -> None:
        assert hasattr(BaseAgent, "supports_context")
        assert hasattr(BaseAgent, "run")

    def test_base_agent_name_is_abstract(self) -> None:
        assert getattr(BaseAgent.name, "__isabstractmethod__", False) is True

    def test_base_agent_description_is_abstract(self) -> None:
        assert getattr(BaseAgent.description, "__isabstractmethod__", False) is True

    def test_base_agent_system_prompt_is_abstract(self) -> None:
        assert getattr(BaseAgent.system_prompt, "__isabstractmethod__", False) is True

    def test_base_agent_output_type_is_abstract(self) -> None:
        assert getattr(BaseAgent.output_type, "__isabstractmethod__", False) is True

    def test_base_agent_supports_context_is_abstract(self) -> None:
        assert getattr(BaseAgent.supports_context, "__isabstractmethod__", False) is True

    def test_base_agent_run_is_abstract(self) -> None:
        assert getattr(BaseAgent.run, "__isabstractmethod__", False) is True

    def test_base_agent_generic(self) -> None:
        assert hasattr(BaseAgent, "__class_getitem__")
