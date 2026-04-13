"""Agent metadata types: AgentCardMeta, AgentResult, MissingCredentialsError, ServingMode.

These types are used across the hub, CLI, and worker — they have no dependency
on the ConfigAgent class itself, so they live in their own module to avoid
circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

ServingMode = Literal["do", "talk"]


class MissingCredentialsError(Exception):
    """Raised when an agent cannot run because required API keys are missing.

    Carries the list of provider names that need credentials so the worker
    can set ``auth-required`` task state with a helpful message.
    """

    def __init__(self, *, providers: list[str]) -> None:
        self.providers = providers
        hints = ", ".join(f"{p.upper()}_API_KEY" for p in providers)
        super().__init__(
            f"Missing API key for: {', '.join(providers)}. "
            f"Set {hints} or use `fin connect` to configure credentials."
        )


@dataclass
class AgentResult:
    success: bool
    output: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentCardMeta(BaseModel):
    """Static UI/capability metadata published in the A2A agent card extension.

    Clients read these fields to decide which UI elements to show or hide without
    needing any agent-specific knowledge.
    """

    serving_modes: list[ServingMode] = Field(default_factory=lambda: ["do", "talk"])
    """Which CLI invocation modes this agent supports. Determines whether
    ``fin do <agent>`` and/or ``fin talk <agent>`` are valid."""

    multi_turn: bool = True
    """True if the agent supports multi-turn conversation (context_id threading).
    Derived from serving_modes — True when "talk" is present."""

    supports_thinking: bool = True
    """True if the agent benefits from chain-of-thought / thinking effort selector."""

    supports_model_selection: bool = True
    """True if the agent can work with any configured provider/model."""

    supported_providers: list[str] | None = None
    """Restrict to specific providers. None means all configured providers."""

    color_scheme: str | None = None
    """Optional theming hint for clients."""

    tags: list[str] = Field(default_factory=list)
    """Categorisation tags (e.g. ['shell', 'one-shot'])."""

    requires_approval: bool = False
    """If True, CLI shows approval widget before executing the suggested action."""
