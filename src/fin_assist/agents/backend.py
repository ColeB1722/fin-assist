"""AgentBackend protocol and PydanticAIBackend implementation.

Defines the ``AgentBackend`` protocol — the abstraction layer between the
Executor (A2A task lifecycle) and any LLM framework.  The only concrete
implementation today is ``PydanticAIBackend``, which wraps pydantic-ai.

Protocol shape
~~~~~~~~~~~~~~
- ``check_credentials()`` — delegates to ``AgentSpec.check_credentials()`` (uses public API)
- ``convert_history()`` — A2A ``Message`` → framework messages
- ``run_steps()`` — returns a ``StepHandle`` for step events + final result
- ``serialize_history()`` / ``deserialize_history()`` — framework ↔ bytes
- ``convert_result_to_part()`` — structured output → A2A ``Part``
- ``convert_response_parts()`` — framework response parts → A2A ``Part`` list

``StepHandle`` is a two-phase protocol (replaces the former ``StreamHandle``):
1. Iterate (``async for event in handle``) for ``StepEvent`` values — each
   event has a ``kind`` (``text_delta``, ``thinking_delta``, ``tool_call``,
   ``tool_result``, ``step_start``, ``step_end``, ``deferred``).
2. Call ``await handle.result()`` after iteration for the ``RunResult``.

The step-driven model aligns with the Executor's dispatch loop: the Executor
pattern-matches on ``kind`` and routes each event (streaming deltas as
artifacts, tracking tool calls, enforcing approval gates, etc.).

Implementation uses pydantic-ai's ``agent.iter()`` API, which exposes the
agent graph node-by-node.  For each ``ModelRequestNode`` we open
``node.stream(ctx)`` and map stream events onto ``StepEvent`` values.
For ``CallToolsNode`` we emit ``tool_call`` and ``tool_result`` events.
After iteration completes, the final ``AgentRun.result`` gives us output
and message history for ``RunResult``.
"""

from __future__ import annotations

import base64
import struct
from collections.abc import AsyncIterator, Sequence  # noqa: TC003
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from a2a.types import Part
from google.protobuf.struct_pb2 import Struct, Value
from pydantic import TypeAdapter
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.messages import TextPart as PydanticTextPart

from fin_assist.agents.metadata import MissingCredentialsError
from fin_assist.agents.step import StepEvent

_message_ta = TypeAdapter(list[ModelMessage])

_CONTEXT_STORE_VERSION = 1
_VERSION_PACK = struct.Struct("!B")


def _wrap_payload(data: bytes) -> bytes:
    return _VERSION_PACK.pack(_CONTEXT_STORE_VERSION) + data


def _unwrap_payload(data: bytes) -> bytes:
    if len(data) < _VERSION_PACK.size:
        raise ValueError(f"Context store data too short ({len(data)} bytes)")
    version = _VERSION_PACK.unpack(data[: _VERSION_PACK.size])[0]
    if version != _CONTEXT_STORE_VERSION:
        raise ValueError(f"Unsupported context store version {version}")
    return data[_VERSION_PACK.size :]


if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.models import Model

    from fin_assist.agents.spec import AgentSpec
    from fin_assist.llm.model_registry import ProviderRegistry


@dataclass
class RunResult:
    output: Any
    serialized_history: bytes
    new_message_parts: list[Part] = field(default_factory=list)


@runtime_checkable
class AgentBackend(Protocol):
    def check_credentials(self) -> list[str]: ...
    def convert_history(self, a2a_messages: Sequence[Any]) -> list[Any]: ...
    def run_steps(self, *, messages: list[Any], model: Any = None) -> Any: ...
    def serialize_history(self, messages: list[Any]) -> bytes: ...
    def deserialize_history(self, data: bytes) -> list[Any]: ...
    def convert_result_to_part(self, result: Any) -> Part: ...
    def convert_response_parts(self, parts: Sequence[Any]) -> list[Part]: ...


