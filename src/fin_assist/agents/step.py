"""Platform-level step event types and the StepHandle protocol.

These types are framework-agnostic — they live in the ``agents/`` package
alongside ``AgentSpec`` and have **zero** imports from any LLM framework.
Backends emit ``StepEvent`` values; the Executor dispatches on ``kind``.

The ``content`` field carries framework-specific payloads (e.g., a
pydantic-ai ``ToolCallPart``) but the Executor treats it opaquely — it
only dispatches on ``kind`` and reads ``tool_name`` / ``metadata``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass
class StepEvent:
    """A single event emitted during one step of the agent loop.

    Any backend must emit these same event types.  The Executor treats
    ``content`` opaquely — it only dispatches on ``kind``.

    ``content`` contract by ``kind``:

    * ``text_delta`` / ``thinking_delta`` — ``str`` (delta text chunk).
    * ``tool_call`` — backend-specific call part; Executor reads only
      ``tool_name`` and ``metadata["args"]`` from the event, not
      ``content``.
    * ``tool_result`` — ``str`` (rendered tool output text).  Backends
      must convert framework-specific return parts to a plain string
      before emitting so the Executor stays framework-agnostic.
    * ``step_start`` / ``step_end`` — ``None``.
    * ``deferred`` — a ``DeferredToolCall`` (framework-agnostic
      dataclass from ``agents.tools``).
    """

    kind: Literal[
        "text_delta",
        "thinking_delta",
        "tool_call",
        "tool_result",
        "step_start",
        "step_end",
        "deferred",
    ]
    content: Any
    step: int
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class StepHandle(Protocol):
    """Async iterator of ``StepEvent`` values with a final ``RunResult``.

    Replaces the former ``StreamHandle``.  Consumers iterate events and
    then call ``result()`` to obtain the completed ``RunResult``.
    """

    def __aiter__(self) -> AsyncIterator[StepEvent]: ...
    async def result(self) -> Any: ...
