from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast, get_args

from pydantic import BaseModel, Field

from fin_assist.context.base import ContextType
from fin_assist.providers import PROVIDER_META

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.models import Model

    from fin_assist.config.schema import Config
    from fin_assist.credentials.store import CredentialStore
    from fin_assist.llm.model_registry import ProviderRegistry


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

    tags: list[str] = Field(default_factory=list)
    """Categorisation tags (e.g. ['shell', 'one-shot'])."""

    requires_approval: bool = False
    """If True, CLI shows approval widget before executing the suggested action."""


class BaseAgent[T](ABC):
    """Base class for all agents.

    Provides the abstract interface (``name``, ``description``, ``system_prompt``,
    ``output_type``) that every agent must implement, plus concrete defaults for
    context support, model building, and pydantic-ai Agent construction.

    Subclasses override ``agent_card_metadata`` to publish their capabilities and
    may override ``build_pydantic_agent`` to customise Agent construction (e.g.
    add thinking capabilities, tools, etc.).
    """

    def __init__(self, config: Config, credentials: CredentialStore) -> None:
        self._config = config
        self._credentials = credentials
        self._registry = None

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        """Static UI/capability hints published in the A2A agent card.

        The default is ``AgentCardMeta()`` (multi-turn, thinking, model selection all on).
        Override to customise -- e.g. one-shot shell agents set ``multi_turn=False``.
        """
        return AgentCardMeta()

    # ------------------------------------------------------------------
    # Abstract properties -- subclasses must implement
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Context support
    # ------------------------------------------------------------------

    _SUPPORTED_CONTEXT_TYPES: frozenset[str] = frozenset(get_args(ContextType))

    def supports_context(self, context_type: str) -> bool:
        """Return True if this agent can use context items of the given type.

        Default accepts all ``ContextType`` values.  Override in subclasses that
        only support a subset (e.g. a docs-only agent).
        """
        return context_type in self._SUPPORTED_CONTEXT_TYPES

    # ------------------------------------------------------------------
    # pydantic-ai Agent construction
    # ------------------------------------------------------------------

    def build_pydantic_agent(self) -> Agent[Any, T]:
        """Build the pydantic-ai Agent that fasta2a's AgentWorker will execute.

        The Agent is constructed **without a model** — pydantic-ai accepts
        ``model=None`` at construction and resolves it at run time via the
        ``model`` parameter on ``agent.run()``.  This lets the hub start and
        serve discovery/health endpoints even when credentials are not yet
        configured.

        ``FinAssistWorker`` calls ``build_model()`` on the agent definition
        before each task and passes the result to the pydantic-ai agent's
        ``.run(model=...)``.  If credentials are missing,
        ``MissingCredentialsError`` is caught and translated to
        ``auth-required`` task state instead of crashing the hub.

        Override to add thinking, tools, etc. (see ``DefaultAgent``).
        """
        from pydantic_ai import Agent

        return cast(
            "Agent[Any, T]",
            Agent(
                output_type=self.output_type,
                instructions=self.system_prompt,
            ),
        )

    # ------------------------------------------------------------------
    # Credential validation
    # ------------------------------------------------------------------

    def check_credentials(self) -> list[str]:
        """Return names of enabled providers that require an API key but have none configured.

        An empty list means all credentials are present.
        """
        missing: list[str] = []
        for provider in self._get_enabled_providers():
            meta = PROVIDER_META.get(provider)
            if (
                meta is not None
                and meta.requires_api_key
                and not self._credentials.get_api_key(provider)
            ):
                missing.append(provider)
        return missing

    # ------------------------------------------------------------------
    # Shared model-building utilities
    # ------------------------------------------------------------------

    def _get_registry(self) -> ProviderRegistry:
        if self._registry is None:
            from fin_assist.llm.model_registry import ProviderRegistry

            self._registry = ProviderRegistry()
        return self._registry

    def build_model(self) -> Model:
        from pydantic_ai.models.fallback import FallbackModel

        missing = self.check_credentials()
        if missing:
            raise MissingCredentialsError(providers=missing)

        default_model = self._config.general.default_model
        enabled_providers = self._get_enabled_providers()

        if len(enabled_providers) == 1:
            provider_name = enabled_providers[0]
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self._credentials.get_api_key(provider_name)
            return self._get_registry().create_model(provider_name, model_name, api_key=api_key)

        models = []
        for provider_name in enabled_providers:
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self._credentials.get_api_key(provider_name)
            model = self._get_registry().create_model(provider_name, model_name, api_key=api_key)
            models.append(model)

        return FallbackModel(*models)

    def _get_model_name(self, provider: str, default: str) -> str:
        provider_config = self._config.providers.get(provider)
        if provider_config and provider_config.default_model:
            return provider_config.default_model
        return default

    def _get_enabled_providers(self) -> list[str]:
        default_provider = self._config.general.default_provider
        enabled = [default_provider]
        for name, provider_config in self._config.providers.items():
            if name != default_provider and provider_config.enabled:
                enabled.append(name)
        return enabled