class _PydanticAIStepHandle:
    """Emits ``StepEvent`` values from a pydantic-ai ``agent.iter()`` run.

    The iteration walks the agent graph node-by-node:

    - ``ModelRequestNode`` → ``step_start``, streaming ``text_delta`` /
      ``thinking_delta`` events, then ``step_end``.
    - ``CallToolsNode`` → ``tool_call`` / ``tool_result`` events for each
      tool invocation in the node.

    After iteration completes, ``result()`` returns the ``RunResult``.
    """

    def __init__(
        self,
        pydantic_agent: Any,
        model: Any,
        message_history: list[Any],
        backend: PydanticAIBackend,
    ) -> None:
        self._pydantic_agent = pydantic_agent
        self._model = model
        self._message_history = message_history
        self._backend = backend
        self._result: RunResult | None = None

    async def __aiter__(self) -> AsyncIterator[StepEvent]:
        from pydantic_ai import Agent

        step = 0

        async with self._pydantic_agent.iter(
            model=self._model,
            message_history=self._message_history,
        ) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    yield StepEvent(kind="step_start", content=None, step=step)
                    async with node.stream(run.ctx) as event_stream:
                        async for event in event_stream:
                            step_event = _stream_event_to_step_event(event, step)
                            if step_event is not None:
                                yield step_event
                    yield StepEvent(kind="step_end", content=None, step=step)
                    step += 1

                elif Agent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if isinstance(part, ToolCallPart):
                            yield StepEvent(
                                kind="tool_call",
                                content=part,
                                step=step,
                                tool_name=part.tool_name,
                                metadata={"args": part.args_as_dict()},
                            )
                    async with node.stream(run.ctx) as tool_stream:
                        async for tool_event in tool_stream:
                            te = _tool_event_to_step_event(tool_event, step)
                            if te is not None:
                                yield te

            final = run.result
            if final is None:
                self._result = RunResult(
                    output="", serialized_history=self._backend.serialize_history([])
                )
                return

            all_msgs = final.all_messages()
            new_msgs = final.new_messages()
            new_parts = self._backend.convert_response_parts(
                [p for m in new_msgs if not isinstance(m, ModelRequest) for p in m.parts]
            )
            self._result = RunResult(
                output=final.output,
                serialized_history=self._backend.serialize_history(all_msgs),
                new_message_parts=new_parts,
            )

    async def result(self) -> RunResult:
        if self._result is None:
            raise RuntimeError("Must iterate StepHandle before calling result()")
        return self._result


def _stream_event_to_step_event(event: Any, step: int) -> StepEvent | None:
    """Map a pydantic-ai stream event onto a ``StepEvent``, or ``None`` to skip.

    Handles ``PartStartEvent`` and ``PartDeltaEvent`` for text/thinking parts.
    Tool-call and other event types return ``None``.
    """
    match event:
        case PartStartEvent(part=PydanticTextPart(content=c)) if c:
            return StepEvent(kind="text_delta", content=c, step=step)
        case PartStartEvent(part=ThinkingPart(content=c)) if c:
            return StepEvent(kind="thinking_delta", content=c, step=step)
        case PartDeltaEvent(delta=TextPartDelta(content_delta=d)) if d:
            return StepEvent(kind="text_delta", content=d, step=step)
        case PartDeltaEvent(delta=ThinkingPartDelta(content_delta=d)) if d:
            return StepEvent(kind="thinking_delta", content=d, step=step)
        case _:
            return None


def _tool_event_to_step_event(event: Any, step: int) -> StepEvent | None:
    """Map a pydantic-ai tool execution event onto a ``StepEvent``.

    Handles ``FunctionToolCallEvent`` and ``FunctionToolResultEvent``.
    """
    from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent

    match event:
        case FunctionToolCallEvent():
            return StepEvent(
                kind="tool_call",
                content=event.part,
                step=step,
                tool_name=event.part.tool_name,
                metadata={"args": event.part.args_as_dict()},
            )
        case FunctionToolResultEvent():
            tool_name = event.result.tool_name
            return StepEvent(
                kind="tool_result",
                content=event.result,
                step=step,
                tool_name=tool_name,
            )
        case _:
            return None


