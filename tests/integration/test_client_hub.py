"""Integration tests: HubClient → ASGI hub → FakeBackend.

These tests exercise the full in-process request path without subprocesses,
real LLM calls, or network I/O.  They cover the automated (Part 1) scenarios
from ``docs/manual-testing.md`` that can be tested without a TTY.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from a2a.client.errors import AgentCardResolutionError
from a2a.types import Part

from fin_assist.agents.spec import AgentSpec
from fin_assist.agents.step import StepEvent
from fin_assist.agents.tools import DeferredToolCall
from fin_assist.cli.client import HubClient, StreamEvent
from tests.integration.conftest import FakeBackend, FakeStepHandle, _make_hub_client


async def _stream_result(client: HubClient, agent: str, prompt: str, **kwargs) -> StreamEvent:
    """Return the terminal event from ``stream_agent()``."""
    terminal_kinds = {"completed", "failed", "auth_required", "input_required"}
    async for event in client.stream_agent(agent, prompt, **kwargs):
        if event.kind in terminal_kinds:
            return event
    return StreamEvent(kind="failed", result=None)


# -----------------------------------------------------------------------
# 1b. Agent Listing  (manual tests A1, A2)
# -----------------------------------------------------------------------


class TestAgentDiscovery:
    """Covers manual tests A1/A2: ``fin agents`` discovers mounted agents."""

    async def test_discover_agents_returns_all_mounted(self, hub_client: HubClient) -> None:
        agents = await hub_client.discover_agents()
        names = {a.name for a in agents}
        assert names == {"shell", "default"}

    async def test_discover_agents_has_descriptions(self, hub_client: HubClient) -> None:
        agents = await hub_client.discover_agents()
        by_name = {a.name: a for a in agents}
        assert by_name["shell"].description == "Shell agent"
        assert by_name["default"].description == "Default agent"

    async def test_discover_agents_has_urls(self, hub_client: HubClient) -> None:
        agents = await hub_client.discover_agents()
        for agent in agents:
            assert agent.url.endswith(f"/agents/{agent.name}/")

    async def test_discover_agents_has_card_meta(self, hub_client: HubClient) -> None:
        agents = await hub_client.discover_agents()
        by_name = {a.name: a for a in agents}
        assert by_name["shell"].card_meta.serving_modes == ["do"]
        assert by_name["default"].card_meta.serving_modes == ["do", "talk"]


# -----------------------------------------------------------------------
# 1c. One-Shot Dispatch  (manual tests A4, A5, A13)
# -----------------------------------------------------------------------


class TestOneShotDispatch:
    """Covers manual tests A4/A5: ``fin do default "hello"`` returns a result."""

    async def test_run_default_agent(self, hub_client: HubClient) -> None:
        events = []
        async for event in hub_client.stream_agent("default", "hello"):
            events.append(event)
        completed = [e for e in events if e.kind == "completed"]
        assert len(completed) == 1
        assert completed[0].result.success is True
        assert "response from default" in completed[0].result.output

    async def test_run_shell_agent(self, hub_client: HubClient) -> None:
        events = []
        async for event in hub_client.stream_agent("shell", "list files"):
            events.append(event)
        completed = [e for e in events if e.kind == "completed"]
        assert len(completed) == 1
        assert completed[0].result.success is True
        assert "response from shell" in completed[0].result.output


class TestUnknownAgent:
    """Covers manual test A13: ``fin do nonexistent "hi"`` fails."""

    async def test_unknown_agent_raises(self, hub_client: HubClient) -> None:
        with pytest.raises(AgentCardResolutionError):
            async for _ in hub_client.stream_agent("nonexistent", "hi"):
                pass


# -----------------------------------------------------------------------
# 1e. Credentials / Auth-Required  (manual tests F1, F3)
# -----------------------------------------------------------------------


class TestAuthRequired:
    """Covers manual tests F1/F3: missing credentials → auth-required flow."""

    @pytest.fixture
    async def auth_client(self, fake_agents: list[AgentSpec]) -> AsyncIterator[HubClient]:
        def factory(spec: AgentSpec) -> FakeBackend:
            return FakeBackend(missing_providers=["anthropic"])

        client = _make_hub_client(fake_agents, backend_factory=factory)
        yield client
        await client.close()

    async def test_auth_required_result(self, auth_client: HubClient) -> None:
        event = await _stream_result(auth_client, "default", "hello")
        assert event.kind == "auth_required"
        assert event.result.auth_required is True
        assert event.result.success is False

    async def test_recovery_after_credential_fix(self, fake_agents: list[AgentSpec]) -> None:
        def bad_factory(spec: AgentSpec) -> FakeBackend:
            return FakeBackend(missing_providers=["anthropic"])

        def good_factory(spec: AgentSpec) -> FakeBackend:
            return FakeBackend(response="all good")

        bad_client = _make_hub_client(fake_agents, backend_factory=bad_factory)
        event = await _stream_result(bad_client, "default", "hello")
        await bad_client.close()
        assert event.result.auth_required is True

        good_client = _make_hub_client(fake_agents, backend_factory=good_factory)
        event = await _stream_result(good_client, "default", "hello")
        await good_client.close()
        assert event.result.success is True
        assert event.result.output == "all good"


# -----------------------------------------------------------------------
# Streaming round-trip  (not in manual-testing.md, but fills a coverage gap)
# -----------------------------------------------------------------------


class TestStreamingRoundTrip:
    """Exercise ``stream_agent()`` end-to-end through the ASGI hub."""

    async def test_stream_yields_text_deltas(self, hub_client: HubClient) -> None:
        events = []
        async for event in hub_client.stream_agent("default", "hello"):
            events.append(event)

        text_events = [e for e in events if e.kind == "text_delta"]
        assert len(text_events) >= 1
        assert any("response from default" in e.text for e in text_events)

    async def test_stream_ends_with_completed(self, hub_client: HubClient) -> None:
        events = []
        async for event in hub_client.stream_agent("default", "hello"):
            events.append(event)

        assert events[-1].kind == "completed"
        assert events[-1].result is not None
        assert events[-1].result.success is True

    async def test_stream_populates_result_output_from_artifacts(
        self, hub_client: HubClient
    ) -> None:
        events = []
        async for event in hub_client.stream_agent("default", "hello"):
            events.append(event)

        completed = [e for e in events if e.kind == "completed"]
        assert len(completed) == 1
        assert completed[0].result.output != ""

    async def test_stream_with_thinking(self, fake_agents: list[AgentSpec]) -> None:
        def factory(spec: AgentSpec) -> FakeBackend:
            return FakeBackend(response="answer", thinking=["hmm", "let me think"])

        client = _make_hub_client(fake_agents, backend_factory=factory)

        events = []
        async for event in client.stream_agent("default", "hello"):
            events.append(event)
        await client.close()

        thinking_events = [e for e in events if e.kind == "thinking_delta"]
        assert len(thinking_events) == 2
        assert thinking_events[0].text == "hmm"
        assert thinking_events[1].text == "let me think"

    async def test_stream_auth_required(self, fake_agents: list[AgentSpec]) -> None:
        def factory(spec: AgentSpec) -> FakeBackend:
            return FakeBackend(missing_providers=["anthropic"])

        client = _make_hub_client(fake_agents, backend_factory=factory)

        events = []
        async for event in client.stream_agent("default", "hello"):
            events.append(event)
        await client.close()

        assert events[-1].kind == "auth_required"
        assert events[-1].result is not None
        assert events[-1].result.auth_required is True


# -----------------------------------------------------------------------
# Multi-turn conversation  (not in manual-testing.md manual Part 1)
# -----------------------------------------------------------------------


class TestMultiTurnConversation:
    """Exercise multi-turn conversation via ``stream_agent()`` with ``context_id``."""

    async def test_context_id_returned(self, hub_client: HubClient) -> None:
        event = await _stream_result(hub_client, "default", "first message")
        assert event.result is not None
        assert event.result.context_id is not None

    async def test_multi_turn_preserves_context(self, hub_client: HubClient) -> None:
        first = await _stream_result(hub_client, "default", "first message")
        assert first.result is not None
        assert first.result.context_id is not None

        second = await _stream_result(
            hub_client, "default", "second message", context_id=first.result.context_id
        )
        assert second.result is not None
        assert second.result.success is True


# -----------------------------------------------------------------------
# Health / infrastructure  (manual test A7)
# -----------------------------------------------------------------------


class TestHealthEndpoint:
    """Covers manual test A7's health check (in-process, not subprocess)."""

    async def test_health_returns_ok(self, raw_client: httpx.AsyncClient) -> None:
        resp = await raw_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# -----------------------------------------------------------------------
