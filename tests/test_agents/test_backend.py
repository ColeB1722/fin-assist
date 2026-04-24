"""Tests for AgentBackend protocol and PydanticAIBackend implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Message, Part, Role
from pydantic import TypeAdapter
from pydantic_ai import ModelRequest, UserPromptPart
from pydantic_ai.messages import ModelResponse, TextPart as PydanticTextPart

from fin_assist.agents.spec import AgentSpec
from fin_assist.agents.backend import (
    AgentBackend,
    PydanticAIBackend,
    RunResult,
)
from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.step import StepEvent, StepHandle
from fin_assist.config.schema import AgentConfig


def _make_spec(mock_config, mock_credentials) -> AgentSpec:
    return AgentSpec(
        name="default",
        agent_config=AgentConfig(
            description="Default agent",
            system_prompt="chain-of-thought",
            output_type="text",
        ),
        config=mock_config,
        credentials=mock_credentials,
    )


def _make_a2a_user_message(text: str) -> Message:
    return Message(
        role=Role.ROLE_USER,
        parts=[Part(text=text)],
    )


# -- RunResult tests -----------------------------------------------------------


class TestRunResult:
    def test_stores_fields(self) -> None:
        result = RunResult(
            output="hello",
            serialized_history=b'{"data": "test"}',
            new_message_parts=[Part(text="response")],
        )
        assert result.output == "hello"
        assert result.serialized_history == b'{"data": "test"}'
        assert len(result.new_message_parts) == 1

    def test_output_can_be_structured(self) -> None:
        result = RunResult(
            output={"command": "ls"},
            serialized_history=b"[]",
            new_message_parts=[],
        )
        assert result.output == {"command": "ls"}

    def test_new_message_parts_default_empty(self) -> None:
        result = RunResult(output="hi", serialized_history=b"[]")
        assert result.new_message_parts == []


# -- AgentBackend protocol structural check ------------------------------------


class TestAgentBackendProtocol:
    def test_pydantic_ai_backend_satisfies_protocol(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        assert isinstance(backend, AgentBackend)


# -- PydanticAIBackend.check_credentials ---------------------------------------


class TestPydanticAIBackendCheckCredentials:
    def test_delegates_to_spec(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        result = backend.check_credentials()
        assert result == []

    def test_returns_missing_providers(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        result = backend.check_credentials()
        assert "anthropic" in result


# -- PydanticAIBackend.convert_history -----------------------------------------


class TestPydanticAIBackendConvertHistory:
    def test_converts_user_message(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        a2a_messages = [_make_a2a_user_message("hello")]
        result = backend.convert_history(a2a_messages)
        assert len(result) == 1
        assert isinstance(result[0], ModelRequest)
        assert any(isinstance(p, UserPromptPart) and p.content == "hello" for p in result[0].parts)

    def test_empty_history_returns_empty(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        result = backend.convert_history([])
        assert result == []


# -- PydanticAIBackend.serialize/deserialize_history ---------------------------


class TestPydanticAIBackendSerializeHistory:
    def test_roundtrip(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        original = [ModelRequest(parts=[UserPromptPart(content="hello")])]
        data = backend.serialize_history(original)
        assert isinstance(data, bytes)

        restored = backend.deserialize_history(data)
        assert len(restored) == 1
        assert isinstance(restored[0], ModelRequest)

    def test_empty_history_roundtrip(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        data = backend.serialize_history([])
        restored = backend.deserialize_history(data)
        assert restored == []


# -- PydanticAIBackend.convert_result_to_part ----------------------------------


class TestPydanticAIBackendConvertResultToPart:
    def test_string_result_returns_text_part(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        part = backend.convert_result_to_part("hello world")
        assert part.text == "hello world"

    def test_structured_result_returns_data_part(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.results import CommandResult

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        result = CommandResult(command="ls -la", warnings=[])
        part = backend.convert_result_to_part(result)
        assert part.HasField("data")

    def test_structured_result_includes_json_schema(self, mock_config, mock_credentials) -> None:
        from fin_assist.agents.results import CommandResult

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        result = CommandResult(command="ls", warnings=[])
        part = backend.convert_result_to_part(result)
        assert part.metadata is not None


# -- PydanticAIBackend.convert_response_parts ----------------------------------


class TestPydanticAIBackendConvertResponseParts:
    def test_text_parts_become_a2a_parts(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        parts = [PydanticTextPart(content="response text")]
        result = backend.convert_response_parts(parts)
        assert len(result) == 1
        assert result[0].text == "response text"

    def test_empty_parts_returns_empty(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        result = backend.convert_response_parts([])
        assert result == []

    def test_tool_call_parts_are_skipped(self, mock_config, mock_credentials) -> None:
        from pydantic_ai.messages import ToolCallPart

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        parts = [ToolCallPart(tool_name="test", args={})]
        result = backend.convert_response_parts(parts)
        assert result == []


# -- PydanticAIBackend.run_steps ---------------------------------------------


class _FakeAgentRun:
    """Stand-in for pydantic-ai's AgentRun async context manager.

    Yields a sequence of fake nodes, each of which may optionally expose a
    ``.stream()`` async context manager that yields a list of events.
    """

    def __init__(self, nodes: list[Any], final_result: Any) -> None:
        self._nodes = nodes
        self.ctx = MagicMock()
        self.result = final_result

    def __aiter__(self):
        async def _gen():
            for node in self._nodes:
                yield node

        return _gen()


def _make_model_request_node(events: list[Any]) -> Any:
    """Build a ``ModelRequestNode`` whose ``.stream(ctx)`` yields the given events."""

    async def _event_gen():
        for ev in events:
            yield ev

    event_stream = MagicMock()
    event_stream.__aiter__ = lambda self: _event_gen()

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=event_stream)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    from pydantic_ai._agent_graph import ModelRequestNode
    from pydantic_ai.messages import ModelRequest

    node = ModelRequestNode(request=ModelRequest(parts=[]))
    node.stream = MagicMock(return_value=stream_cm)
    return node


def _make_agent_run_cm(nodes: list[Any], final_result: Any) -> Any:
    """Build an async context manager returning a _FakeAgentRun."""
    run = _FakeAgentRun(nodes=nodes, final_result=final_result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=run)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestPydanticAIBackendRunSteps:
    @pytest.mark.asyncio
    async def test_yields_step_events_from_text_events(self, mock_config, mock_credentials) -> None:
        from pydantic_ai.messages import (
            PartDeltaEvent,
            PartStartEvent,
            TextPart,
            TextPartDelta,
        )

        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        events = [
            PartStartEvent(index=0, part=TextPart(content="hel")),
            PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="lo")),
        ]
        node = _make_model_request_node(events)

        final_result = MagicMock()
        final_result.output = "hello"
        final_result.all_messages = MagicMock(return_value=[])
        final_result.new_messages = MagicMock(return_value=[])

        agent_run_cm = _make_agent_run_cm(nodes=[node], final_result=final_result)

        pydantic_agent = MagicMock()
        pydantic_agent.output_type = str
        pydantic_agent.iter = MagicMock(return_value=agent_run_cm)

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=MagicMock()),
        ):
            handle = backend.run_steps(messages=[])
            assert isinstance(handle, StepHandle)
            step_events = [e async for e in handle]

        kinds_and_contents = [
            (e.kind, e.content) for e in step_events if e.kind in ("text_delta", "thinking_delta")
        ]
        assert kinds_and_contents == [
            ("text_delta", "hel"),
            ("text_delta", "lo"),
        ]

    @pytest.mark.asyncio
    async def test_emits_step_start_and_step_end(self, mock_config, mock_credentials) -> None:
        from pydantic_ai.messages import PartStartEvent, TextPart

        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        events = [PartStartEvent(index=0, part=TextPart(content="hi"))]
        node = _make_model_request_node(events)

        final_result = MagicMock()
        final_result.output = "hi"
        final_result.all_messages = MagicMock(return_value=[])
        final_result.new_messages = MagicMock(return_value=[])

        agent_run_cm = _make_agent_run_cm(nodes=[node], final_result=final_result)

        pydantic_agent = MagicMock()
        pydantic_agent.output_type = str
        pydantic_agent.iter = MagicMock(return_value=agent_run_cm)

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=MagicMock()),
        ):
            handle = backend.run_steps(messages=[])
            step_events = [e async for e in handle]

        boundary_kinds = [e.kind for e in step_events if e.kind in ("step_start", "step_end")]
        assert boundary_kinds == ["step_start", "step_end"]

    @pytest.mark.asyncio
    async def test_yields_thinking_and_text_step_events(
        self, mock_config, mock_credentials
    ) -> None:
        from pydantic_ai.messages import (
            PartDeltaEvent,
            PartStartEvent,
            TextPart,
            TextPartDelta,
            ThinkingPart,
            ThinkingPartDelta,
        )

        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        events = [
            PartStartEvent(index=0, part=ThinkingPart(content="let")),
            PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=" me think")),
            PartStartEvent(index=1, part=TextPart(content="hi")),
            PartDeltaEvent(index=1, delta=TextPartDelta(content_delta=" there")),
        ]
        node = _make_model_request_node(events)

        final_result = MagicMock()
        final_result.output = "hi there"
        final_result.all_messages = MagicMock(return_value=[])
        final_result.new_messages = MagicMock(return_value=[])

        agent_run_cm = _make_agent_run_cm(nodes=[node], final_result=final_result)

        pydantic_agent = MagicMock()
        pydantic_agent.output_type = str
        pydantic_agent.iter = MagicMock(return_value=agent_run_cm)

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=MagicMock()),
        ):
            handle = backend.run_steps(messages=[])
            step_events = [e async for e in handle]

        delta_events = [
            (e.kind, e.content) for e in step_events if e.kind in ("text_delta", "thinking_delta")
        ]
        assert delta_events == [
            ("thinking_delta", "let"),
            ("thinking_delta", " me think"),
            ("text_delta", "hi"),
            ("text_delta", " there"),
        ]

    @pytest.mark.asyncio
    async def test_handle_result_returns_run_result(self, mock_config, mock_credentials) -> None:
        from pydantic_ai.messages import PartStartEvent, TextPart

        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        original_messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        response_msg = ModelResponse(parts=[PydanticTextPart(content="hello")])

        events = [PartStartEvent(index=0, part=TextPart(content="hello"))]
        node = _make_model_request_node(events)

        final_result = MagicMock()
        final_result.output = "hello"
        final_result.all_messages = MagicMock(return_value=[*original_messages, response_msg])
        final_result.new_messages = MagicMock(return_value=[response_msg])

        agent_run_cm = _make_agent_run_cm(nodes=[node], final_result=final_result)

        pydantic_agent = MagicMock()
        pydantic_agent.output_type = str
        pydantic_agent.iter = MagicMock(return_value=agent_run_cm)

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=MagicMock()),
        ):
            handle = backend.run_steps(messages=original_messages)
            _ = [e async for e in handle]
            result = await handle.result()

        assert isinstance(result, RunResult)
        assert result.output == "hello"
        assert isinstance(result.serialized_history, bytes)
        assert len(result.new_message_parts) == 1
        assert result.new_message_parts[0].text == "hello"

    @pytest.mark.asyncio
    async def test_raises_missing_credentials(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with pytest.raises(MissingCredentialsError):
            backend.run_steps(messages=[])

    @pytest.mark.asyncio
    async def test_result_raises_before_iteration(self, mock_config, mock_credentials) -> None:
        """Calling result() before iterating should raise per the protocol contract."""
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        pydantic_agent = MagicMock()
        pydantic_agent.output_type = str

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=MagicMock()),
        ):
            handle = backend.run_steps(messages=[])
            with pytest.raises(RuntimeError, match="Must iterate"):
                await handle.result()


# -- PydanticAIBackend._build_pydantic_agent -----------------------------------


class TestPydanticAIBackendBuildPydanticAgent:
    def test_returns_pydantic_agent(self, mock_config, mock_credentials) -> None:
        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        from pydantic_ai import Agent as PydanticAgent

        agent = backend._build_pydantic_agent()
        assert isinstance(agent, PydanticAgent)


# -- PydanticAIBackend._build_model -------------------------------------------


class TestPydanticAIBackendBuildModel:
    def test_raises_on_missing_credentials(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with pytest.raises(MissingCredentialsError):
            backend._build_model()

    def test_returns_model_when_credentials_present(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.general.default_model = "claude-sonnet-4-6"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        mock_model = MagicMock()
        with patch(
            "fin_assist.llm.model_registry.ProviderRegistry.create_model",
            return_value=mock_model,
        ):
            backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
            result = backend._build_model()
            assert result is mock_model
