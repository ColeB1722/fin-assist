"""Tests for cli/client.py — hub client wrapping a2a-sdk."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fin_assist.cli.client import AgentResult, DiscoveredAgent, HubClient


def _make_task(
    state: str = "completed",
    artifacts: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
    context_id: str = "ctx-1",
) -> dict:
    return {
        "id": "task-1",
        "context_id": context_id,
        "status": {"state": state},
        "artifacts": artifacts or [],
        "history": history or [],
    }


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


class TestExtractResult:
    def test_extracts_data_part_command(self):
        task = _make_task(
            artifacts=[{"parts": [{"data": {"result": {"command": "ls -la", "warnings": []}}}]}]
        )
        result = HubClient._extract_result(task)

        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []

    def test_extracts_text_part(self):
        task = _make_task(artifacts=[{"parts": [{"text": "Hello world"}]}])
        result = HubClient._extract_result(task)

        assert result.output == "Hello world"

    def test_extracts_warnings_from_data_part(self):
        task = _make_task(
            artifacts=[
                {
                    "parts": [
                        {
                            "data": {
                                "result": {
                                    "command": "rm -rf /",
                                    "warnings": ["Dangerous!", "Be careful"],
                                }
                            }
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
                            "data": {
                                "result": {
                                    "command": "ls",
                                    "metadata": {"accept_action": "insert_command"},
                                }
                            }
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
        for state in ("failed", "canceled", "rejected"):
            task = _make_task(state=state)
            result = HubClient._extract_result(task)
            assert result.success is False, f"expected failure for state={state}"

    def test_auth_required_is_not_successful(self):
        task = _make_task(state="auth-required")
        result = HubClient._extract_result(task)
        assert result.success is False

    def test_auth_required_extracts_status_message_from_history(self):
        task = _make_task(
            state="auth-required",
            artifacts=[],
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {
                            "text": "Missing API key for anthropic. Set ANTHROPIC_API_KEY or use `fin connect anthropic`.",
                        }
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert "anthropic" in result.output.lower()

    def test_auth_required_sets_auth_required_flag_in_metadata(self):
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
            history=[
                {"role": "agent", "parts": [{"text": "from history"}]},
            ],
        )
        result = HubClient._extract_result(task)

        assert result.output == "from history"

    def test_artifacts_take_precedence_over_history(self):
        task = _make_task(
            artifacts=[{"parts": [{"text": "artifact text"}]}],
            history=[{"role": "agent", "parts": [{"text": "history text"}]}],
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
                            "text": "Let me reason...",
                            "metadata": {"type": "thinking"},
                        },
                        {"text": "Here is the answer."},
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
                        {"text": "First thought", "metadata": {"type": "thinking"}},
                    ],
                },
                {
                    "role": "agent",
                    "parts": [
                        {
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
                        {"text": "my thoughts", "metadata": {"type": "thinking"}},
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
                        {"text": "regular text"},
                        {"text": "thinking text", "metadata": {"type": "thinking"}},
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
                    "parts": [{"text": "just a response"}],
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
                        {"text": "", "metadata": {"type": "thinking"}},
                        {"text": "real thinking", "metadata": {"type": "thinking"}},
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
                        {"text": "reasoning...", "metadata": {"type": "thinking"}},
                        {"text": "actual answer"},
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
                        {"text": "only thinking", "metadata": {"type": "thinking"}},
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert result.output == ""

    def test_extract_result_includes_thinking(self):
        task = _make_task(
            artifacts=[{"parts": [{"text": "answer"}]}],
            history=[
                {
                    "role": "agent",
                    "parts": [
                        {"text": "hmm...", "metadata": {"type": "thinking"}},
                    ],
                }
            ],
        )
        result = HubClient._extract_result(task)
        assert result.thinking == ["hmm..."]
        assert result.output == "answer"


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


class TestRunAgent:
    async def test_delegates_to_send_and_wait(self):
        expected = AgentResult(success=True, output="hello", context_id="ctx-1")
        client = HubClient("http://localhost")
        client._send_and_wait = AsyncMock(return_value=expected)

        result = await client.run_agent("shell", "list files")

        assert result is expected
        client._send_and_wait.assert_called_once_with("shell", "list files", context_id=None)

    async def test_passes_context_id_to_send_and_wait(self):
        expected = AgentResult(success=True, output="hello", context_id="ctx-1")
        client = HubClient("http://localhost")
        client._send_and_wait = AsyncMock(return_value=expected)

        result = await client.send_message("shell", "hello", context_id="ctx-1")

        assert result is expected
        client._send_and_wait.assert_called_once_with("shell", "hello", context_id="ctx-1")


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
        await client.close()

    def test_base_url_trailing_slash_stripped(self):
        client = HubClient("http://localhost:4096/")
        assert client.base_url == "http://localhost:4096"

    async def test_close_clears_a2a_clients(self):
        client = HubClient("http://localhost")
        mock_httpx = AsyncMock()
        client._http = mock_httpx
        mock_a2a = MagicMock()
        mock_a2a.close = AsyncMock()
        client._a2a_clients["shell"] = mock_a2a
        assert len(client._a2a_clients) == 1

        await client.close()

        assert client._a2a_clients == {}
        mock_a2a.close.assert_called_once()
