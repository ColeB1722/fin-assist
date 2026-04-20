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
        from fin_assist.agents.metadata import AgentCardMeta

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
        assert result.thinking == []

    def test_stores_context_id(self):
        result = AgentResult(success=True, output="x", context_id="ctx-42")
        assert result.context_id == "ctx-42"

    def test_stores_thinking(self):
        result = AgentResult(success=True, output="x", thinking=["hmm", "let me see"])
        assert result.thinking == ["hmm", "let me see"]

    def test_partial_defaults_false(self):
        result = AgentResult(success=True, output="x")
        assert result.partial is False
        assert result.thinking_token_count == 0

    def test_partial_fields(self):
        result = AgentResult(
            success=False,
            output="partial text",
            partial=True,
            thinking_token_count=42,
        )
        assert result.partial is True
        assert result.thinking_token_count == 42


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


class TestExtractThinking:
    def test_extracts_thinking_from_agent_history(self):
        task = _make_task(
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "Let me reason...",
                            "metadata": {"type": "thinking"},
                        },
                        {"kind": "text", "text": "Here is the answer."},
                    ],
                }
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["Let me reason..."]

    def test_extracts_multiple_thinking_blocks(self):
        task = _make_task(
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "First thought", "metadata": {"type": "thinking"}},
                    ],
                },
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "Second thought",
                            "metadata": {"type": "thinking"},
                        },
                    ],
                },
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["First thought", "Second thought"]

    def test_skips_user_messages(self):
        task = _make_task(
            history=[
                {
                    "role": "user",
                    "parts": [
                        {"kind": "text", "text": "my thoughts", "metadata": {"type": "thinking"}},
                    ],
                }
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == []

    def test_skips_non_thinking_parts(self):
        task = _make_task(
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "regular text"},
                        {"kind": "text", "text": "thinking text", "metadata": {"type": "thinking"}},
                    ],
                }
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["thinking text"]

    def test_empty_when_no_history(self):
        task = _make_task(history=[])
        thinking = HubClient._extract_thinking(task)
        assert thinking == []

    def test_empty_when_no_thinking_metadata(self):
        task = _make_task(
            history=[
                {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": "just a response"}],
                }
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == []

    def test_skips_empty_thinking_text(self):
        task = _make_task(
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "", "metadata": {"type": "thinking"}},
                        {"kind": "text", "text": "real thinking", "metadata": {"type": "thinking"}},
                    ],
                }
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["real thinking"]


class TestExtractFromHistorySkipsThinking:
    def test_skips_thinking_parts(self):
        task = _make_task(
            artifacts=[],
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "reasoning...", "metadata": {"type": "thinking"}},
                        {"kind": "text", "text": "actual answer"},
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert result.output == "actual answer"

    def test_returns_empty_when_only_thinking_in_history(self):
        task = _make_task(
            artifacts=[],
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "only thinking", "metadata": {"type": "thinking"}},
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert result.output == ""

    def test_extract_result_includes_thinking(self):
        task = _make_task(
            artifacts=[{"parts": [{"kind": "text", "text": "answer"}]}],
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"kind": "text", "text": "hmm...", "metadata": {"type": "thinking"}},
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert result.thinking == ["hmm..."]
        assert result.output == "answer"


# ---------------------------------------------------------------------------
# HubClient._extract_partial_result
# ---------------------------------------------------------------------------


