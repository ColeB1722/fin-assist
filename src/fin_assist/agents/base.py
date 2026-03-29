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
    """Static UI/capability metadata published in the A2A agent card extension.

    Clients read these fields to decide which UI elements to show or hide without
    needing any agent-specific knowledge.
    """

    multi_turn: bool = True
    """True if the agent supports multi-turn conversation (context_id threading)."""

    supports_thinking: bool = True
    """True if the agent benefits from chain-of-thought / thinking effort selector."""

    supports_model_selection: bool = True
    """True if the agent can work with any configured provider/model."""

    supported_providers: list[str] | None = None
    """Restrict to specific providers. None means all configured providers."""

    color_scheme: str | None = None
    """Optional theming hint for clients."""

    tags: list[str] = field(default_factory=list)
    """Categorisation tags (e.g. ['shell', 'one-shot'])."""

    # Future (Phase 11 — TUI client):
    #   Add ``supported_context_types: list[str] | None = None`` here so that
    #   clients can show/hide context panels (git diff, shell history, etc.) based
    #   on which agent is active without needing a round-trip call.
    #
    #   At that point ``BaseAgent.supports_context()`` and this field will be kept
    #   in sync — either by having agents declare both explicitly, or by adding a
    #   default ``agent_card_metadata`` implementation that derives the field from
    #   ``ContextType.__args__`` filtered through ``self.supports_context()``.
    #
    #   Not added now because no client currently reads context-type hints from
    #   the agent card — premature until Phase 11.


class BaseAgent[T](ABC):
    """Protocol that all specialised agents must implement.

    Subclasses override ``agent_card_metadata`` to publish their capabilities.
    """

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        """Static UI/capability hints published in the A2A agent card.

        The default is ``AgentCardMeta()`` (multi-turn, thinking, model selection all on).
        Override to customise — e.g. one-shot shell agents set ``multi_turn=False``.
        """
        return AgentCardMeta()

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier used as the routing path segment: /agents/{name}/."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for agent discovery."""
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
        """Return True if this agent can use context items of the given type."""
        ...

    @abstractmethod
    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult:
        """Execute the agent and return an AgentResult."""
        ...