# Agent card extensions  (covers serving-mode metadata)
# -----------------------------------------------------------------------


class TestAgentCardExtensions:
    """Verify agent card extensions carry ``fin_assist:meta`` correctly."""

    async def test_shell_card_has_meta_extension(self, raw_client: httpx.AsyncClient) -> None:
        resp = await raw_client.get("/agents/shell/.well-known/agent-card.json")
        data = resp.json()
        extensions = data["capabilities"]["extensions"]
        uris = [e["uri"] for e in extensions]
        assert "fin_assist:meta" in uris

    async def test_default_card_has_serving_modes(self, raw_client: httpx.AsyncClient) -> None:
        resp = await raw_client.get("/agents/default/.well-known/agent-card.json")
        data = resp.json()
        extensions = data["capabilities"]["extensions"]
        meta = next((e for e in extensions if e["uri"] == "fin_assist:meta"), None)
        assert meta is not None, "Expected 'fin_assist:meta' extension not found"
        params = meta.get("params", {})
        assert params.get("serving_modes") == ["do", "talk"]


# -----------------------------------------------------------------------
# Deferred approval flow  (covers the full 8-file HITL path)
# -----------------------------------------------------------------------


class _DeferredBackend(FakeBackend):
    """Backend that emits a deferred StepEvent on first call, then completes on resume."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._call_count = 0

    def run_steps(
        self,
        *,
        messages: list[Any],
        model: Any = None,
        deferred_tool_results: Any = None,
    ) -> FakeStepHandle:
        from fin_assist.agents.backend import RunResult

        self._call_count += 1

        if deferred_tool_results is None and self._call_count == 1:
            text_event = StepEvent(kind="text_delta", content="Generating command...", step=0)
            deferred_event = StepEvent(
                kind="deferred",
                content=DeferredToolCall(
                    tool_name="run_shell",
                    tool_call_id="call_1",
                    args={"command": "echo hello"},
                    reason="Shell command execution requires approval",
                ),
                step=0,
                tool_name="run_shell",
            )
            return FakeStepHandle(
                events=[text_event, deferred_event],
                run_result=RunResult(
                    output=MagicMock(),
                    serialized_history=b'[{"deferred": true}]',
                    new_message_parts=[],
                ),
            )

        return super().run_steps(
            messages=messages, model=model, deferred_tool_results=deferred_tool_results
        )

    def deserialize_history(self, data: bytes) -> list[Any]:
        if data:
            return [MagicMock()]
        return []

    def build_deferred_results(self, decisions: list[Any]) -> Any:
        return MagicMock()


class TestDeferredApprovalFlow:
    """Exercise the full deferred approval path: defer → input_required → resume → completed."""

    @pytest.fixture
    async def deferred_client(self, fake_agents: list[AgentSpec]) -> AsyncIterator[HubClient]:
        def factory(spec: AgentSpec) -> _DeferredBackend:
            return _DeferredBackend(response="command executed successfully")

        client = _make_hub_client(fake_agents, backend_factory=factory)
        yield client
        await client.close()

    async def test_stream_yields_input_required(self, deferred_client: HubClient) -> None:
        events = []
        async for event in deferred_client.stream_agent("shell", "run echo hello"):
            events.append(event)

        terminal_events = [
            e
            for e in events
            if e.kind in ("input_required", "auth_required", "completed", "failed")
        ]
        assert len(terminal_events) >= 1
        assert terminal_events[-1].kind == "input_required"

    async def test_approve_and_resume_completes(self, deferred_client: HubClient) -> None:
        events = []
        async for event in deferred_client.stream_agent("shell", "run echo hello"):
            events.append(event)

        input_required_events = [e for e in events if e.kind == "input_required"]
        assert len(input_required_events) == 1
        context_id = input_required_events[0].result.context_id

        resume_events = []
        decisions = [{"tool_call_id": "call_1", "approved": True}]
        async for event in deferred_client.stream_agent(
            "shell",
            "",
            context_id=context_id,
            approval_decisions=decisions,
        ):
            resume_events.append(event)

        assert resume_events[-1].kind == "completed"
        assert resume_events[-1].result.success is True

    async def test_deny_and_resume_completes(self, deferred_client: HubClient) -> None:
        events = []
        async for event in deferred_client.stream_agent("shell", "run echo hello"):
            events.append(event)

        input_required_events = [e for e in events if e.kind == "input_required"]
        assert len(input_required_events) == 1
        context_id = input_required_events[0].result.context_id

        resume_events = []
        decisions = [{"tool_call_id": "call_1", "approved": False, "denial_reason": "User denied"}]
        async for event in deferred_client.stream_agent(
            "shell",
            "",
            context_id=context_id,
            approval_decisions=decisions,
        ):
            resume_events.append(event)

        assert resume_events[-1].kind == "completed"