class TestExtractPartialResult:
    def test_returns_none_when_no_new_messages(self):
        task = _make_task(
            state="working",
            history=[{"role": "user", "parts": [{"kind": "text", "text": "hello"}]}],
        )
        result = HubClient._extract_partial_result(task, seen_message_count=1)
        assert result is None

    def test_returns_none_when_new_messages_not_partial(self):
        task = _make_task(
            state="working",
            history=[
                {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
                {"role": "agent", "parts": [{"kind": "text", "text": "answer"}]},
            ],
        )
        result = HubClient._extract_partial_result(task, seen_message_count=1)
        assert result is None

    def test_extracts_thinking_delta(self):
        task = _make_task(
            state="working",
            history=[
                {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "let me think about this carefully",
                            "metadata": {"type": "thinking_delta", "partial": True},
                        }
                    ],
                },
            ],
        )
        result = HubClient._extract_partial_result(task, seen_message_count=1)
        assert result is not None
        assert result.partial is True
        assert result.thinking == ["let me think about this carefully"]
        assert result.thinking_token_count > 0
        assert result.output == ""

    def test_extracts_text_delta(self):
        task = _make_task(
            state="working",
            history=[
                {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "The answer is",
                            "metadata": {"type": "text_delta", "partial": True},
                        }
                    ],
                },
            ],
        )
        result = HubClient._extract_partial_result(task, seen_message_count=1)
        assert result is not None
        assert result.partial is True
        assert result.output == "The answer is"
        assert result.thinking == []

    def test_uses_latest_snapshot(self):
        """Multiple partial messages — uses the latest of each type."""
        task = _make_task(
            state="working",
            history=[
                {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "old thinking",
                            "metadata": {"type": "thinking_delta", "partial": True},
                        }
                    ],
                },
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "newer thinking with more detail",
                            "metadata": {"type": "thinking_delta", "partial": True},
                        }
                    ],
                },
            ],
        )
        result = HubClient._extract_partial_result(task, seen_message_count=1)
        assert result is not None
        assert result.thinking == ["newer thinking with more detail"]

    def test_preserves_context_id(self):
        task = _make_task(
            state="working",
            context_id="ctx-42",
            history=[
                {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "thinking",
                            "metadata": {"type": "thinking_delta", "partial": True},
                        }
                    ],
                },
            ],
        )
        result = HubClient._extract_partial_result(task, seen_message_count=1)
        assert result is not None
        assert result.context_id == "ctx-42"


# ---------------------------------------------------------------------------
# HubClient.stream_message
# ---------------------------------------------------------------------------


class TestStreamMessage:
    async def test_yields_final_result_for_immediate_completion(self):
        """When message/send returns an already-terminal task, yield it."""
        client = HubClient("http://localhost")
        mock_a2a = AsyncMock()
        client._a2a_clients["shell"] = mock_a2a

        terminal_task = {
            "kind": "task",
            "id": "task-1",
            "context_id": "ctx-1",
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "done"}]}],
            "history": [],
        }
        mock_a2a.send_message.return_value = {"result": terminal_task}

        results = []
        async for r in client.stream_message("shell", "hello"):
            results.append(r)

        assert len(results) == 1
        assert results[0].partial is False
        assert results[0].success is True
        assert results[0].output == "done"

    async def test_yields_partial_then_final(self):
        """When polling finds partial progress, yield partial then final."""
        client = HubClient("http://localhost", poll_interval=0.01)
        mock_a2a = AsyncMock()
        client._a2a_clients["shell"] = mock_a2a

        submitted_task = {
            "kind": "task",
            "id": "task-1",
            "context_id": "ctx-1",
            "status": {"state": "submitted"},
            "history": [{"role": "user", "parts": [{"kind": "text", "text": "hello"}]}],
        }
        mock_a2a.send_message.return_value = {"result": submitted_task}

        working_task = {
            "kind": "task",
            "id": "task-1",
            "context_id": "ctx-1",
            "status": {"state": "working"},
            "history": [
                {"role": "user", "parts": [{"kind": "text", "text": "hello"}]},
                {
                    "role": "agent",
                    "parts": [
                        {
                            "kind": "text",
                            "text": "thinking about it",
                            "metadata": {"type": "thinking_delta", "partial": True},
                        }
                    ],
                },
            ],
        }
        completed_task = {
            "kind": "task",
            "id": "task-1",
            "context_id": "ctx-1",
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "final answer"}]}],
            "history": working_task["history"],
        }
        mock_a2a.get_task.side_effect = [
            {"result": working_task},
            {"result": completed_task},
        ]

        results = []
        async for r in client.stream_message("shell", "hello"):
            results.append(r)

        assert len(results) == 2
        assert results[0].partial is True
        assert results[0].thinking_token_count > 0
        assert results[1].partial is False
        assert results[1].success is True
        assert results[1].output == "final answer"


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