class PydanticAIBackend:
    def __init__(self, agent_spec: AgentSpec) -> None:
        self._spec = agent_spec
        self._registry: Any = None

    def check_credentials(self) -> list[str]:
        return self._spec.check_credentials()

    def convert_history(self, a2a_messages: Sequence[Any]) -> list[Any]:
        model_messages: list[Any] = []
        from a2a.types import Role

        for message in a2a_messages:
            if message.role == Role.ROLE_USER:
                model_messages.append(
                    ModelRequest(parts=self._request_parts_from_a2a(message.parts))
                )
            else:
                model_messages.append(
                    ModelResponse(parts=self._response_parts_from_a2a(message.parts))
                )
        return model_messages

    def run_steps(self, *, messages: list[Any], model: Any = None) -> _PydanticAIStepHandle:
        missing = self.check_credentials()
        if missing:
            raise MissingCredentialsError(providers=missing)

        pydantic_agent = self._build_pydantic_agent()
        resolved_model = model or self._build_model()
        return _PydanticAIStepHandle(
            pydantic_agent=pydantic_agent,
            model=resolved_model,
            message_history=messages,
            backend=self,
        )

    def serialize_history(self, messages: list[Any]) -> bytes:
        payload = _message_ta.dump_json(messages)
        return _wrap_payload(payload)

    def deserialize_history(self, data: bytes) -> list[Any]:
        payload = _unwrap_payload(data)
        return _message_ta.validate_json(payload)

    def convert_result_to_part(self, result: Any) -> Part:
        if isinstance(result, str):
            return Part(text=result)

        output_type = type(result)
        type_adapter = TypeAdapter(output_type)
        data = type_adapter.dump_python(result, mode="json")
        json_schema = type_adapter.json_schema(mode="serialization")

        result_struct = Struct()
        result_struct.update({"result": data})
        result_value = Value(struct_value=result_struct)

        meta_struct = Struct()
        meta_struct.update({"json_schema": json_schema})

        return Part(data=result_value, metadata=meta_struct)

    def convert_response_parts(self, parts: Sequence[Any]) -> list[Part]:
        a2a_parts: list[Part] = []
        for part in parts:
            if isinstance(part, PydanticTextPart):
                a2a_parts.append(Part(text=part.content))
            elif isinstance(part, ThinkingPart):
                thinking_meta = Struct()
                thinking_meta.update(
                    {
                        "type": "thinking",
                        "thinking_id": part.id,
                        "signature": part.signature,
                    }
                )
                a2a_parts.append(Part(text=part.content, metadata=thinking_meta))
            elif isinstance(part, ToolCallPart):
                pass
        return a2a_parts

    def _build_pydantic_agent(self) -> Agent:
        from pydantic_ai import Agent
        from pydantic_ai.capabilities import Thinking

        thinking_effort = self._spec.thinking
        capabilities = (
            [Thinking(effort=thinking_effort)]
            if thinking_effort and thinking_effort != "off"
            else None
        )
        return Agent(
            output_type=self._spec.output_type,
            instructions=self._spec.system_prompt,
            capabilities=capabilities,
        )

    def _build_model(self) -> Model:
        from pydantic_ai.models.fallback import FallbackModel

        missing = self.check_credentials()
        if missing:
            raise MissingCredentialsError(providers=missing)

        default_model = self._spec.default_model
        enabled_providers = self._spec.get_enabled_providers()

        if not enabled_providers:
            raise MissingCredentialsError(providers=["No providers enabled"])

        if len(enabled_providers) == 1:
            provider_name = enabled_providers[0]
            model_name = self._spec.get_model_name(provider_name, default_model)
            api_key = self._spec.get_api_key(provider_name)
            return self._get_registry().create_model(provider_name, model_name, api_key=api_key)

        models = []
        for provider_name in enabled_providers:
            model_name = self._spec.get_model_name(provider_name, default_model)
            api_key = self._spec.get_api_key(provider_name)
            model = self._get_registry().create_model(provider_name, model_name, api_key=api_key)
            models.append(model)

        return FallbackModel(*models)

    def _get_registry(self) -> ProviderRegistry:
        if self._registry is None:
            from fin_assist.llm.model_registry import ProviderRegistry

            self._registry = ProviderRegistry()
        return self._registry

    def _request_parts_from_a2a(self, parts: Sequence[Any]) -> list[ModelRequestPart]:
        model_parts: list[ModelRequestPart] = []
        for part in parts:
            if part.text:
                model_parts.append(UserPromptPart(content=part.text))
            elif part.HasField("data"):
                raise NotImplementedError("Data parts in requests are not supported yet.")
            elif part.url:
                from pydantic_ai.messages import DocumentUrl, ImageUrl

                matched = False
                for url_cls in (DocumentUrl, ImageUrl):
                    try:
                        content = url_cls(url=part.url)
                        _ = content.media_type
                        model_parts.append(UserPromptPart(content=[content]))
                        matched = True
                        break
                    except ValueError:
                        continue
                if not matched:
                    model_parts.append(UserPromptPart(content=part.url))
            elif part.raw:
                from pydantic_ai.messages import BinaryContent

                data = base64.b64decode(part.raw)
                mime_type = part.media_type or "application/octet-stream"
                content = BinaryContent(data=data, media_type=mime_type)
                model_parts.append(UserPromptPart(content=[content]))
        return model_parts

    def _response_parts_from_a2a(self, parts: Sequence[Any]) -> list[ModelResponsePart]:
        model_parts: list[ModelResponsePart] = []
        for part in parts:
            if part.text:
                model_parts.append(PydanticTextPart(content=part.text))
            elif part.HasField("data"):
                raise NotImplementedError("Data parts in responses are not supported yet.")
            elif part.url:
                raise NotImplementedError("URL parts in responses are not supported yet.")
            elif part.raw:
                raise NotImplementedError("Binary parts in responses are not supported yet.")
        return model_parts
