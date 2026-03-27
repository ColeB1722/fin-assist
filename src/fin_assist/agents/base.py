from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fin_assist.context.base import ContextItem


@dataclass
class AgentResult:
    success: bool
    output: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent[T](ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier (used for routing, e.g. 'shell', 'sdd', 'tdd')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for agent selection UI."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Agent-specific system instructions."""
        ...

    @property
    @abstractmethod
    def output_type(self) -> type[T]:
        """Pydantic model for structured output."""
        ...

    @abstractmethod
    def supports_context(self, context_type: str) -> bool:
        """Check if agent can use a given context type."""
        ...

    @abstractmethod
    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult[T]:
        """Execute the agent."""
        ...
