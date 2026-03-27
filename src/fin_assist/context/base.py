from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

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
