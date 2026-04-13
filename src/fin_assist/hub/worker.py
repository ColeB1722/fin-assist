"""Custom Worker that maps MissingCredentialsError to ``auth-required``.

Implements ``fasta2a.Worker`` directly (public API) rather than subclassing
``AgentWorker`` from the private ``pydantic_ai._a2a`` module. This resolves
issue #68 and eliminates the tech debt around private imports.

The worker owns its own message conversion logic using public types from
``pydantic_ai.messages`` and ``fasta2a.schema`` — no implicit behavior
inherited from ``AgentWorker``.

Why not subclass AgentWorker?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. ``AgentWorker`` lives in ``pydantic_ai._a2a`` — a private module that can
   change without notice. Subclassing it couples us to unstable internals.
2. ``AgentWorker.run_task()`` is a blocking call with no hooks for custom
   task states (``auth-required``, ``input-required``). We override the
   entire method anyway, so inheritance buys nothing.
3. ``pydantic_agent.to_a2a()`` creates a default ``AgentWorker`` that is
   immediately discarded. Constructing ``FastA2A`` directly avoids this waste.
4. The "two agents" pattern (``agent_def`` + inherited ``agent``) is
   confusing. This worker takes an explicit ``agent`` parameter — a single
   ``ConfigAgent`` that carries all domain logic.
"""

from __future__ import annotations

import base64
import uuid
from typing import TYPE_CHECKING, Any, cast

from fasta2a.schema import Artifact, DataPart, Message, Part, TaskIdParams, TaskSendParams, TextPart
from fasta2a.worker import Worker
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

    from fasta2a.broker import Broker
    from fasta2a.storage import Storage

    from fin_assist.agents.agent import ConfigAgent

Context = list[Any]


