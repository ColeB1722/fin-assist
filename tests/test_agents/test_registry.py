from __future__ import annotations

import pytest

from fin_assist.agents.registry import AgentRegistry

from tests.conftest import AnotherAgent, ConcreteAgent


class TestAgentRegistry:
    def test_register_adds_agent_to_registry(self, clean_registry) -> None:
        AgentRegistry.register(ConcreteAgent)
        assert AgentRegistry.get("test_agent") is not None
        assert isinstance(AgentRegistry.get("test_agent"), ConcreteAgent)

    def test_register_returns_agent_class(self, clean_registry) -> None:
        result = AgentRegistry.register(ConcreteAgent)
        assert result is ConcreteAgent

    def test_get_returns_agent_instance(self, clean_registry) -> None:
        AgentRegistry.register(ConcreteAgent)
        agent = AgentRegistry.get("test_agent")
        assert agent is not None
        assert isinstance(agent, ConcreteAgent)

    def test_get_returns_none_for_unregistered_agent(self, clean_registry) -> None:
        agent = AgentRegistry.get("nonexistent")
        assert agent is None

    def test_get_returns_new_instance_each_time(self, clean_registry) -> None:
        AgentRegistry.register(ConcreteAgent)
        agent1 = AgentRegistry.get("test_agent")
        agent2 = AgentRegistry.get("test_agent")
        assert agent1 is not agent2

    def test_list_agents_returns_all_registered(self, clean_registry) -> None:
        AgentRegistry.register(ConcreteAgent)
        AgentRegistry.register(AnotherAgent)
        agents = AgentRegistry.list_agents()
        assert len(agents) == 2
        assert ("test_agent", "A test agent") in agents
        assert ("another_agent", "Another test agent") in agents

    def test_list_agents_empty_when_no_agents(self, clean_registry) -> None:
        agents = AgentRegistry.list_agents()
        assert agents == []

    def test_decorator_registers_agent(self, clean_registry) -> None:
        @AgentRegistry.register
        class DecoratedAgent(ConcreteAgent):
            @property
            def name(self) -> str:
                return "decorated"

        assert AgentRegistry.get("decorated") is not None
        assert isinstance(AgentRegistry.get("decorated"), DecoratedAgent)

    def test_multiple_registrations_with_different_names(self, clean_registry) -> None:
        AgentRegistry.register(ConcreteAgent)
        AgentRegistry.register(AnotherAgent)
        agents = AgentRegistry.list_agents()
        names = [name for name, _ in agents]
        assert "test_agent" in names
        assert "another_agent" in names
