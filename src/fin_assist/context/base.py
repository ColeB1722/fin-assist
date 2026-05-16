from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from fin_assist.config.schema import ContextSettings

ContextType = Literal["file", "git_diff", "git_log", "git_status", "history", "env"]
ItemStatus = Literal["available", "not_found", "excluded", "error"]


@dataclass
class ContextItem:
    id: str
    type: ContextType
    content: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    status: ItemStatus = "available"
    error_reason: str | None = None


class ContextProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[ContextItem]:
        """Search for context items matching query."""

    @abstractmethod
    def get_item(self, id: str) -> ContextItem:
        """Get a specific context item by ID.

        Returns:
            ContextItem with explicit status:
            - "available": item found and returned
            - "not_found": ID does not exist in this provider
            - "excluded": excluded by policy (e.g., size limit)
            - "error": failed to retrieve (error details in error_reason)
        """

    @abstractmethod
    def get_all(self) -> list[ContextItem]:
        """Get all available context items from this provider."""

    def supports_context(self, context_type: ContextType) -> bool:
        """Check if this provider supports a given context type."""
        return context_type in self._supported_types()

    @abstractmethod
    def _supported_types(self) -> set[ContextType]:
        """Return the set of context types this provider supports."""
        ...


class ContextProviderRegistry:
    """Global registry of context providers.  Shared across all agents.

    Providers are registered once (at startup) and looked up by the
    ``ContextType`` they support.  Each type has exactly one provider.
    """

    def __init__(self) -> None:
        self._providers: dict[ContextType, ContextProvider] = {}
        self._providers_by_id: dict[int, ContextProvider] = {}

    def register(self, provider: ContextProvider) -> None:
        """Register a provider and index it by the types it supports."""
        provider_id = id(provider)
        if provider_id in self._providers_by_id:
            raise ValueError(f"Provider instance {provider!r} is already registered")
        self._providers_by_id[provider_id] = provider
        for ct in provider._supported_types():
            if ct in self._providers:
                existing = self._providers[ct].__class__.__name__
                raise ValueError(f"Context type '{ct}' already has a provider ({existing})")
            self._providers[ct] = provider

    def get_by_type(self, context_type: ContextType) -> ContextProvider | None:
        """Return the provider responsible for *context_type*, or None."""
        return self._providers.get(context_type)

    def list_providers(self) -> list[ContextProvider]:
        """Return all registered providers (deduplicated)."""
        return list(self._providers_by_id.values())

    def list_types(self) -> list[ContextType]:
        """Return all context types with a registered provider."""
        return list(self._providers.keys())


def create_default_context_registry(
    settings: ContextSettings | None = None,
) -> ContextProviderRegistry:
    """Create a ``ContextProviderRegistry`` pre-loaded with built-in providers.

    The built-in providers cover the six core context types:
    ``file``, ``git_diff``, ``git_log``, ``git_status``, ``history``, ``env``.
    """
    from fin_assist.context.environment import Environment
    from fin_assist.context.files import FileFinder
    from fin_assist.context.git import GitContext
    from fin_assist.context.history import ShellHistory

    registry = ContextProviderRegistry()
    registry.register(FileFinder(settings=settings))
    registry.register(GitContext(settings=settings))
    registry.register(ShellHistory(settings=settings))
    registry.register(Environment())
    return registry
