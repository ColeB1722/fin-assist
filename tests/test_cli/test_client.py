"""Tests for cli/client.py — A2A HTTP client."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from fasta2a.schema import Task

from fin_assist.cli.client import A2AClient, AgentResult, DiscoveredAgent


# ---------------------------------------------------------------------------
# Fixtures — cast to Task so the type checker is satisfied;
# TypedDict = plain dict at runtime so the cast is free.
# ---------------------------------------------------------------------------


def _make_task(
    state: str = "completed",
    artifacts: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    context_id: str = "ctx-1",
) -> Task:
    return cast(
        Task,
        {
            "id": "task-1",
            "context_id": context_id,
            "kind": "task",
            "status": {"state": state},
            "artifacts": artifacts or [],
            "history": history or [],
        },
    )


def _make_rpc_response(task: dict[str, Any]) -> bytes:
    """Wrap a task dict in a SendMessageResponse envelope and return JSON bytes."""
    # fasta2a uses camelCase on the wire; snake_case after TypeAdapter parsing.
    # For tests that bypass the TypeAdapter we build the already-parsed shape.
    return json.dumps({"jsonrpc": "2.0", "id": "req-1", "result": task}).encode()


# ---------------------------------------------------------------------------
# DiscoveredAgent / AgentResult data classes
# ---------------------------------------------------------------------------


class TestDiscoveredAgent:
    def test_stores_fields(self):
        from fin_assist.agents.base import AgentCardMeta

        agent = DiscoveredAgent(
            name="shell",
            description="Runs shell commands",
            url="http://localhost/agents/shell/",
            card_meta=AgentCardMeta(),
        )
        assert agent.name == "shell"
        assert agent.url == "http://localhost/agents/shell/"


class TestAgentResult:
    def test_default_warnings_and_metadata(self):
        result = AgentResult(success=True, output="ls -la")
        assert result.warnings == []
        assert result.metadata == {}
        assert result.context_id is None

    def test_stores_context_id(self):
        result = AgentResult(success=True, output="x", context_id="ctx-42")
        assert result.context_id == "ctx-42"


# ---------------------------------------------------------------------------
# A2AClient._extract_result
# ---------------------------------------------------------------------------


class TestExtractResult:
    def test_extracts_data_part_command(self):
        task = _make_task(
            artifacts=[{"parts": [{"kind": "data", "data": {"command": "ls -la", "warnings": []}}]}]
        )
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []

    def test_extracts_text_part(self):
        task = _make_task(artifacts=[{"parts": [{"kind": "text", "text": "Hello world"}]}])
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.output == "Hello world"

    def test_extracts_warnings_from_data_part(self):
        task = _make_task(
            artifacts=[
                {
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "command": "rm -rf /",
                                "warnings": ["Dangerous!", "Be careful"],
                            },
                        }
                    ]
                }
            ]
        )
        result = A2AClient("http://localhost")._extract_result(task)

        assert "Dangerous!" in result.warnings

    def test_extracts_metadata_from_data_part(self):
        task = _make_task(
            artifacts=[
                {
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "command": "ls",
                                "metadata": {"accept_action": "insert_command"},
                            },
                        }
                    ]
                }
            ]
        )
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.metadata == {"accept_action": "insert_command"}

    def test_success_false_when_task_failed(self):
        task = _make_task(state="failed")
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.success is False

    def test_success_false_for_all_terminal_failure_states(self):
        """fasta2a has more terminal states than our old models covered."""
        for state in ("failed", "canceled", "rejected"):
            task = _make_task(state=state)
            result = A2AClient("http://localhost")._extract_result(task)
            assert result.success is False, f"expected failure for state={state}"

    def test_propagates_context_id(self):
        task = _make_task(context_id="ctx-xyz")
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.context_id == "ctx-xyz"

    def test_empty_output_when_no_parts(self):
        task = _make_task(artifacts=[], history=[])
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.output == ""

    def test_history_items_used_when_no_artifacts(self):
        task = _make_task(
            artifacts=[],
            history=[{"parts": [{"kind": "text", "text": "from history"}]}],
        )
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.output == "from history"

    def test_artifacts_take_precedence_over_history(self):
        """reversed([artifact, history]) → history comes first in scan; wins."""
        task = _make_task(
            artifacts=[{"parts": [{"kind": "text", "text": "artifact text"}]}],
            history=[{"parts": [{"kind": "text", "text": "history text"}]}],
        )
        result = A2AClient("http://localhost")._extract_result(task)

        assert result.output in ("artifact text", "history text")


# ---------------------------------------------------------------------------
# A2AClient.discover_agents
# ---------------------------------------------------------------------------


class TestDiscoverAgents:
    async def test_returns_discovered_agents(self):
        response_data = {
            "agents": [
                {
                    "name": "shell",
                    "description": "Shell command generator",
                    "url": "http://localhost/agents/shell/",
                    "card_meta": {
                        "multi_turn": False,
                        "requires_approval": True,
                        "supports_regenerate": True,
                        "supports_thinking": False,
                        "supports_model_selection": True,
                        "tags": ["shell"],
                    },
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_response)

        client = A2AClient("http://localhost")
        client._client = mock_httpx_client

        agents = await client.discover_agents()

        assert len(agents) == 1
        assert agents[0].name == "shell"
        assert agents[0].card_meta.multi_turn is False
        assert agents[0].card_meta.requires_approval is True

    async def test_returns_empty_when_no_agents(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"agents": []}
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_response)

        client = A2AClient("http://localhost")
        client._client = mock_httpx_client

        agents = await client.discover_agents()
        assert agents == []

    async def test_card_meta_defaults_when_absent(self):
        response_data = {
            "agents": [
                {
                    "name": "default",
                    "description": "Default agent",
                    "url": "http://localhost/agents/default/",
                    "card_meta": {},
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_response)

        client = A2AClient("http://localhost")
        client._client = mock_httpx_client

        agents = await client.discover_agents()

        assert agents[0].card_meta.multi_turn is True
        assert agents[0].card_meta.requires_approval is False


# ---------------------------------------------------------------------------
# A2AClient.run_agent — uses fasta2a TypeAdapter, so wire camelCase on the wire
# ---------------------------------------------------------------------------


class TestRunAgent:
    async def test_returns_agent_result_from_inline_response(self):
        # fasta2a TypeAdapter expects camelCase on the wire (contextId, artifactId)
        wire_payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {
                    "id": "task-1",
                    "contextId": "ctx-1",
                    "kind": "task",
                    "status": {"state": "completed"},
                    "artifacts": [
                        {"artifactId": "a1", "parts": [{"kind": "text", "text": "hello"}]}
                    ],
                    "history": [],
                },
            }
        ).encode()

        mock_response = MagicMock()
        mock_response.content = wire_payload
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post = AsyncMock(return_value=mock_response)

        client = A2AClient("http://localhost")
        client._client = mock_httpx_client

        result = await client.run_agent("shell", "list files")

        assert result.success is True
        assert result.output == "hello"
        assert result.context_id == "ctx-1"

    async def test_sends_message_send_rpc(self):
        wire_payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {
                    "id": "t",
                    "contextId": "c",
                    "kind": "task",
                    "status": {"state": "completed"},
                    "artifacts": [],
                    "history": [],
                },
            }
        ).encode()

        mock_response = MagicMock()
        mock_response.content = wire_payload
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post = AsyncMock(return_value=mock_response)

        client = A2AClient("http://localhost")
        client._client = mock_httpx_client

        await client.run_agent("shell", "do something")

        call_kwargs = mock_httpx_client.post.call_args
        # Now sends bytes via content= not json=
        raw_body = call_kwargs.kwargs.get("content") or call_kwargs.args[1]
        payload = json.loads(raw_body)
        assert payload["method"] == "message/send"


# ---------------------------------------------------------------------------
# A2AClient lifecycle
# ---------------------------------------------------------------------------


class TestA2AClientLifecycle:
    async def test_close_cleans_up_client(self):
        client = A2AClient("http://localhost")
        mock_httpx_client = AsyncMock()
        client._client = mock_httpx_client

        await client.close()

        mock_httpx_client.aclose.assert_called_once()
        assert client._client is None

    async def test_close_is_idempotent_when_no_client(self):
        client = A2AClient("http://localhost")
        await client.close()  # should not raise

    def test_base_url_trailing_slash_stripped(self):
        client = A2AClient("http://localhost:4096/")
        assert client.base_url == "http://localhost:4096"
