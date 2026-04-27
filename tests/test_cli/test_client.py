"""Tests for cli/client.py — hub client wrapping a2a-sdk."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.protobuf.struct_pb2 import Struct, Value

from fin_assist.agents.metadata import AgentCardMeta, AgentResult
from fin_assist.agents.tools import DeferredToolCall
from fin_assist.cli.client import (
    DiscoveredAgent,
    HubClient,
    StreamEvent,
    _Extraction,
    _extract_deferred_calls,
    _is_deferred,
    _is_thinking,
    _part_struct_data,
)


def _make_struct(d: dict) -> Struct:
    s = Struct()
    s.update(d)
    return s


def _make_task(
    state: TaskState = TaskState.TASK_STATE_COMPLETED,
    artifacts: list[Artifact] | None = None,
    history: list[Message] | None = None,
    context_id: str = "ctx-1",
) -> Task:
    return Task(
        id="task-1",
        context_id=context_id,
        status=TaskStatus(state=state),
        artifacts=artifacts or [],
        history=history or [],
    )


def _make_data_part(result_data: dict) -> Part:
    result_struct = Struct()
    result_struct.update({"result": result_data})
    return Part(data=Value(struct_value=result_struct))


def _make_text_part(text: str, metadata: dict | None = None) -> Part:
    if metadata:
        return Part(text=text, metadata=_make_struct(metadata))
    return Part(text=text)


class TestDiscoveredAgent:
    def test_stores_fields(self):
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
        assert result.auth_required is False

    def test_stores_context_id(self):
        result = AgentResult(success=True, output="x", context_id="ctx-42")
        assert result.context_id == "ctx-42"

    def test_stores_thinking(self):
        result = AgentResult(success=True, output="x", thinking=["hmm", "let me see"])
        assert result.thinking == ["hmm", "let me see"]

    def test_stores_auth_required(self):
        result = AgentResult(success=False, output="missing key", auth_required=True)
        assert result.auth_required is True


class TestExtractResult:
    def test_extracts_data_part_command(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[_make_data_part({"command": "ls -la", "warnings": []})],
                )
            ]
        )
        result = HubClient._extract_result(task)

        assert result.success is True
        assert result.output == "ls -la"
        assert result.warnings == []

    def test_extracts_text_part(self):
        task = _make_task(
            artifacts=[
                Artifact(artifact_id="a1", name="result", parts=[_make_text_part("Hello world")])
            ]
        )
        result = HubClient._extract_result(task)

        assert result.output == "Hello world"

    def test_extracts_warnings_from_data_part(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_data_part(
                            {"command": "rm -rf /", "warnings": ["Dangerous!", "Be careful"]}
                        )
                    ],
                )
            ]
        )
        result = HubClient._extract_result(task)

        assert "Dangerous!" in result.warnings

    def test_extracts_metadata_from_data_part(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_data_part(
                            {"command": "ls", "metadata": {"accept_action": "insert_command"}}
                        )
                    ],
                )
            ]
        )
        result = HubClient._extract_result(task)

        assert result.metadata == {"accept_action": "insert_command"}

    def test_success_false_when_task_failed(self):
        task = _make_task(state=TaskState.TASK_STATE_FAILED)
        result = HubClient._extract_result(task)

        assert result.success is False

    def test_success_false_for_all_terminal_failure_states(self):
        for state in (
            TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_CANCELED,
            TaskState.TASK_STATE_REJECTED,
        ):
            task = _make_task(state=state)
            result = HubClient._extract_result(task)
            assert result.success is False, f"expected failure for state={state}"

    def test_auth_required_is_not_successful(self):
        task = _make_task(state=TaskState.TASK_STATE_AUTH_REQUIRED)
        result = HubClient._extract_result(task)
        assert result.success is False

    def test_auth_required_extracts_status_message_from_history(self):
        task = _make_task(
            state=TaskState.TASK_STATE_AUTH_REQUIRED,
            artifacts=[],
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[
                        _make_text_part(
                            "Missing API key for anthropic. Set ANTHROPIC_API_KEY or use `fin connect anthropic`."
                        )
                    ],
                )
            ],
        )
        result = HubClient._extract_result(task)
        assert "anthropic" in result.output.lower()

    def test_auth_required_sets_auth_required_flag(self):
        task = _make_task(state=TaskState.TASK_STATE_AUTH_REQUIRED)
        result = HubClient._extract_result(task)
        assert result.auth_required is True

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
                Message(
                    message_id="m1", role=Role.ROLE_AGENT, parts=[_make_text_part("from history")]
                ),
            ],
        )
        result = HubClient._extract_result(task)

        assert result.output == "from history"

    def test_artifacts_take_precedence_over_history(self):
        task = _make_task(
            artifacts=[
                Artifact(artifact_id="a1", name="result", parts=[_make_text_part("artifact text")])
            ],
            history=[
                Message(
                    message_id="m1", role=Role.ROLE_AGENT, parts=[_make_text_part("history text")]
                ),
            ],
        )
        result = HubClient._extract_result(task)

        assert result.output == "artifact text"


class TestExtractThinking:
    def test_extracts_thinking_from_agent_history(self):
        task = _make_task(
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[
                        _make_text_part("Let me reason...", metadata={"type": "thinking"}),
                        _make_text_part("Here is the answer."),
                    ],
                )
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["Let me reason..."]

    def test_extracts_multiple_thinking_blocks(self):
        task = _make_task(
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[_make_text_part("First thought", metadata={"type": "thinking"})],
                ),
                Message(
                    message_id="m2",
                    role=Role.ROLE_AGENT,
                    parts=[_make_text_part("Second thought", metadata={"type": "thinking"})],
                ),
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["First thought", "Second thought"]

    def test_skips_user_messages(self):
        task = _make_task(
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_USER,
                    parts=[_make_text_part("my thoughts", metadata={"type": "thinking"})],
                )
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == []

    def test_skips_non_thinking_parts(self):
        task = _make_task(
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[
                        _make_text_part("regular text"),
                        _make_text_part("thinking text", metadata={"type": "thinking"}),
                    ],
                )
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
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[_make_text_part("just a response")],
                )
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == []

    def test_skips_empty_thinking_text(self):
        task = _make_task(
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[
                        _make_text_part("", metadata={"type": "thinking"}),
                        _make_text_part("real thinking", metadata={"type": "thinking"}),
                    ],
                )
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["real thinking"]


class TestExtractFromHistorySkipsThinking:
    def test_skips_thinking_parts(self):
        task = _make_task(
            artifacts=[],
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[
                        _make_text_part("reasoning...", metadata={"type": "thinking"}),
                        _make_text_part("actual answer"),
                    ],
                )
            ],
        )
        result = HubClient._extract_result(task)
        assert result.output == "actual answer"

    def test_returns_empty_when_only_thinking_in_history(self):
        task = _make_task(
            artifacts=[],
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[_make_text_part("only thinking", metadata={"type": "thinking"})],
                )
            ],
        )
        result = HubClient._extract_result(task)
        assert result.output == ""

    def test_extract_result_includes_thinking(self):
        task = _make_task(
            artifacts=[
                Artifact(artifact_id="a1", name="result", parts=[_make_text_part("answer")])
            ],
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[_make_text_part("hmm...", metadata={"type": "thinking"})],
                )
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
                        "serving_modes": ["do"],
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
        assert agents[0].card_meta.serving_modes == ["do"]

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

        assert agents[0].card_meta.serving_modes == ["do", "talk"]


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


class TestPartStructData:
    def test_returns_dict_when_struct_value_present(self):
        part = _make_data_part({"command": "ls", "warnings": []})
        result = _part_struct_data(part)
        assert result is not None
        assert result["result"]["command"] == "ls"

    def test_returns_none_when_no_data_field(self):
        part = _make_text_part("hello")
        result = _part_struct_data(part)
        assert result is None

    def test_returns_none_when_data_has_no_struct_value(self):
        part = Part(data=Value(number_value=42.0))
        result = _part_struct_data(part)
        assert result is None

    def test_unwraps_result_envelope(self):
        part = _make_data_part({"command": "ls"})
        result = _part_struct_data(part)
        assert result is not None
        inner = result.get("result", result)
        assert inner["command"] == "ls"


class TestIsThinking:
    def test_returns_true_for_thinking_metadata(self):
        part = _make_text_part("hmm...", metadata={"type": "thinking"})
        assert _is_thinking(part) is True

    def test_returns_false_for_no_metadata(self):
        part = _make_text_part("hello")
        assert _is_thinking(part) is False

    def test_returns_false_for_non_thinking_metadata(self):
        part = _make_text_part("hello", metadata={"type": "response"})
        assert _is_thinking(part) is False

    def test_returns_false_for_empty_metadata(self):
        part = _make_text_part("hello", metadata={})
        assert _is_thinking(part) is False


class TestExtraction:
    def test_named_fields(self):
        ext = _Extraction(output="ls", warnings=["careful"], metadata={"key": "val"})
        assert ext.output == "ls"
        assert ext.warnings == ["careful"]
        assert ext.metadata == {"key": "val"}

    def test_unpacks_like_tuple(self):
        ext = _Extraction(output="ls", warnings=[], metadata={})
        output, warnings, metadata = ext
        assert output == "ls"
        assert warnings == []
        assert metadata == {}


class TestProcessResponse:
    def test_task_in_terminal_state(self):
        task = Task(id="t1", status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED))
        response = StreamResponse(task=task)
        is_terminal, resp_task, artifact = HubClient._process_response(response)
        assert is_terminal is True
        assert resp_task is not None
        assert resp_task.id == "t1"
        assert artifact is None

    def test_task_in_non_terminal_state(self):
        task = Task(id="t1", status=TaskStatus(state=TaskState.TASK_STATE_WORKING))
        response = StreamResponse(task=task)
        is_terminal, resp_task, artifact = HubClient._process_response(response)
        assert is_terminal is False
        assert resp_task is not None

    def test_status_update_in_terminal_state(self):
        tsue = TaskStatusUpdateEvent(
            task_id="t1",
            status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
        )
        response = StreamResponse(status_update=tsue)
        is_terminal, resp_task, artifact = HubClient._process_response(response)
        assert is_terminal is True
        assert resp_task is None
        assert artifact is None

    def test_status_update_in_non_terminal_state(self):
        tsue = TaskStatusUpdateEvent(
            task_id="t1",
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )
        response = StreamResponse(status_update=tsue)
        is_terminal, resp_task, artifact = HubClient._process_response(response)
        assert is_terminal is False

    def test_artifact_update(self):
        artifact = Artifact(artifact_id="a1", name="result", parts=[Part(text="chunk")])
        taue = TaskArtifactUpdateEvent(task_id="t1", artifact=artifact)
        response = StreamResponse(artifact_update=taue)
        is_terminal, resp_task, resp_artifact = HubClient._process_response(response)
        assert is_terminal is False
        assert resp_task is None
        assert resp_artifact is not None

    def test_empty_response(self):
        response = StreamResponse()
        is_terminal, resp_task, artifact = HubClient._process_response(response)
        assert is_terminal is False
        assert resp_task is None
        assert artifact is None


class TestStreamEventThinkingDelta:
    def test_thinking_delta_kind(self):
        event = StreamEvent(kind="thinking_delta", text="hmm...")
        assert event.kind == "thinking_delta"
        assert event.text == "hmm..."

    def test_thinking_delta_result_is_none_by_default(self):
        event = StreamEvent(kind="thinking_delta", text="hmm...")
        assert event.result is None


class TestStreamEventToolCall:
    def test_tool_call_fields(self):
        event = StreamEvent(
            kind="tool_call",
            tool_name="run_shell",
            tool_args={"command": "ls -F"},
        )
        assert event.kind == "tool_call"
        assert event.tool_name == "run_shell"
        assert event.tool_args == {"command": "ls -F"}

    def test_tool_call_defaults(self):
        event = StreamEvent(kind="tool_call")
        assert event.tool_name == ""
        assert event.tool_args == {}


class TestStreamEventToolResult:
    def test_tool_result_fields(self):
        event = StreamEvent(
            kind="tool_result",
            text="AGENTS.md  README.md",
            tool_name="run_shell",
        )
        assert event.kind == "tool_result"
        assert event.text == "AGENTS.md  README.md"
        assert event.tool_name == "run_shell"

    def test_tool_result_defaults(self):
        event = StreamEvent(kind="tool_result")
        assert event.text == ""
        assert event.tool_name == ""


class TestExtractFromArtifactsSkipsThinking:
    def test_skips_thinking_parts_in_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_text_part("Let me reason...", metadata={"type": "thinking"}),
                        _make_text_part("Here is the answer."),
                    ],
                )
            ]
        )
        result = HubClient._extract_result(task)
        assert result.output == "Here is the answer."
        assert result.thinking == ["Let me reason..."]

    def test_thinking_only_artifacts_produce_empty_output(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[_make_text_part("just thinking", metadata={"type": "thinking"})],
                )
            ]
        )
        result = HubClient._extract_result(task)
        assert result.output == ""
        assert result.thinking == ["just thinking"]

    def test_skips_tool_call_parts_in_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_text_part(
                            "",
                            metadata={
                                "type": "tool_call",
                                "tool_name": "run_shell",
                                "args": {"command": "ls"},
                            },
                        ),
                        _make_text_part("Here is the answer."),
                    ],
                )
            ]
        )
        result = HubClient._extract_result(task)
        assert result.output == "Here is the answer."

    def test_skips_tool_result_parts_in_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_text_part(
                            "AGENTS.md  README.md",
                            metadata={"type": "tool_result", "tool_name": "run_shell"},
                        ),
                        _make_text_part("The answer."),
                    ],
                )
            ]
        )
        result = HubClient._extract_result(task)
        assert result.output == "The answer."


class TestExtractThinkingFromArtifacts:
    def test_extracts_thinking_from_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[_make_text_part("artifact thought", metadata={"type": "thinking"})],
                )
            ]
        )
        thinking = HubClient._extract_thinking(task)
        assert thinking == ["artifact thought"]

    def test_combines_artifact_and_history_thinking(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[_make_text_part("artifact thought", metadata={"type": "thinking"})],
                )
            ],
            history=[
                Message(
                    message_id="m1",
                    role=Role.ROLE_AGENT,
                    parts=[_make_text_part("history thought", metadata={"type": "thinking"})],
                )
            ],
        )
        thinking = HubClient._extract_thinking(task)
        assert "artifact thought" in thinking
        assert "history thought" in thinking


class TestIsDeferred:
    def test_returns_true_for_deferred_metadata(self):
        part = _make_text_part("args...", metadata={"type": "deferred"})

        assert _is_deferred(part) is True

    def test_returns_false_for_no_metadata(self):
        part = _make_text_part("hello")

        assert _is_deferred(part) is False

    def test_returns_false_for_thinking_metadata(self):
        part = _make_text_part("hmm...", metadata={"type": "thinking"})

        assert _is_deferred(part) is False

    def test_returns_false_for_empty_metadata(self):
        part = _make_text_part("hello", metadata={})

        assert _is_deferred(part) is False


class TestExtractDeferredCalls:
    def test_extracts_deferred_calls_from_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_text_part("some text"),
                        _make_text_part(
                            "args...",
                            metadata={
                                "type": "deferred",
                                "tool_name": "run_shell",
                                "tool_call_id": "call_1",
                                "args": {"command": "ls"},
                                "reason": "requires approval",
                            },
                        ),
                    ],
                )
            ]
        )
        calls = _extract_deferred_calls(task)
        assert len(calls) == 1
        assert calls[0].tool_name == "run_shell"
        assert calls[0].tool_call_id == "call_1"
        assert calls[0].args == {"command": "ls"}
        assert calls[0].reason == "requires approval"

    def test_returns_empty_when_no_deferred_artifacts(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[_make_text_part("just text")],
                )
            ]
        )
        calls = _extract_deferred_calls(task)
        assert calls == []

    def test_returns_empty_when_no_artifacts(self):
        task = _make_task(artifacts=[])
        calls = _extract_deferred_calls(task)
        assert calls == []

    def test_extracts_multiple_deferred_calls(self):
        task = _make_task(
            artifacts=[
                Artifact(
                    artifact_id="a1",
                    name="result",
                    parts=[
                        _make_text_part(
                            "args1",
                            metadata={
                                "type": "deferred",
                                "tool_name": "run_shell",
                                "tool_call_id": "call_1",
                                "args": {},
                                "reason": "",
                            },
                        ),
                        _make_text_part(
                            "args2",
                            metadata={
                                "type": "deferred",
                                "tool_name": "run_shell",
                                "tool_call_id": "call_2",
                                "args": {},
                                "reason": "",
                            },
                        ),
                    ],
                )
            ]
        )
        calls = _extract_deferred_calls(task)
        assert len(calls) == 2


class TestStreamEventInputRequired:
    def test_input_required_kind(self):
        event = StreamEvent(
            kind="input_required",
            result=AgentResult(success=False, output="waiting"),
            deferred_calls=[DeferredToolCall(tool_name="run_shell", tool_call_id="c1", args={})],
        )
        assert event.kind == "input_required"
        assert len(event.deferred_calls) == 1

    def test_input_required_carries_result(self):
        result = AgentResult(success=False, output="waiting for approval", context_id="ctx-1")
        event = StreamEvent(kind="input_required", result=result, deferred_calls=[])
        assert event.result is not None
        assert event.result.context_id == "ctx-1"

    def test_input_required_deferred_calls_default_empty(self):
        event = StreamEvent(kind="input_required")
        assert event.deferred_calls == []
