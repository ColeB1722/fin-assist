"""Tests for cli/client.py — hub client wrapping fasta2a."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from fasta2a.schema import Task

from fin_assist.cli.client import AgentResult, DiscoveredAgent, HubClient

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
        "Task",
        {
            "id": "task-1",
            "context_id": context_id,
            "kind": "task",
            "status": {"state": state},
            "artifacts": artifacts or [],
            "history": history or [],
        },
    )


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
# HubClient._extract_result  (static method — no client instance needed)
# ---------------------------------------------------------------------------


class TestExtractResult:
    def test_extracts_data_part_command(self):
        task = _make_task(
            artifacts=[{"parts": [{"kind": "data", "data": {"command": "ls -la", "warnings": []}}]}]
        )
        result = HubClient._extract_result(task)

        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []

    def test_extracts_text_part(self):
        task = _make_task(artifacts=[{"parts": [{"kind": "text", "text": "Hello world"}]}])
        result = HubClient._extract_result(task)

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
        result = HubClient._extract_result(task)

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
        result = HubClient._extract_result(task)

        assert result.metadata == {"accept_action": "insert_command"}

    def test_success_false_when_task_failed(self):
        task = _make_task(state="failed")
        result = HubClient._extract_result(task)

        assert result.success is False

    def test_success_false_for_all_terminal_failure_states(self):
        """Non-completed terminal states should all produce success=False."""
        for state in ("failed", "canceled", "rejected"):
            task = _make_task(state=state)
            result = HubClient._extract_result(task)
            assert result.success is False, f"expected failure for state={state}"

    def test_auth_required_is_not_successful(self):
        task = _make_task(state="auth-required")
        result = HubClient._extract_result(task)
        assert result.success is False

    def test_auth_required_extracts_status_message_from_history(self):
        """When state is auth-required, _extract_result should surface the
        agent message from history as the output text."""
        task = _make_task(
            state="auth-required",
            artifacts=[],
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "Missing API key for anthropic. Set ANTHROPIC_API_KEY or use `fin connect anthropic`.",
                        }
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert "anthropic" in result.output.lower()

    def test_auth_required_sets_auth_required_flag_in_metadata(self):
        """auth-required results should carry a metadata flag for display layer."""
        task = _make_task(state="auth-required")
        result = HubClient._extract_result(task)
        assert result.metadata.get("auth_required") is True

    def test_propagates_context_id(self):
        task = _make_task(context_id="ctx-xyz")
        result = HubClient._extract_result(task)

        assert result.context_id == "ctx-xyz"

    def test_empty_output_when_no_parts(self):
        task = _make_task(artifacts=[], history=[])
        result = HubClient._extract_result(task)

        assert result.output == ""

    def test_history_items_used_when_no_artifacts(self):
        task = _make_task(
            artifacts=[],
            history=[{"parts": [{"kind": "text", "text": "from history"}]}],
        )
        result = HubClient._extract_result(task)

        assert result.output == "from history"

    def test_artifacts_take_precedence_over_history(self):
        """Artifacts contain the agent's response and should take precedence over history."""
        task = _make_task(
            artifacts=[{"parts": [{"kind": "text", "text": "artifact text"}]}],
            history=[{"parts": [{"kind": "text", "text": "history text"}]}],
        )
        result = HubClient._extract_result(task)

        assert result.output == "artifact text"


# ---------------------------------------------------------------------------
# HubClient.discover_agents
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

        mock_httpx = AsyncMock()
        mock_httpx.get = AsyncMock(return_value=mock_response)

        client = HubClient("http://localhost")
        client._http = mock_httpx

        agents = await client.discover_agents()

        assert len(agents) == 1
        assert agents[0].name == "shell"
        assert agents[0].card_meta.multi_turn is False
        assert agents[0].card_meta.requires_approval is True

    async def test_returns_empty_when_no_agents(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"agents": []}
        mock_response.raise_for_status = MagicMock()

        mock_httpx = AsyncMock()
        mock_httpx.get = AsyncMock(return_value=mock_response)

        client = HubClient("http://localhost")
        client._http = mock_httpx

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

        mock_httpx = AsyncMock()
        mock_httpx.get = AsyncMock(return_value=mock_response)

        client = HubClient("http://localhost")
        client._http = mock_httpx

        agents = await client.discover_agents()

        assert agents[0].card_meta.multi_turn is True
        assert agents[0].card_meta.requires_approval is False


# ---------------------------------------------------------------------------
# HubClient.run_agent — delegates to fasta2a A2AClient under the hood
# ---------------------------------------------------------------------------


class TestRunAgent:
    async def test_returns_agent_result_from_inline_response(self):
        """A completed task returned inline from message/send needs no polling."""
        # fasta2a's TypeAdapter expects camelCase on the wire
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
        mock_response.status_code = 200

        mock_httpx = AsyncMock()
        mock_httpx.post = AsyncMock(return_value=mock_response)

        client = HubClient("http://localhost")
        client._http = mock_httpx

        result = await client.run_agent("shell", "list files")

        assert result.success is True
        assert result.output == "hello"
        assert result.context_id == "ctx-1"

    async def test_sends_message_send_rpc(self):
        """run_agent should delegate to fasta2a's send_message (message/send RPC)."""
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
        mock_response.status_code = 200

        mock_httpx = AsyncMock()
        mock_httpx.post = AsyncMock(return_value=mock_response)

        client = HubClient("http://localhost")
        client._http = mock_httpx

        await client.run_agent("shell", "do something")

        call_kwargs = mock_httpx.post.call_args
        raw_body = call_kwargs.kwargs.get("content") or call_kwargs.args[1]
        payload = json.loads(raw_body)
        assert payload["method"] == "message/send"


# ---------------------------------------------------------------------------
# HubClient lifecycle
# ---------------------------------------------------------------------------


class TestHubClientLifecycle:
    async def test_close_cleans_up_client(self):
        client = HubClient("http://localhost")
        mock_httpx = AsyncMock()
        client._http = mock_httpx

        await client.close()

        mock_httpx.aclose.assert_called_once()
        assert client._http is None

    async def test_close_is_idempotent_when_no_client(self):
        client = HubClient("http://localhost")
        await client.close()  # should not raise

    def test_base_url_trailing_slash_stripped(self):
        client = HubClient("http://localhost:4096/")
        assert client.base_url == "http://localhost:4096"

    async def test_close_clears_a2a_clients(self):
        client = HubClient("http://localhost")
        mock_httpx = AsyncMock()
        client._http = mock_httpx
        # Force creation of an a2a sub-client
        _ = client._get_a2a("shell")
        assert len(client._a2a_clients) == 1

        await client.close()

        assert client._a2a_clients == {}
