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


@dataclass
class AgentCardMeta:
    multi_turn: bool = True
    supports_thinking: bool = True
    supports_model_selection: bool = True
    supported_providers: list[str] | None = None
    color_scheme: str | None = None
    tags: list[str] = field(default_factory=list)


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
    ) -> AgentResult:
        """Execute the agent."""
        ...

    @property
    def supports_model_selection(self) -> bool:
        """Whether this agent supports model/provider selection.

        Some agents only work with specific models (e.g., vision models).
        Return False to hide the model selector in the UI.
        """
        return True

    @property
    def supported_providers(self) -> list[str] | None:
        """List of providers this agent supports, or None for all providers.

        Some agents may only work with certain providers.
        Return None to allow all configured providers.
        """
        return None

    @property
    def supports_thinking(self) -> bool:
        """Whether this agent supports chain-of-thought thinking.

        If False, the thinking selector should be hidden in the UI.
        """
        return True

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        return AgentCardMeta(
            multi_turn=self.supports_thinking,
            supports_thinking=self.supports_thinking,
            supports_model_selection=self.supports_model_selection,
            supported_providers=self.supported_providers,
        )
