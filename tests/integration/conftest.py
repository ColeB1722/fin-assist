"""Integration test fixtures.

Provides a ``FakeBackend`` that satisfies the ``AgentBackend`` protocol,
plus fixtures that wire ``HubClient`` → ASGI hub → ``FakeBackend`` with
zero subprocesses and zero LLM calls.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from a2a.types import Part

from fin_assist.agents.backend import AgentBackend, RunResult
from fin_assist.agents.metadata import AgentCardMeta
from fin_assist.agents.spec import AgentSpec
from fin_assist.agents.step import StepEvent
from fin_assist.cli.client import HubClient
from fin_assist.config.schema import AgentConfig
from fin_assist.hub.app import create_hub_app


def _make_hub_client(
    fake_agents: list[AgentSpec],
    *,
    backend_factory: Any = None,
) -> HubClient:
    """Create a ``HubClient`` wired to an in-process ASGI hub."""
    kwargs: dict[str, Any] = dict(
        agents=fake_agents,
        db_path=":memory:",
        base_url="http://testserver",
    )
    if backend_factory is not None:
        kwargs["backend_factory"] = backend_factory
    app = create_hub_app(**kwargs)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return HubClient(base_url="http://testserver", http_client=http_client)


class FakeStepHandle:
    """Deterministic ``StepHandle`` that yields pre-set step events."""

    def __init__(self, events: list[StepEvent], run_result: RunResult) -> None:
        self._events = events
        self._run_result = run_result

    async def __aiter__(self) -> AsyncIterator[StepEvent]:
        for event in self._events:
            yield event

    async def result(self) -> RunResult:
        return self._run_result


class FakeBackend:
    """Deterministic ``AgentBackend`` for integration tests.

    Parameters
    ----------
    response:
        Text content for the final text delta.
    thinking:
        List of thinking strings; each becomes a ``StreamDelta(kind="thinking")``.
    missing_providers:
        Non-empty list triggers ``auth-required`` via ``check_credentials()``.
    structured_output:
        If provided, used as ``RunResult.output`` instead of *response*.
    new_message_parts:
        Forwarded to ``RunResult.new_message_parts``.
    """

    def __init__(
        self,
        *,
        response: str = "test response",
        thinking: list[str] | None = None,
        missing_providers: list[str] | None = None,
        structured_output: Any = None,
        new_message_parts: list[Part] | None = None,
    ) -> None:
        self._response = response
        self._thinking = thinking or []
        self._missing_providers = missing_providers or []
        self._output = structured_output or response
        self._new_message_parts = new_message_parts or []

    def check_credentials(self) -> list[str]:
        return self._missing_providers

    def convert_history(self, a2a_messages: Sequence[Any]) -> list[Any]:
        return []

    def run_steps(self, *, messages: list[Any], model: Any = None) -> FakeStepHandle:
        events = [StepEvent(kind="thinking_delta", content=t, step=0) for t in self._thinking]
        events.append(StepEvent(kind="text_delta", content=self._response, step=0))
        result = RunResult(
            output=self._output,
            serialized_history=b"[]",
            new_message_parts=self._new_message_parts,
        )
        return FakeStepHandle(events=events, run_result=result)

    def serialize_history(self, messages: list[Any]) -> bytes:
        return b"[]"

    def deserialize_history(self, data: bytes) -> list[Any]:
        return []

    def convert_result_to_part(self, result: Any) -> Part:
        return Part(text=str(result))

    def convert_response_parts(self, parts: Sequence[Any]) -> list[Part]:
        return []


def _make_agent_specs(mock_config: MagicMock, mock_credentials: MagicMock) -> list[AgentSpec]:
    shell_config = AgentConfig(
        description="Shell agent",
        system_prompt="shell",
        output_type="command",
        thinking="off",
        serving_modes=["do"],
        requires_approval=True,
        tags=["shell", "one-shot"],
    )
    default_config = AgentConfig(
        description="Default agent",
        system_prompt="chain-of-thought",
        output_type="text",
        thinking="medium",
        serving_modes=["do", "talk"],
    )
    return [
        AgentSpec(
            name="shell",
            agent_config=shell_config,
            config=mock_config,
            credentials=mock_credentials,
        ),
        AgentSpec(
            name="default",
            agent_config=default_config,
            config=mock_config,
            credentials=mock_credentials,
        ),
    ]


@pytest.fixture
def fake_agents(mock_config: MagicMock, mock_credentials: MagicMock) -> list[AgentSpec]:
    return _make_agent_specs(mock_config, mock_credentials)


@pytest.fixture
def fake_backend_factory() -> type[FakeBackend]:
    """Return the ``FakeBackend`` class itself; tests can subclass or wrap."""
    return FakeBackend


@pytest.fixture
async def hub_client(
    fake_agents: list[AgentSpec],
) -> AsyncIterator[HubClient]:
    """Full integration: ``HubClient`` → ASGI hub → ``FakeBackend``.

    Each agent gets a ``FakeBackend(response="response from {name}")``.
    """

    def factory(spec: AgentSpec) -> FakeBackend:
        return FakeBackend(response=f"response from {spec.name}")

    client = _make_hub_client(fake_agents, backend_factory=factory)
    yield client
    await client.close()


@pytest.fixture
async def raw_client(fake_agents: list[AgentSpec]) -> AsyncIterator[httpx.AsyncClient]:
    """Raw ``httpx.AsyncClient`` pointed at the ASGI hub (no A2A client layer)."""
    app = create_hub_app(agents=fake_agents, db_path=":memory:")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
