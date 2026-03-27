from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fin_assist.agents.base import BaseAgent


class AgentRegistry:
    _agents: dict[str, type[BaseAgent]] = {}

    @classmethod
    def register(cls, agent_cls: type[BaseAgent]) -> type[BaseAgent]:
        """Decorator to register an agent class."""
        agent = agent_cls()
        cls._agents[agent.name] = agent_cls
        return agent_cls

    @classmethod
    def get(cls, name: str) -> BaseAgent | None:
        """Get agent instance by name."""
        agent_cls = cls._agents.get(name)
        if agent_cls is None:
            return None
        return agent_cls()

    @classmethod
    def list_agents(cls) -> list[tuple[str, str]]:
        """List all registered agents as (name, description) pairs."""
        result: list[tuple[str, str]] = []
        for agent_cls in cls._agents.values():
            agent = agent_cls()
            result.append((agent.name, agent.description))
        return result
