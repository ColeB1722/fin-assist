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

from fin_assist.agents.agent import AgentSpec
from fin_assist.agents.backend import (
    AgentBackend,
    PydanticAIBackend,
    RunResult,
    StreamHandle,
)
from fin_assist.agents.metadata import MissingCredentialsError
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


# -- StreamHandle protocol tests -----------------------------------------------


class _FakeStreamHandle:
    def __init__(self, deltas: list[str], run_result: RunResult) -> None:
        self._deltas = deltas
        self._run_result = run_result
        self._iterated = False

    async def __aiter__(self) -> AsyncIterator[str]:
        self._iterated = True
        for delta in self._deltas:
            yield delta

    async def result(self) -> RunResult:
        return self._run_result


class TestStreamHandle:
    @pytest.mark.asyncio
    async def test_yields_deltas(self) -> None:
        handle = _FakeStreamHandle(
            deltas=["hel", "lo"],
            run_result=RunResult(output="hello", serialized_history=b"[]"),
        )
        collected = [d async for d in handle]
        assert collected == ["hel", "lo"]

    @pytest.mark.asyncio
    async def test_returns_result(self) -> None:
        expected = RunResult(output="hello", serialized_history=b"[]")
        handle = _FakeStreamHandle(deltas=["hello"], run_result=expected)
        result = await handle.result()
        assert result is expected


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


# -- PydanticAIBackend.run_stream ---------------------------------------------


class TestPydanticAIBackendRunStream:
    @pytest.mark.asyncio
    async def test_returns_stream_handle(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        mock_model = MagicMock()
        pydantic_agent = MagicMock()
        pydantic_agent.__aenter__ = AsyncMock(return_value=pydantic_agent)
        pydantic_agent.__aexit__ = AsyncMock(return_value=False)

        stream_mock = MagicMock()
        stream_mock.all_messages.return_value = []
        stream_mock.new_messages.return_value = []
        stream_mock.get_output = AsyncMock(return_value="hello")
        stream_mock.stream_text.return_value = _async_gen(["hel", "lo"])

        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=stream_mock)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        pydantic_agent.run_stream = MagicMock(return_value=stream_ctx)

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=mock_model),
        ):
            handle = backend.run_stream(messages=[])

        assert isinstance(handle, StreamHandle)
        deltas = [d async for d in handle]
        assert deltas == ["hel", "lo"]

    @pytest.mark.asyncio
    async def test_handle_result_returns_run_result(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = "sk-test"

        mock_model = MagicMock()
        pydantic_agent = MagicMock()
        pydantic_agent.__aenter__ = AsyncMock(return_value=pydantic_agent)
        pydantic_agent.__aexit__ = AsyncMock(return_value=False)

        original_messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]

        stream_mock = MagicMock()
        stream_mock.all_messages.return_value = original_messages
        stream_mock.new_messages.return_value = []
        stream_mock.get_output = AsyncMock(return_value="hello")
        stream_mock.stream_text.return_value = _async_gen(["hello"])

        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=stream_mock)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        pydantic_agent.run_stream = MagicMock(return_value=stream_ctx)

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with (
            patch.object(backend, "_build_pydantic_agent", return_value=pydantic_agent),
            patch.object(backend, "_build_model", return_value=mock_model),
        ):
            handle = backend.run_stream(messages=original_messages)
            _ = [d async for d in handle]
            result = await handle.result()

        assert isinstance(result, RunResult)
        assert result.output == "hello"
        assert isinstance(result.serialized_history, bytes)
        assert result.new_message_parts == []

    @pytest.mark.asyncio
    async def test_raises_missing_credentials(self, mock_config, mock_credentials) -> None:
        mock_config.general.default_provider = "anthropic"
        mock_config.providers = {}
        mock_credentials.get_api_key.return_value = None

        backend = PydanticAIBackend(agent_spec=_make_spec(mock_config, mock_credentials))
        with pytest.raises(MissingCredentialsError):
            backend.run_stream(messages=[])


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


# -- Helpers -------------------------------------------------------------------


async def _async_gen(items: list[str]) -> AsyncIterator[str]:
    for item in items:
        yield item