class FinAssistWorker(Worker[Context]):
    """Worker that gracefully handles missing credentials.

    Takes a ``ConfigAgent`` (our domain agent) alongside the shared storage and
    per-agent broker. On each task:

    1. Calls ``agent.build_model()`` to lazily construct the LLM model.
    2. Builds the pydantic-ai Agent and runs it with the resolved model.
    3. Converts the result to A2A artifacts and messages.

    If ``build_model()`` raises ``MissingCredentialsError``, the task is set
    to ``auth-required`` with a helpful message instead of crashing the hub.
    """

    def __init__(
        self,
        *,
        agent: ConfigAgent,
        broker: Broker,
        storage: Storage[Context],
    ) -> None:
        super().__init__(broker=broker, storage=storage)
        self._agent = agent

    async def run_task(self, params: TaskSendParams) -> None:
        task = await self.storage.load_task(params["id"])
        if task is None:
            raise ValueError(f"Task {params['id']} not found")

        if task["status"]["state"] != "submitted":
            raise ValueError(
                f"Task {params['id']} has already been processed (state: {task['status']['state']})"
            )

        await self.storage.update_task(task["id"], state="working")

        message_history = await self.storage.load_context(task["context_id"]) or []
        message_history.extend(self.build_message_history(task.get("history", [])))

        try:
            model = self._agent.build_model()
        except MissingCredentialsError as exc:
            agent_msg: Message = {
                "role": "agent",
                "parts": [{"kind": "text", "text": str(exc)}],
                "kind": "message",
                "message_id": str(uuid.uuid4()),
            }
            await self.storage.update_task(
                task["id"],
                state="auth-required",
                new_messages=[agent_msg],
            )
            return

        pydantic_agent = self._agent.build_pydantic_agent()

        try:
            async with pydantic_agent:
                result = await pydantic_agent.run(model=model, message_history=message_history)
        except Exception:
            await self.storage.update_task(task["id"], state="failed")
            raise

        await self.storage.update_context(task["context_id"], result.all_messages())

        a2a_messages: list[Message] = []
        for message in result.new_messages():
            if isinstance(message, ModelRequest):
                continue
            a2a_parts = self._response_parts_to_a2a(message.parts)
            if a2a_parts:
                a2a_messages.append(
                    {
                        "role": "agent",
                        "parts": a2a_parts,
                        "kind": "message",
                        "message_id": str(uuid.uuid4()),
                    }
                )

        artifacts = self.build_artifacts(result.output)
        await self.storage.update_task(
            task["id"],
            state="completed",
            new_artifacts=artifacts,
            new_messages=a2a_messages,
        )

    async def cancel_task(self, params: TaskIdParams) -> None:
        task = await self.storage.load_task(params["id"])
        if task and task["status"]["state"] not in ("completed", "failed", "canceled"):
            await self.storage.update_task(params["id"], state="canceled")

    def build_message_history(self, history: list[Message]) -> list[Any]:
        model_messages: list[Any] = []
        for message in history:
            if message["role"] == "user":
                model_messages.append(
                    ModelRequest(parts=self._request_parts_from_a2a(message["parts"]))
                )
            else:
                model_messages.append(
                    ModelResponse(parts=self._response_parts_from_a2a(message["parts"]))
                )
        return model_messages

    def build_artifacts(self, result: Any) -> list[Artifact]:
        artifact_id = str(uuid.uuid4())
        part = self._convert_result_to_part(result)
        return [Artifact(artifact_id=artifact_id, name="result", parts=[part])]

    def _convert_result_to_part(self, result: Any) -> Part:
        if isinstance(result, str):
            return TextPart(kind="text", text=result)
        output_type = type(result)
        type_adapter = TypeAdapter(output_type)
        data = type_adapter.dump_python(result, mode="json")
        json_schema = type_adapter.json_schema(mode="serialization")
        return DataPart(kind="data", data={"result": data}, metadata={"json_schema": json_schema})

    def _request_parts_from_a2a(self, parts: list[Part]) -> list[ModelRequestPart]:
        model_parts: list[ModelRequestPart] = []
        for part in parts:
            if part["kind"] == "text":
                model_parts.append(UserPromptPart(content=part["text"]))
            elif part["kind"] == "file":
                file_content = cast("dict[str, Any]", part["file"])
                if "bytes" in file_content:
                    from pydantic_ai.messages import BinaryContent

                    data = base64.b64decode(file_content["bytes"])
                    mime_type = file_content.get("mime_type", "application/octet-stream")
                    content = BinaryContent(data=data, media_type=mime_type)
                    model_parts.append(UserPromptPart(content=[content]))
                else:
                    url = file_content["uri"]
                    from pydantic_ai.messages import DocumentUrl, ImageUrl

                    matched = False
                    for url_cls in (DocumentUrl, ImageUrl):
                        try:
                            content = url_cls(url=url)
                            _ = content.media_type
                            model_parts.append(UserPromptPart(content=[content]))
                            matched = True
                            break
                        except ValueError:
                            continue
                    if not matched:
                        model_parts.append(UserPromptPart(content=url))
            elif part["kind"] == "data":
                raise NotImplementedError("Data parts in requests are not supported yet.")
        return model_parts

    def _response_parts_from_a2a(self, parts: list[Part]) -> list[ModelResponsePart]:
        model_parts: list[ModelResponsePart] = []
        for part in parts:
            if part["kind"] == "text":
                model_parts.append(PydanticTextPart(content=part["text"]))
            elif part["kind"] == "data":
                raise NotImplementedError("Data parts in responses are not supported yet.")
        return model_parts

    def _response_parts_to_a2a(self, parts: Sequence[ModelResponsePart]) -> list[Part]:
        a2a_parts: list[Part] = []
        for part in parts:
            if isinstance(part, PydanticTextPart):
                a2a_parts.append(TextPart(kind="text", text=part.content))
            elif isinstance(part, ThinkingPart):
                a2a_parts.append(
                    TextPart(
                        kind="text",
                        text=part.content,
                        metadata={
                            "type": "thinking",
                            "thinking_id": part.id,
                            "signature": part.signature,
                        },
                    )
                )
            elif isinstance(part, ToolCallPart):
                pass
        return a2a_parts
