"""FinAssistExecutor — a2a-sdk AgentExecutor for fin-assist agents.

Replaces ``FinAssistWorker(Worker[Context])`` from the fasta2a integration.
Uses ``TaskUpdater`` for all state transitions (start_work, complete, failed,
requires_auth) and ``ContextStore`` for conversation history persistence.

Key differences from FinAssistWorker:
- No broker — the a2a-sdk ``DefaultRequestHandler`` routes tasks internally.
- No ``Storage`` parameter — A2A task storage is handled by ``InMemoryTaskStore``
  while conversation history lives in our ``ContextStore``.
- ``TaskUpdater`` replaces manual ``storage.update_task()`` calls.
- ``requires_auth()`` is a first-class ``TaskUpdater`` method.
- Message conversion uses protobuf types (``Part(text=...)``) instead of
  TypedDicts (``{"kind": "text", "text": ...}``).
"""

from __future__ import annotations

import base64
import uuid
from typing import TYPE_CHECKING, Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.tasks import TaskUpdater
from a2a.types import Artifact, Message, Part, Role, TaskState
from google.protobuf.struct_pb2 import Struct, Value
from pydantic import TypeAdapter
from pydantic_ai.messages import (
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.messages import TextPart as PydanticTextPart

from fin_assist.agents.metadata import MissingCredentialsError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from a2a.server.events import EventQueue
    from pydantic_ai import ModelMessage

    from fin_assist.agents.agent import ConfigAgent
    from fin_assist.hub.context_store import ContextStore


class FinAssistExecutor(AgentExecutor):
    """AgentExecutor that runs a ConfigAgent and handles missing credentials.

    Takes a ``ConfigAgent`` (our domain agent) alongside a shared
    ``ContextStore`` for conversation history.  On each task:

    1. Calls ``agent.build_model()`` to lazily construct the LLM model.
    2. Loads conversation history from ``ContextStore``.
    3. Builds the pydantic-ai Agent and runs it with the resolved model.
    4. Converts the result to A2A artifacts and messages via ``TaskUpdater``.
    5. Saves updated conversation history to ``ContextStore``.

    If ``build_model()`` raises ``MissingCredentialsError``, the task is set
    to ``auth-required`` with a helpful message instead of failing.
    """

    def __init__(
        self,
        *,
        agent: ConfigAgent,
        context_store: ContextStore,
    ) -> None:
        self._agent = agent
        self._context_store = context_store

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,  # type: ignore[arg-type]
            context_id=context.context_id,  # type: ignore[arg-type]
        )
        await updater.start_work()

        # 1. Build model (catch MissingCredentialsError early)
        try:
            model = self._agent.build_model()
        except MissingCredentialsError as exc:
            auth_msg = updater.new_agent_message(parts=[Part(text=str(exc))])
            await updater.requires_auth(message=auth_msg)
            return

        # 2. Load conversation history
        context_id = context.context_id
        message_history: list[ModelMessage] = (
            await self._context_store.load(context_id) if context_id else []
        ) or []

        # 3. Convert A2A message → pydantic-ai message history
        if context.message:
            a2a_history = [context.message]
            message_history.extend(self._build_message_history(a2a_history))

        # 4. Run pydantic-ai agent with streaming
        pydantic_agent = self._agent.build_pydantic_agent()
        artifact_id = str(uuid.uuid4())
        try:
            async with (
                pydantic_agent,
                pydantic_agent.run_stream(model=model, message_history=message_history) as stream,
            ):
                accumulated_text = ""
                async for delta in stream.stream_text(delta=True):
                    accumulated_text += delta
                    await updater.add_artifact(
                        parts=[Part(text=delta)],
                        artifact_id=artifact_id,
                        name="result",
                        append=True,
                        last_chunk=False,
                    )
                # Final chunk signals completion
                await updater.add_artifact(
                    parts=[Part(text="")],
                    artifact_id=artifact_id,
                    name="result",
                    append=True,
                    last_chunk=True,
                )
                result_output = stream.get_output()
                all_msgs = stream.all_messages()
                new_msgs = stream.new_messages()
        except Exception:
            await updater.failed()
            raise

        # 5. Save updated conversation history
        await self._context_store.save(context_id, all_msgs)  # type: ignore[arg-type]

        # 6. Send agent messages (thinking, etc.)
        a2a_messages: list[Message] = []
        for message in new_msgs:
            if isinstance(message, ModelRequest):
                continue
            a2a_parts = self._response_parts_to_a2a(message.parts)
            if a2a_parts:
                a2a_messages.append(updater.new_agent_message(parts=a2a_parts))

        for msg in a2a_messages:
            await updater.update_status(TaskState.TASK_STATE_WORKING, message=msg)

        # 7. If structured output, add as a separate artifact
        if not isinstance(result_output, str):
            artifacts = self._build_artifacts(result_output)
            for artifact in artifacts:
                await updater.add_artifact(
                    parts=list(artifact.parts),
                    artifact_id=artifact.artifact_id,
                    name=artifact.name,
                )

        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,  # type: ignore[arg-type]
            context_id=context.context_id,  # type: ignore[arg-type]
        )
        await updater.cancel()

    # ------------------------------------------------------------------
    # Message conversion: A2A → pydantic-ai
    # ------------------------------------------------------------------

    def _build_message_history(self, history: Sequence[Message]) -> list[Any]:
        model_messages: list[Any] = []
        for message in history:
            if message.role == Role.ROLE_USER:
                model_messages.append(
                    ModelRequest(parts=self._request_parts_from_a2a(message.parts))
                )
            else:
                model_messages.append(
                    ModelResponse(parts=self._response_parts_from_a2a(message.parts))
                )
        return model_messages

    def _request_parts_from_a2a(self, parts: list[Part]) -> list[ModelRequestPart]:
        model_parts: list[ModelRequestPart] = []
        for part in parts:
            if part.text:
                model_parts.append(UserPromptPart(content=part.text))
            elif part.HasField("data") or len(part.data.struct_value) > 0:
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

    def _response_parts_from_a2a(self, parts: list[Part]) -> list[ModelResponsePart]:
        model_parts: list[ModelResponsePart] = []
        for part in parts:
            if part.text:
                model_parts.append(PydanticTextPart(content=part.text))
            elif part.HasField("data") or len(part.data.struct_value) > 0:
                raise NotImplementedError("Data parts in responses are not supported yet.")
        return model_parts

    # ------------------------------------------------------------------
    # Result conversion: pydantic-ai → A2A
    # ------------------------------------------------------------------

    def _build_artifacts(self, result: Any) -> list[Artifact]:
        import uuid

        artifact_id = str(uuid.uuid4())
        part = self._convert_result_to_part(result)
        return [Artifact(artifact_id=artifact_id, name="result", parts=[part])]

    def _convert_result_to_part(self, result: Any) -> Part:
        if isinstance(result, str):
            return Part(text=result)

        output_type = type(result)
        type_adapter = TypeAdapter(output_type)
        data = type_adapter.dump_python(result, mode="json")
        json_schema = type_adapter.json_schema(mode="serialization")

        # Wrap in {"result": ...} envelope for structured output
        result_struct = Struct()
        result_struct.update({"result": data})
        result_value = Value(struct_value=result_struct)

        meta_struct = Struct()
        meta_struct.update({"json_schema": json_schema})
        meta_value = Value(struct_value=meta_struct)

        return Part(data=result_value, metadata=meta_value)

    def _response_parts_to_a2a(self, parts: Sequence[ModelResponsePart]) -> list[Part]:
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
